"""Row 211 (HTL-23): the window before the first pull.

Ruled 2026-11-06 as the row reads: "the cold-start sentence governs, by that sentence". sync_engine.md §5:
"`warn-and-observe` (default) logs a warning and evaluates against an empty policy set, in the client's own mode, with
`cache_status: "empty"` until a sync succeeds". So a record written in the window is written, never held, under the
SDK's own declaration; the first pull that lands carries the org's, and the next write takes both (event_format.md
§Redaction, Open). Design: the HTL-23 test design, row 211. Mirrors
typescript/packages/sdk/tests/unit/row211.test.ts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from unittest.mock import MagicMock, patch

from hiitl import HIITL
from hiitl.core.redaction import MARKER

ORG = "org_r211window0000000"
OWN = ["parameters.account_number"]
ORGS = ["target.email"]
PARAMETERS = {"account_number": "GB29NWBK60161331926819", "amount": 1250}
TARGET = {"email": "dana@example.com", "vendor_id": "vnd_42"}


def _stored(db) -> list[dict]:
    with sqlite3.connect(db) as c:
        return [json.loads(e) for (e,) in c.execute("SELECT envelope FROM audit_log ORDER BY rowid")]


def test_the_window_takes_the_sdks_declaration_and_the_pull_brings_the_orgs(tmp_path, caplog):
    """Behaviors 1 and 2: a write before the first pull lands is redacted under the SDK's own `redact_fields`, with the
    cold-start warning logged; once the pull lands, the next write takes the union."""
    engine = MagicMock()
    engine.initial_sync.return_value = False                  # the first pull has not landed
    db = tmp_path / "audit.db"
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine), \
            caplog.at_level(logging.WARNING, logger="hiitl"):
        h = HIITL(api_key="sk_test_row211", org_id=ORG, environment="dev", agent_id="payout-agent",
                  audit_db_path=str(db), cache_dir=str(tmp_path / "cache"), redact_fields=OWN)
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "cache_status='empty'" in r.getMessage()]

    before = h.evaluate("pay", parameters=PARAMETERS, target=TARGET)
    assert before.cache_status == "empty"
    h._sync_cache.update_policies({"policies": [], "version": "v1", "redaction_policy": {
        "manual_redact_fields": ORGS}}, etag="e1")            # the first pull lands, as the engine writes it
    after = h.evaluate("pay", parameters=PARAMETERS, target=TARGET)
    h.close()

    first, second = _stored(db)
    assert (first["parameters"]["account_number"], first["target"]["email"]) == (MARKER, TARGET["email"]), \
        "in the window: the SDK's declaration only, and the record is written, never held"
    assert (second["parameters"]["account_number"], second["target"]["email"]) == (MARKER, MARKER), \
        "after the pull: the union"
    assert after.cache_status == "synced"
