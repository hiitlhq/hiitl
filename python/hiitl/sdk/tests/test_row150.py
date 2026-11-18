"""Row 150 (HTL-22): what a record is, and `record_result` up to the write, in the SDK.

The Stop 1 ruling (HTL-20): "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle fields
(`event_type`; `execution_result` on a result), appended against the decision's `action_id`". Principle 4: BLOCKED is
terminal. Infrastructure spec 2: "idempotent state transitions". Derived state is computed, never stored: every reader
carries `event_type`, and no column holds it. Design: the HTL-22 test design, row 150, behaviors 4-6 and the exit cell
(10), which turned with Stop A (HTL-23 row 191: the result's hash covers its `execution_result`, so the write is built).
Mirrors typescript/packages/sdk/tests/unit/row150.test.ts.
"""

from __future__ import annotations

import json
import os

import pytest

from hiitl import HIITL, LifecycleError
from hiitl.core.lifecycle import MESSAGES, event_type
from hiitl.sdk.exceptions import ServerError

ORG = "org_test000000000000000"
SET = {"version": "v1.0.0", "name": "refunds", "description": "The refund agent's refunds",
       "scope": {"org_id": ORG, "environment": "dev"}}
SERVER = "https://ecp.example"
SIGNING_KEY = "row150-local-signing-key-0123456789abcdef"
RULES = [
    {"name": "allow_refunds", "priority": 100, "description": "Refunds are allowed",
     "conditions": {"field": "action", "operator": "equals", "value": "refund"},
     "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"},
    {"name": "block_wires", "priority": 90, "description": "Wire transfers are not this agent's",
     "conditions": {"field": "action", "operator": "equals", "value": "wire_transfer"},
     "decision": "BLOCK", "reason_code": "WIRES_BLOCKED"},
]


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _client(tmp_path, **kw) -> HIITL:
    path = tmp_path / "refunds.json"
    path.write_text(json.dumps({**SET, "rules": RULES}))
    return HIITL(environment="dev", agent_id="refund-agent", org_id=ORG, policy_path=str(path),
                 audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY", **kw)


def _answer(call):
    """The call's answer, or what it raised."""
    try:
        return call()
    except Exception as e:  # noqa: BLE001 - what was raised is the finding
        return e


def _lifecycle(h: HIITL, action_id: str) -> list:
    return [r.get("event_type") for r in h._audit_logger.lifecycle(ORG, "dev", action_id)]


def test_every_reader_carries_event_type(tmp_path, monkeypatch):
    """Behavior 4: each reader's records carry the event their decision is."""
    h = _client(tmp_path, signature_key=SIGNING_KEY)
    allowed = h.evaluate("refund")
    build = h._build_envelope

    def altered(**fields):
        envelope = build(**fields)
        envelope.parameters["amount"] = 1_000_000
        return envelope

    monkeypatch.setattr(h, "_build_envelope", altered)
    refused = h.evaluate("refund", parameters={"amount": 10})
    monkeypatch.undo()
    assert (allowed.decision, refused.decision) == ("ALLOW", "SIGNATURE_INVALID")

    log = h._audit_logger
    reads = {
        "query_by_org": log.query_by_org(ORG, limit=10),
        "query_by_action_id": [log.query_by_action_id(allowed.action_id), log.query_by_action_id(refused.action_id)],
        "get_unsynced": log.get_unsynced(limit=10),
        "lifecycle": log.lifecycle(ORG, "dev", allowed.action_id) + log.lifecycle(ORG, "dev", refused.action_id),
    }
    for reader, records in reads.items():
        carried = sorted((r["decision_type"], r.get("event_type")) for r in records)
        assert carried == [("ALLOW", "action.evaluated"), ("SIGNATURE_INVALID", "signature.invalid")], reader


def test_record_result_refuses_as_the_spec_says(tmp_path):
    """Behavior 5: each refusal is a LifecycleError with its reason and message, and nothing is written."""
    h = _client(tmp_path)
    allowed, blocked = h.evaluate("refund"), h.evaluate("wire_transfer")
    assert (allowed.decision, blocked.decision) == ("ALLOW", "BLOCK")
    cases = {
        "RESULT_INVALID": lambda: h.record_result(allowed.action_id, "done"),
        "ACTION_NOT_FOUND": lambda: h.record_result("act_r150nevereval00000000", "succeeded"),
        "RESULT_ON_UNALLOWED_DECISION": lambda: h.record_result(blocked.action_id, "succeeded"),
    }
    for reason, call in cases.items():
        refused = _answer(call)
        assert isinstance(refused, LifecycleError), f"{reason}: {refused!r}"
        assert (refused.reason, str(refused)) == (reason, f"[{reason}] {MESSAGES[reason]}")
    assert _lifecycle(h, allowed.action_id) == ["action.evaluated"], "nothing is written"
    assert _lifecycle(h, blocked.action_id) == ["action.evaluated"]


def _hosted() -> HIITL:
    return HIITL(api_key="sk_test_1234567890abcdef", server_url=SERVER, evaluation="remote", max_retries=0,
                 signature_key="s" * 32)


RESULT_URL = f"{SERVER}/v1/actions/act_r150hosted0000000000/result"
RECORD = {"event_id": "evt_r150hosted", "action_id": "act_r150hosted0000000000", "event_type": "action.executed"}


def test_the_hosted_client_sends_the_result_and_reads_its_answer(httpx_mock):
    """Behavior 6: the result goes to the endpoint; a refusal is a LifecycleError, any other error a ServerError."""
    refusal = {"detail": {"error": "RESULT_ON_UNALLOWED_DECISION", "message": MESSAGES["RESULT_ON_UNALLOWED_DECISION"],
                          "details": {"action_id": "act_r150hosted0000000000"}}}
    httpx_mock.add_response(url=RESULT_URL, method="POST", status_code=200, json=RECORD)
    httpx_mock.add_response(url=RESULT_URL, method="POST", status_code=409, json=refusal)
    httpx_mock.add_response(url=RESULT_URL, method="POST", status_code=401,
                            json={"detail": {"error": "UNAUTHORIZED", "message": "No API key was sent."}})
    h = _hosted()

    sent = _answer(lambda: h.record_result("act_r150hosted0000000000", "succeeded", duration_ms=12))
    refused = _answer(lambda: h.record_result("act_r150hosted0000000000", "succeeded"))
    unauthorized = _answer(lambda: h.record_result("act_r150hosted0000000000", "succeeded"))

    assert sent == RECORD, repr(sent)
    assert json.loads(httpx_mock.get_requests()[0].content) == {"status": "succeeded", "duration_ms": 12}
    assert isinstance(refused, LifecycleError) and refused.reason == "RESULT_ON_UNALLOWED_DECISION", repr(refused)
    assert isinstance(unauthorized, ServerError) and (unauthorized.status_code, unauthorized.error_code) == (
        401, "UNAUTHORIZED"), repr(unauthorized)


def test_a_result_recorded_for_an_evaluated_action_reads_back_with_its_lifecycle(tmp_path):
    """The exit cell (behavior 10; HTL-23 row 191 behavior 5): the write is built once the hash covers the result."""
    h = _client(tmp_path)
    d = h.evaluate("refund")
    record = h.record_result(d.action_id, "succeeded", duration_ms=12)
    assert record["event_type"] == event_type(d.decision, {"status": "succeeded"}) == "action.executed"
    assert _lifecycle(h, d.action_id) == ["action.evaluated", "action.executed"]
    assert h.record_result(d.action_id, "succeeded", duration_ms=12) == record
    with pytest.raises(LifecycleError) as refused:
        h.record_result(d.action_id, "failed", error="card declined")
    assert refused.value.reason == "RESULT_ALREADY_RECORDED"
