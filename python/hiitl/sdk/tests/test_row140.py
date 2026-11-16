"""Row 140 (HTL-29): the SDK sends only over TLS, and only the credential it can read.

routes.md Validation Rules, "`endpoint` is an `https` URL" and "The party that sends reads the `auth`"; sync_engine.md
section 8, a `server_url` that is not https "is refused when the client is constructed, naming it". Design: the
HTL-29 test design, row 140, behaviors 5-9. Mirrors typescript/packages/sdk/tests/unit/row140.test.ts.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from hiitl.sdk.client import HIITL
from hiitl.sdk.config import HostedModeConfig, SyncConfig
from hiitl.sdk.exceptions import ConfigurationError, RouteLoadError, ServerError, SyncError
from hiitl.sdk.route_loader import RouteLoader
from hiitl.sdk.sync_client import SyncClient

ORG = "org_test000000000000000"
KEY = "sk_test_1234567890abcdef"
POLICY = """
version: "v1.0.0"
description: "Refunds are checked before they are paid"
scope:
  org_id: org_test000000000000000
  environment: dev
name: refund_policy
rules:
  - name: ask_refund_check
    priority: 500
    conditions: {field: action, operator: equals, value: issue_refund}
    decision: ROUTE
    reason_code: REFUND_CHECK
    route: refund-check
    description: Refunds are checked before they are paid
  - name: allow_otherwise
    priority: 1
    conditions: {field: action, operator: exists, value: true}
    decision: ALLOW
    reason_code: ALLOWED
    description: Everything else
"""


def _route(**over):
    r = {"name": "refund-check", "version": "v1.0.0", "direction": "bidirectional", "timing": "sync",
         "endpoint": "https://risk.example/v1/refunds",
         "auth": {"type": "bearer_token", "secret_ref": "env:HIITL_TEST_RISK_TOKEN"},
         "response_schema": {"decision_options": ["approve", "deny"], "required_fields": ["verdict"]},
         "sla": {"timeout": "5s", "timeout_action": "fail_closed"}}
    r.update(over)
    return r


@pytest.fixture
def routes(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_TEST_RISK_TOKEN", "r1sk")
    (tmp_path / "policy.yaml").write_text(POLICY)
    (tmp_path / "routes").mkdir()

    def write(route):
        path = tmp_path / "routes" / f"{route['name']}.json"
        path.write_text(json.dumps(route))
        return path
    return tmp_path, write


def _client(tmp_path, seen, answer=lambda r: httpx.Response(200, json={"verdict": "approve"})):
    def h(request):
        seen.append(request)
        return answer(request)
    return HIITL(environment="dev", agent_id="refunder", org_id=ORG, policy_path=str(tmp_path / "policy.yaml"),
                 routes_path=str(tmp_path / "routes"), audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY",
                 route_client=httpx.Client(transport=httpx.MockTransport(h)))


REFUSED = [
    ({"auth": {"type": "hmac_sha256", "secret_ref": "env:HIITL_TEST_RISK_TOKEN"}}, "'hmac_sha256'"),
    ({"auth": {"type": "bearer_token", "secret_ref": "vault:risk/token"}}, "'vault:risk/token'"),
    ({"auth": {"type": "api_key", "secret_ref": "env:HIITL_TEST_UNSET_TOKEN"}}, "HIITL_TEST_UNSET_TOKEN, which is unset"),
    ({"endpoint": "http://127.0.0.1:9000/v1/refunds"}, "'http://127.0.0.1:9000/v1/refunds'"),
]


@pytest.mark.parametrize("over,cause", REFUSED)
def test_the_loader_refuses_a_route_it_cannot_send_naming_the_file_and_why(routes, monkeypatch, over, cause):
    tmp_path, write = routes
    monkeypatch.delenv("HIITL_TEST_UNSET_TOKEN", raising=False)
    path = write(_route(**over))
    with pytest.raises(RouteLoadError) as e:
        RouteLoader(str(tmp_path / "routes")).get("refund-check")
    assert str(path) in str(e.value) and cause in str(e.value)


def test_an_inbound_route_s_auth_is_not_read_at_load(routes):
    tmp_path, write = routes
    write({"name": "risk-signals", "version": "v1.0.0", "direction": "inbound", "timing": "async",
           "auth": {"type": "hmac_sha256", "secret_ref": "vault:risk/signing"},
           "inbound": {"permissions": {"can_signal": True}}})
    assert RouteLoader(str(tmp_path / "routes")).get("risk-signals").name == "risk-signals"


@pytest.mark.parametrize("over,cause", REFUSED)
def test_through_evaluate_the_refusal_fails_closed_and_sends_nothing(routes, monkeypatch, caplog, over, cause):
    tmp_path, write = routes
    monkeypatch.delenv("HIITL_TEST_UNSET_TOKEN", raising=False)
    write(_route(**over))
    seen = []
    with caplog.at_level(logging.ERROR):
        d = _client(tmp_path, seen).evaluate("issue_refund", parameters={"amount": 120})
    assert (d.decision, d.allowed, d.reason_codes) == ("POLICY_ERROR", False, ["POLICY_EVALUATION_FAILED"])
    assert seen == [], "the route is not asked"
    assert cause in caplog.text, "the log names the cause"


def test_an_auth_unsendable_at_the_ask_is_unanswered_not_sent_bare(routes, monkeypatch):
    tmp_path, write = routes
    write(_route())
    seen = []
    h = _client(tmp_path, seen)
    assert h.evaluate("issue_refund", parameters={"amount": 120}).decision == "ALLOW"
    assert seen[0].headers["Authorization"] == "Bearer r1sk"
    monkeypatch.delenv("HIITL_TEST_RISK_TOKEN")
    d = h.evaluate("issue_refund", parameters={"amount": 120})
    assert (d.decision, d.allowed, d.route_ref) == ("ROUTE", False, "refund-check")
    assert "ROUTE_UNANSWERED" in d.reason_codes and "HIITL_TEST_RISK_TOKEN" in d.routes[0].error
    assert len(seen) == 1, "nothing is sent without the credential its route declares"


def test_api_key_defaults_to_the_authorization_header_through_a_real_ask(routes):
    tmp_path, write = routes
    write(_route(auth={"type": "api_key", "secret_ref": "env:HIITL_TEST_RISK_TOKEN"}))
    seen = []
    assert _client(tmp_path, seen).evaluate("issue_refund", parameters={"amount": 120}).decision == "ALLOW"
    (req,) = seen
    assert req.headers["Authorization"] == "r1sk" and "X-Api-Key" not in req.headers


HTTP = ["http://api.hiitl.example", "http://127.0.0.1:8000", "http://localhost:8000"]


@pytest.fixture
def no_server_variable(monkeypatch):
    for name in ("HIITL_SERVER_URL", "HIITL_API_KEY", "HIITL_EVALUATION", "HIITL_SIGNATURE_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("url", HTTP)
def test_every_server_url_that_carries_the_key_is_https(tmp_path, monkeypatch, no_server_variable, url):
    hosted = dict(environment="dev", agent_id="a", org_id=ORG, api_key=KEY)
    with pytest.raises(ValidationError, match=f"server_url \\(HIITL_SERVER_URL\\) is '{url}'"):
        HostedModeConfig(server_url=url, **hosted)
    with pytest.raises(ValidationError, match=f"server_url \\(HIITL_SERVER_URL\\) is '{url}'"):
        SyncConfig(server_url=url)
    with pytest.raises(ConfigurationError, match=f"is '{url}'"):
        HIITL(api_key=KEY, server_url=url, audit_db_path=str(tmp_path / "a.db"))
    with pytest.raises(ConfigurationError, match=f"is '{url}'"):
        HIITL(api_key=KEY, server_url=url, evaluation="remote", signature_key="s" * 32,
              audit_db_path=str(tmp_path / "a.db"))
    with pytest.raises(ConfigurationError, match=f"server_url is '{url}'"):
        SyncClient(server_url=url, api_key=KEY, org_id=ORG, environment="dev")
    monkeypatch.setenv("HIITL_SERVER_URL", url)
    with pytest.raises(ConfigurationError, match=f"HIITL_SERVER_URL\\) is '{url}'"):
        HIITL(api_key=KEY, audit_db_path=str(tmp_path / "a.db"))


@pytest.mark.parametrize("url", HTTP)
def test_a_server_url_is_refused_when_the_client_is_constructed_whatever_the_mode(tmp_path, monkeypatch,
                                                                                  no_server_variable, url):
    """sync_engine.md section 8 names no mode: a local client given one refuses it as a hybrid one does."""
    with pytest.raises(ConfigurationError, match=f"HIITL_SERVER_URL\\) is '{url}'"):
        HIITL(server_url=url, audit_db_path=str(tmp_path / "a.db"))
    monkeypatch.setenv("HIITL_SERVER_URL", url)
    with pytest.raises(ConfigurationError, match=f"HIITL_SERVER_URL\\) is '{url}'"):
        HIITL(audit_db_path=str(tmp_path / "a.db"))


def test_an_https_server_url_passes_and_its_trailing_slash_is_stripped(no_server_variable):
    assert SyncConfig(server_url="https://sync.example/").server_url == "https://sync.example"
    hosted = HostedModeConfig(server_url="https://127.0.0.1:8443/", environment="dev", agent_id="a", org_id=ORG,
                              api_key=KEY)
    assert hosted.server_url == "https://127.0.0.1:8443"
    assert SyncConfig().server_url.startswith("https://"), "the default is https"


# sync_engine.md section 8: a send goes only to the URL its check read, so no sender follows a redirect; a 3xx is the
# endpoint's answer, read as any answer that is not a success (HTL-29 review, condition 1). Each sender is handed an
# endpoint that redirects every https request to the same path over http, where a request would be answered.

def _redirecting(seen, answer):
    def respond(request):
        seen.append(request)
        if request.url.scheme == "https":
            return httpx.Response(307, headers={"Location": str(request.url.copy_with(scheme="http"))})
        return answer
    return respond


def _served(monkeypatch, respond):
    """Every request the client's own transport would send, answered by `respond`: the client's redirect setting is
    the one it was built with."""
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: respond(request))


def test_the_hosted_call_follows_no_redirect(tmp_path, monkeypatch, no_server_variable):
    seen = []
    decision = {"action_id": "act_x", "decision": "ALLOW", "allowed": True, "reason_codes": [], "policy_version": "v"}
    _served(monkeypatch, _redirecting(seen, httpx.Response(200, json=decision)))
    h = HIITL(api_key=KEY, server_url="https://ecp.example", evaluation="remote", max_retries=0,
              signature_key="s" * 32, audit_db_path=str(tmp_path / "a.db"))
    with pytest.raises(ServerError) as e:
        h.evaluate("issue_refund", parameters={"amount": 120})
    assert e.value.status_code == 307, "the redirect is the service's answer"
    assert [str(r.url) for r in seen] == ["https://ecp.example/v1/evaluate"], "nothing is sent to its Location"


def test_the_sync_client_follows_no_redirect(monkeypatch):
    seen = []
    _served(monkeypatch, _redirecting(seen, httpx.Response(200, json={"kill_switches": []})))
    sync = SyncClient(server_url="https://sync.example", api_key=KEY, org_id=ORG, environment="dev", max_retries=0)
    with pytest.raises(SyncError, match="status 307"):
        sync.poll_kill_switches()
    assert [r.url.scheme for r in seen] == ["https"], "the key is not sent to the redirect's Location"


def test_the_route_ask_follows_no_redirect_though_the_client_it_is_handed_would(routes):
    tmp_path, write = routes
    write(_route())
    seen = []
    handler = _redirecting(seen, httpx.Response(200, json={"verdict": "approve"}))
    h = HIITL(environment="dev", agent_id="refunder", org_id=ORG, policy_path=str(tmp_path / "policy.yaml"),
              routes_path=str(tmp_path / "routes"), audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY",
              route_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    d = h.evaluate("issue_refund", parameters={"amount": 120})
    assert (d.decision, d.allowed) == ("ROUTE", False) and "ROUTE_UNANSWERED" in d.reason_codes
    assert "the route answered 307" in d.routes[0].error
    assert [str(r.url) for r in seen] == ["https://risk.example/v1/refunds"], "its credential goes nowhere else"
