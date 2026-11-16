"""Row 140 (HTL-29): the gateway sends its API key only over TLS, and row 238: its SSE upstream too.

sync_engine.md section 8, a `server_url` that is not an `https` URL naming a host is refused, "every URL that carries
the `api_key`"; the gateway's `server_url` carries it to the SDK client and to the review flow alike. Row 238, ruled
2026-11-09: an SSE upstream's `url` is "https, refused at config load naming it", by "TLS everywhere. No exceptions."
Design: the HTL-29 test design, row 140, behaviors 10 and 16.
"""

from __future__ import annotations

import httpx
import pytest
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from hiitl.mcp_proxy.config import ProxyConfig, SseServerConfig, load_config
from hiitl.mcp_proxy.proxy import _apply_review_outcome
from hiitl.mcp_proxy.review_client import request_review
from hiitl.mcp_proxy.upstream import UpstreamConnectError, UpstreamManager

HTTP = ["http://api.hiitl.example", "http://127.0.0.1:8765", "http://localhost:8765"]
SERVERS = {"t": {"command": "x"}}


@pytest.mark.parametrize("url", HTTP)
def test_the_config_refuses_a_server_url_that_is_not_https_naming_it(tmp_path, url):
    with pytest.raises(ValidationError, match=f"server_url is '{url}'"):
        ProxyConfig.model_validate({"api_key": "sk_x", "server_url": url, "servers": SERVERS})
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(f"server_url: {url}\nservers:\n  t:\n    command: x\n", encoding="utf-8")
    with pytest.raises(ValidationError, match=f"server_url is '{url}'"):
        load_config(path, environ={"HIITL_API_KEY": "sk_from_the_environment"})


def test_an_https_server_url_loads():
    cfg = ProxyConfig.model_validate({"api_key": "sk_x", "server_url": "https://127.0.0.1:8765", "servers": SERVERS})
    assert cfg.server_url == "https://127.0.0.1:8765"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", HTTP)
async def test_the_review_flow_sends_nothing_to_a_server_url_that_is_not_https(url):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"case_id": "rc_1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        outcome = await request_review(
            server_url=url, api_key="sk_x", action_id="act_1", envelope={"action": "send_email"},
            decision={"decision": "REQUIRE_APPROVAL"}, policy_version="v1", rule_name="ask", timeout_seconds=5,
            original_arguments={}, http_client=client)
    assert seen == [], "the key is not sent"
    assert outcome.kind == "error" and outcome.reason.startswith(f"server_url is '{url}'.")
    with pytest.raises(McpError, match=f"server_url is '{url}'"):
        await _apply_review_outcome(outcome, "send_email", upstreams=None, timeout_seconds=5)   # fails closed


@pytest.mark.parametrize("url", HTTP)
def test_the_config_refuses_an_sse_upstream_that_is_not_https_naming_it(tmp_path, url):
    with pytest.raises(ValidationError, match=f"url is '{url}'"):
        SseServerConfig(url=url)
    with pytest.raises(ValidationError, match=f"url is '{url}'"):
        ProxyConfig.model_validate({"servers": {"remote": {"url": url}}})
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(f"servers:\n  remote:\n    url: {url}\n", encoding="utf-8")
    with pytest.raises(ValidationError, match=f"url is '{url}'"):
        load_config(path, environ={})


def test_an_https_sse_upstream_loads():
    cfg = ProxyConfig.model_validate({"servers": {"remote": {"url": "https://127.0.0.1:8765/sse"}}})
    assert cfg.servers["remote"].url == "https://127.0.0.1:8765/sse"


# sync_engine.md section 8: a send goes only to the URL its check read, so no sender follows a redirect; a 3xx is the
# endpoint's answer, read as any answer that is not a success (HTL-29 review, condition 1).

def _to_http(request: httpx.Request) -> httpx.Response:
    return httpx.Response(307, headers={"Location": str(request.url.copy_with(scheme="http"))})


@pytest.mark.asyncio
@pytest.mark.parametrize("leg, refused", [("case", "rejected review-case creation (HTTP 307)"),
                                          ("stream", "review stream returned HTTP 307")], ids=["case", "stream"])
async def test_the_review_flow_follows_no_redirect_though_the_client_it_is_handed_would(leg, refused):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.scheme == "https" and (leg == "case") == (request.method == "POST"):
            return _to_http(request)
        if request.method == "POST":
            return httpx.Response(201, json={"case_id": "rc_1"})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b'event: resolved\ndata: {"decision": "approve"}\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        outcome = await request_review(
            server_url="https://api.hiitl.example", api_key="sk_x", action_id="act_1",
            envelope={"action": "send_email"}, decision={"decision": "REQUIRE_APPROVAL"}, policy_version="v1",
            rule_name="ask", timeout_seconds=5, original_arguments={}, http_client=client)
    assert outcome.kind == "error" and refused in outcome.reason, outcome
    assert [r.url.scheme for r in seen] == ["https"] * len(seen), "the key goes nowhere else"


@pytest.mark.asyncio
async def test_the_sse_upstream_follows_no_redirect_off_its_origin(monkeypatch):
    """The SSE upstream is the mcp library's to send: from mcp 1.30, which the gateway requires, it follows a
    redirect only within the endpoint's origin, whatever its client's setting. A redirect to http is another origin,
    so the start fails and the upstream's header reaches nothing else."""
    seen: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.scheme == "https":
            return _to_http(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"event: endpoint\ndata: /messages\n\n")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    cfg = ProxyConfig(servers={"remote": SseServerConfig(url="https://mcp.example/sse",
                                                         headers={"X-Api-Key": "upstream-key"})})
    with pytest.raises(UpstreamConnectError):
        async with UpstreamManager(cfg) as manager:
            await manager.start()
    assert [str(r.url) for r in seen] == ["https://mcp.example/sse"], "nothing is sent to the redirect's Location"
