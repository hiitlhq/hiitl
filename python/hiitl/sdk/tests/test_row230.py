"""Row 230 (HTL-29): the SDK store names the record's action `action`, its source's name.

Ruled 2026-11-09: "the record's projection of the action takes its source's name, `action`, in the next version of the
record format ... the hosted `AuditEvent` column, both SDK stores' columns and the audit query's filter rename with it,
by migration, never in place". event_format.md 2.0, "From 1.x": each SDK store, when it opens, renames each column of
its own whose name the envelope schema renamed, so a store written before 2.0 keeps each record it holds, with its
value, its hash and its `synced` mark. Design: the HTL-29 test design, row 230, behaviors 6-7. Mirrors
typescript/packages/sdk/tests/unit/row230.test.ts.
"""

from __future__ import annotations

import json
import sqlite3

from hiitl.core.canonical import audit_content_hash
from hiitl.core.types import ENVELOPE_RENAMED
from hiitl.sdk.audit import AuditLogger

ORG, ENV = "org_r230action00000000", "dev"
DECISION = {"decision": "ALLOW", "allowed": True, "reason_codes": ["ALLOWED"], "policy_version": "v1.0.0"}


def _written(store: AuditLogger, n: int) -> list[str]:
    """n records in the store, oldest first; their event_ids."""
    return [store.write({"org_id": ORG, "environment": ENV, "action_id": f"act_r230{i:020d}", "action": "send_email",
                         "agent_id": "r230-agent", "parameters": {"to": f"ops+{i}@example.com"}}, DECISION)
            for i in range(n)]


def _columns(path) -> list[str]:
    conn = sqlite3.connect(str(path))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(audit_log)")]
    conn.close()
    return columns


def _rows(path) -> dict:
    """Each record as the store holds it, by event_id: the columns, read directly."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = {r["event_id"]: dict(r) for r in conn.execute("SELECT * FROM audit_log")}
    conn.close()
    return rows


def test_a_new_store_names_the_action_as_the_envelope_does(tmp_path):
    """Behavior 6: the table has `action` and no column the envelope schema renamed; a record as written, as its
    lifecycle reads it and as the upload reads it, carries `action`, its envelope's, and a result record too."""
    path = tmp_path / "audit.db"
    store = AuditLogger(str(path))
    _written(store, 1)
    assert "action" in _columns(path) and not set(ENVELOPE_RENAMED) & set(_columns(path)), _columns(path)

    [decided] = store.lifecycle(ORG, ENV, f"act_r230{0:020d}")
    assert decided.get("action") == decided["envelope"]["action"] == "send_email" and "tool_name" not in decided
    result = store.write_result(decided, {"status": "succeeded"})
    assert result.get("action") == "send_email" and "tool_name" not in result, "the result record names it as its decision"

    sent = store.get_unsynced()
    assert [r.get("action") for r in sent] == ["send_email", "send_email"]
    assert all("tool_name" not in r for r in sent), "the upload carries the member under the envelope's name"


def test_a_store_written_before_2_0_is_renamed_when_it_opens_keeping_each_record(tmp_path):
    """Behavior 7: a store whose table names the column `tool_name`, holding a synced record and a pending one, opens
    with `action`: each record keeps its value, its hash and its mark, the pending one uploads carrying `action`, and
    the store writes on as any 2.0 store does."""
    path = tmp_path / "audit.db"
    first = AuditLogger(str(path))
    events = _written(first, 2)
    first.mark_synced(events[:1])
    conn = sqlite3.connect(str(path))
    for old, new in ENVELOPE_RENAMED.items():
        conn.execute(f"ALTER TABLE audit_log RENAME COLUMN {new} TO {old}")
    conn.commit()
    conn.close()
    before = _rows(path)
    assert {r["tool_name"] for r in before.values()} == {"send_email"}, "a 1.x store, holding its records"

    store = AuditLogger(str(path))
    columns = _columns(path)
    assert "action" in columns and "tool_name" not in columns, columns
    after = _rows(path)
    assert after == {e: {ENVELOPE_RENAMED.get(k, k): v for k, v in r.items()} for e, r in before.items()}, \
        "each record keeps each value it held, under the column's new name"
    assert {e: r["synced"] for e, r in after.items()} == {events[0]: 1, events[1]: 0}
    for e, r in after.items():
        assert r["content_hash"] == audit_content_hash(e, json.loads(r["envelope"]), json.loads(r["decision"])), e

    [pending] = store.get_unsynced()
    assert (pending["event_id"], pending.get("action")) == (events[1], "send_email") and "tool_name" not in pending

    [again] = _written(store, 1)
    assert _rows(path)[again].get("action") == "send_email"
    AuditLogger(str(path))
    assert _columns(path) == columns, "a 2.0 store opens as it is"
