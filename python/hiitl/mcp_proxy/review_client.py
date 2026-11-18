"""Block 3b: proxy-side client for the review-case API.

When the proxy receives a PAUSE / REQUIRE_APPROVAL / ESCALATE decision
AND has a configured `server_url` + `api_key`, it:

1. POSTs to /v1/reviews to open a case.
2. Opens GET /v1/reviews/{case_id}/stream (SSE).
3. Waits for the one terminal event: "resolved" or "timeout".
4. Returns a `ReviewOutcome` to the caller, which decides whether to
   forward the tool call (with original or modified args) or surface
   an MCP error.

When `server_url` is NOT configured, the proxy falls back to the Block
3a behavior — return a placeholder MCP error and don't try to talk to
a backend that isn't there. That branch lives in `proxy.py`; this
module is only used on the happy path.

SSE parsing: we use `httpx`'s streaming JSON-line iteration. Each SSE
event is a multi-line block separated by `\\n\\n`. We accumulate
`event:` and `data:` fields and emit one event at a time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from hiitl.core.redaction import MARKER
from hiitl.core.transport import https_refusal


logger = logging.getLogger(__name__)


# Headers we set on every backend call. The proxy authenticates with the
# same API key the SDK uses.
def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@dataclass
class ReviewOutcome:
    """The terminal state of a review case as seen by the proxy.

    `kind`:
        "approved"  — forward the tool call with `args`.
        "modified"  — forward with the reviewer-supplied `args` (replaces
                      the originals).
        "rejected"  — return MCP error with `reason`.
        "timed_out" — the service recorded the case's timeout; the caller
                      takes `timeout_action` (forward `args`, the original
                      arguments, on fail_open; refuse otherwise).
        "error"     — backend call failed, or the wait ended with no
                      recorded outcome; the caller fail-closes per
                      `safe-by-default`.

    Only a recorded timeout is `timed_out` (routes.md 1.3): the proxy's own
    deadline, or a stream that closes with no event, is an `error`.
    """

    kind: str
    reason: Optional[str] = None
    args: Optional[dict[str, Any]] = None
    timeout_action: Optional[str] = None


async def request_review(
    *,
    server_url: str,
    api_key: str,
    action_id: str,
    envelope: dict[str, Any],
    decision: dict[str, Any],
    policy_version: str,
    rule_name: Optional[str],
    timeout_seconds: int,
    original_arguments: dict[str, Any],
    timeout_action: str = "fail_closed",
    http_client: Optional[httpx.AsyncClient] = None,
) -> ReviewOutcome:
    """Open a review case and wait for the terminal event over SSE.

    `timeout_seconds` and `timeout_action` are recorded on the case: what a
    timeout takes is the case's, never decided here.

    `original_arguments` is what the agent passed to call_tool — used as
    the fallback `args` on "approved" outcomes (the reviewer didn't ask
    for modifications, so the original args carry through).
    """
    refusal = https_refusal(server_url, "server_url")      # the API key goes there (sync_engine.md section 8)
    if refusal:
        return ReviewOutcome(kind="error", reason=refusal)
    owns_client = http_client is None
    base_url = server_url.rstrip("/")
    headers = _auth_headers(api_key)

    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, read=None),  # No read-timeout for SSE.
    )

    try:
        # Step 1: create the case.
        try:
            response = await client.post(
                f"{base_url}/v1/reviews",
                json={
                    "action_id": action_id,
                    "envelope": envelope,
                    "decision": decision,
                    "policy_version": policy_version,
                    "rule_name": rule_name,
                    "timeout_seconds": timeout_seconds,
                    "timeout_action": timeout_action,
                },
                headers=headers,
                follow_redirects=False,     # a redirect is the service's answer, not a hop (sync_engine.md section 8)
            )
        except httpx.HTTPError as exc:
            return ReviewOutcome(
                kind="error",
                reason=f"Could not reach hiitl backend to open review case: {exc}",
            )
        if response.status_code != 201:
            return ReviewOutcome(
                kind="error",
                reason=(
                    f"hiitl backend rejected review-case creation "
                    f"(HTTP {response.status_code}): {response.text[:200]}"
                ),
            )
        case = response.json()
        case_id = case["case_id"]

        # Step 2: open the SSE stream and wait for the terminal event.
        # The backend's SSE handler emits exactly one event then closes.
        return await _consume_review_stream(
            client=client,
            base_url=base_url,
            api_key=api_key,
            case_id=case_id,
            timeout_seconds=timeout_seconds,
            original_arguments=original_arguments,
        )
    finally:
        if owns_client:
            await client.aclose()


async def _consume_review_stream(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    case_id: str,
    timeout_seconds: int,
    original_arguments: dict[str, Any],
) -> ReviewOutcome:
    headers = _auth_headers(api_key)
    # Slight grace beyond timeout_seconds so the backend's own timeout
    # event reaches us before we cut the connection.
    overall_timeout = timeout_seconds + 10
    try:
        async with client.stream(
            "GET",
            f"{base_url}/v1/reviews/{case_id}/stream",
            headers=headers,
            timeout=httpx.Timeout(30.0, read=None),
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                return ReviewOutcome(
                    kind="error",
                    reason=(
                        f"hiitl review stream returned HTTP "
                        f"{response.status_code}: {body[:200]!r}"
                    ),
                )

            async def _iter():
                async for event_name, payload in _iter_sse_events(response):
                    yield event_name, payload

            try:
                async for event_name, payload in _aiter_with_timeout(
                    _iter(), overall_timeout,
                ):
                    if event_name == "resolved":
                        return _outcome_from_resolved(payload, original_arguments)
                    if event_name == "timeout":
                        return _outcome_from_resolved(
                            {**payload, "status": "timed_out"}, original_arguments,
                        )
                    # Unknown event types: ignore (keepalive comments
                    # are filtered out at the SSE-parser layer).
            except asyncio.TimeoutError:
                return ReviewOutcome(
                    kind="error",
                    reason=(
                        "Review wait exceeded the proxy's review_timeout_seconds "
                        "with no recorded outcome; the case may still be pending "
                        "on the backend."
                    ),
                )

        # Stream closed without an event: no outcome is recorded, so fail closed.
        return ReviewOutcome(
            kind="error",
            reason="Review stream closed with no recorded outcome.",
        )
    except httpx.HTTPError as exc:
        return ReviewOutcome(
            kind="error",
            reason=f"Review stream failed: {exc}",
        )


_UNHELD = object()


def _filled(modified: Any, call: Any, unheld: list[str], path: str = "") -> Any:
    """`modified` with the redaction marker at each path replaced by the call's own value there (row 213). A marked
    path at which the call holds no value is added to `unheld`."""
    if modified == MARKER:
        if call is _UNHELD:
            unheld.append(path)
        return call
    if isinstance(modified, dict):
        held = call if isinstance(call, dict) else {}
        return {k: _filled(v, held.get(k, _UNHELD), unheld, f"{path}.{k}" if path else str(k))
                for k, v in modified.items()}
    if isinstance(modified, list):
        held = call if isinstance(call, list) else []
        return [_filled(v, held[i] if i < len(held) else _UNHELD, unheld, f"{path}[{i}]")
                for i, v in enumerate(modified)]
    return modified


def _outcome_from_resolved(
    payload: dict[str, Any], original_arguments: dict[str, Any],
) -> ReviewOutcome:
    status = payload.get("status", "")
    response = payload.get("reviewer_response") or {}
    reason = response.get("reason")
    if status == "approved":
        return ReviewOutcome(kind="approved", reason=reason, args=original_arguments)
    if status == "modified":
        modified = response.get("modified_arguments")
        if not isinstance(modified, dict):
            return ReviewOutcome(
                kind="error",
                reason=(
                    "Review case was resolved 'modified' but no "
                    "modified_arguments were provided."
                ),
            )
        # The case records the org's declared fields as the marker (HTL-22 row 163(b)); the gateway holds the call
        # whole and fills each marked path from it (row 213, ruled 2026-11-06). The marker is never forwarded.
        unheld: list[str] = []
        filled = _filled(modified, original_arguments, unheld)
        if unheld:
            return ReviewOutcome(
                kind="error",
                reason=(
                    f"Review case was resolved 'modified', and its recorded modified_arguments hold {MARKER} at "
                    f"{', '.join(unheld)}, where the call holds no value: the gateway fills a redacted argument from "
                    "the call, and has nothing to fill these with. The call is not forwarded. Resolve the case with "
                    "arguments that give a value at each of those paths, or 'approved' or 'rejected'."
                ),
            )
        return ReviewOutcome(kind="modified", reason=reason, args=filled)
    if status == "rejected":
        return ReviewOutcome(kind="rejected", reason=reason)
    if status == "timed_out":
        return ReviewOutcome(
            kind="timed_out", reason=reason, args=original_arguments,
            timeout_action=payload.get("timeout_action") or "fail_closed",
        )
    return ReviewOutcome(
        kind="error",
        reason=f"Review case resolved with unrecognized status '{status}'.",
    )


# ============================================================================
# SSE parser — minimal, keepalive-tolerant
# ============================================================================


async def _iter_sse_events(
    response: httpx.Response,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Parse an SSE byte stream into (event_name, data_json) tuples.

    SSE spec: events are blocks separated by a blank line. Each line is
    either `event: NAME`, `data: PAYLOAD`, or a comment (`:` prefix —
    used for keepalives). We don't support the `id:` / `retry:` fields
    because the review-stream protocol doesn't use them.
    """
    event_name = ""
    data_parts: list[str] = []
    async for raw_line in response.aiter_lines():
        # httpx yields lines without trailing \n. Blank line == event terminator.
        if raw_line == "":
            if event_name and data_parts:
                payload_str = "\n".join(data_parts)
                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    payload = {"raw": payload_str}
                yield event_name, payload
            event_name = ""
            data_parts = []
            continue
        if raw_line.startswith(":"):
            # Keepalive / comment. Ignore.
            continue
        if raw_line.startswith("event:"):
            event_name = raw_line[len("event:"):].strip()
            continue
        if raw_line.startswith("data:"):
            data_parts.append(raw_line[len("data:"):].lstrip())
            continue
        # Anything else (id:, retry:, malformed): ignore.


async def _aiter_with_timeout(aiter, timeout_seconds: float):
    """Wrap an async iterator with an overall timeout budget.

    Each `anext` call gets the remaining budget; on expiry, raises
    `asyncio.TimeoutError`. The aiter itself isn't aware of the budget.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    iterator = aiter.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            item = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield item
