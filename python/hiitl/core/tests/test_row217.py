"""Row 217 (HTL-24): a result for a held action, written where no review case is held.

Ruled 2026-11-07: "the local store writes the result, naming the review it cannot read … the service, which holds
the case, reads the case at sync ingest and refuses the record when the case did not let the action run; in local
mode the record stands as named … One rule in the store and one read at ingest; no per-mode branching." By the
ontology §4 commitment 3 ("under-attribution the operator sees as requires_information, never a silent 'governed'")
and Principle 4. The one rule takes the review as its writer holds it; a writer holding no case passes the decision's
unread review (event_format.md 1.6, "A result whose writer holds no case"). Design: the HTL-24 test design, row 217,
behavior 1. Mirrors typescript/packages/core/tests/unit/row217.test.ts.
"""

from __future__ import annotations

import pytest

from hiitl.core.lifecycle import decision_refusal, result_refusal, unread_review

RESULT = {"status": "succeeded"}
TOKEN = "rtk_5e0c2a9d41b7"
HELD = {"decision": "REQUIRE_APPROVAL", "allowed": False, "resume_token": TOKEN}
PAUSED = {"decision": "PAUSE", "allowed": False, "resume_token": "rtk_0b9e4c7d2a61"}
BLOCKED = {"decision": "BLOCK", "allowed": False}
ALLOWED = {"decision": "ALLOW", "allowed": True}


def test_the_unread_review_names_a_held_decisions_token():
    assert unread_review(HELD) == {"unread": TOKEN}
    assert unread_review(PAUSED) == {"unread": PAUSED["resume_token"]}
    assert (unread_review(ALLOWED), unread_review(BLOCKED)) == (None, None)
    assert unread_review({**ALLOWED, "resume_token": TOKEN}) is None, "an allowed decision is held for nothing"


def test_a_held_decision_takes_its_result_when_the_review_is_unread():
    assert decision_refusal(HELD, unread_review(HELD)) is None
    assert result_refusal([{"decision": HELD}], RESULT, review=unread_review(HELD)) is None


@pytest.mark.parametrize("review", [
    {"unread": PAUSED["resume_token"]}, {"unread": TOKEN, "case": "rc_1"}, {"unread": None}, {"unread": ""}, {},
    TOKEN, None,
], ids=["another decision's", "a second member", "no token", "an empty token", "empty", "a bare token", "none"])
def test_any_other_review_leaves_a_held_decision_unexecuted(review):
    assert decision_refusal(HELD, review) == "RESULT_ON_UNALLOWED_DECISION"


@pytest.mark.parametrize("review", [None, {"unread": TOKEN}, {"status": "approved", "timeout_action": "fail_closed"}])
def test_a_decision_held_for_no_review_is_refused_whatever_the_review(review):
    """BLOCKED is terminal: a decision carrying no `resume_token` takes no result, read or unread."""
    assert decision_refusal(BLOCKED, review) == "RESULT_ON_UNALLOWED_DECISION"
    assert result_refusal([{"decision": BLOCKED}], RESULT, review=review) == "RESULT_ON_UNALLOWED_DECISION"


def test_an_allowed_decision_needs_no_review():
    assert decision_refusal(ALLOWED, None) is None
    assert decision_refusal(ALLOWED, unread_review(ALLOWED)) is None


def test_the_result_rule_reads_the_decision_rule():
    """`result_refusal` is the action read (ACTION_NOT_FOUND), the decision rule and the one result
    (RESULT_ALREADY_RECORDED), so the store and the ingest hold one rule."""
    review = unread_review(HELD)
    assert result_refusal([], RESULT, review=review) == "ACTION_NOT_FOUND"
    recorded = [{"decision": HELD}, {"decision": HELD, "execution_result": {"status": "failed"}}]
    assert result_refusal(recorded, RESULT, review=review) == "RESULT_ALREADY_RECORDED"
