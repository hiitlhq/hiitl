"""Row 217 (HTL-24): a result for a held action, in the SDK's store.

Ruled 2026-11-07: "the local store writes the result, naming the review it cannot read … in local mode the record
stands as named … One rule in the store and one read at ingest; no per-mode branching." By the ontology §4
commitment 3 and Principle 4. The store holds no review case: it passes the decision's unread review to the one rule
and writes it as the record's `review`, a further term of its hash (event_format.md 1.6). Design: the HTL-24 test
design, row 217, behavior 4. Mirrors typescript/packages/sdk/tests/unit/row217.test.ts.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from hiitl import HIITL
from hiitl.core.canonical import AUDIT_FURTHER, audit_content_hash
from hiitl.sdk.exceptions import LifecycleError

ORG = "org_test000000000000000"
SET = {"version": "v1.0.0", "name": "payouts", "description": "The payout agent's payouts",
       "scope": {"org_id": ORG, "environment": "dev"},
       "rules": [{"name": "block_large_payouts", "priority": 200, "description": "Payouts over 10,000 are refused",
                  "conditions": {"all_of": [{"field": "action", "operator": "equals", "value": "payout"},
                                            {"field": "parameters.amount", "operator": "greater_than",
                                             "value": 10000}]},
                  "decision": "BLOCK", "reason_code": "PAYOUT_OVER_LIMIT"},
                 {"name": "review_payouts", "priority": 100, "description": "Payouts over 1,000 are reviewed",
                  "conditions": {"all_of": [{"field": "action", "operator": "equals", "value": "payout"},
                                            {"field": "parameters.amount", "operator": "greater_than",
                                             "value": 1000}]},
                  "decision": "REQUIRE_APPROVAL", "reason_code": "PAYOUT_REVIEW", "route": "finance-review"},
                 {"name": "allow_payouts", "priority": 10, "description": "Other payouts are allowed",
                  "conditions": {"field": "action", "operator": "equals", "value": "payout"},
                  "decision": "ALLOW", "reason_code": "PAYOUT_ALLOWED"}]}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _client(tmp_path) -> HIITL:
    path = tmp_path / "payouts.json"
    path.write_text(json.dumps(SET))
    return HIITL(environment="dev", agent_id="payout-agent", org_id=ORG, policy_path=str(path),
                 audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")


def _held(h: HIITL):
    d = h.evaluate("payout", parameters={"amount": 4800})
    assert d.decision == "REQUIRE_APPROVAL" and d.resume_token, d
    return d


def _written(h: HIITL, action_id: str, *args, **kwargs) -> dict:
    """The record a held result is written as: a refusal fails the cell naming it, since the store holds no case and
    a held result refused is read as if the action had not executed (the gap row 217 fault)."""
    try:
        return h.record_result(action_id, *args, **kwargs)
    except LifecycleError as e:
        pytest.fail(f"the held result was refused {e.reason}, as if the action had not executed")


def test_a_held_result_is_written_naming_its_unread_review(tmp_path):
    h = _client(tmp_path)
    d = _held(h)
    record = _written(h, d.action_id, "succeeded", duration_ms=412)
    assert record.get("review") == {"unread": d.resume_token}
    assert record["execution_result"] == {"status": "succeeded", "duration_ms": 412}
    further = {m: record[m] for m in AUDIT_FURTHER if m in record}
    assert set(further) >= {"execution_result", "review"}
    assert audit_content_hash(record["event_id"], record["envelope"], record["decision"], **further) == \
        record["content_hash"], "the hash covers the review"
    assert h.record_result(d.action_id, "succeeded", duration_ms=412)["event_id"] == record["event_id"], \
        "the same result again returns the record that holds it"


def test_a_stored_review_altered_no_longer_verifies(tmp_path):
    h = _client(tmp_path)
    d = _held(h)
    record = h.record_result(d.action_id, "succeeded")
    log = h._audit_logger
    assert log.verify_integrity(record["event_id"])
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    conn.execute("UPDATE audit_log SET review = ? WHERE event_id = ?",
                 (json.dumps({"status": "approved", "timeout_action": "fail_closed"}), record["event_id"]))
    conn.commit()
    conn.close()
    assert not log.verify_integrity(record["event_id"]), "a review rewritten as read no longer verifies"


def test_the_upload_carries_the_review(tmp_path):
    h = _client(tmp_path)
    d = _held(h)
    h.record_result(d.action_id, "failed", error="the bank refused the transfer")
    decision, result = h._audit_logger.get_unsynced(limit=10)
    assert "review" not in decision and result["review"] == {"unread": d.resume_token}
    assert [r["event_type"] for r in (decision, result)] == ["action.evaluated", "action.failed"]
    further = {m: result[m] for m in AUDIT_FURTHER if m in result}
    assert audit_content_hash(result["event_id"], result["envelope"], result["decision"], **further) == \
        result["content_hash"]


def test_an_allowed_result_names_no_review(tmp_path):
    h = _client(tmp_path)
    d = h.evaluate("payout", parameters={"amount": 120})
    assert d.allowed
    assert "review" not in h.record_result(d.action_id, "succeeded")


def test_a_blocked_result_is_refused_and_nothing_is_written(tmp_path):
    h = _client(tmp_path)
    d = h.evaluate("payout", parameters={"amount": 25000})
    assert d.decision == "BLOCK"
    with pytest.raises(LifecycleError) as e:
        h.record_result(d.action_id, "succeeded")
    assert e.value.reason == "RESULT_ON_UNALLOWED_DECISION"
    assert len(h._audit_logger.lifecycle(ORG, "dev", d.action_id)) == 1


def test_the_stores_further_columns_are_the_cores_terms(tmp_path):
    """The table's columns for the further terms are generated from core's `AUDIT_FURTHER`, in a new store and in one
    written before a term existed."""
    _client(tmp_path).close()
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    conn.close()
    assert set(AUDIT_FURTHER) <= columns

    old = tmp_path / "old"
    old.mkdir()
    conn = sqlite3.connect(str(old / "audit.db"))
    conn.execute("CREATE TABLE audit_log (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, org_id TEXT NOT NULL, "
                 "environment TEXT NOT NULL, action_id TEXT NOT NULL, envelope TEXT NOT NULL, decision TEXT NOT NULL, "
                 "policy_version TEXT NOT NULL, decision_type TEXT NOT NULL, tool_name TEXT, agent_id TEXT, "
                 "content_hash TEXT NOT NULL)")
    conn.commit()
    conn.close()
    _client(old).close()
    conn = sqlite3.connect(str(old / "audit.db"))
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    conn.close()
    assert set(AUDIT_FURTHER) <= columns
