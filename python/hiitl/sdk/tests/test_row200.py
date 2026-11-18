"""Row 200 (HTL-23): the hosted result write during an outage.

Ruled 2026-11-06: "The hosted result write does not raise on an outage: with 192 (i) ruled, the result is held in the
same local buffer and pushed; a typed error only when the buffer itself cannot be written", by Principle 4 and
Principle 6. The contract is event_format.md "The Lifecycle" ("A result the hosted service could not take") and
sync_engine.md "The hosted client's buffer". Design: the HTL-23 test design, row 200. Mirrors
typescript/packages/sdk/tests/unit/row200.test.ts.
"""

from __future__ import annotations

import gzip
import json
import os

import httpx
import pytest

from hiitl.core.lifecycle import MESSAGES
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL
from hiitl.sdk.exceptions import AuditLogError

ORG_ID = "org_r200heldresult000000"
SERVER = "https://ecp.r200.example.com"
EVALUATE, PUSH = f"{SERVER}/v1/evaluate", f"{SERVER}/v1/sync/audit"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell, and the retries' backoff does not wait in real time."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("hiitl.sdk.http_client.time.sleep", lambda _seconds: None)


def _hiitl(store, **overrides) -> HIITL:
    return HIITL(environment="dev", agent_id="r200-agent", org_id=ORG_ID, api_key="sk_test_r200heldresult0",
                 server_url=SERVER, evaluation="remote", signature_key="r200-signing-secret-0123456789abcdef",
                 audit_db_path=str(store), max_retries=0, **overrides)


def _body(request: httpx.Request) -> dict:
    content = request.content
    return json.loads(gzip.decompress(content) if request.headers.get("content-encoding") == "gzip" else content)


def _decides(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "action_id": _body(request)["action_id"], "decision": "ALLOW", "allowed": True, "reason_codes": ["ALLOWED"],
        "policy_version": "v1.0.0", "timing": {"total_ms": 1.0}})


def _takes(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"accepted": len(_body(request)["records"]), "duplicates": 0, "errors": []})


def _result_url(action_id: str) -> str:
    return f"{SERVER}/v1/actions/{action_id}/result"


def _sent(httpx_mock) -> list[str]:
    return [r.url.path for r in httpx_mock.get_requests()]


def _held_results(store) -> list[dict]:
    return AuditLogger(str(store)).held_results()


def test_a_result_during_an_outage_is_held(httpx_mock, tmp_path, caplog):
    """Behavior 1: the result is returned as held, a warning is logged, and nothing raises."""
    store = tmp_path / "audit.db"
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    d = h.evaluate("send_email")
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=_result_url(d.action_id))
    with caplog.at_level("WARNING", logger="hiitl.sdk.http_client"):
        held = h.record_result(d.action_id, "succeeded", duration_ms=412)
    h.close()
    result = {"status": "succeeded", "duration_ms": 412}
    assert held == {"action_id": d.action_id, "execution_result": result, "held": True}
    assert [r.levelname for r in caplog.records if d.action_id in r.getMessage()] == ["WARNING"]
    assert _held_results(store) == [{"action_id": d.action_id, "execution_result": result}]


def test_a_held_result_is_pushed_after_the_records(httpx_mock, tmp_path):
    """Behavior 2: under FAIL_OPEN an outage decision's action executes; its result, held while the service is down,
    is pushed after the decision's record, so the service finds the decision, and then the call is sent."""
    store = tmp_path / "audit.db"
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=EVALUATE)
    h = _hiitl(store, fail_mode="FAIL_OPEN")
    outage = h.evaluate("send_email")
    assert outage.allowed

    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=PUSH)
    held = h.record_result(outage.action_id, "failed", error="smtp 421")
    assert held["held"] is True

    result = {"status": "failed", "error": "smtp 421"}
    httpx_mock.add_callback(_takes, url=PUSH)
    httpx_mock.add_response(url=_result_url(outage.action_id), json={"action_id": outage.action_id,
                                                                     "execution_result": result})
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h.evaluate("send_email")
    h.close()
    assert _sent(httpx_mock) == ["/v1/evaluate", "/v1/sync/audit", "/v1/sync/audit",
                                 f"/v1/actions/{outage.action_id}/result", "/v1/evaluate"]
    assert _body(httpx_mock.get_requests(url=_result_url(outage.action_id))[0]) == result
    assert _held_results(store) == []
    assert AuditLogger(str(store)).get_unsynced() == []


def test_a_held_result_refused_at_the_push_is_removed(httpx_mock, tmp_path, caplog):
    """Behavior 3: the service's refusal is final; the held result is removed and logged at error, naming the action
    and the reason, and the call is sent."""
    store = tmp_path / "audit.db"
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(store)
    d = h.evaluate("send_email")
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=_result_url(d.action_id))
    h.record_result(d.action_id, "succeeded")

    httpx_mock.add_response(url=_result_url(d.action_id), status_code=409, json={"detail": {
        "error": "RESULT_ALREADY_RECORDED", "message": MESSAGES["RESULT_ALREADY_RECORDED"]}})
    httpx_mock.add_callback(_decides, url=EVALUATE)
    with caplog.at_level("WARNING", logger="hiitl.sdk.http_client"):
        after = h.evaluate("send_email")
    h.close()
    assert after.decision == "ALLOW"
    assert _sent(httpx_mock)[-2:] == [f"/v1/actions/{d.action_id}/result", "/v1/evaluate"]
    assert _held_results(store) == [], "a refused result is no record"
    assert [r.levelname for r in caplog.records
            if d.action_id in r.getMessage() and "RESULT_ALREADY_RECORDED" in r.getMessage()] == ["ERROR"]


def test_a_result_the_store_cannot_hold_raises(httpx_mock, tmp_path):
    """Behavior 4: a result the service could not take and the store cannot hold is the typed error."""
    (tmp_path / "file").write_text("a file where the store's directory would be")
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(tmp_path / "file" / "audit.db")
    d = h.evaluate("send_email")
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=_result_url(d.action_id))
    with pytest.raises(AuditLogError):
        h.record_result(d.action_id, "succeeded")
    h.close()
