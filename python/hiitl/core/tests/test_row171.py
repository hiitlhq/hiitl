"""Row 171 (HTL-22): the envelope names its own signature version (one version marker; no request header names it).

Trevor's ruling on HTL-20: "one signature marker kept, by B.foundation.6". The marker kept is the envelope's
`signature_version`, by the project rule "Don't remove or rename existing fields", and the header goes. The spec is read
at its producer: envelope_schema.json's `signature_version`. Design: the HTL-22 test design, row 171, behavior 1.
Mirrors typescript/packages/core/tests/unit/row171.test.ts.
"""

import json
from pathlib import Path

from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, Envelope

ROOT = Path(__file__).resolve().parents[4]
SPEC = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))[
    "properties"]["signature_version"]

ENVELOPE = {"schema_version": ENVELOPE_SCHEMA_VERSION,
            "org_id": "org_test123456789012", "environment": "dev", "agent_id": "agent-171",
            "action_id": "act_01234567890123456789", "idempotency_key": "idem_row171", "action": "send_invoice",
            "timestamp": "2026-11-05T12:00:00Z", "signature": "a" * 64}


def test_an_envelope_left_without_one_names_the_schemas_default_its_one_value():
    assert SPEC["enum"] == [SPEC["default"]]
    assert Envelope(**ENVELOPE).signature_version == SPEC["default"]
