"""Row 191 (HTL-23, Stop A): what a record's hash covers, in the SDK's store.

Ruled 2026-11-06: "each content member a record carries beyond its envelope and decision joins the hash as a further
term in a fixed order ...; a record carrying neither hashes exactly as today". By the security architecture §1.4 and
Tier 1, "Enables individual record tamper detection". The store reads the hash's terms from the record, never from a
list of what it should carry. Design: the HTL-23 test design, row 191, behaviors 3 and 5. Mirrors
typescript/packages/sdk/tests/unit/row191.test.ts.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from hiitl import HIITL
from hiitl.core.canonical import AUDIT_FURTHER, audit_content_hash

ORG = "org_test000000000000000"
SET = {"version": "v1.0.0", "name": "refunds", "description": "The refund agent's refunds",
       "scope": {"org_id": ORG, "environment": "dev"},
       "rules": [{"name": "allow_refunds", "priority": 100, "description": "Refunds are allowed",
                  "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                  "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}]}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _client(tmp_path) -> HIITL:
    path = tmp_path / "refunds.json"
    path.write_text(json.dumps(SET))
    return HIITL(environment="dev", agent_id="refund-agent", org_id=ORG, policy_path=str(path),
                 audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")


def test_a_stored_result_altered_no_longer_verifies(tmp_path):
    """Behavior 3, in the store: the result record verifies as written; once its result is changed in the store, it
    does not, and the decision record beside it still does."""
    h = _client(tmp_path)
    d = h.evaluate("refund")
    result = h.record_result(d.action_id, "succeeded", duration_ms=12)
    decided = [r for r in h._audit_logger.lifecycle(ORG, "dev", d.action_id) if "execution_result" not in r][0]
    log = h._audit_logger
    assert log.verify_integrity(result["event_id"]) and log.verify_integrity(decided["event_id"])

    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    conn.execute("UPDATE audit_log SET execution_result = ? WHERE event_id = ?",
                 (json.dumps({"status": "failed", "duration_ms": 12}), result["event_id"]))
    conn.commit()
    conn.close()

    assert not log.verify_integrity(result["event_id"]), "an altered result no longer verifies"
    assert log.verify_integrity(decided["event_id"])


def test_the_upload_carries_the_result_and_its_hash(tmp_path):
    """Behavior 5, the hybrid upload: the result record goes up with its `execution_result`, and its `content_hash`
    is over every term it carries; the decision record carries no `execution_result` and hashes as before."""
    h = _client(tmp_path)
    d = h.evaluate("refund")
    h.record_result(d.action_id, "succeeded", duration_ms=12)

    unsynced = h._audit_logger.get_unsynced(limit=10)
    assert [r.get("execution_result") for r in unsynced] == [None, {"status": "succeeded", "duration_ms": 12}]
    assert [r["event_type"] for r in unsynced] == ["action.evaluated", "action.executed"]
    assert "execution_result" not in unsynced[0] and "redaction" not in unsynced[0], "a member is carried or absent"
    for r in unsynced:
        further = {m: r[m] for m in AUDIT_FURTHER if m in r}
        assert audit_content_hash(r["event_id"], r["envelope"], r["decision"], **further) == r["content_hash"]
    decision, result = unsynced
    assert (result["envelope"], result["decision"]) == (decision["envelope"], decision["decision"]), \
        "the result record carries the decision record's envelope and decision as stored"
    assert result["event_id"] != decision["event_id"]
