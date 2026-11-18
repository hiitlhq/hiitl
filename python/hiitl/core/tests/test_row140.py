"""Row 140 (HTL-29): hiitl sends only over TLS, and only the credential it can read.

Security, "TLS everywhere. No exceptions."; sync_engine.md section 8, loopback included; routes.md Validation Rules,
"`endpoint` is an `https` URL" and "The party that sends reads the `auth`". Design: the HTL-29 test design,
row 140, behaviors 1-4, and row 236, behavior 1. Mirrors typescript/packages/core/tests/unit/row140.test.ts: both read
the URL table in tests/conformance/transport/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiitl.core import routing
from hiitl.core.route_types import Route
from hiitl.core.transport import https_refusal, written_authority

# One verdict per written value in both cores, from the one table both read (routes.md, read by its written form)
TABLE = Path(__file__).resolve().parents[4] / "tests" / "conformance" / "transport" / "case_001_written_urls.json"
URLS = [tuple(pair) for pair in json.loads(TABLE.read_text(encoding="utf-8"))["urls"]]


@pytest.mark.parametrize("url,sent", URLS)
def test_one_check_decides_where_hiitl_sends(url, sent):
    refusal = https_refusal(url, "server_url")
    if sent:
        assert refusal is None
    else:
        assert refusal and refusal.startswith(f"server_url is {url!r}.") and "https://<host>" in refusal


def test_a_port_of_more_digits_than_a_number_is_read_from_is_refused():
    url = "https://api.hiitl.com:" + "1" * 5000
    assert https_refusal(url, "server_url").startswith(f"server_url is {url!r}.")


def test_a_port_is_read_by_its_value_however_many_zeros_lead_it():
    """By its written form (routes.md, "a port is a number up to 65535"): the zeros that lead a port are not digits of
    its number, in both cores, however many there are (HTL-29 review, condition 7)."""
    url = "https://api.hiitl.com:" + "0" * 5000 + "443"
    try:
        refusal, authority = https_refusal(url, "server_url"), written_authority(url)
    except ValueError as exc:   # the check answers every value; a raise is a reading outside its handler
        raise AssertionError(f"the URL check raised {exc!r:.80}") from None
    assert refusal is None
    assert authority == ("api.hiitl.com", 443)


def _route(endpoint="https://checks.example/v1", *, auth=None, direction="bidirectional", name="content-check"):
    r = {"name": name, "version": "v1.0.0", "direction": direction, "timing": "sync"}
    if direction == "inbound":
        r["inbound"] = {"permissions": {"can_signal": True}}
    else:
        r.update({"endpoint": endpoint, "response_schema": {"decision_options": ["approve", "deny"]},
                  "sla": {"timeout": "5s", "timeout_action": "fail_closed"}})
    if auth:
        r["auth"] = auth
    return r


@pytest.mark.parametrize("endpoint", ["http://checks.example/v1", "http://127.0.0.1:9000/v1", "http://localhost/v1"])
def test_a_route_s_endpoint_is_https_loopback_included(endpoint):
    with pytest.raises(ValidationError) as e:
        Route.model_validate(_route(endpoint))
    assert f"route 'content-check' endpoint is {endpoint!r}" in str(e.value)
    assert Route.model_validate(_route(endpoint.replace("http://", "https://"))).endpoint.startswith("https://")


BEARER = {"type": "bearer_token", "secret_ref": "env:CHECKS_TOKEN"}


@pytest.mark.parametrize("auth,environ,names", [
    ({"type": "hmac_sha256", "secret_ref": "env:CHECKS_TOKEN"}, {"CHECKS_TOKEN": "s"}, "'hmac_sha256'"),
    ({"type": "mtls", "secret_ref": "env:CHECKS_TOKEN"}, {"CHECKS_TOKEN": "s"}, "'mtls'"),
    ({"type": "oauth2", "secret_ref": "env:CHECKS_TOKEN"}, {"CHECKS_TOKEN": "s"}, "'oauth2'"),
    ({"type": "bearer_token", "secret_ref": "vault:secret/checks"}, {}, "'vault:secret/checks'"),
    ({"type": "api_key", "secret_ref": "CHECKS_TOKEN"}, {"CHECKS_TOKEN": "s"}, "'CHECKS_TOKEN'"),
    ({"type": "api_key", "secret_ref": "env:"}, {"": "s"}, "'env:'"),
    (BEARER, {}, "CHECKS_TOKEN, which is unset or empty"),
    (BEARER, {"CHECKS_TOKEN": ""}, "CHECKS_TOKEN, which is unset or empty"),
])
def test_the_auth_the_sdk_cannot_send_is_named(auth, environ, names):
    route = _route(auth=auth)
    reason = routing.auth_refusal(route, environ)
    assert reason and reason.startswith("route 'content-check' ") and names in reason
    with pytest.raises(routing.RouteUnanswered) as e:
        routing.auth_headers(route, environ)
    assert str(e.value) == reason, "the ask is not sent without its credential, and says why"


def test_an_auth_it_can_send_or_none_or_an_inbound_one_is_not_refused():
    assert routing.auth_refusal(_route(auth=BEARER), {"CHECKS_TOKEN": "s"}) is None
    assert routing.auth_refusal(_route(), {}) is None
    inbound = _route(direction="inbound", auth={"type": "hmac_sha256", "secret_ref": "vault:x"})
    assert routing.auth_refusal(inbound, {}) is None, "an inbound route's auth is what its sender presents"
    assert routing.auth_refusal(Route.model_validate(inbound), {}) is None


@pytest.mark.parametrize("auth,headers", [
    ({"type": "bearer_token", "secret_ref": "env:CHECKS_TOKEN"}, {"Authorization": "Bearer s3"}),
    ({"type": "api_key", "secret_ref": "env:CHECKS_TOKEN"}, {"Authorization": "s3"}),
    ({"type": "api_key", "secret_ref": "env:CHECKS_TOKEN", "header": "X-Api-Key"}, {"X-Api-Key": "s3"}),
    ({"type": "bearer_token", "secret_ref": "env:CHECKS_TOKEN", "header": "X-Token"}, {"X-Token": "Bearer s3"}),
])
def test_the_header_carries_the_secret_and_defaults_to_authorization(auth, headers):
    environ = {"CHECKS_TOKEN": "s3"}
    assert routing.auth_headers(_route(auth=auth), environ) == headers
    assert routing.auth_headers(Route.model_validate(_route(auth=auth)), environ) == headers
    assert routing.auth_headers(_route(), environ) == {}
