"""Row 223 (HTL-24): envelope schema 2.0.

Ruled 2026-11-07: "`$id` v2, `schema_version` `v2.0` as both SDKs' default, and a v1 envelope refused
`VALIDATION_ERROR` naming the version and the migration note; no acceptance window, no dual handling". By R-0007
("Backward-compatible field additions only … Migration path documented before breaking changes") and 1.3's
`policy_refs` "removed at the next major version". The schema's version is read from envelope_schema.json, and the
migration note's heading from the docs page that carries it. Design: the HTL-24 test design, row 223, behaviors 1–3.
Mirrors typescript/packages/core/tests/unit/row223.test.ts.
"""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiitl.core.types import ENVELOPE_MIGRATION_NOTE, ENVELOPE_SCHEMA_VERSION, Envelope

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))
DOCS = (ROOT / "docs-site" / "concepts" / "envelope.mdx").read_text(encoding="utf-8")


def _major(version: str) -> str:
    return re.fullmatch(r"v([0-9]+)\.[0-9]+", version).group(1)


def _envelope(**fields) -> dict:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": "org_test123456789012", "environment": "dev",
            "agent_id": "agent-223", "action_id": "act_01234567890123456789", "idempotency_key": "idem_row223",
            "action": "send_invoice", "timestamp": "2026-11-07T12:00:00Z", "signature": "a" * 64, **fields}


def test_the_schemas_version_is_the_cores():
    """Behavior 1: the schema states its version three times, `$id`, the pattern and the example, and each is the
    core's one constant."""
    taken = SCHEMA["properties"]["schema_version"]
    major = _major(ENVELOPE_SCHEMA_VERSION)
    assert re.search(r"/v([0-9]+)\.json$", SCHEMA["$id"]).group(1) == major
    assert re.fullmatch(taken["pattern"], ENVELOPE_SCHEMA_VERSION)
    assert taken["examples"] == [ENVELOPE_SCHEMA_VERSION]
    assert not re.fullmatch(taken["pattern"], f"v{int(major) - 1}.0")


def test_a_minor_version_of_the_major_loads():
    major = _major(ENVELOPE_SCHEMA_VERSION)
    for version in (ENVELOPE_SCHEMA_VERSION, f"v{major}.7"):
        assert Envelope.model_validate(_envelope(schema_version=version)).schema_version == version


@pytest.mark.parametrize("delta", [-1, 1])
def test_another_major_is_refused_naming_the_version_and_the_note(delta):
    """Behavior 2: the refusal names the version read, the version taken and the migration note, whose heading the
    docs page carries."""
    other = f"v{int(_major(ENVELOPE_SCHEMA_VERSION)) + delta}.0"
    with pytest.raises(ValidationError) as e:
        Envelope.model_validate(_envelope(schema_version=other))
    [error] = e.value.errors()
    assert error["loc"] == ("schema_version",)
    assert other in error["msg"] and ENVELOPE_SCHEMA_VERSION in error["msg"] and ENVELOPE_MIGRATION_NOTE in error["msg"]
    assert f"\n### {ENVELOPE_MIGRATION_NOTE}\n" in DOCS, "the note is a heading of the envelope's docs page"


def test_policy_refs_is_a_field_the_schema_does_not_define():
    """Behavior 3: refused as any undefined field is (R-0872), naming it; the schema defines it no more."""
    assert "policy_refs" not in SCHEMA["properties"]
    with pytest.raises(ValidationError) as e:
        Envelope.model_validate(_envelope(policy_refs=["payments"]))
    assert [(err["type"], err["loc"]) for err in e.value.errors()] == [("extra_forbidden", ("policy_refs",))]
