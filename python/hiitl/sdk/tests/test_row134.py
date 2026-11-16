"""Row 134 with row 127 (HTL-20): the Python SDK signs the envelope it records, verifies it before evaluating, and
every decision carries envelope_hash.

the security architecture §1.3: "The SDK signs every envelope … The evaluator verifies before processing". Row 127
(Trevor, 2026-11-04): "one canonical form everywhere". Security Tier 1: "Decision includes SHA-256 of the evaluated
envelope". Design: the HTL-20 test design, row 134, behaviors 2, 11 and 12.
"""

from __future__ import annotations

import json

import pytest

from hiitl.core.canonical import envelope_hash, envelope_signature
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL

KEY = "row134-local-signing-key-0123456789abcdef"


def _verifier(token: str) -> dict:
    return {"sub": "ledgerbot-ops", "scope": "refunds:write"}


def _client(tmp_path, **kw):
    return HIITL(audit_db_path=str(tmp_path / "a.db"), principal_verifier=_verifier, **kw)


def _records(tmp_path):
    return AuditLogger(str(tmp_path / "a.db")).get_unsynced(limit=10)


def test_the_record_alone_re_derives_its_signature(tmp_path):
    """Behavior 2 (row 127's exit cell): the recorded envelope — an SDK-verified principal, a nested value, a float, a
    caller's null — signs to its own `signature` through the one signed form, under the key."""
    _client(tmp_path, signature_key=KEY).evaluate(
        "refund", parameters={"amount": 150.0, "memo": "é", "items": [{"sku": "a", "note": None}]},
        target={"account_id": "acct_123"}, principal_token="t")
    (rec,) = _records(tmp_path)
    env = rec["envelope"]
    assert env["principal"]["verified_by"] == "sdk_verifier"
    assert env["signature"] == envelope_signature(KEY, env)
    assert env["parameters"]["items"][0] == {"sku": "a", "note": None}


def test_without_a_key_the_signature_is_zeros(tmp_path):
    _client(tmp_path).evaluate("refund")
    (rec,) = _records(tmp_path)
    assert rec["envelope"]["signature"] == "0" * 64


def test_an_envelope_altered_after_signing_is_refused_and_recorded(tmp_path, monkeypatch):
    """Behavior 11: local mode verifies before evaluating, with the same key. The refusal is the decision
    SIGNATURE_INVALID, recorded (the security architecture §1.3: "action rejected with `SIGNATURE_INVALID`, audit
    record written"; HTL-22 row 159)."""
    h = _client(tmp_path, signature_key=KEY)
    build = h._build_envelope

    def altered(**fields):
        envelope = build(**fields)
        envelope.parameters["amount"] = 1_000_000
        return envelope

    monkeypatch.setattr(h, "_build_envelope", altered)
    d = h.evaluate("refund", parameters={"amount": 10})
    assert (d.decision, d.allowed, d.reason_codes) == (
        "SIGNATURE_INVALID", False, ["ENVELOPE_SIGNATURE_VERIFICATION_FAILED"])
    assert d.error.code == "SIGNATURE_INVALID"
    (rec,) = _records(tmp_path)
    assert rec["decision"]["decision"] == "SIGNATURE_INVALID"
    assert rec["envelope"]["parameters"]["amount"] == 1_000_000
    assert d.envelope_hash == envelope_hash(rec["envelope"])


@pytest.mark.parametrize("key", [KEY, None], ids=["signed", "unsigned"])
def test_the_local_decision_carries_the_envelope_hash(tmp_path, key):
    """Behavior 12: SHA-256 of the evaluated envelope's signed form, in local mode too, recorded with the decision."""
    decision = _client(tmp_path, signature_key=key).evaluate("refund", parameters={"amount": 10})
    (rec,) = _records(tmp_path)
    assert decision.envelope_hash == envelope_hash(rec["envelope"])
    assert rec["decision"]["envelope_hash"] == decision.envelope_hash
    assert json.dumps(rec["envelope"]).count('"signature"') == 1
