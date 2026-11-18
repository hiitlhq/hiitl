"""Row 143 (HTL-20): in the local store, a repeated idempotency key returns the first decision and writes no record.

Principle 5: "Embrace idempotency, retries, deduplication, and partial failure as first-class concerns." The security
architecture §1.3: "A replayed envelope produces a dedup hit, not a re-evaluation. The dedup window is configurable
(default: 24 hours)." Design: the HTL-20 test design, row 143, behaviors 1, 2 and 4.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL


def _client(tmp_path, **kw):
    return HIITL(audit_db_path=str(tmp_path / "a.db"), **kw)


def _records(tmp_path):
    return AuditLogger(str(tmp_path / "a.db")).get_unsynced(limit=10)


def test_a_retry_under_the_same_key_returns_the_first_decision_and_writes_one_record(tmp_path):
    """Behaviors 1 and 2: the SDK builds a new envelope each call (its own action_id and timestamp); under the first
    call's key the second gets the first call's decision."""
    h = _client(tmp_path)

    first = h.evaluate("refund", parameters={"amount": 10}, idempotency_key="idem_row143_local")
    retry = h.evaluate("refund", parameters={"amount": 900}, idempotency_key="idem_row143_local")

    recs = _records(tmp_path)
    assert len(recs) == 1
    assert retry.action_id == first.action_id == recs[0]["envelope"]["action_id"]
    assert retry.decision == first.decision
    assert retry.envelope_hash == first.envelope_hash


def test_without_a_key_each_call_is_its_own_action(tmp_path):
    h = _client(tmp_path)

    first = h.evaluate("refund")
    second = h.evaluate("refund")

    assert second.action_id != first.action_id
    assert len(_records(tmp_path)) == 2


def test_a_key_reused_after_the_window_is_evaluated_afresh(tmp_path, monkeypatch):
    """Behavior 4: the second call's envelope is timestamped further from the first than the configured window."""
    h = _client(tmp_path, dedup_window_seconds=60)
    first = h.evaluate("refund", idempotency_key="idem_row143_later")

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=120)

    monkeypatch.setattr("hiitl.sdk.client.datetime", _Later)
    later = h.evaluate("refund", idempotency_key="idem_row143_later")

    assert later.action_id != first.action_id
    assert len(_records(tmp_path)) == 2


def test_the_same_key_in_another_environment_is_evaluated_afresh(tmp_path):
    """Behavior 3: two clients sharing one store, dev and prod — one key, two actions."""
    dev = _client(tmp_path, environment="dev").evaluate("refund", idempotency_key="idem_row143_env")
    prod = _client(tmp_path, environment="prod").evaluate("refund", idempotency_key="idem_row143_env")

    assert prod.action_id != dev.action_id
    assert len(_records(tmp_path)) == 2
