"""Row 224 (HTL-27): a record the service refuses for its own content, settled in the SDK's store.

Ruled 2026-11-08: "a record the service refuses for its own content stays in the local store as written, marked
refused with the service's code, logged at error, and not sent again". By event_format.md "The Lifecycle" ("a refused
result is no record and the service's answer is final"), sync_engine.md "Records are never dropped" and the `synced`
mark. sync_engine.md §2.1 is the contract: the codes are core's `RECORD_REFUSALS`, and every other refusal is retried.
Design: the HTL-27 test design, row 224, behaviors 3-7. Mirrors typescript/packages/sdk/tests/unit/row224.test.ts.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3

import httpx
import pytest

from hiitl.core.lifecycle import RECORD_REFUSALS
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import AuditUploadResult
from hiitl.sdk.sync_engine import SyncEngine

ORG, ENV = "org_r224refused00000000", "dev"
DECISION = {"decision": "ALLOW", "allowed": True, "reason_codes": ["ALLOWED"], "policy_version": "v1.0.0"}
RETRIED = ["TENANT_MISMATCH", "INSERT_FAILED", "QUOTA_EXCEEDED"]  # the spec's two, and one the SDK does not know


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell, and the retries' backoff does not wait in real time."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("hiitl.sdk.http_client.time.sleep", lambda _seconds: None)


def _written(store: AuditLogger, n: int) -> list[str]:
    """n records in the store, oldest first; their event_ids."""
    return [store.write({"org_id": ORG, "environment": ENV, "action_id": f"act_r224{i:020d}", "action": "send_email",
                         "parameters": {"to": f"ops+{i}@example.com"}}, DECISION) for i in range(n)]


class _Service:
    """The upload answer: each record named in `refusals` refused with its code, every other one accepted."""

    def __init__(self, refusals: dict):
        self.refusals, self.sent = refusals, []

    def upload_audit(self, records, sync_sequence):
        self.sent.append([r["event_id"] for r in records])
        errors = [{"event_id": r["event_id"], "code": self.refusals[r["event_id"]], "message": "not stored"}
                  for r in records if r["event_id"] in self.refusals]
        return AuditUploadResult(accepted=len(records) - len(errors), errors=errors)

    def close(self):
        pass


def _engine(tmp_path, store: AuditLogger, service: _Service, batch: int = 100) -> SyncEngine:
    engine = SyncEngine(sync_config=SyncConfig(cache_dir=str(tmp_path / "cache"), audit_batch_size=batch),
                        sync_cache=SyncCache(cache_dir=str(tmp_path / "cache"), org_id=ORG, environment=ENV),
                        audit_logger=store, api_key="sk_test_r224refused0000", org_id=ORG, environment=ENV)
    engine._client = service
    return engine


def _rows(path) -> dict:
    """Each record as the store holds it, by event_id: the columns, read directly."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = {r["event_id"]: dict(r) for r in conn.execute("SELECT * FROM audit_log")}
    conn.close()
    return rows


@pytest.mark.parametrize("code", RECORD_REFUSALS)
def test_a_record_refused_for_its_content_is_kept_marked_and_not_sent_again(tmp_path, caplog, code):
    """Behavior 3: kept as written, marked refused with the code, out of every pending read, logged at error."""
    path = tmp_path / "audit.db"
    store = AuditLogger(str(path))
    refused, accepted = _written(store, 2)
    before = _rows(path)[refused]
    service = _Service({refused: code})
    engine = _engine(tmp_path, store, service)

    with caplog.at_level(logging.WARNING, logger="hiitl.sdk.sync_engine"):
        engine._sync_audit()
        engine._sync_audit()

    rows = _rows(path)
    assert (rows[refused]["refused"], rows[refused]["synced"]) == (code, 0)
    assert (rows[accepted]["refused"], rows[accepted]["synced"]) == (None, 1)
    assert {k: v for k, v in rows[refused].items() if k != "refused"} == {k: v for k, v in before.items()
                                                                           if k != "refused"}, "kept as written"
    assert store.verify_integrity(refused)
    assert service.sent == [[refused, accepted]], "not sent again"
    assert (store.get_unsynced(), store.unsynced_backlog(), store.count_unsynced(), store.unsynced_action_ids()) == (
        [], (0, 0), 0, set())
    logged = [(r.levelname, r.getMessage()) for r in caplog.records if refused in r.getMessage()]
    assert [level for level, _ in logged] == ["ERROR"]
    assert code in logged[0][1] and "not stored" in logged[0][1], "naming the event, the code and the message"


@pytest.mark.parametrize("code", RETRIED)
def test_every_other_refusal_is_retried(tmp_path, caplog, code):
    """Behavior 4: the record stays pending, logged at warning, and the drain stops until the next interval."""
    path = tmp_path / "audit.db"
    store = AuditLogger(str(path))
    held, behind = _written(store, 2)
    service = _Service({held: code})
    engine = _engine(tmp_path, store, service, batch=1)

    with caplog.at_level(logging.WARNING, logger="hiitl.sdk.sync_engine"):
        engine._sync_audit()

    assert service.sent == [[held]], "the drain stops"
    assert _rows(path)[held]["refused"] is None
    assert [r["event_id"] for r in store.get_unsynced()] == [held, behind]
    assert [r.levelname for r in caplog.records if held in r.getMessage()] == ["WARNING"]

    service.refusals = {}
    engine._sync_audit()
    assert service.sent[1:] == [[held], [behind]], "sent again at the next interval"
    assert store.get_unsynced() == []


def test_the_records_behind_a_refused_one_drain(tmp_path):
    """Behavior 5: a refusal for the record's content does not stop the drain."""
    path = tmp_path / "audit.db"
    store = AuditLogger(str(path))
    refused, *behind = _written(store, 3)
    service = _Service({refused: "CONTENT_HASH_MISMATCH"})

    _engine(tmp_path, store, service, batch=1)._sync_audit()

    assert service.sent == [[refused], [behind[0]], [behind[1]]]
    assert [_rows(path)[e]["synced"] for e in behind] == [1, 1]


def test_a_store_written_before_the_mark_gains_it(tmp_path):
    """Behavior 7: a store whose table has no `refused` column opens with it, null on every record it holds, and keeps
    their marks: the record it had synced stays synced, and the other is still to send (Codex's condition 3, C3.1)."""
    path = tmp_path / "audit.db"
    first = AuditLogger(str(path))
    events = _written(first, 2)
    first.mark_synced(events[:1])
    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE audit_log DROP COLUMN refused")
    conn.commit()
    conn.close()

    store = AuditLogger(str(path))
    conn = sqlite3.connect(str(path))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(audit_log)")]
    conn.close()
    assert "refused" in columns, "the store gains the mark"
    assert [r["event_id"] for r in store.get_unsynced()] == events[1:]
    assert {e: (r["synced"], r["refused"]) for e, r in _rows(path).items()} == {events[0]: (1, None),
                                                                               events[1]: (0, None)}


# The hosted client settles its push the same way (behavior 6)

SERVER = "https://ecp.r224.example.com"
EVALUATE, PUSH = f"{SERVER}/v1/evaluate", f"{SERVER}/v1/sync/audit"


def _decides(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "action_id": json.loads(request.content)["action_id"], "decision": "ALLOW", "allowed": True,
        "reason_codes": ["ALLOWED"], "policy_version": "v1.0.0", "timing": {"total_ms": 1.0}})


def _hiitl(path) -> HIITL:
    return HIITL(environment=ENV, agent_id="r224-agent", org_id=ORG, api_key="sk_test_r224refused0000",
                 server_url=SERVER, evaluation="remote", signature_key="r224-signing-secret-0123456789abcdef",
                 audit_db_path=str(path), max_retries=0)


def test_the_hosted_client_settles_its_push_the_same_way(httpx_mock, tmp_path, caplog):
    """Two outages hold two records (the second call's push met none); the next push refuses the first for its own
    content, and the client marks it refused, the second synced, and sends neither again."""
    path = tmp_path / "audit.db"
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=EVALUATE)
    httpx_mock.add_exception(httpx.ConnectError("Connection refused"), url=PUSH)

    def refuses_the_first(request: httpx.Request) -> httpx.Response:
        records = json.loads(request.content)["records"]
        return httpx.Response(200, json={"accepted": 1, "duplicates": 0, "errors": [
            {"event_id": records[0]["event_id"], "code": "EVENT_TYPE_MISMATCH", "message": "not its decision's"}]})

    httpx_mock.add_callback(refuses_the_first, url=PUSH)
    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(path)
    first, second = h.evaluate("send_email"), h.evaluate("send_email")
    with caplog.at_level(logging.WARNING):
        h.evaluate("send_email")
    h.close()

    rows = {r["action_id"]: r for r in _rows(path).values()}
    assert (rows[first.action_id]["refused"], rows[first.action_id]["synced"]) == ("EVENT_TYPE_MISMATCH", 0)
    assert (rows[second.action_id]["refused"], rows[second.action_id]["synced"]) == (None, 1)
    assert [r.levelname for r in caplog.records if "EVENT_TYPE_MISMATCH" in r.getMessage()] == ["ERROR"]

    httpx_mock.add_callback(_decides, url=EVALUATE)
    h = _hiitl(path)
    h.evaluate("send_email")
    h.close()
    assert [r.url.path for r in httpx_mock.get_requests()][4:] == ["/v1/evaluate"], \
        "constructed again, the client sends nothing refused"
