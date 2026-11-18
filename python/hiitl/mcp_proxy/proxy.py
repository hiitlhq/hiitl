"""hiitl MCP proxy — the server that Claude Desktop talks to.

Pulls upstream tools/resources/prompts into a single MCP server. Every
`call_tool` is intercepted, run through `hiitl.evaluate()`, and only
forwarded if the decision allows it. Read-only methods (`list_*`,
`read_resource`, `get_prompt`) are forwarded directly — they have no
side effects worth governing.

Decision handling:
    ALLOW / SANDBOX / OBSERVE  → forward upstream; return result verbatim.
    BLOCK / RATE_LIMIT / KILL_SWITCH
                               → return an `isError=True` CallToolResult
                                 with a structured reason message.
    REQUIRE_APPROVAL / PAUSE / ESCALATE
                               → with `server_url` + `api_key` configured,
                                 open a review case and wait for the
                                 reviewer: approve forwards, modify
                                 forwards the reviewer's arguments,
                                 reject or timeout is an error. Without
                                 them no reviewer can be asked, and the
                                 error says how to configure one. Either
                                 way the original decision is already in
                                 the SDK's audit log (the call to
                                 evaluate() recorded it).
    ROUTE                      → mapped to BLOCK. The SDK the proxy calls
                                 has already asked the sync route the
                                 rule names and evaluated again with its
                                 answer (TICKET-046), so a ROUTE that
                                 reaches the proxy is one the route did
                                 not answer, or a rule with no sync
                                 route: fail closed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError

from hiitl._version import __version__
from hiitl.core import routing
from hiitl.mcp_proxy.config import ProxyConfig
from hiitl.mcp_proxy.review_client import ReviewOutcome, request_review
from hiitl.mcp_proxy.upstream import UpstreamManager
from hiitl.sdk.client import HIITL


logger = logging.getLogger(__name__)


PROXY_SERVER_NAME = "hiitl-mcp-proxy"
PROXY_SERVER_VERSION = __version__


# Reason text returned to the MCP client when a decision blocks a call.
# Kept as short, actionable strings — Claude Desktop renders these to the
# user (or the model) verbatim.
_BLOCK_HEADER = "This action was blocked by hiitl policy"
_NO_REVIEWER_TEXT = (
    "This action requires human approval. The review flow requires a "
    "hiitl backend, and this proxy has none configured (set `server_url` "
    "and `api_key` in hiitl-mcp.yaml), so no reviewer was asked and the "
    "request was not forwarded. It has been logged to the hiitl audit trail."
)
_ROUTE_PLACEHOLDER_TEXT = (
    "This action's policy returned a ROUTE decision, and the route it names "
    "gave no answer (or is not a sync route), so the request was not "
    "forwarded (fail closed). It has been logged to the hiitl audit trail; "
    "check the route's endpoint and its SLA."
)

# Decision types that mean "the user needs a human in the loop" — all
# three go to the review case API when the proxy has a backend, and get
# the same no-reviewer message when it has none.
_HUMAN_LOOP_DECISIONS = frozenset({"PAUSE", "REQUIRE_APPROVAL", "ESCALATE"})


def build_proxy_server(
    config: ProxyConfig,
    upstreams: UpstreamManager,
    hiitl_client: HIITL,
) -> Server:
    """Build the MCP `Server` instance for the proxy.

    Caller owns lifetime: open the upstream manager, build the hiitl
    client, call this to get the server, then call `run_proxy(server)`
    to drop into the stdio event loop.
    """
    server: Server = Server(PROXY_SERVER_NAME, version=PROXY_SERVER_VERSION)

    # ---------------------------------------------------------------- #
    # Tools
    # ---------------------------------------------------------------- #

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        """Return the union of every upstream's tools, names verbatim."""
        return upstreams.all_tools()

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None,
    ) -> mcp_types.CallToolResult:
        """Intercept, evaluate, then forward (or block)."""
        args = arguments or {}

        # Step 1: evaluate, off the event loop: a sync route's wait holds this call only, and the gateway keeps
        # answering every other (HTL-18 row 126; the third core design principle: "ECP must never become the bottleneck").
        try:
            decision = await asyncio.to_thread(
                hiitl_client.evaluate,
                action=name,
                parameters=args,
            )
        except Exception as exc:  # noqa: BLE001
            # An evaluator failure is its own MCP error — we can't tell
            # whether the call is safe without it.
            logger.exception("hiitl.evaluate() failed for tool '%s'", name)
            raise McpError(
                mcp_types.ErrorData(
                    code=mcp_types.INTERNAL_ERROR,
                    message=f"hiitl evaluator failed: {exc}",
                )
            ) from exc

        # Step 2: branch on decision.
        if decision.ok or decision.observed:
            return await _forward_tool_call(
                name, args, upstreams,
                timeout_seconds=config.timeout_seconds,
            )

        # PAUSE / REQUIRE_APPROVAL / ESCALATE → talk to the review-case
        # API IF the proxy was configured with a backend (server_url +
        # api_key). Otherwise no reviewer can be asked, and the block
        # message says so. ROUTE keeps its own message regardless: the SDK
        # already asked the route (TICKET-046), so a ROUTE here went unanswered.
        decision_type = _decision_type_str(decision)
        if decision_type in _HUMAN_LOOP_DECISIONS and config.server_url and config.api_key:
            outcome = await _wait_for_review(
                config=config,
                hiitl_client=hiitl_client,
                name=name,
                args=args,
                decision=decision,
            )
            return await _apply_review_outcome(
                outcome, name, upstreams, config.timeout_seconds,
            )

        # Block-path: return an isError CallToolResult so Claude Desktop
        # surfaces the message to the user/agent without making the
        # connection look broken. (Raising McpError here would propagate
        # as a protocol-level error, which is heavier and less actionable.)
        message = _format_block_message(decision)
        logger.info(
            "Tool '%s' blocked by hiitl (decision=%s reason=%s)",
            name, decision.decision, decision.reason_codes,
        )
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INVALID_REQUEST,
                message=message,
            )
        )

    # ---------------------------------------------------------------- #
    # Resources — read-only, forwarded transparently
    # ---------------------------------------------------------------- #

    @server.list_resources()
    async def _list_resources() -> list[mcp_types.Resource]:
        return upstreams.all_resources()

    @server.read_resource()
    async def _read_resource(uri) -> str | bytes:
        """Forward to the owning upstream by URI.

        The MCP SDK's decorator accepts a string return for text
        resources or bytes for blobs.
        """
        uri_str = str(uri)
        try:
            session = upstreams.session_for_resource(uri_str)
        except KeyError:
            raise McpError(
                mcp_types.ErrorData(
                    code=mcp_types.INVALID_PARAMS,
                    message=f"Unknown resource: {uri_str}",
                )
            )
        result = await session.read_resource(uri)
        # MCP read_resource returns a ReadResourceResult with contents
        # list. Return the first content block in the format the
        # framework expects.
        if not result.contents:
            return ""
        first = result.contents[0]
        if hasattr(first, "text") and first.text is not None:
            return first.text
        if hasattr(first, "blob") and first.blob is not None:
            return first.blob
        return ""

    # ---------------------------------------------------------------- #
    # Prompts — read-only, forwarded transparently
    # ---------------------------------------------------------------- #

    @server.list_prompts()
    async def _list_prompts() -> list[mcp_types.Prompt]:
        return upstreams.all_prompts()

    @server.get_prompt()
    async def _get_prompt(
        name: str, arguments: dict[str, str] | None,
    ) -> mcp_types.GetPromptResult:
        try:
            session = upstreams.session_for_prompt(name)
        except KeyError:
            raise McpError(
                mcp_types.ErrorData(
                    code=mcp_types.INVALID_PARAMS,
                    message=f"Unknown prompt: {name}",
                )
            )
        return await session.get_prompt(name, arguments)

    return server


# ====================================================================== #
# Helpers
# ====================================================================== #


async def _forward_tool_call(
    name: str,
    args: dict[str, Any],
    upstreams: UpstreamManager,
    *,
    timeout_seconds: float,
) -> mcp_types.CallToolResult:
    """Forward to the owning upstream and return its result.

    A hanging upstream must NOT hang Claude Desktop. We wrap the
    forwarded call in `asyncio.wait_for(...)` and surface a timeout as
    an MCP error so the client sees a clear failure rather than a stuck
    request.
    """
    try:
        session = upstreams.session_for_tool(name)
    except KeyError:
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INVALID_PARAMS,
                message=f"Unknown tool: {name}",
            )
        )
    try:
        result = await asyncio.wait_for(
            session.call_tool(name, args),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INTERNAL_ERROR,
                message=(
                    f"Upstream tool '{name}' did not respond within "
                    f"{timeout_seconds:g}s (timeout configured via "
                    "hiitl-mcp.yaml `timeout_seconds`)."
                ),
            )
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface upstream errors as MCP errors
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INTERNAL_ERROR,
                message=f"Upstream tool '{name}' failed: {exc}",
            )
        ) from exc
    # If the upstream itself signaled an error in its content, propagate
    # by raising — keeps the client's error UX consistent.
    if result.isError:
        text = _extract_text(result.content) or f"Upstream tool '{name}' reported an error"
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INTERNAL_ERROR,
                message=text,
            )
        )
    # the upstream's own result, whole: its content and — for a tool that declares an outputSchema — its
    # structuredContent, which the SDK validates on the way out (T-134: the content list alone failed that validation
    # on every structured tool of the official filesystem server)
    return result


def _format_block_message(decision: Any) -> str:
    """Compose the human-readable BLOCK message for the MCP client.

    PAUSE / REQUIRE_APPROVAL / ESCALATE reach here only when the proxy
    has no backend to ask a reviewer, and get the message that says how
    to configure one. ROUTE gets its own placeholder since it's a
    "different action needed" signal, not a "needs human" signal. Other blocking decisions echo the policy's
    reason codes so the agent (or user) can act on the information.
    """
    decision_type = getattr(decision, "decision", "BLOCK")
    # Decision.decision is stored as the str value of the enum via
    # use_enum_values=True; defensive coercion in case the SDK ever
    # changes shape.
    if hasattr(decision_type, "value"):
        decision_type = decision_type.value
    reason_codes = list(getattr(decision, "reason_codes", []) or [])

    if decision_type in _HUMAN_LOOP_DECISIONS:
        suffix = f" (reason: {', '.join(reason_codes)})" if reason_codes else ""
        return f"{_NO_REVIEWER_TEXT}{suffix}"

    if decision_type == "ROUTE":
        suffix = f" (reason: {', '.join(reason_codes)})" if reason_codes else ""
        return f"{_ROUTE_PLACEHOLDER_TEXT}{suffix}"

    # Remediation hints — surface them if the rule attached them.
    remediation = getattr(decision, "remediation", None)
    remediation_msg = ""
    if remediation is not None and getattr(remediation, "message", None):
        remediation_msg = f" — {remediation.message}"

    reasons_text = ", ".join(reason_codes) if reason_codes else "no reason given"
    return (
        f"{_BLOCK_HEADER} (decision={decision_type}; reason: {reasons_text})"
        f"{remediation_msg}"
    )


def _decision_type_str(decision: Any) -> str:
    """Defensive accessor — Decision uses `use_enum_values=True` so
    `.decision` is already a string, but coerce to be safe.
    """
    dt = getattr(decision, "decision", "")
    return dt.value if hasattr(dt, "value") else str(dt)


async def _wait_for_review(
    *,
    config: ProxyConfig,
    hiitl_client: HIITL,
    name: str,
    args: dict[str, Any],
    decision: Any,
) -> ReviewOutcome:
    """Open a review case on the backend and wait for the terminal event.

    The envelope sent up is a minimal projection — we include enough for
    a reviewer to understand the request without re-deriving it from
    scratch, but we do NOT replicate every Block 1A enrichment field.
    The audit row at `audit_events.action_id` already has the full
    envelope.
    """
    action_id = getattr(decision, "action_id", "") or ""
    envelope_for_review = {
        "action": name,
        "parameters": args,
        "agent_id": config.agent_id,
        "environment": config.environment,
    }
    decision_for_review = {
        "decision": _decision_type_str(decision),
        "reason_codes": list(getattr(decision, "reason_codes", []) or []),
    }
    policy_version = getattr(decision, "policy_version", "") or "unknown"
    rule_name = None
    matched = getattr(decision, "matched_rules", None) or []
    if matched:
        rule_name = getattr(matched[0], "rule_name", None)
    timeout_seconds, timeout_action = _review_wait(decision, config)
    try:
        return await request_review(
            server_url=config.server_url,
            api_key=config.api_key,
            action_id=action_id,
            envelope=envelope_for_review,
            decision=decision_for_review,
            policy_version=policy_version,
            rule_name=rule_name,
            timeout_seconds=timeout_seconds,
            timeout_action=timeout_action,
            original_arguments=args,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Review-case wait failed for tool '%s'", name)
        return ReviewOutcome(
            kind="error",
            reason=f"Review flow failed: {exc}",
        )


def _review_wait(decision: Any, config: ProxyConfig) -> tuple[int, str]:
    """The case's wait and what its timeout takes (routes.md 1.3).

    The route's `sla.timeout` and `sla.timeout_action`, which the SDK copies
    into `escalation_context`, when that wait fits within the gateway's own
    `review_timeout_seconds`; else the gateway's bound and fail_closed. A
    `timeout_action` belongs to its `timeout`: a shorter wait never takes a
    route's fail_open.
    """
    ctx = getattr(decision, "escalation_context", None) or {}
    sla = {"timeout": ctx.get("timeout"), "timeout_action": ctx.get("timeout_action")}
    if sla["timeout"] and sla["timeout_action"]:
        route_wait = routing.timeout_seconds({"sla": sla})
        if route_wait <= config.review_timeout_seconds:
            return int(route_wait), str(sla["timeout_action"])
    return config.review_timeout_seconds, "fail_closed"


async def _apply_review_outcome(
    outcome: ReviewOutcome,
    name: str,
    upstreams: UpstreamManager,
    timeout_seconds: float,
) -> list[mcp_types.TextContent | mcp_types.ImageContent | mcp_types.EmbeddedResource]:
    """Turn a `ReviewOutcome` into a tool result or an MCP error.

    Safe-by-default: on `error` outcomes (backend unreachable, malformed
    response, etc.) we fail-CLOSED with an MCP error — never silently
    forward a tool call that didn't get an explicit approval.
    """
    if outcome.kind in ("approved", "modified"):
        args = outcome.args if outcome.args is not None else {}
        if outcome.kind == "modified":
            logger.info(
                "Tool '%s' approved with modifications by reviewer", name,
            )
        return await _forward_tool_call(
            name, args, upstreams, timeout_seconds=timeout_seconds,
        )

    reason_suffix = f" — {outcome.reason}" if outcome.reason else ""
    if outcome.kind == "rejected":
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INVALID_REQUEST,
                message=f"Action rejected by reviewer{reason_suffix}",
            )
        )
    if outcome.kind == "timed_out":
        # The service recorded the timeout; the case's timeout_action decides.
        if routing.fails_open({"sla": {"timeout_action": outcome.timeout_action}}):
            logger.warning(
                "Review of tool '%s' timed out; forwarding per the route's "
                "timeout_action fail_open", name,
            )
            return await _forward_tool_call(
                name, outcome.args if outcome.args is not None else {}, upstreams,
                timeout_seconds=timeout_seconds,
            )
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INVALID_REQUEST,
                message=(
                    f"Action review timed out (timeout_action: "
                    f"{outcome.timeout_action or 'fail_closed'}); not forwarded{reason_suffix}"
                ),
            )
        )
    # Anything else, including "error": fail-closed.
    raise McpError(
        mcp_types.ErrorData(
            code=mcp_types.INTERNAL_ERROR,
            message=f"Review flow could not complete safely{reason_suffix}",
        )
    )


def _extract_text(content: list[Any]) -> str:
    """Best-effort extract a text message from a content list."""
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


# ====================================================================== #
# Entry point
# ====================================================================== #


def hiitl_kwargs(config: ProxyConfig) -> dict[str, Any]:
    """The hiitl client the proxy builds once and reuses: the SDK's own configuration, passed through (HTL-18).

    - **No api_key, no policy file** is the zero-config path: the SDK's default, which observes and records every call.
      T-134 found that it never started: it asked for RESPECT_POLICY, which the SDK refuses without a policy file.
    - **A policy file** (local mode) is evaluated in-process and its rules bind: RESPECT_POLICY. A ROUTE rule's sync
      route, from `routes_path`, is asked by the SDK.
    - **With an api_key**, the policies the backend syncs are respected. The backend the config names is the SDK's sync
      target, not only the review API's; before T-134, hybrid sync always went to the SDK's default URL.
    - A `mode` the config sets wins. A field left unset is not passed, so the SDK reads its `HIITL_*` setting from the
      gateway's environment, then its own default (row 129). The signature key is read that way, never from the file.
    - The record holds each argument's name and a hash of its value, except the arguments `recorded_arguments` records
      as given (row 139). It is always passed: an empty mapping hashes every argument, and leaving it out would record
      them all."""
    out: dict[str, Any] = {"agent_id": config.agent_id, "environment": config.environment}
    if config.api_key:
        out["api_key"] = config.api_key
        if config.server_url:
            out["server_url"] = config.server_url
    passed = {
        "mode": config.mode or ("RESPECT_POLICY" if config.api_key or config.policy_path else None),
        "policy_path": config.policy_path,
        "routes_path": config.routes_path,
        "audit_db_path": config.audit_db_path,
    }
    out.update({k: v for k, v in passed.items() if v})
    out["recorded_parameters"] = {tool: list(names) for tool, names in config.recorded_arguments.items()}
    return out


async def run_proxy(config: ProxyConfig) -> None:
    """Open upstreams, build the proxy server, serve on stdio until shutdown.

    The MCP SDK's `Server.run()` expects async streams; for the CLI
    case we run on stdin/stdout via `mcp.server.stdio.stdio_server`.
    """
    from mcp.server.stdio import stdio_server

    hiitl_client = HIITL(**hiitl_kwargs(config))

    async with UpstreamManager(config) as upstreams:
        await upstreams.start()
        server = build_proxy_server(config, upstreams, hiitl_client)
        init_opts = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_opts)
