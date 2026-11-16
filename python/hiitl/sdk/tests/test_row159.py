"""Row 159 (HTL-22): an error is a decision, in the SDK too.

decision_response.md, Error Handling: "All errors produce structured decision responses", and "Even error decisions
produce audit records". The Stop 2 ruling: "The SDKs raise a typed hiitl error only where no envelope exists yet."
Infrastructure spec 3: "Audit write failures in fail-closed mode must block the action". Design: the HTL-22 test
design, row 159, behaviors 4-8. Mirrors typescript/packages/sdk/tests/unit/row159.test.ts.
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from hiitl import HIITL
from hiitl.core.types import Decision
from hiitl.sdk.exceptions import ServerError

ORG = "org_test000000000000000"
SET = {"version": "v1.0.0", "name": "refunds", "description": "The refund agent's refunds",
       "scope": {"org_id": ORG, "environment": "dev"}}
SERVER = "https://ecp.example"
SENTINEL = "r159-cause-the-caller-never-reads"

ALLOW_REFUNDS = {"name": "allow_refunds", "priority": 100, "description": "Refunds are allowed",
                 "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                 "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _client(tmp_path, *, rules=(ALLOW_REFUNDS,), policy=None, mode="RESPECT_POLICY", **kw) -> HIITL:
    path = tmp_path / "refunds.json"
    if policy is None:
        path.write_text(json.dumps({**SET, "rules": list(rules)}))
    elif policy != "absent":
        path.write_text(policy)
    return HIITL(environment="dev", agent_id="refund-agent", org_id=ORG, policy_path=str(path),
                 audit_db_path=str(tmp_path / f"audit_{mode}.db"), mode=mode, **kw)


def _records(h: HIITL) -> list[str]:
    return [r["decision"]["decision"] for r in h._audit_logger.get_unsynced(limit=10)]


def _answer(call):
    """The call's decision, or what it raised: once an envelope exists, nothing raises."""
    try:
        return call()
    except Exception as e:  # noqa: BLE001 - what was raised is the finding
        return e


@pytest.mark.parametrize("mode", ["RESPECT_POLICY", "OBSERVE_ALL"])
def test_a_failed_audit_write_blocks_and_writes_nothing(tmp_path, mode, monkeypatch):
    """Behavior 4: the action whose record cannot be written does not run, whatever the mode."""
    h = _client(tmp_path, mode=mode)
    monkeypatch.setattr(h._audit_logger, "write", _store_down)
    d = _answer(lambda: h.evaluate("refund"))
    assert (d.decision, d.allowed, d.error and d.error.code) == ("BLOCK", False, "AUDIT_WRITE_FAILED")
    monkeypatch.undo()
    assert _records(h) == [], "the record is what failed"


def _store_down(envelope, decision):
    raise RuntimeError(SENTINEL)


def _evaluator_raises(h, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError(SENTINEL)
    monkeypatch.setattr(h._evaluator, "evaluate", broken)


@pytest.mark.parametrize("policy, arm, reason", [
    ("absent", None, "POLICY_NOT_FOUND"),
    ('{"version": "v1.0.0", "name": "refunds", "rules": [', None, "POLICY_VALIDATION_ERROR"),
    (None, _evaluator_raises, "POLICY_EVALUATION_FAILED"),
], ids=["missing-file", "unparseable-file", "evaluator-raises"])
def test_local_errors_are_decisions_with_records(tmp_path, policy, arm, reason, monkeypatch):
    """Behavior 5: an envelope exists, so nothing raises; the failure is POLICY_ERROR, recorded."""
    h = _client(tmp_path, policy=policy)
    if arm:
        arm(h, monkeypatch)
    d = _answer(lambda: h.evaluate("refund"))
    assert isinstance(d, Decision), f"an envelope exists, so the failure is a decision, not {d!r}"
    assert (d.decision, d.allowed, d.reason_codes, d.error.code) == ("POLICY_ERROR", False, [reason], "POLICY_ERROR")
    assert _records(h) == ["POLICY_ERROR"]


class _UnreadableStore:
    def check_and_increment(self, envelope, decision):
        raise RuntimeError(SENTINEL)


def _limiter(tmp_path, monkeypatch):
    h = _client(tmp_path, enable_rate_limiting=True)
    h._rate_limiter = _UnreadableStore()
    return h


def _evaluator(tmp_path, monkeypatch):
    h = _client(tmp_path)
    _evaluator_raises(h, monkeypatch)
    return h


def _policy_load(tmp_path, monkeypatch):
    # The schema's own error quotes the value it refused, so a decision no rule may write carries the sentinel
    return _client(tmp_path, rules=[dict(ALLOW_REFUNDS, decision=SENTINEL)])


def _audit_write(tmp_path, monkeypatch):
    h = _client(tmp_path)
    monkeypatch.setattr(h._audit_logger, "write", _store_down)
    return h


@pytest.mark.parametrize("arrive, code", [
    (_limiter, "RATE_LIMIT_SERVICE_ERROR"),
    (_evaluator, "POLICY_ERROR"),
    (_policy_load, "POLICY_ERROR"),
    (_audit_write, "AUDIT_WRITE_FAILED"),
], ids=["limiter", "evaluator", "policy-load", "audit-write"])
def test_no_error_message_carries_the_caught_exception_s_text(tmp_path, arrive, code, monkeypatch, caplog):
    """Behavior 6: the message is authored; the cause is logged, never said."""
    caplog.set_level(logging.ERROR, logger="hiitl.sdk.client")
    d = arrive(tmp_path, monkeypatch).evaluate("refund")
    assert (d.allowed, d.error.code) == (False, code)
    assert SENTINEL not in d.model_dump_json()
    assert SENTINEL in caplog.text


def _hosted() -> HIITL:
    return HIITL(api_key="sk_test_1234567890abcdef", server_url=SERVER, evaluation="remote", max_retries=0,
                 signature_key="s" * 32)


def _decision_body(decision, reason, code, message):
    return {"action_id": "act_r159hosted0000000000", "decision": decision, "allowed": False,
            "reason_codes": [reason], "policy_version": "", "timing": {"total_ms": 0.4},
            "error": {"code": code, "message": message}}


@pytest.mark.parametrize("status, body", [
    (403, _decision_body("SIGNATURE_INVALID", "ENVELOPE_SIGNATURE_VERIFICATION_FAILED", "SIGNATURE_INVALID",
                         "The envelope does not verify under the key it was signed with.")),
    (500, _decision_body("BLOCK", "AUDIT_WRITE_FAILED", "AUDIT_WRITE_FAILED",
                         "The audit record could not be written, so the action is blocked.")),
], ids=["403-signature-invalid", "500-audit-write-failed"])
def test_the_hosted_client_reads_a_decision_body_on_any_status(status, body, httpx_mock):
    """Behavior 7: an error keeps its status and is the decision its body carries."""
    httpx_mock.add_response(url=f"{SERVER}/v1/evaluate", method="POST", json=body, status_code=status)
    d = _answer(lambda: _hosted().evaluate("refund"))
    assert isinstance(d, Decision), f"a decision body is the decision on any status, not {d!r}"
    assert (d.decision, d.allowed, d.reason_codes, d.error.code, d.error.message) == (
        body["decision"], False, body["reason_codes"], body["error"]["code"], body["error"]["message"])


def test_a_response_with_no_decision_body_still_raises(httpx_mock):
    """Behavior 7: R-1174's shape, a request refused before an envelope, carries no decision."""
    httpx_mock.add_response(url=f"{SERVER}/v1/evaluate", method="POST", status_code=401,
                            json={"detail": {"error": "UNAUTHORIZED", "message": "No API key was sent."}})
    with pytest.raises(ServerError) as e:
        _hosted().evaluate("refund")
    assert (e.value.status_code, e.value.error_code) == (401, "UNAUTHORIZED")


def test_a_refused_envelope_is_not_the_first_decision_under_its_key(tmp_path, monkeypatch):
    """Behavior 8: a refused envelope was never evaluated, so its key returns the first evaluated decision."""
    h = _client(tmp_path, signature_key="row159-local-signing-key-0123456789abcdef")
    build = h._build_envelope

    def altered(**fields):
        envelope = build(**fields)
        envelope.parameters["amount"] = 1_000_000
        return envelope

    monkeypatch.setattr(h, "_build_envelope", altered)
    refused = h.evaluate("refund", parameters={"amount": 10}, idempotency_key="refund-K")
    monkeypatch.undo()
    corrected = h.evaluate("refund", parameters={"amount": 10}, idempotency_key="refund-K")
    again = h.evaluate("refund", parameters={"amount": 10}, idempotency_key="refund-K")
    assert (refused.decision, corrected.decision, again.decision) == ("SIGNATURE_INVALID", "ALLOW", "ALLOW")
    assert again.action_id == corrected.action_id, "the replay is a dedup hit on the evaluated one"
    assert _records(h) == ["SIGNATURE_INVALID", "ALLOW"]
