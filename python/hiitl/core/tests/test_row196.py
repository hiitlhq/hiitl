"""Row 196 (HTL-23): the result rule takes the action's review.

Ruled 2026-11-06 as the row reads: "a result attaches to an action whose review case resolved approved, read from the
case's transitions", by Principle 4 (QUEUED → EXECUTING). The review is the case's latest transition and the case's
`timeout_action`; the resolutions under which the action executes are the gateway's (routes.md "A review case"). A
decision is held for review when it carries a `resume_token` (decision_response.md). Design:
the HTL-23 test design, row 196, behavior 4. Mirrors typescript/packages/core/tests/unit/row196.test.ts.
"""

from __future__ import annotations

import pytest

from hiitl.core.lifecycle import result_refusal

RESULT = {"status": "succeeded"}
HELD = [{"decision": {"decision": "REQUIRE_APPROVAL", "allowed": False, "resume_token": "rtk_5e0c2a9d41b7"}}]
BLOCKED = [{"decision": {"decision": "BLOCK", "allowed": False}}]


@pytest.mark.parametrize("status,timeout_action", [
    ("approved", "fail_closed"), ("modified", "fail_closed"), ("timed_out", "fail_open")])
def test_a_resolution_that_executes_lets_the_result_attach(status, timeout_action):
    assert result_refusal(HELD, RESULT, review={"status": status, "timeout_action": timeout_action}) is None


@pytest.mark.parametrize("status,timeout_action", [
    ("pending", "fail_open"), ("rejected", "fail_open"), ("timed_out", "fail_closed"), ("timed_out", "escalate"),
    ("timed_out", "extend")])
def test_any_other_leaves_the_action_unexecuted(status, timeout_action):
    review = {"status": status, "timeout_action": timeout_action}
    assert result_refusal(HELD, RESULT, review=review) == "RESULT_ON_UNALLOWED_DECISION"


def test_with_no_review_read_the_decision_answers_alone():
    assert result_refusal(HELD, RESULT) == "RESULT_ON_UNALLOWED_DECISION"
    assert result_refusal(HELD, RESULT, review=None) == "RESULT_ON_UNALLOWED_DECISION"


def test_a_review_reaches_only_a_decision_held_for_one():
    review = {"status": "approved", "timeout_action": "fail_closed"}
    assert result_refusal(BLOCKED, RESULT, review=review) == "RESULT_ON_UNALLOWED_DECISION"


def test_the_other_refusals_stand_with_a_review():
    review = {"status": "approved", "timeout_action": "fail_closed"}
    assert result_refusal([], RESULT, review=review) == "ACTION_NOT_FOUND"
    recorded = [*HELD, {"decision": HELD[0]["decision"], "execution_result": {"status": "failed"}}]
    assert result_refusal(recorded, RESULT, review=review) == "RESULT_ALREADY_RECORDED"
