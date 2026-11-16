"""Row 139 (HTL-20): the SDK's local audit store applies the SDK's declared redaction list before every write.

Ruled 2026-11-04: "a declared redaction list applies before every write in both stores". The contract is
event_format.md §Redaction; these are the row's test design cells 7-8. A hosted SDK's refusal of a declaration turned
with Stop B (i) (HTL-23 row 192): the hosted client now writes its outage records, under the declaration
(test_row192.py::test_the_hosted_record_takes_the_sdks_declaration).
"""

import json
import sqlite3

import pytest

from hiitl.core.canonical import AUDIT_FURTHER, audit_content_hash
from hiitl.core.redaction import MARKER
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL
from hiitl.sdk.exceptions import ConfigurationError

POLICY = """
version: "v1.0.0"
description: "A frozen account is never paid"
scope:
  org_id: org_test000000000000000
  environment: dev
name: payouts
rules:
  - name: no-payouts-to-frozen-accounts
    priority: 900
    conditions:
      all_of:
        - {field: action, operator: equals, value: pay}
        - {field: parameters.account_number, operator: in, value: ["GB82WEST12345698765432"]}
    decision: BLOCK
    reason_code: FROZEN_ACCOUNT
    description: A frozen account is never paid
  - name: allow-otherwise
    priority: 1
    conditions: {field: action, operator: exists, value: true}
    decision: ALLOW
    reason_code: ALLOWED
    description: Everything else
"""


@pytest.fixture
def client(tmp_path):
    (tmp_path / "policy.yaml").write_text(POLICY)
    c = HIITL(environment="dev", agent_id="payout-agent", org_id="org_test000000000000000",
              policy_path=str(tmp_path / "policy.yaml"), audit_db_path=str(tmp_path / "audit.db"),
              mode="RESPECT_POLICY", redact_fields=["parameters.account_number", "target.email"])
    yield c
    c.close()


def _rows(db):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY rowid")]


def test_the_local_store_holds_the_declared_field_redacted(client, tmp_path):
    frozen = client.evaluate("pay", parameters={"account_number": "GB82WEST12345698765432", "amount": 1250},
                             target={"email": "dana@example.com", "vendor_id": "vnd_42"})
    paid = client.evaluate("pay", parameters={"account_number": "GB29NWBK60161331926819", "amount": 80})
    assert frozen.decision == "BLOCK" and frozen.reason_codes == ["FROZEN_ACCOUNT"], \
        "evaluation saw the declared field whole"
    assert paid.decision == "ALLOW"

    db = tmp_path / "audit.db"
    rows = _rows(db)
    assert len(rows) == 2
    for row, amount in zip(rows, (1250, 80)):
        envelope = json.loads(row["envelope"])
        assert envelope["parameters"] == {"account_number": MARKER, "amount": amount}
        assert "GB82WEST" not in row["envelope"] + row["decision"] and "GB29NWBK" not in row["envelope"]
        # Each content member the record carries joins the hash as a further term (row 191, ruled 2026-11-06): the
        # second call holds no target.email, so its record carries `redaction.absent`
        further = {m: json.loads(row[m]) for m in AUDIT_FURTHER if row[m] is not None}
        assert row["content_hash"] == audit_content_hash(row["event_id"], envelope, json.loads(row["decision"]),
                                                         **further), "content_hash is over the record as stored"
    assert [json.loads(r["redaction"]) if r["redaction"] else None for r in rows] == [None, {"absent": ["target.email"]}]
    assert json.loads(rows[0]["envelope"])["target"] == {"email": MARKER, "vendor_id": "vnd_42"}
    assert "dana@example.com" not in rows[0]["envelope"]

    logger = AuditLogger(str(db))
    assert all(logger.verify_integrity(r["event_id"]) for r in rows)
    uploaded = logger.get_unsynced()
    assert [u["envelope"]["parameters"]["account_number"] for u in uploaded] == [MARKER, MARKER], \
        "a record leaves for sync already redacted"
    assert [u["content_hash"] for u in uploaded] == [r["content_hash"] for r in rows]


def test_a_declaration_that_is_not_a_field_is_refused(tmp_path):
    with pytest.raises(ConfigurationError, match="event_format.md §Redaction"):
        HIITL(audit_db_path=str(tmp_path / "audit.db"), redact_fields=["org_id"])
    with pytest.raises(ConfigurationError, match="list of field paths"):
        HIITL(audit_db_path=str(tmp_path / "audit.db"), redact_fields="parameters.account_number")
