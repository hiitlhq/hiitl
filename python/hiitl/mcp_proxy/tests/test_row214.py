"""Row 214 (HTL-23): an SSE upstream's headers by reference.

Ruled 2026-11-06 as the row reads: "`headers` take `secret_refs` in the same `env:<NAME>` form, by L264" (routes.md,
`secret_ref`: "Never stored in plaintext … References a secret manager key or environment variable"). Row 157's class
read at the other transport: an SSE upstream's header may name a gateway environment variable by reference, in a field
of its own, resolved when the gateway starts; an unset name fails the start, naming it; one validator checks both
transports' references. The cell reads the headers at the transport the gateway hands them to, the MCP library's
`sse_client`. Design: the HTL-23 test design, row 214.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

import mcp.client.sse
from hiitl.mcp_proxy.config import ProxyConfig, SseServerConfig, StdioServerConfig
from hiitl.mcp_proxy.upstream import UpstreamConnectError, UpstreamManager

TOKEN = "Bearer token-from-the-gateway-environment-7f3a"      # the value the gateway's environment holds
URL = "https://mcp.r214.example.com/github/sse"


class _Reached(Exception):
    """The transport was opened: what it was handed is recorded, and the start goes no further."""


@pytest.fixture
def opened(monkeypatch):
    seen: list[dict] = []

    @asynccontextmanager
    async def sse_client(url, headers=None, **_):
        seen.append({"url": url, "headers": dict(headers or {})})
        raise _Reached()
        yield  # pragma: no cover

    monkeypatch.setattr(mcp.client.sse, "sse_client", sse_client)
    return seen


async def _start(**upstream):
    cfg = ProxyConfig(servers={"github": SseServerConfig(url=URL, **upstream)})
    async with UpstreamManager(cfg) as manager:
        await manager.start()


@pytest.mark.asyncio
async def test_a_header_by_reference_reaches_the_upstream(opened, monkeypatch):
    """Behavior 1: the header named in `secret_refs` is sent with the variable's value, beside a literal one."""
    monkeypatch.setenv("GATEWAY_GITHUB_TOKEN", TOKEN)
    with pytest.raises(UpstreamConnectError):
        await _start(headers={"X-Client": "hiitl-gateway"},
                     secret_refs={"Authorization": "env:GATEWAY_GITHUB_TOKEN"})
    assert opened == [{"url": URL, "headers": {"X-Client": "hiitl-gateway", "Authorization": TOKEN}}]


@pytest.mark.asyncio
async def test_an_unset_name_fails_the_start(opened, monkeypatch):
    """Behavior 2: the start fails naming the header and the variable, and the upstream is never opened."""
    monkeypatch.delenv("GATEWAY_GITHUB_TOKEN", raising=False)
    with pytest.raises(UpstreamConnectError) as e:
        await _start(secret_refs={"Authorization": "env:GATEWAY_GITHUB_TOKEN"})
    message = str(e.value)
    assert all(name in message for name in ("GATEWAY_GITHUB_TOKEN", "Authorization", "'github'")), message
    assert opened == []


@pytest.mark.parametrize("ref", ["vault:hiitl/github/token", "GATEWAY_GITHUB_TOKEN", "env:", "${GATEWAY_GITHUB_TOKEN}"])
def test_a_reference_is_checked_as_stdios_is(ref):
    """Behavior 3: a reference outside `env:<NAME>` is refused as stdio's is, naming the entry; a header named in both
    fields, in any case (a header's name is case-insensitive), is refused naming it."""
    with pytest.raises(ValidationError) as sse:
        SseServerConfig(url=URL, secret_refs={"Authorization": ref})
    with pytest.raises(ValidationError) as stdio:
        StdioServerConfig(command="npx", secret_refs={"Authorization": ref})
    assert "Authorization" in str(sse.value) and ref in str(sse.value)
    assert sse.value.errors()[0]["msg"] == stdio.value.errors()[0]["msg"], "one validator"

    for literal in ("Authorization", "authorization"):
        with pytest.raises(ValidationError) as e:
            SseServerConfig(url=URL, headers={literal: "Bearer x"}, secret_refs={"Authorization": "env:A"})
        assert literal in str(e.value), "one header has one source"
