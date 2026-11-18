"""Row 193 (HTL-23) in the SDK: an unexpected failure once the envelope exists is a decision.

Ruled 2026-11-06: "once an envelope exists, an unexpected failure on the evaluate path is `BLOCK`, fail-closed, with
`error.code` and an authored message, its record written where the store answers; the same for a failed dedup read in
both SDKs", by decision_response.md "Never return generic 500 errors without a decision response body" and Principle
7. `error` "= ECP itself failed ... The action was not evaluated" (decision_response.md), so neither is the first
decision under its key. Design: the HTL-23 test design, row 193, behavior 6. Mirrors
typescript/packages/sdk/tests/unit/row193.test.ts.
"""

from __future__ import annotations

import json
import logging

import pytest

from hiitl import HIITL
from hiitl.core.error_decisions import MESSAGES
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.exceptions import AuditLogError

ORG = "org_test000000000000000"
SENTINEL = "/var/lib/hiitl/r193_the_cause_never_said"
SET = {"version": "v1.0.0", "name": "refunds", "description": "The refund agent's refunds",
       "scope": {"org_id": ORG, "environment": "dev"},
       "rules": [{"name": "allow_refunds", "priority": 100, "description": "Refunds are allowed",
                  "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                  "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}]}


class _UnreadableCache:
    """A hybrid client's sync cache whose read of its held policy fails unexpectedly."""

    def get_policy_set(self):
        raise OSError(SENTINEL)

    def tick_part(self):
        return None                 # no kill-switch tick pending (row 240)

    def cache_status(self):
        return "synced"


def _client(tmp_path) -> HIITL:
    policy = tmp_path / "refunds.json"
    policy.write_text(json.dumps(SET))
    return HIITL(environment="dev", agent_id="refund-agent", org_id=ORG, policy_path=str(policy),
                 audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")


def _cache_unreadable(h: HIITL, monkeypatch) -> None:
    monkeypatch.setattr(h, "_mode", "hybrid")
    monkeypatch.setattr(h, "_sync_cache", _UnreadableCache())


def _dedup_unreadable(h: HIITL, monkeypatch) -> None:
    def unreadable(*_, **__):
        raise AuditLogError(f"Failed to read the first decision under the key: {SENTINEL}")
    monkeypatch.setattr(h._audit_logger, "first_decision_under_key", unreadable)


def _store_down(h: HIITL, monkeypatch) -> None:
    def unwritable(*_, **__):
        raise AuditLogError(f"Failed to write audit record: {SENTINEL}")
    monkeypatch.setattr(h._audit_logger, "write", unwritable)


FAULTS = [(_cache_unreadable, "EVALUATION_FAILED"), (_dedup_unreadable, "AUDIT_READ_FAILED")]


def _answered(h: HIITL, key: str):
    """The decision evaluate() answers; a failure it raises instead fails the cell on its assertion (the row: a
    decision, never a raise)."""
    try:
        return h.evaluate("refund", idempotency_key=key)
    except Exception as e:
        pytest.fail(f"evaluate() raised {type(e).__name__} instead of answering a decision: {e}")


@pytest.mark.parametrize("fault,reason", FAULTS, ids=["unexpected", "dedup-read"])
def test_the_failure_is_a_block_decision_recorded(tmp_path, monkeypatch, caplog, fault, reason):
    """Each answers `BLOCK` with `error.code` and the reason its cause, the authored message, no part of the cause's
    text, which is logged; and one record of it."""
    h = _client(tmp_path)
    fault(h, monkeypatch)
    with caplog.at_level(logging.ERROR, logger="hiitl.sdk.client"):
        d = _answered(h, "idem_r193_record")
    assert (d.decision, d.allowed, d.reason_codes) == ("BLOCK", False, [reason])
    assert (d.error.code, d.error.message) == (reason, MESSAGES[reason])
    assert SENTINEL not in d.model_dump_json() and SENTINEL in caplog.text
    [record] = AuditLogger(str(tmp_path / "audit.db")).lifecycle(ORG, "dev", d.action_id)
    assert (record["decision_type"], record["decision"]["error"]["code"]) == ("BLOCK", reason)
    h.close()


@pytest.mark.parametrize("fault,reason", FAULTS, ids=["unexpected", "dedup-read"])
def test_with_the_store_down_too_the_answer_stands(tmp_path, monkeypatch, caplog, fault, reason):
    """A store that does not answer leaves no record; the answer is the same and the write's failure is logged."""
    h = _client(tmp_path)
    fault(h, monkeypatch)
    _store_down(h, monkeypatch)
    with caplog.at_level(logging.ERROR, logger="hiitl.sdk.client"):
        d = h.evaluate("refund", idempotency_key="idem_r193_down")
    assert (d.decision, d.reason_codes, d.error.code) == ("BLOCK", [reason], reason)
    assert "could not be written" in caplog.text
    h.close()


@pytest.mark.parametrize("fault,reason", FAULTS, ids=["unexpected", "dedup-read"])
def test_neither_is_the_first_decision_under_its_key(tmp_path, monkeypatch, fault, reason):
    """The same idempotency_key sent again once the fault clears is evaluated afresh, never answered the failure."""
    h = _client(tmp_path)
    with monkeypatch.context() as faulted:
        fault(h, faulted)
        assert h.evaluate("refund", idempotency_key="idem_r193_retry").reason_codes == [reason]
    again = h.evaluate("refund", idempotency_key="idem_r193_retry")
    assert (again.decision, again.reason_codes) == ("ALLOW", ["REFUND_ALLOWED"])
    h.close()
