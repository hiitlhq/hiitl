"""Row 163 (HTL-22) (a), (c) and (e): the SDK's store and the org's declaration, and the store's value-hash key.

Ruled by Trevor 2026-11-05, on HTL-20: "(a) the hybrid SDK pulls the org's redaction policy; … (c) the gateway's hash is
keyed (HMAC); … (e) a declared path the call does not carry is named in the record, never skipped silently". The SDK
redacts the union of the org's declaration and its own, since a path only one of them declares would otherwise be
written in clear, and the store's key is made at its first start and kept beside it, never synced. (e) turned with
Stop A (HTL-23 row 191: the record's `redaction` member joins its hash). The contract is event_format.md §Redaction;
these are the row's test design cells 2, 3, 10 and 13.
"""

from __future__ import annotations

import itertools
import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hiitl.core.canonical import audit_content_hash
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.redaction import KEY_BYTES, MARKER, Redaction, value_hash
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, Envelope, PolicySet
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import AuditLogError, SyncError
from hiitl.sdk.hash_key import SUFFIX, key_path
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import PolicyDownloadResult
from hiitl.sdk.sync_engine import SyncEngine

ORG, ENV = "org_test0123456789ab", "dev"
ALLOW = PolicySet(name="p", version="v1.0.0", description="Payouts the payout agent may make",
                  scope={"org_id": ORG, "environment": ENV}, rules=[
    {"name": "allow", "description": "a", "priority": 1, "decision": "ALLOW", "reason_code": "OK",
     "conditions": {"field": "action", "operator": "exists", "value": True}}])
PARAMETERS = {"account_number": "GB29NWBK60161331926819", "amount": 1250}
TARGET = {"email": "dana@example.com", "vendor_id": "vnd_42"}


def _write(audit, i=0, parameters=PARAMETERS, action="pay"):
    env = Envelope(schema_version=ENVELOPE_SCHEMA_VERSION, org_id=ORG, environment=ENV, agent_id="payout-agent",
                   action_id=f"act_{i:020d}", idempotency_key=f"k{i}", action=action, operation="execute",
                   target=TARGET, parameters=parameters, timestamp=datetime.now(timezone.utc), signature="0" * 64)
    audit.write(env, PolicyEvaluator().evaluate(env, ALLOW))


def _stored(db):
    with sqlite3.connect(db) as c:
        return [json.loads(e) for (e,) in c.execute("SELECT envelope FROM audit_log ORDER BY rowid")]


def _engine(tmp_path, redaction_policy):
    cache = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    engine = SyncEngine(sync_config=SyncConfig(server_url="https://api.hiitl.com", cache_dir=str(tmp_path / "cache")),
                        sync_cache=cache, audit_logger=MagicMock(), api_key="sk_test_123", org_id=ORG,
                        environment=ENV)
    engine._client = MagicMock()
    engine._client.download_policies.return_value = PolicyDownloadResult(
        policies=[], version="v2", etag="e2", redaction_policy=redaction_policy)
    return engine, cache


# ── (a) the pull and the union ─────────────────────────────────────────────────────────────────────────────────

def test_the_pull_caches_the_orgs_declaration(tmp_path):
    engine, cache = _engine(tmp_path, {"manual_redact_fields": ["target.email", "parameters.iban"]})
    assert cache.get_redaction_fields() == [], "nothing until a pull lands"
    assert engine._sync_policies() is True
    assert cache.get_redaction_fields() == ["target.email", "parameters.iban"]
    restarted = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    restarted.load_from_disk()
    assert restarted.get_redaction_fields() == ["target.email", "parameters.iban"], "kept across a restart"
    engine._client.close()


@pytest.mark.parametrize("redaction_policy", [
    None,                                                    # a server that does not send it
    {},                                                      # the member missing
    {"manual_redact_fields": "target.email"},                # not a list
    {"manual_redact_fields": ["org_id"]},                    # an entry that is not a declared field
])
def test_a_pull_without_the_declaration_is_refused(tmp_path, redaction_policy):
    engine, cache = _engine(tmp_path, redaction_policy)
    cache.update_policies({"policies": [{"name": "seed"}], "version": "v1",
                           "redaction_policy": {"manual_redact_fields": ["target.email"]}}, etag="e1")
    with pytest.raises(SyncError) as e:
        engine._sync_policies()
    assert e.value.channel == "policy" and "redaction_policy" in str(e.value)
    assert cache.get_policies_etag() == "e1" and cache.get_redaction_fields() == ["target.email"], \
        "a false absence is the dangerous direction: the cache keeps what it had"
    engine._client.close()


def test_the_store_applies_the_union_at_each_write(tmp_path):
    db = tmp_path / "audit.db"
    org = []
    audit = AuditLogger(str(db), redaction=Redaction.declared(["parameters.account_number"]),
                        org_declared=lambda: org)
    _write(audit, 0)
    org[:] = ["target.email", "parameters.account_number"]
    _write(audit, 1)
    before, after = _stored(db)
    assert before["parameters"]["account_number"] == MARKER and before["target"]["email"] == TARGET["email"]
    assert after["parameters"] == {"account_number": MARKER, "amount": 1250}
    assert after["target"] == {"email": MARKER, "vendor_id": "vnd_42"}, "the cache's change reaches the next write"


# ── (c) the store's value-hash key ─────────────────────────────────────────────────────────────────────────────

GATEWAY = Redaction.declared(None, {"pay": []})               # the gateway's form: every parameter hashed


def test_the_key_is_made_beside_the_store_once(tmp_path):
    db = tmp_path / "gateway" / "audit.db"
    first = AuditLogger(str(db), redaction=GATEWAY)
    key_file = key_path(db)
    assert key_file.parent == db.parent and stat.S_IMODE(key_file.stat().st_mode) == 0o600
    key = key_file.read_bytes()
    assert len(key) == KEY_BYTES
    _write(first, 0)
    first.close()

    second = AuditLogger(str(db), redaction=GATEWAY)           # the next start
    _write(second, 1)
    a, b = _stored(db)
    assert a["parameters"] == b["parameters"] == {k: value_hash(v, key) for k, v in PARAMETERS.items()}, \
        "the next start reads the key it made: hashes compare across restarts"
    assert key_file.read_bytes() == key

    uploaded = json.dumps(second.get_unsynced(limit=10))
    on_disk = db.read_bytes() + b"".join(p.read_bytes() for p in db.parent.glob("audit.db-*"))
    assert key.hex() not in uploaded and key not in on_disk, "the key is in no record and no upload"
    second.close()



def test_a_name_through_a_link_reads_the_one_key_beside_the_file(tmp_path):
    """The key is beside the file the store's name resolves to, where SQLite keeps its journal, so a name through a
    symbolic link reads the key the file's own path made and makes none beside the link (HTL-29 review, condition 3)."""
    db = tmp_path / "audit.db"
    first = AuditLogger(str(db), redaction=GATEWAY)
    _write(first, 0)
    first.close()
    (tmp_path / "links").mkdir()
    link = tmp_path / "links" / "audit.db"
    link.symlink_to(db)

    second = AuditLogger(str(link), redaction=GATEWAY)
    _write(second, 1)
    a, b = _stored(db)
    assert a["parameters"] == b["parameters"], "both names hash under the one key"
    assert list((tmp_path / "links").iterdir()) == [link], "no key is made beside the link"
    second.close()


def test_a_first_start_through_a_link_makes_the_key_beside_the_file(tmp_path):
    """The key is read once the store has opened, so a first start through a link to a file not yet made makes the key
    beside the file SQLite made, never beside the link (HTL-29 review, condition 3)."""
    (tmp_path / "links").mkdir()
    link = tmp_path / "links" / "audit.db"
    link.symlink_to(tmp_path / "audit.db")
    AuditLogger(str(link), redaction=GATEWAY).close()
    assert list((tmp_path / "links").iterdir()) == [link], "no key is made beside the link"
    assert key_path(tmp_path / "audit.db").parent == tmp_path and key_path(tmp_path / "audit.db").exists()


def _earlier_release(db: Path, name: Path) -> bytes:
    """The store a release before HTL-29's condition 3 left when it was given `name`, a symbolic link to `db`: a record
    hashed under the key it made beside the name it was given, and no key beside the file. Returns that key."""
    name.parent.mkdir(exist_ok=True)
    name.symlink_to(db)
    audit = AuditLogger(str(db), redaction=GATEWAY)
    _write(audit, 0)
    audit.close()
    os.rename(key_path(db), f"{name}{SUFFIX}")
    return Path(f"{name}{SUFFIX}").read_bytes()


def test_a_key_an_earlier_release_left_beside_the_link_is_the_stores_key(tmp_path):
    """A release before this one made the key beside the name it was given, a link to the file. The next start through
    that name reads that key and writes it beside the file, leaving it where it was, so a value hashes the same across
    the upgrade; the file's own name then reads it, and the two equal keys on the way are one (HTL-29 second review,
    condition 3; event_format.md "a value hashes the same across restarts and two records of one store compare")."""
    db, link = tmp_path / "audit.db", tmp_path / "links" / "audit.db"
    old = _earlier_release(db, link)
    for i, name in enumerate((link, db, link), start=1):
        audit = AuditLogger(str(name), redaction=GATEWAY)
        _write(audit, i)
        audit.close()
        assert key_path(db).is_file() and key_path(db).read_bytes() == old, "the key is written beside the file"
    hashed = {k: value_hash(v, old) for k, v in PARAMETERS.items()}
    assert [r["parameters"] for r in _stored(db)] == [hashed] * 4, "every record hashes under the one key"
    assert stat.S_IMODE(key_path(db).stat().st_mode) == 0o600
    assert Path(f"{link}{SUFFIX}").is_file() and Path(f"{link}{SUFFIX}").read_bytes() == old, \
        "and never removed from where it was"


def test_a_key_beside_a_link_the_name_passes_through_is_the_stores_key(tmp_path):
    """A name can reach the file through more than one link, each written relative to its own directory; a key beside
    any of them is one a release before this one made for the name it was given, and is the store's key."""
    db, first = tmp_path / "audit.db", tmp_path / "links" / "first.db"
    old = _earlier_release(db, first)
    second = tmp_path / "more" / "second.db"
    second.parent.mkdir()
    second.symlink_to(Path("..") / "links" / "first.db")
    audit = AuditLogger(str(second), redaction=GATEWAY)
    _write(audit, 1)
    audit.close()
    a, b = _stored(db)
    assert a["parameters"] == b["parameters"] == {k: value_hash(v, old) for k, v in PARAMETERS.items()}
    assert key_path(db).read_bytes() == old
    assert not Path(f"{second}{SUFFIX}").exists(), "no key is made beside the name written"


def test_keys_on_the_way_that_differ_fail_the_start_naming_each(tmp_path):
    """The store was given two names under a release before this one, each of which made its own key. Its records were
    hashed under one or both, and nothing on disk says which: the start fails naming each file, and none is chosen,
    written or removed."""
    db, link = tmp_path / "audit.db", tmp_path / "links" / "audit.db"
    old = _earlier_release(db, link)
    AuditLogger(str(db), redaction=GATEWAY).close()            # the file's own name, which passes through no link
    made = key_path(db).read_bytes()
    assert made != old
    with pytest.raises(AuditLogError) as e:
        AuditLogger(str(link), redaction=GATEWAY)
    assert str(key_path(db)) in str(e.value) and f"{link}{SUFFIX}" in str(e.value)
    assert key_path(db).read_bytes() == made and Path(f"{link}{SUFFIX}").read_bytes() == old


def test_a_key_another_start_wrote_beside_the_file_meanwhile_that_differs_fails_the_start(tmp_path, monkeypatch):
    """Two starts of one store upgrade together: one through the file's own name, which reaches no link and makes a new
    key, and one through the link, which writes the earlier release's key beside the file. The first lands; the second
    reads a key beside the file that is not the one on its way, and fails naming each, as two keys found together do."""
    db, link = tmp_path / "audit.db", tmp_path / "links" / "audit.db"
    old = _earlier_release(db, link)
    other, link_file = os.urandom(KEY_BYTES), os.link

    def lands_first(src, dst):                                 # the other start's key lands beside the file first
        Path(dst).write_bytes(other)
        link_file(src, dst)

    monkeypatch.setattr(os, "link", lands_first)
    with pytest.raises(AuditLogError) as e:
        AuditLogger(str(link), redaction=GATEWAY)
    assert str(key_path(db)) in str(e.value) and f"{link}{SUFFIX}" in str(e.value)
    assert key_path(db).read_bytes() == other and Path(f"{link}{SUFFIX}").read_bytes() == old


# ── a name read as the filesystem reads it (HTL-29 third review, condition 3) ──────────────────────────────────────

def _tree(root: Path) -> Path:
    """A store and the names into it an operator makes: a link beside it, relative, and one absolute; a link in the
    directory below, written up through `..`; and a link to that directory beside the store's own. Returns the store."""
    (root / "real" / "sub").mkdir(parents=True)
    (root / "real" / "middle.db").symlink_to("audit.db")
    (root / "real" / "abs.db").symlink_to(root / "real" / "audit.db")
    (root / "real" / "sub" / "outer.db").symlink_to(Path("..") / "middle.db")
    (root / "alias").symlink_to(Path("real") / "sub")
    return root / "real" / "audit.db"


def _alias_cases(root: Path) -> list[tuple[str, str]]:
    """(a name for the store, a link on its way), each relative to `root`. The names are spelled from the tree's own
    directory names and `..`, joined as text and never normalised, up to the tree's depth and one more, through every
    directory of the tree they reach; the links are each one the filesystem passes from that name to the store, named
    in the directory the filesystem finds it in."""
    store = _tree(root)
    store.touch()
    walked = list(os.walk(root))
    names = sorted({d for _, dirs, _ in walked for d in dirs} | {os.pardir})
    depth = max(len(Path(d).relative_to(root).parts) for d, _, _ in walked) + 1
    home, cases = os.path.realpath(root), []
    for n in range(1, depth + 1):
        for parts in itertools.product(names, repeat=n):
            spelled = "/".join(parts)
            if parts[0] == os.pardir or not os.path.isdir(f"{root}/{spelled}"):
                continue
            here = os.path.realpath(f"{root}/{spelled}")
            if os.path.commonpath([here, home]) != home:
                continue
            for entry in sorted(os.listdir(here)):
                hop = f"{here}/{entry}"
                if not os.path.islink(hop) or os.path.realpath(hop) != os.path.realpath(store):
                    continue
                while os.path.islink(hop):
                    cases.append((f"{spelled}/{entry}", os.path.relpath(hop, home)))
                    target = os.readlink(hop)
                    beyond = target if os.path.isabs(target) else f"{os.path.dirname(hop)}/{target}"
                    hop = f"{os.path.realpath(os.path.dirname(beyond))}/{os.path.basename(beyond)}"
    return cases


def _upgrade(root: Path, hop: str) -> tuple[Path, Path, bytes]:
    """The tree a release before this one left when it was given a name whose way passes `hop`: a record hashed under
    the key it made beside that link, and no key beside the file. Returns the store, that key's file and the key."""
    db = _tree(root)
    audit = AuditLogger(str(db), redaction=GATEWAY)
    _write(audit, 0)
    audit.close()
    left = Path(os.path.realpath(root), f"{hop}{SUFFIX}")
    os.rename(key_path(db), left)
    return db, left, left.read_bytes()


def test_every_name_through_a_link_to_a_directory_reads_the_key_on_its_way(tmp_path):
    """Every name for the store the tree's names spell, `..` after a link to a directory included, passes the links
    the filesystem passes, so a key a release before this one left beside any of them is the store's key: written
    beside the file, left where it was, and every record hashes under it (HTL-29 third review, condition 3;
    event_format.md "Every name, the one given and each on the way, is read as the filesystem reads it")."""
    cases, missed = _alias_cases(tmp_path / "tree"), []
    assert {"alias/../middle.db", "alias/outer.db"} <= {name for name, _ in cases}, cases
    for i, (name, hop) in enumerate(cases):
        root = tmp_path / str(i)
        db, left, old = _upgrade(root, hop)
        hashed = {k: value_hash(v, old) for k, v in PARAMETERS.items()}
        try:
            audit = AuditLogger(f"{root}/{name}", redaction=GATEWAY)
            _write(audit, 1)
            audit.close()
            held = ([r["parameters"] for r in _stored(db)] == [hashed, hashed]
                    and key_path(db).read_bytes() == old and left.read_bytes() == old)
        except Exception as e:  # a start that fails is a name read otherwise than the filesystem reads it
            held = repr(e)
        if held is not True:
            missed.append((name, hop, held))
    assert missed == [], missed


def test_every_name_through_a_link_to_a_directory_refuses_a_key_on_its_way_that_differs(tmp_path):
    """The same names, with another key beside the file: the start fails naming each, and none is chosen, written or
    removed (HTL-29 third review, condition 3)."""
    missed = []
    for i, (name, hop) in enumerate(_alias_cases(tmp_path / "tree")):
        root = tmp_path / str(i)
        db, left, old = _upgrade(root, hop)
        other = os.urandom(KEY_BYTES)
        key_path(db).write_bytes(other)
        try:
            AuditLogger(f"{root}/{name}", redaction=GATEWAY).close()
            held = "started"
        except AuditLogError as e:
            held = (f"audit.db{SUFFIX}" in str(e) and f"{Path(hop).name}{SUFFIX}" in str(e)
                    and key_path(db).read_bytes() == other and left.read_bytes() == old) or str(e)
        if held is not True:
            missed.append((name, hop, held))
    assert missed == [], missed


def test_a_key_on_the_way_of_another_length_fails_the_start(tmp_path):
    db, link = tmp_path / "audit.db", tmp_path / "links" / "audit.db"
    _earlier_release(db, link)
    Path(f"{link}{SUFFIX}").write_bytes(b"\x00" * (KEY_BYTES // 2))
    with pytest.raises(AuditLogError) as e:
        AuditLogger(str(link), redaction=GATEWAY)
    assert f"{link}{SUFFIX}" in str(e.value)
    assert not key_path(db).exists(), "nothing is written beside the file"


def test_a_key_file_of_another_length_fails_the_start(tmp_path):
    db = tmp_path / "audit.db"
    key_path(db).write_bytes(b"\x00" * (KEY_BYTES // 2))
    with pytest.raises(AuditLogError) as e:
        AuditLogger(str(db), redaction=GATEWAY)
    assert str(key_path(db)) in str(e.value)


def test_an_in_memory_store_keeps_its_key_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    AuditLogger(":memory:", redaction=GATEWAY)
    assert list(tmp_path.iterdir()) == [], "a store with no file writes no key file"


def test_a_store_that_hashes_nothing_makes_no_key(tmp_path):
    for i, redaction in enumerate((None, Redaction.declared(["parameters.account_number"]))):
        db = tmp_path / f"{i}.db"
        _write(AuditLogger(str(db), redaction=redaction), i)
        assert not key_path(db).exists()


# ── (e) a declared path the call does not carry ────────────────────────────────────────────────────────────────

def test_a_declared_path_the_call_does_not_carry_is_named(tmp_path):
    """A declared path the call does not carry is named in the record, so a reader can tell a field that was absent
    from one the declaration missed (HTL-23 row 191 behavior 6): the record's `redaction` names it, in the
    declaration's order (the store's own, then the org's), and the record's hash covers it. A record whose every
    declared path is present carries no `redaction`."""
    db = tmp_path / "audit.db"
    audit = AuditLogger(str(db), redaction=Redaction.declared(["parameters.ssn", "target.email"]),
                        org_declared=lambda: ["target.phone", "parameters.ssn"])
    _write(audit, 0)
    _write(AuditLogger(str(tmp_path / "all.db"), redaction=Redaction.declared(["target.email"])), 1)
    absent, present = (AuditLogger(str(store)).get_unsynced() for store in (db, tmp_path / "all.db"))

    assert absent[0]["redaction"] == {"absent": ["parameters.ssn", "target.phone"]}
    assert audit.verify_integrity(absent[0]["event_id"])
    assert audit_content_hash(absent[0]["event_id"], absent[0]["envelope"], absent[0]["decision"],
                              redaction=absent[0]["redaction"]) == absent[0]["content_hash"]
    assert "redaction" not in present[0]
    assert audit_content_hash(present[0]["event_id"], present[0]["envelope"],
                              present[0]["decision"]) == present[0]["content_hash"]
