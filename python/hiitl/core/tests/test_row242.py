"""Row 242 (HTL-29 review, condition 5), in core: a date-time is read by RFC 3339's grammar, by one reader, in every
field the core's models type `date-time`.

ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar": §5.6's form and its note's lower case `t` and `z`,
§5.6 and §5.7's ranges, a refusal naming the element and its range, the instant held with its offset as written.
Design: the HTL-29 test design, row 137, behaviors 12-14. Mirrors typescript/packages/core/tests/unit/row242.test.ts:
both read the table in tests/conformance/date_time/.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError, TypeAdapter

from hiitl.core import Envelope, PolicyEvaluator
from hiitl.core.date_time import NO_OFFSET, YEAR, read, refusal
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, PolicySet, RateLimit

ROOT = Path(__file__).resolve().parents[4]
TABLE = ROOT / "tests" / "conformance" / "date_time" / "case_001_written_date_times.json"
ROWS = json.loads(TABLE.read_text(encoding="utf-8"))["date_times"]
ORG = "org_test123456789012"
NOW = datetime.now(timezone.utc)


def _utc(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


@pytest.mark.parametrize("row", ROWS, ids=[repr(r[0])[:40] for r in ROWS])
def test_one_reader_reads_each_written_value_as_the_table_does(row):
    if row[1] is None:
        with pytest.raises(ValueError, match=re.escape(row[2])):
            read(row[0])
        assert refusal(row[0]) == row[2]
    else:
        assert refusal(row[0]) is None
        assert _utc(read(row[0])) == row[1]


def test_the_instant_is_held_with_its_offset_as_written():
    assert read("2026-01-02T03:04:05+01:00").utcoffset() == timedelta(hours=1)
    assert read("2026-01-02T03:04:05-05:30").utcoffset() == -timedelta(hours=5, minutes=30)
    assert read("2026-01-02t03:04:05z").utcoffset() == timedelta(0)


# Every field the core's models carry that the specs type `date-time`, read from the specs: the envelope's schema, the
# decision's JSON, and the rule table's `string (date-time)` rows
def _schema_fields(node, path=()):
    if isinstance(node, dict):
        if node.get("format") == "date-time":
            yield ".".join(p for p in path if p not in ("properties", "items"))
        for key, value in node.items():
            yield from _schema_fields(value, (*path, key))
    elif isinstance(node, list):
        for value in node:
            yield from _schema_fields(value, path)


def _json_blocks(name):
    for block in re.findall(r"```json\n(.*?)```", (ROOT / "docs" / "specs" / name).read_text(encoding="utf-8"), re.S):
        try:
            yield json.loads(block)
        except json.JSONDecodeError:
            continue


def _spec_fields() -> set:
    envelope = {f"envelope.{f}" for f in _schema_fields(json.loads((ROOT / "docs/specs/envelope_schema.json").read_text()))}
    decision = {f"decision.{f}" for block in _json_blocks("decision_response.md") for f in _schema_fields(block)}
    rule = {f"rule.{f}" for f in re.findall(r"^\| `([a-z_]+)` \| string \(date-time\) \|",
                                            (ROOT / "docs/specs/policy_format.md").read_text(encoding="utf-8"), re.M)}
    return envelope | decision | rule


def _envelope(**fields):
    return Envelope(**{"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": ORG, "environment": "dev",
                       "agent_id": "refund-agent", "action_id": "act_01234567890123456789", "idempotency_key": "idem_242",
                       "action": "refund", "timestamp": NOW, "signature": "a" * 64, **fields})


def _principal(verified_at):
    return _envelope(principal={"sub": "user-7", "verified_by": "hosted", "verified_at": verified_at}).principal


def _rule(**window):
    return {"name": "refunds_in_window", "description": "Refunds are allowed in the window", "priority": 100,
            "conditions": {"field": "action", "operator": "equals", "value": "refund"},
            "decision": "ALLOW", "reason_code": "REFUND_ALLOWED", **window}


def _policy(*rules):
    return PolicySet(name="refunds", version="v1.0.0", description="The refund agent's refunds",
                     scope={"org_id": ORG, "environment": "dev"}, rules=list(rules))


CARRIERS = {
    "envelope.timestamp": lambda v: _envelope(timestamp=v).timestamp,
    "envelope.principal.verified_at": lambda v: _principal(v).verified_at,
    "rule.valid_from": lambda v: _policy(_rule(valid_from=v)).rules[0].valid_from,
    "rule.valid_to": lambda v: _policy(_rule(valid_to=v)).rules[0].valid_to,
    "decision.rate_limit.reset_at": lambda v: RateLimit(scope="agent", window="60s", limit=2, current=2,
                                                        reset_at=v).reset_at,
}


def test_every_date_time_field_the_specs_type_has_its_cell():
    assert set(CARRIERS) == _spec_fields()


@pytest.mark.parametrize("field", sorted(CARRIERS))
def test_every_date_time_field_is_read_by_the_one_reader(field):
    carry, name = CARRIERS[field], field.rsplit(".", 1)[1]
    with pytest.raises(ValidationError, match=re.escape(f"{name} has offset minute 60; an offset's minute is 00 to 59")):
        carry("2026-01-02T03:04:05+01:60")
    with pytest.raises(ValidationError, match=re.escape(f"{name} is not in RFC 3339's date-time form")):
        carry("2026-01-02 03:04:05Z")
    # Written in the year 0000, an instant inside the years held in UTC: refused in both cores, so a rule's window
    # loads in neither (HTL-29 second review, condition 5)
    with pytest.raises(ValidationError, match=re.escape(f"{name} {YEAR}")):
        carry("0000-12-31T23:59:59-00:01")
    value = carry("2026-01-02t03:04:05z")
    offset = carry("2026-01-02T03:04:05+01:00")
    if field.startswith("envelope."):
        assert value == "2026-01-02t03:04:05z"
        assert offset == "2026-01-02T03:04:05+01:00"
        value, offset = read(value), read(offset)
    assert _utc(value) == "2026-01-02T03:04:05.000000Z"
    assert offset.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize("field", sorted(CARRIERS))
def test_in_python_a_field_takes_a_datetime_that_carries_its_offset(field):
    carry, name = CARRIERS[field], field.rsplit(".", 1)[1]
    written = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=1)))
    value = carry(written)
    if field.startswith("envelope."):
        assert value == TypeAdapter(datetime).dump_python(written, mode="json")
        value = read(value)
    assert value == written and value.utcoffset() == timedelta(hours=1)
    with pytest.raises(ValidationError, match=re.escape(f"{name} {NO_OFFSET}")):
        carry(datetime(2026, 1, 2, 3, 4, 5))


def _offset(instant: datetime, hours: int) -> str:
    """The instant, written in another offset."""
    return instant.astimezone(timezone(timedelta(hours=hours))).isoformat()


def _reasons(*window) -> list:
    return PolicyEvaluator().evaluate(_envelope(), _policy(_rule(**dict(window)))).reason_codes


def test_a_rules_window_is_the_instant_it_writes():
    """A window written in another offset is compared as the instant it writes: a valid_to half an hour past, written
    an hour ahead, reads as a wall clock half an hour to come, and has ended."""
    past, to_come = NOW - timedelta(minutes=30), NOW + timedelta(minutes=30)
    assert _reasons(("valid_to", _offset(past, 1))) == ["NO_MATCHING_RULE"]
    assert _reasons(("valid_from", _offset(to_come, -1))) == ["NO_MATCHING_RULE"]
    assert _reasons(("valid_from", _offset(past, 1)), ("valid_to", _offset(to_come, -1))) == ["REFUND_ALLOWED"]
    assert _reasons(("valid_to", _utc(to_come).replace("T", "t").replace("Z", "z"))) == ["REFUND_ALLOWED"]


def test_temporal_current_time_is_the_calls_instant_in_utc():
    rule = {**_rule(), "decision": "BLOCK", "reason_code": "OUTSIDE_HOURS",
            "remediation": {"type": "temporal", "message": "Refunds run in business hours",
                            "suggestion": "Retry at 09:00", "details": {}}}
    for written, current in (("2026-02-14t16:30:00.250+01:00", "2026-02-14T15:30:00.250Z"),
                             ("0050-06-15T12:00:00.9999Z", "0050-06-15T12:00:00.999Z")):
        details = PolicyEvaluator().evaluate(_envelope(timestamp=written), _policy(rule)).remediation.details
        assert details == {"current_time": current}
