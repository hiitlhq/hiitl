"""Row 137 (HTL-29): a mark is beside the record, and an absent hash is refused as a wrong one is.

The row 224 ruling: "a mark beside the record is what the append-only rule already allows; the record's content never
changes" (event_format.md "Append-Only Requirement"). sync_engine.md §2.2: a policy whose `content_hash` is absent,
empty, or not the hash of its `content` is refused alike; §4 "Integrity": a cache file whose sidecar is absent,
unreadable, or names another hash is discarded, and a sidecar the SDK could not write fails the write. Design: the
HTL-29 test design, row 137, behaviors 5-8. Mirrors typescript/packages/sdk/tests/unit/row137.test.ts.
"""

from __future__ import annotations

import logging
import sqlite3
from unittest.mock import MagicMock

import pytest

from hiitl.core.canonical import canonical_hash
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import SyncError
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import PolicyDownloadResult
from hiitl.sdk.sync_engine import SyncEngine

ORG, ENV = "org_test0123456789ab", "dev"
DECISION = {"decision": "ALLOW", "allowed": True, "reason_codes": ["ALLOWED"], "policy_version": "v1.0.0"}
POLICY = {"policy_id": "pol_r137", "name": "payments", "version": "v1.0.0", "content": {"rules": []}}


# --- Behavior 5: a mark is beside the record ---

def _rows(path) -> dict:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = {r["event_id"]: dict(r) for r in conn.execute("SELECT * FROM audit_log")}
    conn.close()
    return rows


def test_each_mark_changes_its_own_column_and_nothing_of_the_record(tmp_path):
    path = tmp_path / "audit.db"
    store = AuditLogger(str(path))
    synced, refused = (store.write({"org_id": ORG, "environment": ENV, "action_id": f"act_r137{i:020d}",
                                    "action": "send_email", "parameters": {"to": f"ops+{i}@example.com"}}, DECISION)
                       for i in range(2))
    before = _rows(path)

    assert store.mark_synced([synced]) == 1
    assert store.mark_refused({refused: "AUDIT_CONTENT_HASH_MISMATCH"}) == 1

    after = _rows(path)
    assert after[synced] == before[synced] | {"synced": 1}, "mark_synced writes `synced` and nothing else"
    assert after[refused] == before[refused] | {"refused": "AUDIT_CONTENT_HASH_MISMATCH"}, \
        "mark_refused writes `refused` and nothing else"
    assert store.verify_integrity(synced) and store.verify_integrity(refused), "each record's hash verifies"


# --- Behavior 6: a downloaded policy with no hash is refused as a wrong one is ---

def _engine(tmp_path):
    cache = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    engine = SyncEngine(sync_config=SyncConfig(server_url="https://api.hiitl.com", cache_dir=str(tmp_path / "cache")),
                        sync_cache=cache, audit_logger=MagicMock(), api_key="sk_test_123", org_id=ORG,
                        environment=ENV)
    engine._client = MagicMock()
    return engine, cache


def _serve(engine, policy: dict, version: str) -> None:
    engine._client.download_policies.return_value = PolicyDownloadResult(
        policies=[policy], version=version, etag=f"e-{version}", redaction_policy={"manual_redact_fields": []})


@pytest.mark.parametrize("sent, cause", [
    ("absent", "no content_hash"),
    ("", "no content_hash"),
    ("0" * 64, "content hash mismatch"),
])
def test_a_downloaded_policy_with_no_hash_is_refused_as_a_wrong_one_is(tmp_path, caplog, sent, cause):
    engine, cache = _engine(tmp_path)
    _serve(engine, POLICY | {"content_hash": canonical_hash(POLICY["content"])}, "v1")
    assert engine._sync_policies() is True, "a policy whose hash is its content's is taken"
    held = cache.get_policies()
    assert [p["policy_id"] for p in held["policies"]] == ["pol_r137"]

    changed = POLICY | {"content": {"rules": [{"name": "allow-all", "decision": "ALLOW"}]}}
    _serve(engine, changed if sent == "absent" else changed | {"content_hash": sent}, "v2")
    with caplog.at_level(logging.ERROR), pytest.raises(SyncError) as refused:
        engine._sync_policies()

    assert refused.value.channel == "policy" and cause in str(refused.value), str(refused.value)
    assert cache.get_policies() == held, "the cache keeps the policies it had"
    assert any(r.levelno == logging.ERROR and "POLICY_INTEGRITY_VIOLATION" in r.message and cause in r.message
               for r in caplog.records), "logged at error, naming the cause"
    engine._client.close()


# --- Behavior 7: a cache file with no readable sidecar is discarded ---

def _cached(tmp_path):
    SyncCache(str(tmp_path), ORG, ENV).update_policies({"version": "v1"})
    return tmp_path / ORG / ENV / "policies.json.sha256"


def _warm(tmp_path) -> SyncCache:
    cache = SyncCache(str(tmp_path), ORG, ENV)
    cache.load_from_disk()
    return cache


@pytest.mark.parametrize("sidecar", ["absent", "unreadable", "another hash"])
def test_a_cache_file_without_its_readable_hash_is_discarded(tmp_path, caplog, sidecar):
    path = _cached(tmp_path)
    assert _warm(tmp_path).get_policies() == {"version": "v1"}, "a file written with its sidecar reads back"

    path.unlink()
    if sidecar == "unreadable":
        path.mkdir()
    elif sidecar == "another hash":
        path.write_text("0" * 64)
    with caplog.at_level(logging.ERROR):
        cache = _warm(tmp_path)

    assert cache.get_policies() is None, "the file is discarded"
    assert any(r.levelno == logging.ERROR and "CACHE_INTEGRITY_VIOLATION" in r.message for r in caplog.records)


# --- Behavior 8: a sidecar the SDK cannot write fails the write ---

def test_a_sidecar_the_sdk_cannot_write_fails_the_write(tmp_path):
    path = _cached(tmp_path)
    path.unlink()
    path.mkdir()   # the sidecar's place is taken, so it cannot be written

    cache = SyncCache(str(tmp_path), ORG, ENV)
    cache.update_policies({"version": "v2"})

    assert cache.get_policies() == {"version": "v2"}, "memory stands"
    assert cache.status()["disk_synced"] is False, "the disk is marked diverged"
    assert _warm(tmp_path).get_policies() is None, "a warm start reads nothing"
