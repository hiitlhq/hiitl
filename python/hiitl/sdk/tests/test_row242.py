"""Row 242 (HTL-29 review, condition 5), in the SDK: a date-time written in a policy's or route's YAML is the string
written, read by the core's one reader, and the store's dedup window compares the instants that reader reads.

ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar": a YAML policy or route is "a thin parsing layer that
converts to JSON" (policy_format.md), so YAML's timestamp type is not resolved and an explicit `!!timestamp` is refused;
where two are compared, each is the instant the reader reads, and a recorded `timestamp` the store cannot read leaves
the key not known to be new (row 193). Design: the HTL-29 test design, row 137, behaviors 19 and 20. Mirrors
typescript/packages/sdk/tests/unit/row242.test.ts.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import timedelta, timezone

import pytest

from hiitl import HIITL
from hiitl.core.date_time import FORM, read
from hiitl.core.error_decisions import MESSAGES
from hiitl.sdk.exceptions import PolicyLoadError
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.sdk.route_loader import RouteLoader
from hiitl.synthetic.cli import _load_policy

ORG = "org_test000000000000000"
POLICY = """\
name: refunds
version: v1.0.0
description: The refund agent's refunds
scope:
  org_id: {org}
  environment: dev
rules:
  - name: refunds_in_window
    description: Refunds are allowed in the window
    priority: 100
    conditions: {{field: action, operator: equals, value: refund}}
    decision: ALLOW
    reason_code: REFUND_ALLOWED
    valid_to: {valid_to}
"""
ROUTE = """\
name: finance-review
version: v1.0.0
description: High-value refunds go to the finance team
direction: outbound
timing: async
purpose: [review]
endpoint: https://hooks.example.com/hiitl/finance-review
protocol: webhook
metadata:
  reviewed: {reviewed}
"""


def _rule_valid_to(tmp_path, written: str):
    path = tmp_path / "refunds.yaml"
    path.write_text(POLICY.format(org=ORG, valid_to=written))
    return PolicyLoader(str(path)).load().rules[0].valid_to


# --- Behavior 19: a date-time in a YAML policy or route is the string written ---

@pytest.mark.parametrize("written", ["2026-01-02T03:04:05Z", "2026-01-02t03:04:05z", "2026-01-02T04:04:05.5+01:00"])
def test_an_unquoted_date_time_in_a_yaml_policy_is_read_by_the_core(tmp_path, written):
    valid_to = _rule_valid_to(tmp_path, written)
    assert (valid_to, valid_to.utcoffset()) == (read(written), read(written).utcoffset()), "the instant, its offset kept"


@pytest.mark.parametrize("written", ["2026-01-02 03:04:05Z", "2026-01-02T03:04:05", "2026-01-02"],
                         ids=["a-space", "no-offset", "a-date"])
def test_a_yaml_timestamp_rfc_3339_does_not_read_is_refused_by_its_form(tmp_path, written):
    """Each is a YAML 1.1 timestamp, and none an RFC 3339 date-time: the string written is refused as the JSON's is."""
    with pytest.raises(PolicyLoadError, match=re.escape(f"valid_to {FORM}")):
        _rule_valid_to(tmp_path, written)


def test_an_explicit_yaml_timestamp_is_refused(tmp_path):
    with pytest.raises(PolicyLoadError, match="tag:yaml.org,2002:timestamp"):
        _rule_valid_to(tmp_path, "!!timestamp 2026-01-02T03:04:05Z")


def test_a_date_time_in_a_yaml_routes_metadata_is_the_string_written(tmp_path):
    (tmp_path / "finance-review.yaml").write_text(ROUTE.format(reviewed="2026-01-02T03:04:05Z"))
    assert RouteLoader(str(tmp_path)).get("finance-review").metadata == {"reviewed": "2026-01-02T03:04:05Z"}


def test_the_synthetic_runner_reads_a_yaml_policy_as_the_sdk_does(tmp_path, capsys):
    path = tmp_path / "refunds.yaml"
    path.write_text(POLICY.format(org=ORG, valid_to="2026-01-02t03:04:05z"))
    assert _load_policy(str(path)).rules[0].valid_to == read("2026-01-02T03:04:05Z")
    path.write_text(POLICY.format(org=ORG, valid_to="2026-01-02 03:04:05Z"))
    with pytest.raises(SystemExit):
        _load_policy(str(path))
    assert f"valid_to {FORM}" in capsys.readouterr().err, "refused by its form, as the SDK refuses it"


# --- Behavior 20: the store's dedup window reads each recorded timestamp as the core does ---

SET = {"version": "v1.0.0", "name": "refunds", "description": "The refund agent's refunds",
       "scope": {"org_id": ORG, "environment": "dev"},
       "rules": [{"name": "allow_refunds", "priority": 100, "description": "Refunds are allowed",
                  "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                  "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}]}


def _client(tmp_path) -> HIITL:
    policy = tmp_path / "refunds.json"
    policy.write_text(json.dumps(SET))
    return HIITL(environment="dev", agent_id="refund-agent", org_id=ORG, policy_path=str(policy),
                 audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")


def _recorded_as(tmp_path, action_id: str, timestamp: str) -> None:
    """The recorded envelope's `timestamp`, as another writer of this store wrote it."""
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    conn.execute("UPDATE audit_log SET envelope = json_set(envelope, '$.timestamp', ?) "
                 "WHERE json_extract(envelope, '$.action_id') = ?", (timestamp, action_id))
    conn.commit()
    conn.close()


def _in_offset(written: str, hours: int, *, lower: bool = False) -> str:
    """The instant written, in another offset; in RFC 3339's lower case `t` when `lower`."""
    text = read(written).astimezone(timezone(timedelta(hours=hours))).isoformat()
    return text.replace("T", "t") if lower else text


@pytest.mark.parametrize("hours, lower", [(0, True), (1, False), (-5, True)], ids=["utc-lower", "plus-1", "minus-5"])
def test_a_retry_is_read_against_a_timestamp_recorded_in_any_form_rfc_3339_reads(tmp_path, hours, lower):
    h = _client(tmp_path)
    first = h.evaluate("refund", idempotency_key="idem_r242_form")
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    written, = conn.execute("SELECT json_extract(envelope, '$.timestamp') FROM audit_log").fetchone()
    conn.close()
    _recorded_as(tmp_path, first.action_id, _in_offset(written, hours, lower=lower))

    again = h.evaluate("refund", idempotency_key="idem_r242_form")
    assert again.action_id == first.action_id, "the first decision under its key, its instant read as written"
    h.close()


def test_a_recorded_timestamp_the_store_cannot_read_leaves_the_key_not_known_to_be_new(tmp_path):
    h = _client(tmp_path)
    first = h.evaluate("refund", idempotency_key="idem_r242_unread")
    _recorded_as(tmp_path, first.action_id, "2026-11-10T13:04:05.678+01:60")

    d = h.evaluate("refund", idempotency_key="idem_r242_unread")
    assert (d.decision, d.reason_codes) == ("BLOCK", ["AUDIT_READ_FAILED"]), "not the first decision: unread"
    assert (d.error.code, d.error.message) == ("AUDIT_READ_FAILED", MESSAGES["AUDIT_READ_FAILED"])
    h.close()
