"""Row 210 (HTL-23): `trace_id` takes W3C Trace Context's form.

Ruled 2026-11-06: "`trace_id` takes the pattern `^[0-9a-f]{32}$` in place of its `maxLength: 128` … It is a breaking
change and enters through [the schema-versioning rule's] own door, 'migration paths before breaking changes': the
schema version bumps and the migration path is written at the bump." The pattern and its example are read from
envelope_schema.json; each other form is the example changed one way. Design: the HTL-23 test design, row 210,
behavior 1.
Mirrors typescript/packages/core/tests/unit/row210.test.ts.
"""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, Envelope

ROOT = Path(__file__).resolve().parents[4]
TRACE_ID = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))[
    "properties"]["trace_id"]
PATTERN = re.compile(TRACE_ID["pattern"])
EXAMPLE = TRACE_ID["examples"][0]
OTHERS = {
    "uppercase": EXAMPLE.upper(),
    "one short": EXAMPLE[:-1],
    "one long": EXAMPLE + EXAMPLE[-1],
    "a caller's own id": "req-r210-0001",
}


def _envelope(**fields) -> dict:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION,
            "org_id": "org_test123456789012", "environment": "dev", "agent_id": "agent-210",
            "action_id": "act_01234567890123456789", "idempotency_key": "idem_row210", "action": "send_invoice",
            "timestamp": "2026-11-06T12:00:00Z", "signature": "a" * 64, **fields}


def test_the_schema_declares_the_form():
    """The schema's pattern takes its example and none of the other forms; `maxLength` is gone (the ruling's "in place
    of")."""
    assert PATTERN.fullmatch(EXAMPLE)
    assert [name for name, value in OTHERS.items() if PATTERN.fullmatch(value)] == []
    assert "maxLength" not in TRACE_ID


def test_the_form_is_taken():
    """Behavior 1: 32 lowercase hex is taken as given."""
    assert Envelope.model_validate(_envelope(trace_id=EXAMPLE)).trace_id == EXAMPLE


def test_no_trace_id_is_taken():
    """The field stays optional."""
    assert Envelope.model_validate(_envelope()).trace_id is None


@pytest.mark.parametrize("value", OTHERS.values(), ids=OTHERS.keys())
def test_another_form_is_refused_naming_the_field(value):
    """Behavior 1: each other form is refused, at `trace_id`."""
    with pytest.raises(ValidationError) as exc:
        Envelope.model_validate(_envelope(trace_id=value))
    assert [tuple(e["loc"]) for e in exc.value.errors()] == [("trace_id",)]
