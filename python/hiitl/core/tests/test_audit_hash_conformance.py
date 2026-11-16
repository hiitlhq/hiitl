"""The audit content hash — one canonical serialisation in both languages (docs/specs/sync_engine.md §2.1; Trevor,
2026-10-10): a fixed record hashes to the same digest here and in TypeScript (tests/conformance/audit_hash/).

Each content member a record carries beyond its envelope and decision joins the hash as a further term, in a fixed
order (Stop A, ruled 2026-11-06; event_format.md 1.5; `review` at 1.6, row 217): a case carries the members its
record carries, and a case carrying none hashes exactly as before. The terms and their order are read from
event_format.md's `content_hash` row."""

import json
import re
from pathlib import Path

import pytest

from hiitl.core.canonical import AUDIT_FURTHER, audit_content_hash, canonical_json

ROOT = Path(__file__).resolve().parents[4]
CASES = sorted((ROOT / "tests" / "conformance" / "audit_hash").glob("*.json"))
_ROW = next(line for line in (ROOT / "docs" / "specs" / "event_format.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| `content_hash` |"))
FURTHER = tuple(re.findall(r"then `:\{C\((\w+)\)\}`", _ROW))   # the spec's further terms, in its order


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_a_fixed_record_hashes_to_the_conformance_digest(path):
    c = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_json(c["envelope"]) == c["expected"]["canonical_envelope"]
    assert canonical_json(c["decision"]) == c["expected"]["canonical_decision"]
    for member in FURTHER:
        if member in c:
            assert canonical_json(c[member]) == c["expected"][f"canonical_{member}"]
    further = {m: c[m] for m in FURTHER if m in c}
    assert audit_content_hash(c["event_id"], c["envelope"], c["decision"], **further) == c["expected"]["content_hash"]


def test_the_case_exists():
    assert CASES, "tests/conformance/audit_hash/ holds at least one case"


def test_each_further_term_has_a_case():
    """A case carrying none of the further terms, a case for each term, and one carrying them all (event_format.md,
    Conformance Testing); the spec's row names the terms."""
    assert FURTHER, "event_format.md's content_hash row names its further terms"
    carried = [frozenset(m for m in FURTHER if m in json.loads(p.read_text(encoding="utf-8"))) for p in CASES]
    assert frozenset() in carried and frozenset(FURTHER) in carried, carried
    assert [m for m in FURTHER if not any(m in c for c in carried)] == []


def test_the_cores_further_terms_are_the_specs():
    """`AUDIT_FURTHER`, the one copy every store and the ingest read, is the spec's row, member for member, in order."""
    assert AUDIT_FURTHER == FURTHER
