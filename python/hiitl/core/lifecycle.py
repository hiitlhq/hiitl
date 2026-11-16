"""An action's lifecycle, read from its records (Principle 4: "Every action is modeled as a lifecycle"; the Stop 1
ruling, HTL-20: "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle fields
(`event_type`; `execution_result` on a result), appended against the decision's `action_id`"). One definition, read by
both SDKs' stores and the hosted service. Mirrored by @hiitl/core lifecycle.ts.

A record's `event_type` is derived from what the record carries, its decision and its `execution_result`, so it is
computed wherever a record is read and stored in no column (derived state is computed, never stored).
event_format.md, "Event types", is its table.

A result is recorded once, on an action its decision allowed or its review let run. An action that was not allowed
never executed, so it has no result (Principle 4: BLOCKED is terminal), and a second, different result for one action
is refused (Infrastructure spec 2: "idempotent state transitions"). The same result again is the record already
carrying it. A writer that holds no review case names the review it could not read, and the reader that holds the case
reads it (row 217, event_format.md "A result whose writer holds no case").
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

# event_format.md's `execution_result.status`
RESULT_STATUSES = ("succeeded", "failed", "canceled")
# event_format.md's `execution_result` members, in its order (row 197): the one copy, which the hosted result API reads
RESULT_MEMBERS = ("status", "error", "duration_ms")
# Numeric declaration of the result body, shared by admission and diagnostics.
RESULT_NUMBER_SHAPE = {'type': 'object', 'additionalProperties': False, 'properties': {
    'status': {'type': 'string', 'enum': list(RESULT_STATUSES)},
    'error': {'type': 'string'}, 'duration_ms': {'type': 'number', 'minimum': 0}}}

# The event a result is, by its status (event_format.md "Event types")
_RESULT_EVENTS = {"succeeded": "action.executed", "failed": "action.failed", "canceled": "action.canceled"}
# The error decisions that are their own event; every other decision is the action evaluated
_DECISION_EVENTS = {"SIGNATURE_INVALID": "signature.invalid", "CONTROL_PLANE_UNAVAILABLE": "control_plane.unavailable"}
EVALUATED = "action.evaluated"

# Why a result is not recorded, by its reason code. The hosted service answers the same codes.
MESSAGES = {
    "RESULT_INVALID": (
        "The result is not one hiitl records: `status` is one of succeeded, failed or canceled; "
        "`error`, when sent, is a string; `duration_ms`, when sent, is a non-negative number."),
    "ACTION_NOT_FOUND": (
        "No decision is recorded for this action_id in this org and environment, so a result has nothing to attach "
        "to. Send the action_id of the decision evaluate() returned."),
    "RESULT_ON_UNALLOWED_DECISION": (
        "The action's decision did not allow it, and no review let it execute, so it never executed and has no result. "
        "Record a result only for a decision whose `allowed` is true, or one held for review whose review let it "
        "execute."),
    "RESULT_ALREADY_RECORDED": (
        "A different result is already recorded for this action, and an action's result is recorded once. Sending "
        "the same result again returns the record that holds it."),
}

# The codes under which the hosted service refuses a record for its own content (sync_engine.md §2.1; row 224, ruled
# 2026-11-08). Its answer is final, so a store keeps the record as written, marks it refused with the code and never
# sends it again. Every other code is retried, one a store does not know among them (a false final is the dangerous
# direction). The service refuses a record's content under no other code.
RECORD_REFUSALS = ("MISSING_EVENT_ID", "CONTENT_HASH_MISMATCH", "TIMESTAMP_INVALID", "RESULT_INVALID",
                   "REDACTION_INVALID", "REVIEW_INVALID", "RESULT_ON_UNALLOWED_DECISION", "EVENT_TYPE_MISMATCH",
                   "RESULT_ALREADY_RECORDED")


def event_type(decision: str, execution_result: Optional[Mapping[str, Any]] = None) -> str:
    """The record's event, from its decision and its `execution_result` (event_format.md "Event types").

    Raises:
        ValueError: `execution_result` has a status event_format.md does not name
    """
    if execution_result:
        status = execution_result.get("status")
        if status not in _RESULT_EVENTS:
            raise ValueError(f"execution_result.status {status!r} is not one of {', '.join(RESULT_STATUSES)}")
        return _RESULT_EVENTS[status]
    return _DECISION_EVENTS.get(decision, EVALUATED)


def execution_result(status: Any, error: Any = None, duration_ms: Any = None) -> dict:
    """The result as event_format.md's `execution_result` carries it: `status`, and `error` and `duration_ms` when
    given.

    Raises:
        ValueError: a member is not what event_format.md says it is (MESSAGES["RESULT_INVALID"])
    """
    number = isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool)
    if (status not in RESULT_STATUSES or (error is not None and not isinstance(error, str))
            or (duration_ms is not None and not (number and math.isfinite(duration_ms) and duration_ms >= RESULT_NUMBER_SHAPE['properties']['duration_ms']['minimum']))):
        raise ValueError(MESSAGES["RESULT_INVALID"])
    result: dict = {"status": status}
    if error is not None:
        result["error"] = error
    if duration_ms is not None:
        result["duration_ms"] = duration_ms
    return result


def _review_executes(review: Any) -> bool:
    """Whether a review let its held action execute, as the gateway reads the case (routes.md "A review case"):
    `approved`; `modified`; or a recorded `timed_out` under `timeout_action` `fail_open`. Any other, or none, did not."""
    if not isinstance(review, Mapping):
        return False
    status = review.get("status")
    return status in ("approved", "modified") or (status == "timed_out" and review.get("timeout_action") == "fail_open")


def unread_review(decision: Mapping[str, Any]) -> Optional[dict]:
    """The review a writer holding no case names for `decision` (event_format.md `review`; row 217): on a held decision,
    one not allowed that carries a `resume_token` (decision_response.md, the handle "to resume or cancel the action
    after review"), `{"unread": <its resume_token>}`; on any other, None: an allowed decision is held for nothing, and a
    decision with no token is held for no review."""
    token = decision.get("resume_token")
    return {"unread": token} if isinstance(token, str) and token and decision.get("allowed") is not True else None


def decision_refusal(decision: Mapping[str, Any], review: Any = None) -> Optional[str]:
    """Why a result does not attach to `decision`, or None.

    An allowed decision takes it. A held decision takes it when its `review` let it execute (the latest transition
    across the action's review cases, with that case's `timeout_action`; row 196, ruled 2026-11-06), or when `review`
    is the decision's unread review: its writer holds no case and names the review it could not read, which the reader
    holding the case reads (row 217). Any other decision, or a held one under any other review, never executed.
    """
    if decision.get("allowed") is True:
        return None
    held = unread_review(decision)
    if held and (review == held or _review_executes(review)):
        return None
    return "RESULT_ON_UNALLOWED_DECISION"


def result_refusal(lifecycle: Sequence[Mapping[str, Any]], result: Mapping[str, Any],
                   review: Any = None) -> Optional[str]:
    """Why `result` is not recorded on the action whose records are `lifecycle` (oldest first), or None.

    The action's decision is its latest record that carries no result: the answer the caller acted on, read by
    `decision_refusal` under `review`, the review as the writer holds it (a case's, or the decision's unread review).
    """
    decisions = [r for r in lifecycle if not r.get("execution_result")]
    if not decisions:
        return "ACTION_NOT_FOUND"
    return decision_refusal(decisions[-1]["decision"], review) or result_conflict(lifecycle, result)


def result_conflict(lifecycle: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> Optional[str]:
    """Whether the action whose records are `lifecycle` holds a result other than `result`: an action's result is
    recorded once, by every writer of it, the sync ingest included (gap row 265, ruled 2026-11-11)."""
    if any(r["execution_result"] != result for r in lifecycle if r.get("execution_result")):
        return "RESULT_ALREADY_RECORDED"
    return None


def recorded_result(lifecycle: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """The first record of `lifecycle` carrying `result`, or None: the same result again returns it."""
    return next((r for r in lifecycle if r.get("execution_result") == result), None)
