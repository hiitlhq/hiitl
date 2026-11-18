"""Row 206 (HTL-23): each core model refuses a value outside an enum its spec declares.

Ruled 2026-11-06 as the row reads: "each core model refuses it, row 147's class". Row 147 (R-1170): "each model
refuses what its spec refuses". The row found `signature_version`; the class is every enum envelope_schema.json
declares, read from the schema, never listed here (item 13). Design: the HTL-23 test design, row 206.
Mirrors typescript/packages/core/tests/unit/row206.test.ts.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, Envelope

ROOT = Path(__file__).resolve().parents[4]
ENVELOPE_SCHEMA = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))
OUTSIDE = "outside-r206"
PRINCIPAL = {"sub": "user-r206", "verified_by": "sdk_verifier"}


def _enums(node: dict, path: tuple = ()):
    """(path, members) of each enum the schema declares; an array's item is its index 0."""
    if "enum" in node:
        yield path, node["enum"]
    for name, sub in node.get("properties", {}).items():
        yield from _enums(sub, path + (name,))
    if isinstance(node.get("items"), dict):
        yield from _enums(node["items"], path + (0,))


ENUMS = list(_enums(ENVELOPE_SCHEMA))
IDS = [".".join(map(str, path)) for path, _ in ENUMS]


def _envelope(**fields) -> dict:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION,
            "org_id": "org_test123456789012", "environment": "dev", "agent_id": "agent-206",
            "action_id": "act_01234567890123456789", "idempotency_key": "idem_row206", "action": "send_invoice",
            "timestamp": "2026-11-06T12:00:00Z", "signature": "a" * 64, "principal": dict(PRINCIPAL), **fields}


def _with(path: tuple, value) -> dict:
    """An envelope whose value at `path` is `value`."""
    envelope = _envelope()
    node = envelope
    for step, after in zip(path, path[1:]):
        node = node.setdefault(step, [None] if isinstance(after, int) else {})
    node[path[-1]] = value
    return envelope


def test_the_schema_declares_the_row_s_enum():
    assert ("signature_version",) in [path for path, _ in ENUMS]


@pytest.mark.parametrize("path, members", ENUMS, ids=IDS)
def test_a_value_outside_the_enum_is_refused_naming_the_field(path, members):
    """Behavior 1: the model refuses the envelope, at the field."""
    with pytest.raises(ValidationError) as exc:
        Envelope.model_validate(_with(path, OUTSIDE))
    found = [tuple(e["loc"]) for e in exc.value.errors()]
    assert any(loc[:len(path)] == path for loc in found), f"refused at {path}: got {found}"


@pytest.mark.parametrize("path, members", ENUMS, ids=IDS)
def test_each_member_of_the_enum_is_taken(path, members):
    """Behavior 2: each member the schema names is taken."""
    for member in members:
        Envelope.model_validate(_with(path, member))


def test_an_envelope_with_no_signature_version_takes_the_default():
    """Behavior 2: an envelope with none is taken, as the schema's default."""
    assert Envelope.model_validate(_envelope()).signature_version == \
        ENVELOPE_SCHEMA["properties"]["signature_version"]["default"]
