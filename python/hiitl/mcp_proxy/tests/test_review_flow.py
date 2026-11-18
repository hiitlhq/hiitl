"""Block 3b — proxy ↔ review-case backend tests via a mock backend.

The full PAUSE flow involves: proxy → POST /v1/reviews → SSE open →
wait → resolve → SSE event → proxy decision. We don't want to spin up
the real FastAPI backend for proxy unit tests; instead we build a tiny
in-process "review backend" that speaks the same protocol shape and
inject it into the proxy via an `httpx.MockTransport`.

Covered:
- PAUSE → approved → upstream is forwarded with original args, result
  flows back to the MCP client.
- PAUSE → modified → upstream is forwarded with the reviewer's args,
  not the original.
- PAUSE → rejected → MCP error with reviewer's reason.
- PAUSE → timed_out → MCP error mentioning timeout.
- PAUSE → backend unreachable (HTTP error) → safe-by-default MCP error,
  upstream is NOT forwarded.
- ROUTE decision keeps its own message (server_url present or not).
- PAUSE with no server_url asks no reviewer; the message names the setting.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
import pytest
from mcp import types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session

from hiitl.mcp_proxy.config import ProxyConfig, StdioServerConfig
from hiitl.mcp_proxy.proxy import build_proxy_server


# Reuse the fake-upstream + fake-HIITL helpers from the integration suite.
from hiitl.mcp_proxy.tests.test_proxy_integration import (
    _FakeDecision,
    _FakeHiitl,
    _manager_with_fake_upstreams,
)


# ============================================================================
# Mock review backend
# ============================================================================


class _MockReviewBackend:
    """Minimal in-process simulation of /v1/reviews + /stream.

    Resolution is driven by the test: call `resolve(case_id, status, ...)`
    to make the next SSE read for that case_id deliver that outcome.
    """

    def __init__(self):
        # case_id → outcome dict
        self._resolutions: dict[str, dict[str, Any]] = {}
        # case_id → created data
        self._cases: dict[str, dict[str, Any]] = {}
        # Manual delay before SSE emits — None means "immediate".
        self.delay_before_emit: float = 0.0
        # Force POST /v1/reviews to fail.
        self.create_fails: bool = False

    def resolve(self, case_id: str, *, status: str, **kwargs) -> None:
        self._resolutions[case_id] = {"status": status, **kwargs}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/reviews" and request.method == "POST":
            return self._handle_create(request)
        if path.startswith("/v1/reviews/") and path.endswith("/stream"):
            return await self._handle_stream(path)
        return httpx.Response(404, json={"detail": "not found in mock"})

    def _handle_create(self, request: httpx.Request) -> httpx.Response:
        if self.create_fails:
            return httpx.Response(500, json={"detail": "mock failure"})
        body = json.loads(request.content)
        case_id = f"rev_test_{len(self._cases):04d}"
        self._cases[case_id] = body
        return httpx.Response(201, json={
            "case_id": case_id,
            "org_id": "org_test",
            "environment": "dev",
            "action_id": body.get("action_id", ""),
            "envelope": body.get("envelope", {}),
            "decision": body.get("decision", {}),
            "policy_version": body.get("policy_version", ""),
            "rule_name": body.get("rule_name"),
            "status": "pending",
            "reviewer_id": None,
            "reviewer_response": None,
            "created_at": "2026-05-12T00:00:00Z",
            "resolved_at": None,
            "timeout_at": "2026-05-12T00:05:00Z",
        })

    async def _handle_stream(self, path: str) -> httpx.Response:
        case_id = path.split("/")[3]
        if self.delay_before_emit:
            await asyncio.sleep(self.delay_before_emit)
        outcome = self._resolutions.get(case_id)
        if outcome is None:
            # No pre-set resolution — emit timeout immediately to simulate
            # the open-time-already-expired branch on the real backend.
            sse = (
                "event: timeout\n"
                f"data: {json.dumps({'case_id': case_id})}\n\n"
            )
        else:
            payload = {
                "case_id": case_id,
                "status": outcome["status"],
                "reviewer_response": {
                    k: v for k, v in outcome.items() if k != "status"
                },
            }
            sse = (
                "event: resolved\n"
                f"data: {json.dumps(payload)}\n\n"
            )
        return httpx.Response(
            200,
            content=sse.encode("utf-8"),
            headers={"Content-Type": "text/event-stream"},
        )


# ============================================================================
# Harness: drive the proxy with a fake hiitl + fake review backend
# ============================================================================


async def _drive_proxy_with_review_backend(
    stack: AsyncExitStack,
    *,
    upstreams: dict[str, list[dict[str, Any]]],
    decision_factory: Callable[[str, dict], _FakeDecision],
    backend: _MockReviewBackend,
    server_url: str = "https://hiitl.test",
    api_key: str = "sk-hiitl-test",
):
    """Build the proxy with a real fake-MCP upstream + a fake review backend."""
    mgr = await _manager_with_fake_upstreams(stack, upstreams)
    config = ProxyConfig(
        servers={k: StdioServerConfig(command="x") for k in upstreams},
        server_url=server_url,
        api_key=api_key,
        review_timeout_seconds=15,
        timeout_seconds=15.0,
    )
    hiitl = _FakeHiitl(decision_factory)
    # The proxy code uses `httpx.AsyncClient(...)` inside request_review.
    # Monkey-patch it to use our mock transport for THIS test session.
    from hiitl.mcp_proxy import review_client as _rc
    original_async_client = _rc.httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        # Replace timeout/transport with our mock; preserve other kwargs.
        kwargs["transport"] = httpx.MockTransport(backend.handle)
        return original_async_client(*args, **kwargs)

    _rc.httpx.AsyncClient = _client_factory  # type: ignore[attr-defined]
    stack.callback(lambda: setattr(_rc.httpx, "AsyncClient", original_async_client))

    proxy_server = build_proxy_server(config, mgr, hiitl)  # type: ignore[arg-type]
    client = await stack.enter_async_context(
        create_connected_server_and_client_session(proxy_server)
    )
    await client.initialize()
    return client, hiitl


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_pause_approved_forwards_with_original_args():
    backend = _MockReviewBackend()

    received_args: dict[str, Any] = {}
    def _capture(args):
        received_args.update(args)
        return "approved-and-ran"

    async with AsyncExitStack() as stack:
        client, hiitl = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "do_thing", "handler": _capture}]},
            decision_factory=lambda n, a: _FakeDecision(decision="PAUSE"),
            backend=backend,
        )
        # Resolve before the proxy's SSE open — the mock backend will
        # see the resolution mapped to the first case_id it creates.
        backend.resolve("rev_test_0000", status="approved")
        result = await client.call_tool("do_thing", {"k": "original"})
        assert not result.isError
        assert any(getattr(c, "text", "") == "approved-and-ran" for c in result.content)
        # The upstream saw the ORIGINAL args (not the reviewer's, since
        # this was an "approved" outcome).
        assert received_args == {"k": "original"}


@pytest.mark.asyncio
async def test_pause_modified_forwards_with_modified_args():
    backend = _MockReviewBackend()

    received_args: dict[str, Any] = {}
    def _capture(args):
        received_args.update(args)
        return "ok"

    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "deploy", "handler": _capture}]},
            decision_factory=lambda n, a: _FakeDecision(decision="PAUSE"),
            backend=backend,
        )
        backend.resolve(
            "rev_test_0000",
            status="modified",
            modified_arguments={"env": "staging", "k": "modified"},
            reason="staging only — not prod",
        )
        result = await client.call_tool("deploy", {"env": "prod", "k": "original"})
        assert not result.isError
        # Reviewer's modified args were forwarded; original args were dropped.
        assert received_args == {"env": "staging", "k": "modified"}


@pytest.mark.asyncio
async def test_pause_rejected_returns_mcp_error_with_reason():
    backend = _MockReviewBackend()

    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "delete_db"}]},
            decision_factory=lambda n, a: _FakeDecision(decision="REQUIRE_APPROVAL"),
            backend=backend,
        )
        backend.resolve(
            "rev_test_0000",
            status="rejected",
            reason="Production deletion requires VP-Eng sign-off",
        )
        result = await client.call_tool("delete_db", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "rejected" in msg.lower()
        assert "VP-Eng" in msg


@pytest.mark.asyncio
async def test_pause_timed_out_returns_mcp_error():
    backend = _MockReviewBackend()  # No resolution set → backend emits "timeout".

    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "slow_op"}]},
            decision_factory=lambda n, a: _FakeDecision(decision="ESCALATE"),
            backend=backend,
        )
        result = await client.call_tool("slow_op", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "timed out" in msg.lower() or "timeout" in msg.lower()


@pytest.mark.asyncio
async def test_pause_backend_unreachable_fails_closed():
    """If the backend returns 500 on /v1/reviews creation, the proxy
    must NOT forward the tool call. Safe-by-default.
    """
    backend = _MockReviewBackend()
    backend.create_fails = True

    upstream_called = {"flag": False}
    def _watch(args):
        upstream_called["flag"] = True
        return "never-should-run"

    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "risky", "handler": _watch}]},
            decision_factory=lambda n, a: _FakeDecision(decision="PAUSE"),
            backend=backend,
        )
        result = await client.call_tool("risky", {})
        assert result.isError
        assert upstream_called["flag"] is False, (
            "Upstream was forwarded despite backend failure — fail-closed broken"
        )


@pytest.mark.asyncio
async def test_route_decision_uses_placeholder_even_with_server_url():
    """ROUTE still gets the route-specific placeholder; the review flow
    only handles PAUSE / REQUIRE_APPROVAL / ESCALATE.
    """
    backend = _MockReviewBackend()
    async with AsyncExitStack() as stack:
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "high_risk"}]},
            decision_factory=lambda n, a: _FakeDecision(
                decision="ROUTE",
                reason_codes=["NEEDS_ROUTE"],
            ),
            backend=backend,
        )
        result = await client.call_tool("high_risk", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "ROUTE" in msg


@pytest.mark.asyncio
async def test_pause_without_server_url_asks_no_reviewer():
    """If the proxy has no server_url, PAUSE asks no reviewer even when
    the user has an api_key: the backend is never called, and the
    message names the setting the review flow needs.
    """
    backend = _MockReviewBackend()
    async with AsyncExitStack() as stack:
        # server_url=None disables the review flow.
        client, _ = await _drive_proxy_with_review_backend(
            stack,
            upstreams={"x": [{"name": "do_x"}]},
            decision_factory=lambda n, a: _FakeDecision(decision="PAUSE"),
            backend=backend,
            server_url=None,  # type: ignore[arg-type]
        )
        result = await client.call_tool("do_x", {})
        assert result.isError
        msg = "".join(getattr(c, "text", "") for c in result.content)
        assert "`server_url`" in msg
        assert "no reviewer was asked" in msg
        assert backend._cases == {}
