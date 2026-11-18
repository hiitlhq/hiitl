"""Row 198 (HTL-23): `status()` names the hosted breaker.

Ruled 2026-11-06 as the row reads: "no setting until a caller needs one, by 'new things must earn their place', and
`status()` reports the hosted breaker's state as it reports the sync breaker's, by 'no silent degradation'". The
contract is decision_response.md "Where the error is answered" ("`status()` names its state in both SDKs ...
`circuit_breakers.hosted`"). Design: the HTL-23 test design, row 198. Mirrors
typescript/packages/sdk/tests/unit/row198.test.ts.
"""

from __future__ import annotations

import inspect
import os

import httpx
import pytest

from hiitl.sdk.circuit_breaker import CircuitBreaker
from hiitl.sdk.client import HIITL

ORG_ID = "org_r198breaker000000000"
SERVER = "https://ecp.r198.example.com"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell, and the retries' backoff does not wait in real time."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("hiitl.sdk.http_client.time.sleep", lambda _seconds: None)


def _defaults() -> dict:
    """CircuitBreaker's own defaults, read from its signature."""
    return {name: p.default for name, p in inspect.signature(CircuitBreaker).parameters.items()
            if p.default is not inspect.Parameter.empty}


def test_a_hosted_clients_status_names_its_breaker(httpx_mock, tmp_path):
    """Behaviors 1 and 2: `circuit_breakers.hosted` is closed at start, open after the outages that open it, and runs
    at the class's defaults; once open, a call sends nothing."""
    h = HIITL(environment="dev", agent_id="r198-agent", org_id=ORG_ID, api_key="sk_test_r198breaker0000",
              server_url=SERVER, evaluation="remote", signature_key="r198-signing-secret-0123456789abcdef",
              audit_db_path=str(tmp_path / "audit.db"), max_retries=0)
    assert "hosted" in h.status().get("circuit_breakers", {}), "a hosted client's status names its breaker"
    assert h.status()["circuit_breakers"]["hosted"]["state"] == "closed"

    threshold = _defaults()["failure_threshold"]
    for _ in range(threshold):
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    for _ in range(threshold):
        assert h.evaluate("send_email").decision == "CONTROL_PLANE_UNAVAILABLE"
    assert len(httpx_mock.get_requests()) == threshold, "each outage is one send"

    breaker = h.status()["circuit_breakers"]["hosted"]
    assert breaker["state"] == "open"
    assert {k: breaker[k] for k in _defaults()} == _defaults(), "the breaker runs at the class's defaults"

    after = h.evaluate("send_email")
    h.close()
    assert after.reason_codes == ["CIRCUIT_BREAKER_OPEN"]
    assert len(httpx_mock.get_requests()) == threshold, "an open breaker sends nothing, not even a push"


def test_the_hosted_breaker_has_no_setting():
    """Behavior 2: no option of the client names a setting the breaker takes."""
    assert not set(inspect.signature(HIITL).parameters) & set(_defaults())
