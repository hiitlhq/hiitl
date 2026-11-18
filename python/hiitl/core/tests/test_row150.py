"""Row 150 (HTL-22): what a record is, and an action's lifecycle up to the result write.

The Stop 1 ruling (HTL-20): "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle fields
(`event_type`; `execution_result` on a result), appended against the decision's `action_id`". Principle 4: BLOCKED is
terminal. Infrastructure spec 2: "idempotent state transitions". The spec is read at its producer: event_format.md's
Event Types table. Design: the HTL-22 test design, row 150, behaviors 1-3. Mirrors
typescript/packages/core/tests/unit/row150.test.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hiitl.core.lifecycle import (MESSAGES, RESULT_STATUSES, event_type, execution_result, recorded_result,
                                  result_refusal)
from hiitl.core.types import DecisionType

SPEC = (Path(__file__).resolve().parents[4] / "docs" / "specs" / "event_format.md").read_text(encoding="utf-8")

ALLOWED = {"decision": {"decision": "ALLOW", "allowed": True}}
BLOCKED = {"decision": {"decision": "BLOCK", "allowed": False}}
DONE = {"status": "succeeded", "duration_ms": 12}


def _table() -> list[tuple[str, str, str, str]]:
    """The Event Types table's rows: (event_type, record, decision, execution_result.status)."""
    section = SPEC.split("## Event Types", 1)[1].split("**Names earlier versions", 1)[0]
    return re.findall(r"^\| `([a-z_.]+)` \| (a [a-z]+ record) \| ([^|]+?) \| ([^|]+?) \|$", section, re.M)


def _result(result: dict) -> dict:
    return {**ALLOWED, "execution_result": result}


def test_event_type_is_the_spec_s_table():
    rows = _table()
    named = {d.strip("`"): e for e, _, d, s in rows if s == "none" and d != "any other"}
    [other] = [e for e, _, d, s in rows if s == "none" and d == "any other"]
    by_status = {s.strip("`"): e for e, _, _, s in rows if s != "none"}
    assert set(by_status) == set(RESULT_STATUSES), "the table's statuses are the result's"
    assert set(named) <= {d.value for d in DecisionType}
    for decision in DecisionType:
        assert event_type(decision.value) == named.get(decision.value, other), decision.value
        for status, event in by_status.items():
            assert event_type(decision.value, {"status": status}) == event, (decision.value, status)


@pytest.mark.parametrize("status, error, duration_ms", [
    ("done", None, None), (None, None, None), ("succeeded", 404, None), ("failed", None, -1),
    ("failed", None, True), ("succeeded", None, float("nan")), ("succeeded", None, "12"),
], ids=["unnamed-status", "no-status", "error-not-a-string", "negative-duration", "bool-duration",
        "duration-not-finite", "duration-a-string"])
def test_a_result_that_is_not_the_spec_s_is_refused(status, error, duration_ms):
    with pytest.raises(ValueError) as refused:
        execution_result(status, error, duration_ms)
    assert str(refused.value) == MESSAGES["RESULT_INVALID"]


def test_an_unnamed_status_is_no_event():
    with pytest.raises(ValueError):
        event_type("ALLOW", {"status": "done"})


def test_a_result_carries_only_what_was_sent():
    assert execution_result("succeeded") == {"status": "succeeded"}
    assert execution_result("failed", "card declined", 12.5) == {
        "status": "failed", "error": "card declined", "duration_ms": 12.5}


def test_the_lifecycle_refuses_as_the_spec_says():
    assert result_refusal([], DONE) == "ACTION_NOT_FOUND"
    assert result_refusal([BLOCKED], DONE) == "RESULT_ON_UNALLOWED_DECISION"
    assert result_refusal([ALLOWED], DONE) is None
    assert result_refusal([ALLOWED, _result(DONE)], DONE) is None, "the same result again is no refusal"
    assert result_refusal([ALLOWED, _result(DONE)], {"status": "failed"}) == "RESULT_ALREADY_RECORDED"
    # The decision a result attaches to is the latest record carrying no result
    assert result_refusal([ALLOWED, BLOCKED], DONE) == "RESULT_ON_UNALLOWED_DECISION"
    assert result_refusal([BLOCKED, ALLOWED], DONE) is None


def test_the_same_result_again_is_the_first_record():
    first, later = _result(DONE), _result(DONE)
    assert recorded_result([ALLOWED, first, later], DONE) is first
    assert recorded_result([ALLOWED], DONE) is None
    assert recorded_result([ALLOWED, first], {"status": "succeeded"}) is None, "a result differing by a member"
