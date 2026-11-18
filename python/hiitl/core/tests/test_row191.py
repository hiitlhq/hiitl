"""Row 191 (HTL-23, Stop A): what a record's hash covers.

Ruled 2026-11-06: "each content member a record carries beyond its envelope and decision joins the hash as a further
term in a fixed order (`…:{C(execution_result)}` on a result, `…:{C(redaction)}` where a path is named); a record
carrying neither hashes exactly as today ...; one function per language". By the security architecture §1.4, "Every
audit record includes a SHA-256 hash of its own content, computed at write time", and Tier 1, "Enables individual
record tamper detection". Design: the HTL-23 test design, row 191, behavior 3. The digests are the
conformance cases' (tests/conformance/audit_hash/), computed from the spec's string. Mirrors
typescript/packages/core/tests/unit/row191.test.ts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hiitl.core.canonical import _audit_content_hash as audit_content_hash, _canonical_json as canonical_json

CASES = Path(__file__).resolve().parents[4] / "tests" / "conformance" / "audit_hash"


def _case(name: str) -> dict:
    return json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))


def _hash(c: dict, **further) -> str:
    return audit_content_hash(c["event_id"], c["envelope"], c["decision"], **further)


def test_an_altered_result_fails_its_hash():
    """A result record's stored digest no longer verifies once any member of its result is changed, or the result is
    dropped: the result is in the hash, so it cannot be altered unseen."""
    c = _case("case_002_result_record")
    stored, result = c["expected"]["content_hash"], c["execution_result"]
    assert _hash(c, execution_result=result) == stored

    altered = {
        "status": {**result, "status": "succeeded"},
        "error": {**result, "error": "card declined"},
        "duration_ms": {**result, "duration_ms": 1},
        "a member added": {**result, "response_id": "ch_1"},
    }
    for what, result in altered.items():
        assert _hash(c, execution_result=result) != stored, what
    assert _hash(c) != stored, "a result record read without its result does not verify"


def test_an_altered_absent_path_fails_its_hash():
    """The `redaction` member is in the hash: a path dropped from it, or the order changed, no longer verifies."""
    c = _case("case_003_absent_path")
    stored, absent = c["expected"]["content_hash"], c["redaction"]["absent"]
    assert _hash(c, redaction=c["redaction"]) == stored
    assert _hash(c, redaction={"absent": absent[:1]}) != stored
    assert _hash(c, redaction={"absent": absent[::-1]}) != stored
    assert _hash(c) != stored


def test_a_term_is_joined_on_presence_never_on_value():
    """A member is a term because the record carries it. A record carrying `null` joins `:null`; a record carrying
    neither member gives the digest it gave before row 191."""
    c = _case("case_001_fixed_record")
    base = f"{c['event_id']}:{canonical_json(c['envelope'])}:{canonical_json(c['decision'])}"
    assert _hash(c) == c["expected"]["content_hash"] == hashlib.sha256(base.encode("utf-8")).hexdigest()
    assert _hash(c, execution_result=None) == hashlib.sha256(f"{base}:null".encode("utf-8")).hexdigest()
    assert _hash(c, redaction=None) == _hash(c, execution_result=None), "one form for a further term"


def test_a_term_the_record_does_not_name_is_refused():
    """The further terms are the record's own member names: another spelling would hash without its term, unseen."""
    c = _case("case_002_result_record")
    with pytest.raises(TypeError, match="executionResult; a record's further terms are execution_result, redaction"):
        _hash(c, executionResult=c["execution_result"])
