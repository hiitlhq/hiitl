"""Row 174 (HTL-22): an unreachable hosted service is the outage decision, behind the circuit breaker.

decision_response.md, Error Handling: "`CONTROL_PLANE_UNAVAILABLE` - ECP is unreachable", its causes and its
"An outage" bullet; Example 9's `metadata {fail_mode, circuit_breaker_state}` and its caller action, "Circuit breaker
is open - subsequent calls will fail fast". R-0002: "Configurable fail mode: FAIL_CLOSED (default) or FAIL_OPEN",
"circuit breaker". The outage's record and the fail mode turned with Stop B (HTL-23 row 192, ruled 2026-11-06).
Design: the HTL-22 test design, row 174; the HTL-23 test design, row 192, behaviors 1 and 2. Mirrors
typescript/packages/sdk/tests/unit/row174.test.ts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from hiitl.core.canonical import envelope_hash, envelope_signature
from hiitl.core.error_decisions import FAIL_OPEN_MESSAGES, MESSAGES
from hiitl.core.types import DecisionType, ENVELOPE_SCHEMA_VERSION
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.circuit_breaker import CircuitState
from hiitl.sdk.client import HIITL
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import ServerError
from hiitl.sdk.http_client import HostedClient

SPEC = (Path(__file__).resolve().parents[4] / "docs" / "specs" / "decision_response.md").read_text(encoding="utf-8")

ORG_ID = "org_r174outage000000000"
SERVER = "https://ecp.r174.example.com"
URL = f"{SERVER}/v1/evaluate"
PUSH = f"{SERVER}/v1/sync/audit"
# The service's answer to the push of a held record (sync_engine.md §2.1). Row 192 (Stop B (i)): before its next call
# is sent, the client pushes the outage's record; these cells read the call behind it.
PUSHED = {"accepted": 1, "duplicates": 0, "errors": []}
API_KEY = "sk_test_r174outage0000"
SECRET = "r174-signing-secret-0123456789abcdef"
UNAVAILABLE = DecisionType.CONTROL_PLANE_UNAVAILABLE

# What a proxy in front of the service answers when the service behind it does not
GATEWAY_PAGE = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center></body></html>"

BLOCK_DECISION = {
    "action_id": "act_r174outage000000000000", "decision": "BLOCK", "allowed": False,
    "reason_codes": ["AMOUNT_OVER_LIMIT"], "policy_version": "v1.0.0", "timing": {"total_ms": 1.0},
}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """The retries' backoff waits in real time; the cells read what the client answered, not how long it waited."""
    monkeypatch.setattr("hiitl.sdk.http_client.time.sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def _store_in_tmp(monkeypatch, tmp_path):
    """An outage is recorded at `audit_db_path` (row 192), whose default is in the working directory: each cell's is
    its own."""
    monkeypatch.chdir(tmp_path)


def _client(**overrides) -> HostedClient:
    return HostedClient(HostedModeConfig(
        environment="dev", agent_id="r174-agent", org_id=ORG_ID, api_key=API_KEY, server_url=SERVER, **overrides))


def _envelope() -> dict:
    """A signed envelope as HIITL._build_envelope records it (the HostedClient's input)."""
    env = {
        "schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": ORG_ID, "environment": "dev", "agent_id": "r174-agent",
        "action_id": "act_r174outage000000000000", "idempotency_key": "idem_r174", "action": "send_email",
        "operation": "execute", "timestamp": "2026-11-05T12:00:00Z", "target": {}, "parameters": {},
        "signature_version": "hmac-sha256-v1",
    }
    env["signature"] = envelope_signature(SECRET, env)
    return env


def _decided(client: HostedClient, env: dict | None = None):
    """What evaluate answered, which for an outage is a decision, never an exception."""
    try:
        return client.evaluate(env or _envelope())
    except Exception as raised:  # the cell asserts on what was raised
        raise AssertionError(f"an outage is a decision, never an exception: {raised!r}") from raised


def _hiitl(**overrides) -> HIITL:
    return HIITL(environment="dev", agent_id="r174-agent", org_id=ORG_ID, api_key=API_KEY, server_url=SERVER,
                 evaluation="remote", signature_key=SECRET, **overrides)


def _causes() -> set[str]:
    """The causes Error Handling's CONTROL_PLANE_UNAVAILABLE line names, the decision itself left out."""
    line = re.search(r"^- `CONTROL_PLANE_UNAVAILABLE` - .*$", SPEC, re.M).group(0)
    return set(re.findall(r"`([A-Z_]+)`", line)) - {"CONTROL_PLANE_UNAVAILABLE"}


def _schema_metadata() -> dict:
    block = SPEC.split("### JSON Schema", 1)[1].split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)["properties"]["metadata"]


def test_an_unreachable_service_is_the_outage_decision(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("Connection refused by r174-host"), url=URL)
    client, env = _client(), _envelope()
    d = _decided(client, env)
    client.close()

    assert (d.decision, d.allowed, d.reason_codes, d.error.code) == (
        UNAVAILABLE, False, ["CONTROL_PLANE_UNREACHABLE"], "CONTROL_PLANE_UNAVAILABLE")
    assert d.error.message == MESSAGES["CONTROL_PLANE_UNREACHABLE"]
    assert "r174-host" not in d.error.message and SERVER not in d.error.message, "the cause is logged, not shown"
    assert d.metadata.model_dump() == {"fail_mode": "FAIL_CLOSED", "circuit_breaker_state": "closed"}
    assert d.envelope_hash == envelope_hash(env)


def test_a_timeout_on_every_attempt_is_control_plane_timeout(httpx_mock):
    retries = 2
    for _ in range(retries + 1):  # one answer per attempt
        httpx_mock.add_exception(httpx.ReadTimeout("no answer from r174-host"), url=URL)
    client = _client(max_retries=retries)
    d = _decided(client)
    client.close()

    assert len(httpx_mock.get_requests()) == retries + 1, "every attempt the client is configured for"
    assert (d.decision, d.allowed, d.reason_codes) == (UNAVAILABLE, False, ["CONTROL_PLANE_TIMEOUT"])
    assert d.error.message == MESSAGES["CONTROL_PLANE_TIMEOUT"]


def test_a_transient_status_the_service_did_not_answer_is_an_outage(httpx_mock):
    client = _client(max_retries=0)
    httpx_mock.add_response(url=URL, status_code=502, html=GATEWAY_PAGE)
    outage = _decided(client)
    assert (outage.decision, outage.reason_codes) == (UNAVAILABLE, ["CONTROL_PLANE_UNREACHABLE"])

    httpx_mock.add_response(url=PUSH, json=PUSHED)  # the outage's record, pushed before the next call (row 192)
    httpx_mock.add_response(url=URL, status_code=503, json={"detail": {"error": "UNAVAILABLE", "message": "Try again."}})
    with pytest.raises(ServerError) as served:
        client.evaluate(_envelope())
    assert (served.value.status_code, served.value.error_code) == (503, "UNAVAILABLE"), \
        "the service's error format is the service's answer (row 145)"

    httpx_mock.add_response(url=URL, status_code=503, json=BLOCK_DECISION)
    answered = _decided(client)
    assert (answered.decision, answered.reason_codes) == (DecisionType.BLOCK, ["AMOUNT_OVER_LIMIT"]), \
        "a decision is the service's answer, on any status"

    httpx_mock.add_response(url=URL, status_code=500, json={"detail": "Internal server error"})
    with pytest.raises(ServerError) as raised:
        client.evaluate(_envelope())
    assert raised.value.status_code == 500, "a status the client does not retry on is the service's answer"

    httpx_mock.add_response(url=URL, status_code=429, html=GATEWAY_PAGE)
    limited = _decided(client)
    assert (limited.decision, limited.reason_codes) == (UNAVAILABLE, ["CONTROL_PLANE_UNREACHABLE"]), \
        "429 is in the transient set: one the service did not answer is the outage (row 199)"
    client.close()


def test_the_breaker_opens_and_the_next_call_fails_fast(httpx_mock):
    client = _client(max_retries=0)
    threshold = client._breaker.failure_threshold
    for _ in range(threshold):  # one answer per call: its evaluate, or after the first the push before it (row 192)
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    states = [_decided(client).metadata.circuit_breaker_state for _ in range(threshold)]
    assert states == ["closed"] * (threshold - 1) + ["open"]

    sent = len(httpx_mock.get_requests())
    held = _decided(client)
    client.close()
    assert len(httpx_mock.get_requests()) == sent, "an open breaker sends no request"
    assert (held.decision, held.allowed, held.reason_codes) == (UNAVAILABLE, False, ["CIRCUIT_BREAKER_OPEN"])
    assert held.error.message == MESSAGES["CIRCUIT_BREAKER_OPEN"]
    assert held.metadata.circuit_breaker_state == "open"


def test_after_the_reset_interval_a_probe_is_sent_and_an_answer_closes_it(httpx_mock):
    client = _client(max_retries=0)
    breaker = client._breaker
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()
    assert _decided(client).reason_codes == ["CIRCUIT_BREAKER_OPEN"]

    breaker._last_failure_time -= breaker.reset_timeout  # the reset interval has passed
    httpx_mock.add_response(url=PUSH, json=PUSHED)  # the held-back call's record, pushed first (row 192)
    httpx_mock.add_response(url=URL, status_code=200, json=BLOCK_DECISION)
    probe = _decided(client)
    client.close()
    assert len(httpx_mock.get_requests(url=URL)) == 1, "one call probes the service"
    assert probe.decision == DecisionType.BLOCK
    assert breaker.state == CircuitState.CLOSED


def test_the_causes_are_the_spec_s():
    causes = _causes()
    assert causes == {"CONTROL_PLANE_TIMEOUT", "CONTROL_PLANE_UNREACHABLE", "CIRCUIT_BREAKER_OPEN"}
    assert causes <= set(MESSAGES), "each cause has its authored message"
    states = _schema_metadata()["properties"]["circuit_breaker_state"]["enum"]
    assert set(states) == {s.value for s in CircuitState}, "the breaker's states are the schema's"


def test_evaluate_returns_the_outage_decision(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=URL)
    h = _hiitl()
    d = h.evaluate("send_email", parameters={"to": "ops@example.com"})
    h.close()
    assert (d.decision, d.allowed, d.reason_codes) == (UNAVAILABLE, False, ["CONTROL_PLANE_UNREACHABLE"])
    assert d.metadata.fail_mode == "FAIL_CLOSED"


def test_an_outage_the_hosted_client_meets_is_recorded(httpx_mock, tmp_path):
    """Stop B (i), ruled 2026-11-06: the hosted client records the outage decision in its local store, the envelope
    it built and the decision, read in the record's own form (HTL-23 row 192, behavior 1)."""
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=URL)
    store = str(tmp_path / "audit.db")
    h = _hiitl(audit_db_path=store, max_retries=0)
    d = h.evaluate("send_email")
    h.close()
    [record] = AuditLogger(store).lifecycle(ORG_ID, "dev", d.action_id)
    assert record["decision_type"] == "CONTROL_PLANE_UNAVAILABLE"
    assert record["decision"]["metadata"] == {"fail_mode": "FAIL_CLOSED", "circuit_breaker_state": "closed"}
    assert record["envelope"]["action"] == "send_email"


def test_fail_open_is_a_mode_the_client_takes(httpx_mock, tmp_path, caplog):
    """Stop B (ii), ruled 2026-11-06: under FAIL_OPEN the outage decision is `allowed` true, `error.code` the decision
    and `error.message` the warning; it is logged at warning and recorded (HTL-23 row 192, behavior 2)."""
    store = str(tmp_path / "audit.db")
    client = _client(fail_mode="FAIL_OPEN", audit_db_path=store, max_retries=0)
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=URL)
    with caplog.at_level("WARNING", logger="hiitl.sdk.http_client"):
        d = client.evaluate(_envelope())
    client.close()
    assert (d.decision, d.allowed, d.reason_codes) == (UNAVAILABLE, True, ["CONTROL_PLANE_UNREACHABLE"])
    assert (d.error.code, d.error.message) == ("CONTROL_PLANE_UNAVAILABLE",
                                              FAIL_OPEN_MESSAGES["CONTROL_PLANE_UNREACHABLE"])
    assert d.metadata.fail_mode == "FAIL_OPEN"
    assert [r.levelname for r in caplog.records if "fail-open" in r.getMessage()] == ["WARNING"]
    [record] = AuditLogger(store).lifecycle(ORG_ID, "dev", d.action_id)
    assert (record["decision"]["allowed"], record["decision"]["error"]) == (
        True, {"code": "CONTROL_PLANE_UNAVAILABLE", "message": FAIL_OPEN_MESSAGES["CONTROL_PLANE_UNREACHABLE"]})
