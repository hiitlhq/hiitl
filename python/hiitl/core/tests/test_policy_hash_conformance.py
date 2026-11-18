"""The policy content hash — the audit hash's canonical serialisation, read by every policy and route writer and checker
(docs/specs/sync_engine.md §2.2; Trevor, 2026-11-04): a fixed policy set hashes to the same digest here and in
TypeScript (tests/conformance/policy_hash/)."""

import hashlib
import json
from pathlib import Path

import pytest

from hiitl.core.canonical import canonical_hash, canonical_json
from hiitl.core.types import PolicySet

CASES = sorted((Path(__file__).resolve().parents[4] / "tests" / "conformance" / "policy_hash").glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_a_fixed_policy_hashes_to_the_conformance_digest(path):
    c = json.loads(path.read_text(encoding="utf-8"))
    PolicySet(**c["content"])
    assert canonical_json(c["content"]) == c["expected"]["canonical"]
    assert canonical_hash(c["content"]) == c["expected"]["content_hash"]


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_neither_older_form_reaches_the_digest(path):
    """The case discriminates: sorted keys, compact or spaced, hash its content to another digest."""
    c = json.loads(path.read_text(encoding="utf-8"))
    for separators in ((",", ":"), None):
        older = hashlib.sha256(json.dumps(c["content"], sort_keys=True, separators=separators).encode()).hexdigest()
        assert older != c["expected"]["content_hash"]


def test_the_case_exists():
    assert CASES, "tests/conformance/policy_hash/ holds at least one case"
