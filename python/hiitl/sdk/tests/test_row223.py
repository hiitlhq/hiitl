"""Row 223 (HTL-24): the SDK builds a schema 2.0 envelope.

Ruled 2026-11-07: "`$id` v2, `schema_version` `v2.0` as both SDKs' default". The envelope `evaluate()` records in
local mode is read against envelope_schema.json by the schema's own keywords (`required`, `properties`,
`additionalProperties`, a property's `pattern` and `enum`), and its version is the core's one constant. Design: the
HTL-24 test design, row 223, behavior 4. Mirrors typescript/packages/sdk/tests/unit/row223.test.ts.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from hiitl import HIITL
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))
ORG = "org_test000000000000000"


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _departures(envelope: dict) -> list[str]:
    """Where the envelope departs from the schema file, read at the file."""
    taken = SCHEMA["properties"]
    found = [f"{name} is required" for name in SCHEMA["required"] if name not in envelope]
    if SCHEMA.get("additionalProperties") is False:
        found += [f"{name} is not a property" for name in envelope if name not in taken]
    for name, value in envelope.items():
        stated = taken.get(name, {})
        if "pattern" in stated and not (isinstance(value, str) and re.search(stated["pattern"], value)):
            found.append(f"{name} {value!r} does not match {stated['pattern']}")
        if "enum" in stated and value not in stated["enum"]:
            found.append(f"{name} {value!r} is not one of {stated['enum']}")
    return found


def test_the_envelope_evaluate_records_is_a_schema_2_envelope(tmp_path):
    h = HIITL(environment="dev", agent_id="invoice-agent", org_id=ORG, audit_db_path=str(tmp_path / "audit.db"))
    try:
        d = h.evaluate("send_invoice", parameters={"invoice_id": "inv_2231", "amount": 640})
        [record] = h._audit_logger.get_unsynced(limit=10)
    finally:
        h.close()
    envelope = record["envelope"]
    assert envelope["action_id"] == d.action_id
    assert envelope["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert _departures(envelope) == []
