"""Row 192 (HTL-23, Stop B): the hosted client's outage record, held and pushed, and its fail mode.

Ruled 2026-11-06, (i): "the pure-hosted client keeps a local audit buffer for the records the service could not take,
pushed when it answers, as hybrid buffers", by Principle 6 ("Every attempted action produces a durable record") and
R-0002's "structured CONTROL_PLANE_UNAVAILABLE audit event"; (ii): "a `fail_mode` setting on the hosted client,
`FAIL_CLOSED` by default, `FAIL_OPEN` opt-in", by R-0002 and the error-handling rule "Fail-open is opt-in and must be
explicitly configured". The contract is decision_response.md "Where the error is answered" (the fail mode, the outage's
record, the hosted client's settings). Design: the HTL-23 test design, row 192, behaviors 3-9. Mirrors
typescript/packages/sdk/tests/unit/row192.test.ts.
"""

from __future__ import annotations

import gzip
import json
import os

import httpx
import pytest

from hiitl.core.redaction import MARKER
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL
from hiitl.sdk.exceptions import ConfigurationError

ORG_ID = "org_r192buffer0000000000"
SERVER = "https://ecp.r192.example.com"
EVALUATE, PUSH = f"{SERVER}/v1/evaluate", f"{SERVER}/v1/sync/audit"
API_KEY = "sk_test_r192buffer0000"
SECRET = "r192-signing-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell, and the retries' backoff does not wait in real time."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("hiitl.sdk.http_client.time.sleep", lambda _seconds: None)


def _hiitl(store, **overrides) -> HIITL:
    settings = {"max_retries": 0, **overrides}
    return HIITL(environment="dev", agent_id="r192-agent", org_id=ORG_ID, api_key=API_KEY, server_url=SERVER,
                 evaluation="remote", signature_key=SECRET, audit_db_path=str(store), **settings)


def _down(httpx_mock, url: str = EVALUATE) -> None:
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=url)


def _body(request: httpx.Request) -> dict:
    content = request.content
    return json.loads(gzip.decompress(content) if request.headers.get("content-encoding") == "gzip" else content)


def _decides(request: httpx.Request) -> httpx.Response:
    """The service's answer to an evaluate: a decision on the action sent."""
    return httpx.Response(200, json={
        "action_id": _body(request)["action_id"], "decision": "ALLOW", "allowed": True, "reason_codes": ["ALLOWED"],
        "policy_version": "v1.0.0", "timing": {"total_ms": 1.0}})


def _takes(request: httpx.Request) -> httpx.Response:
    """The service's answer to a push: every record accepted (sync_engine.md §2.1's response)."""
    return httpx.Response(200, json={"accepted": len(_body(request)["records"]), "duplicates": 0, "errors": []})


def _sent(httpx_mock) -> list[str]:
    """What the client sent, in order."""
    return [r.url.path for r in httpx_mock.get_requests()]


def _pushed(httpx_mock, n: int = 0) -> list[str]:
    """The action_ids the client's n-th push carried, in its order."""
    return [r["action_id"] for r in _body(httpx_mock.get_requests(url=PUSH)[n])["records"]]


def _held(store) -> list[str]:
    """The action_ids the store holds unpushed, oldest first."""
    return [r["action_id"] for r in AuditLogger(str(store)).get_unsynced()]


def test_fail_closed_is_the_default_and_the_setting_is_checked(httpx_mock, tmp_path, monkeypatch):
    """Behavior 3: with no setting the outage is not allowed; the variable sets the mode; a value outside the two is
    refused at construction, naming both."""
    _down(httpx_mock)
    h = _hiitl(tmp_path / "closed.db")
    d = h.evaluate("send_email")
    h.close()
    assert (d.allowed, d.metadata.fail_mode) == (False, "FAIL_CLOSED")

    monkeypatch.setenv("HIITL_FAIL_MODE", "FAIL_OPEN")
    _down(httpx_mock)
    h = _hiitl(tmp_path / "open.db")
    d = h.evaluate("send_email")
    h.close()
    assert (d.allowed, d.metadata.fail_mode) == (True, "FAIL_OPEN"), "the setting is read from its variable"

    with pytest.raises(ConfigurationError) as given:
        _hiitl(tmp_path / "x.db", fail_mode="FAIL_SOMETIMES")
    monkeypatch.setenv("HIITL_FAIL_MODE", "OPEN")
    with pytest.raises(ConfigurationError) as read:
        _hiitl(tmp_path / "x.db")
    for raised in (given, read):
        assert "FAIL_CLOSED" in str(raised.value) and "FAIL_OPEN" in str(raised.value)


def test_held_records_are_pushed_oldest_first_before_the_next_send(httpx_mock, tmp_path):
    """Behavior 4: once the service answers, the client pushes what it holds, in write order, before its own
    evaluate; a pushed record is marked synced."""
    store = tmp_path / "audit.db"
    _down(httpx_mock)
    _down(httpx_mock, PUSH)
    httpx_mock.add_callback(_takes, url=PUSH)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    first, second = h.evaluate("send_email"), h.evaluate("send_email")
    assert _held(store) == [first.action_id, second.action_id]

    third = h.evaluate("send_email")
    h.close()
    assert third.decision == "ALLOW"
    assert _sent(httpx_mock) == ["/v1/evaluate", "/v1/sync/audit", "/v1/sync/audit", "/v1/evaluate"]
    assert _pushed(httpx_mock, 1) == [first.action_id, second.action_id], "oldest first"
    assert _held(store) == [], "a pushed record is marked synced"


def test_an_unanswered_push_sends_nothing_further(httpx_mock, tmp_path):
    """Behavior 5: a push the service does not answer leaves everything held, and the call is answered as the same
    outage, recorded, with no evaluate sent behind it."""
    store = tmp_path / "audit.db"
    _down(httpx_mock)
    httpx_mock.add_exception(httpx.ReadTimeout("no answer"), url=PUSH)
    h = _hiitl(store)
    first, second = h.evaluate("send_email"), h.evaluate("send_email")
    h.close()
    assert _sent(httpx_mock) == ["/v1/evaluate", "/v1/sync/audit"], "no evaluate is sent behind an unanswered push"
    assert (second.decision, second.allowed, second.reason_codes) == (
        "CONTROL_PLANE_UNAVAILABLE", False, ["CONTROL_PLANE_TIMEOUT"])
    assert _held(store) == [first.action_id, second.action_id], "the call is recorded, and nothing held is dropped"


def test_a_refused_record_stays_held(httpx_mock, tmp_path, caplog):
    """Behavior 6: a record the service does not store for a reason other than its own content stays held, logged
    at warning; it is not sent again before every call, and a client constructed again pushes it. A refusal of its own
    content is final, row 224's cell (sync_engine.md §2.1, ruled 2026-11-08)."""
    store = tmp_path / "audit.db"

    def refuses(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accepted": 0, "duplicates": 0, "errors": [
            {"event_id": r["event_id"], "code": "INSERT_FAILED", "message": "The audit record was not stored"}
            for r in _body(request)["records"]]})

    _down(httpx_mock)
    httpx_mock.add_callback(refuses, url=PUSH)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    first = h.evaluate("send_email")
    with caplog.at_level("WARNING", logger="hiitl.sdk.http_client"):
        h.evaluate("send_email")
        h.evaluate("send_email")
    h.close()
    assert _sent(httpx_mock) == ["/v1/evaluate", "/v1/sync/audit", "/v1/evaluate", "/v1/evaluate"], \
        "a refused record is not re-sent before every call"
    assert _held(store) == [first.action_id], "a refused record is never dropped"
    assert [r.levelname for r in caplog.records if "INSERT_FAILED" in r.getMessage()] == ["WARNING"]

    httpx_mock.add_callback(_takes, url=PUSH)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    h.evaluate("send_email")
    h.close()
    assert _sent(httpx_mock)[4:] == ["/v1/sync/audit", "/v1/evaluate"], "constructed again, the client pushes it"
    assert _held(store) == []


def test_held_records_survive_a_restart(httpx_mock, tmp_path):
    """Behavior 7: a client constructed on the same `audit_db_path` pushes what the last one held."""
    store = tmp_path / "audit.db"
    _down(httpx_mock)
    h = _hiitl(store)
    held = h.evaluate("send_email")
    h.close()

    httpx_mock.add_callback(_takes, url=PUSH)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    h.evaluate("send_email")
    h.close()
    assert _sent(httpx_mock) == ["/v1/evaluate", "/v1/sync/audit", "/v1/evaluate"]
    assert _pushed(httpx_mock) == [held.action_id]
    assert _held(store) == []


def test_a_store_that_cannot_write_blocks_in_either_mode(httpx_mock, tmp_path):
    """Behavior 8: an outage whose record the store cannot write is `AUDIT_WRITE_FAILED`, `BLOCK`, in either fail
    mode ("Audit write failures in fail-closed mode must block the action", Infrastructure spec 3)."""
    (tmp_path / "file").write_text("a file where the store's directory would be")
    store = tmp_path / "file" / "audit.db"
    for mode in ("FAIL_CLOSED", "FAIL_OPEN"):
        _down(httpx_mock)
        h = _hiitl(store, fail_mode=mode)
        d = h.evaluate("send_email")
        h.close()
        assert (d.decision, d.allowed, d.reason_codes, d.error.code) == (
            "BLOCK", False, ["AUDIT_WRITE_FAILED"], "AUDIT_WRITE_FAILED"), mode


def test_the_hosted_record_takes_the_sdks_declaration(httpx_mock, tmp_path):
    """Behavior 9: the SDK's `redact_fields` applies to the outage record as to every record its store writes
    (event_format.md §Redaction); a declared path the call does not carry is named (row 191)."""
    store = tmp_path / "audit.db"
    _down(httpx_mock)
    h = _hiitl(store, redact_fields=["parameters.to", "parameters.cc"])
    d = h.evaluate("send_email", parameters={"to": "ops@example.com", "subject": "Q3"})
    h.close()
    logger = AuditLogger(str(store))
    [record] = logger.lifecycle(ORG_ID, "dev", d.action_id)
    assert record["envelope"]["parameters"] == {"to": MARKER, "subject": "Q3"}
    assert record["redaction"] == {"absent": ["parameters.cc"]}
    assert logger.verify_integrity(record["event_id"])
