"""The envelope's signed form — one canonical serialisation in both languages (the security architecture §1.3;
row 127, Trevor, 2026-11-04): a fixed envelope signs and hashes to the same values here and in TypeScript
(tests/conformance/envelope_signature/)."""

import json
from pathlib import Path

import pytest

from hiitl.core.canonical import envelope_hash, envelope_signature, envelope_signed_form, envelope_verifies

CASES = sorted((Path(__file__).resolve().parents[4] / "tests" / "conformance" / "envelope_signature").glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_a_fixed_envelope_signs_to_the_conformance_values(path):
    c = json.loads(path.read_text(encoding="utf-8"))
    assert envelope_signed_form(c["envelope"]) == c["expected"]["signed_form"]
    assert envelope_signature(c["secret"], c["envelope"]) == c["expected"]["signature"] == c["envelope"]["signature"]
    assert envelope_verifies(c["secret"], c["envelope"])
    assert envelope_hash(c["envelope"]) == c["expected"]["envelope_hash"]


def test_the_cases_exist():
    assert CASES, "tests/conformance/envelope_signature/ holds at least one case"
