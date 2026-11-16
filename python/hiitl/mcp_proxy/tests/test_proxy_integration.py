"""End-to-end proxy tests via the MCP SDK's in-memory transport.

We don't spawn subprocesses. Instead we:

1. Build a small "fake upstream" MCP `Server` with a handful of tools
   registered.
2. Connect a `ClientSession` to it via the SDK's in-memory helper
   (`create_connected_server_and_client_session`).
3. Inject that pre-connected session into an `UpstreamManager` via a
   small test hook so we sidestep stdio/sse entirely.
4. Build the proxy server and connect a *second* in-memory client to
   it. That client plays the role of Claude Desktop.
5. Drive call_tool / list_tools through the proxy and assert.

The fake HIITL client is a Pydantic-shaped stand-in that lets each test
control the Decision returned by `evaluate()`.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any, Callable

import pytest
import pytest_asyncio
from mcp import types as mcp_types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from hiitl.mcp_proxy.config import ProxyConfig, StdioServerConfig
from hiitl.mcp_proxy.proxy import build_proxy_server
from hiitl.mcp_proxy.upstream import (
    ToolCollisionError,
    UpstreamManager,
    UpstreamServer,
)


# ============================================================================
# Fake hiitl client — controllable Decision factory
# ============================================================================


class _FakeDecision:
    """Match the surface the proxy reads on Decision."""

    def __init__(
        self,
        *,
        decision: str = "ALLOW",
        reason_codes: list[str] | None = None,
        remediation=None,
    ):
        self.decision = decision
        self.reason_codes = reason_codes or []
        self.remediation = remediation

    @property
    def ok(self) -> bool:
        return self.decision in ("ALLOW", "SANDBOX")

    @property
    def observed(self) -> bool:
        return self.decision == "OBSERVE"

    @property
    def blocked(self) -> bool:
        return not self.ok and not self.observed


class _FakeHiitl:
    """Stand-in for `hiitl.sdk.client.HIITL` — drives the proxy from tests."""

    def __init__(self, decision_factory: Callable[[str, dict], _FakeDecision] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._factory = decision_factory or (lambda name, args: _FakeDecision())

    def evaluate(self, action: str, *, parameters: dict | None = None, **_):
        self.calls.append((action, parameters or {}))
        return self._factory(action, parameters or {})


# ============================================================================
# Fake upstream MCP server
# ============================================================================


def _build_fake_upstream(name: str, tools: list[dict[str, Any]]) -> Server:
    """Build a fake MCP server exposing the given tools.

    `tools` is a list of {"name": str, "description": str, "handler":
    callable(args) -> str}. The handler return is wrapped in a single
    TextContent for the call_tool response.
    """
    server: Server = Server(name)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in tools
        ]

    @server.call_tool()
    async def _call_tool(
        tool_name: str, arguments: dict[str, Any] | None,
    ) -> list[mcp_types.TextContent]:
        import inspect as _inspect

        for t in tools:
            if t["name"] == tool_name:
                handler = t.get("handler") or (lambda args: f"called {tool_name} with {args}")
                value = handler(arguments or {})
                if _inspect.iscoroutine(value):
                    value = await value
                return [mcp_types.TextContent(type="text", text=str(value))]
        raise McpError(
            mcp_types.ErrorData(
                code=mcp_types.INVALID_PARAMS,
                message=f"unknown tool: {tool_name}",
            )
        )

    return server


# ============================================================================
# Test hook: build an UpstreamManager pre-loaded with injected sessions
# ============================================================================


async def _manager_with_fake_upstreams(
    stack: AsyncExitStack,
    upstreams: dict[str, list[dict[str, Any]]],
) -> UpstreamManager:
    """Wire fake upstream servers into a working UpstreamManager.

    For each upstream label → list of tool dicts, we spin up an in-memory
    server, get a connected ClientSession, and inject it into the
    manager so it looks fully started.
    """
    config = ProxyConfig(
        servers={
            label: StdioServerConfig(command="never-spawned-in-tests")
            for label in upstreams
        },
    )
    mgr = UpstreamManager(config)
    await stack.enter_async_context(mgr)
    for label, tools in upstreams.items():
        server = _build_fake_upstream(label, tools)
        session = await stack.enter_async_context(
            create_connected_server_and_client_session(server)
        )
        await session.initialize()
        # Stash discovered tools so the manager's routing tables build.
        listed = await session.list_tools()
        mgr._servers[label] = UpstreamServer(
            label=label,
            session=session,
            tools=list(listed.tools),
        )
    # Trigger collision check + mark started.
    mgr._check_collisions()
    mgr._started = True
    return mgr


# ============================================================================
# Tool discovery
# ============================================================================


@pytest.mark.asyncio
async def test_discovery_aggregates_tools_across_upstreams():
    async with AsyncExitStack() as stack:
        mgr = await _manager_with_fake_upstreams(stack, {
            "email": [{"name": "send_email"}, {"name": "list_emails"}],
            "db":    [{"name": "query_db"}],
        })
        tool_names = sorted(t.name for t in mgr.all_tools())
        assert tool_names == ["list_emails", "query_db", "send_email"]
        assert mgr.tool_routes["send_email"] == "email"
        assert mgr.tool_routes["query_db"] == "db"


@pytest.mark.asyncio
async def test_collision_across_upstreams_raises_at_startup():
    async with AsyncExitStack() as stack:
        with pytest.raises(ToolCollisionError) as exc_info:
            await _manager_with_fake_upstreams(stack, {
                "primary":   [{"name": "search"}],
                "secondary": [{"name": "search"}],
            })
        msg = str(exc_info.value)
        assert "search" in msg
        assert "primary" in msg
        assert "secondary" in msg


# ============================================================================
# End-to-end proxy: drive it with an in-memory MCP client
# ============================================================================


async def _drive_proxy(
    stack: AsyncExitStack,
    upstreams: dict[str, list[dict[str, Any]]],
    hiitl_client: _FakeHiitl,
) -> ClientSession:
    """Spin up the proxy with fake upstreams and return a ClientSession
    that talks to the proxy (the way Claude Desktop would).
    """
    mgr = await _manager_with_fake_upstreams(stack, upstreams)
    config = ProxyConfig(servers={
        label: StdioServerConfig(command="x") for label in upstreams
    })
    proxy_server = build_proxy_server(config, mgr, hiitl_client)  # type: ignore[arg-type]
    client = await stack.enter_async_context(
        create_connected_server_and_client_session(proxy_server)
    )
    await client.initialize()
    return client


@pytest.mark.asyncio
async def test_list_tools_via_proxy_returns_union():
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl()
        client = await _drive_proxy(stack, {
            "a": [{"name": "tool_a"}],
            "b": [{"name": "tool_b"}],
        }, hiitl)
        listed = await client.list_tools()
        names = sorted(t.name for t in listed.tools)
        assert names == ["tool_a", "tool_b"]


@pytest.mark.asyncio
async def test_call_tool_allow_forwards_and_returns_result():
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="ALLOW"))
        client = await _drive_proxy(stack, {
            "x": [{
                "name": "echo",
                "handler": lambda args: f"echo:{args.get('msg', '')}",
            }],
        }, hiitl)
        result = await client.call_tool("echo", {"msg": "hi"})
        assert not result.isError
        assert any(
            getattr(c, "text", None) == "echo:hi" for c in result.content
        )
        # hiitl.evaluate was called exactly once with the tool name + args.
        assert hiitl.calls == [("echo", {"msg": "hi"})]


@pytest.mark.asyncio
async def test_call_tool_observe_also_forwards_to_upstream():
    """OBSERVE means 'don't enforce' — the tool still runs."""
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="OBSERVE"))
        client = await _drive_proxy(stack, {
            "x": [{
                "name": "echo",
                "handler": lambda args: "observed-result",
            }],
        }, hiitl)
        result = await client.call_tool("echo", {})
        assert not result.isError
        assert any(
            getattr(c, "text", None) == "observed-result" for c in result.content
        )


@pytest.mark.asyncio
async def test_call_tool_block_returns_error_with_reason():
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(
            decision="BLOCK",
            reason_codes=["AMOUNT_EXCEEDS_LIMIT"],
        ))
        client = await _drive_proxy(stack, {
            "x": [{"name": "pay"}],
        }, hiitl)
        result = await client.call_tool("pay", {"amount": 9999})
        # MCP returns isError=True with a content block describing what
        # happened (the SDK converts the raised McpError into this shape).
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "blocked by hiitl policy" in msg.lower()
        assert "AMOUNT_EXCEEDS_LIMIT" in msg


@pytest.mark.asyncio
async def test_call_tool_pause_without_a_backend_says_how_to_get_review():
    """PAUSE / REQUIRE_APPROVAL with no backend configured: refused, and the message names what review needs."""
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(
            decision="REQUIRE_APPROVAL",
            reason_codes=["NEEDS_HUMAN_REVIEW"],
        ))
        client = await _drive_proxy(stack, {
            "x": [{"name": "deploy"}],
        }, hiitl)
        result = await client.call_tool("deploy", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        # The message must say approval is needed and name the two settings the review flow needs.
        assert "human approval" in msg.lower()
        assert "`server_url`" in msg and "`api_key`" in msg
        assert "not forwarded" in msg
        # The original reason code is still echoed.
        assert "NEEDS_HUMAN_REVIEW" in msg


@pytest.mark.asyncio
async def test_call_tool_pause_records_evaluate_call():
    """The original PAUSE decision goes through evaluate() (and thus audit).

    The proxy maps PAUSE → BLOCK on the response side, but the SDK has
    already recorded the PAUSE decision in its audit log. Verify the
    evaluate call happened — Block 3b's review-case API will pick up
    these audit rows.
    """
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="PAUSE"))
        client = await _drive_proxy(stack, {
            "x": [{"name": "risky"}],
        }, hiitl)
        await client.call_tool("risky", {"k": "v"})
        assert hiitl.calls == [("risky", {"k": "v"})]


@pytest.mark.asyncio
async def test_call_tool_upstream_error_propagates_as_mcp_error():
    """A handler crash on the upstream surfaces as an error, not a hang."""
    def boom(_args):
        raise RuntimeError("kaboom")

    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="ALLOW"))
        client = await _drive_proxy(stack, {
            "x": [{"name": "fragile", "handler": boom}],
        }, hiitl)
        result = await client.call_tool("fragile", {})
        # The upstream raises McpError inside its handler; the SDK
        # converts that into an error CallToolResult on our end.
        assert result.isError


@pytest.mark.asyncio
async def test_call_tool_unknown_tool_returns_error():
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="ALLOW"))
        client = await _drive_proxy(stack, {
            "x": [{"name": "known_tool"}],
        }, hiitl)
        result = await client.call_tool("not_a_real_tool", {})
        # Unknown tool name → the proxy refuses with INVALID_PARAMS.
        # The client surfaces this as an error CallToolResult.
        assert result.isError


# ============================================================================
# Multi-upstream routing
# ============================================================================


@pytest.mark.asyncio
async def test_call_tool_route_decision_uses_route_placeholder():
    """ROUTE → its own placeholder message (not the generic block text)."""
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(
            decision="ROUTE",
            reason_codes=["NEEDS_HUMAN_REVIEW_VIA_ROUTE"],
        ))
        client = await _drive_proxy(stack, {
            "x": [{"name": "high_risk_op"}],
        }, hiitl)
        result = await client.call_tool("high_risk_op", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "ROUTE" in msg
        # Reason code is echoed so the agent / user knows why.
        assert "NEEDS_HUMAN_REVIEW_VIA_ROUTE" in msg


@pytest.mark.asyncio
async def test_upstream_timeout_produces_clear_error():
    """A hanging upstream surfaces as an MCP error mentioning the timeout.

    Built around a handler that blocks forever; we set timeout_seconds
    very low in the proxy config so the test runs fast.
    """
    import asyncio as _asyncio

    async def _hang(_args):
        await _asyncio.sleep(60)  # Way past the timeout we configure.

    async with AsyncExitStack() as stack:
        # Need to build the proxy with a custom config (low timeout).
        mgr = await _manager_with_fake_upstreams(stack, {
            "slow": [{"name": "slow_op", "handler": _hang}],
        })
        from hiitl.mcp_proxy.config import ProxyConfig, StdioServerConfig
        from hiitl.mcp_proxy.proxy import build_proxy_server
        config = ProxyConfig(
            servers={"slow": StdioServerConfig(command="x")},
            timeout_seconds=0.1,
        )
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="ALLOW"))
        proxy_server = build_proxy_server(config, mgr, hiitl)  # type: ignore[arg-type]
        client = await stack.enter_async_context(
            create_connected_server_and_client_session(proxy_server)
        )
        await client.initialize()
        result = await client.call_tool("slow_op", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        # Message should make the timeout visible and tell the user
        # where the budget comes from.
        assert "did not respond" in msg
        assert "timeout_seconds" in msg


@pytest.mark.asyncio
async def test_multi_upstream_routes_to_correct_server():
    """A call to tool X goes to the upstream that owns X, not some other one."""
    async with AsyncExitStack() as stack:
        hiitl = _FakeHiitl(lambda n, a: _FakeDecision(decision="ALLOW"))
        client = await _drive_proxy(stack, {
            "email":    [{"name": "send_email", "handler": lambda a: "from-email"}],
            "database": [{"name": "query_db",   "handler": lambda a: "from-database"}],
        }, hiitl)

        email_result = await client.call_tool("send_email", {})
        assert any(
            getattr(c, "text", "") == "from-email" for c in email_result.content
        )

        db_result = await client.call_tool("query_db", {})
        assert any(
            getattr(c, "text", "") == "from-database" for c in db_result.content
        )
