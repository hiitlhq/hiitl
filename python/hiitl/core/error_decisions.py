"""An error is a decision (decision_response.md "Error Handling": "All errors produce structured decision responses";
the Stop 2 ruling, HTL-20: "An error is a decision carrying `error.code` and `error.message`, `allowed` false, with a
record written"). One definition, read by both SDKs' local path and the hosted service. Mirrored by @hiitl/core
error-decisions.ts.

`error.code` is the decision (Examples 8 and 9) and the cause is the reason code. A message says what happened and
what to do; it never carries a caught exception's text, which the caller logs instead (Principle 11; the text of a
store or a parser can hold a secret or a path)."""

from __future__ import annotations

from typing import Optional

from hiitl.core.types import Decision, DecisionMetadata, ErrorDetail, Timing

# The error decisions, as Error Handling lists them: what the control point answers when it could not evaluate an
# envelope. A rule never writes one (PRODUCED_DECISIONS). No decision carrying `error` is the first decision under a
# key, these and the BLOCKs below alike: the envelope was never evaluated, so its retry is (Error Handling, "Audit
# requirement"; §1.3 "A replayed envelope produces a dedup hit, not a re-evaluation"; row 193).
ERROR_DECISIONS = frozenset({"SIGNATURE_INVALID", "CONTROL_PLANE_UNAVAILABLE", "VALIDATION_ERROR", "POLICY_ERROR"})

# What each caught failure is said as, by its reason code. The cause itself is logged where it was caught.
MESSAGES = {
    "ENVELOPE_SIGNATURE_VERIFICATION_FAILED": (
        "The envelope's signature does not verify over the envelope as built. It is HMAC-SHA256 under the signing key "
        "over the RFC 8785 form of the envelope without its signature. Check that signature_key is the API key's "
        "signing secret and that nothing changed the envelope after it was signed; do not retry the same envelope."),
    "POLICY_NOT_FOUND": (
        "No policy file is at the configured policy_path, so the action was not evaluated (fail-closed). Check the "
        "path; the log names it."),
    "POLICY_LOAD_FAILED": (
        "The policy file could not be read, so the action was not evaluated (fail-closed). Check that the file at "
        "policy_path is readable; the cause is in the log."),
    "POLICY_VALIDATION_ERROR": (
        "The policy file is not a policy set the format admits (policy_format.md), so the action was not evaluated "
        "(fail-closed). Correct the file; each problem is in the log."),
    "POLICY_EVALUATION_FAILED": (
        "The policy could not be evaluated against this envelope, so the action was not allowed (fail-closed). Check "
        "the policy's conditions against the envelope's fields; the cause is in the log."),
    "AUDIT_WRITE_FAILED": (
        "The audit record could not be written, so the action is blocked (fail-closed: an action with no record never "
        "runs). Check the audit store; the cause is in the log."),
    "RATE_LIMIT_SERVICE_ERROR": (
        "The rate limiter could not be read, so the action is blocked (fail-closed). Check the rate-limit store; the "
        "cause is in the log."),
    # The BLOCKs the control point answers once an envelope exists (Error Handling, row 193)
    "EVALUATION_FAILED": (
        "The control point failed unexpectedly while deciding this action, so it was not evaluated and is blocked "
        "(fail-closed). Do not execute it; send it again, and if the failure repeats, the cause is in the log."),
    "AUDIT_READ_FAILED": (
        "The audit store could not be read for the first decision under this envelope's idempotency_key, so the "
        "action was not evaluated and is blocked (fail-closed). Check the audit store; the cause is in the log."),
    # CONTROL_PLANE_UNAVAILABLE's causes (Error Handling: "ECP is unreachable (circuit breaker, timeout)"), answered
    # by the hosted client
    "CONTROL_PLANE_TIMEOUT": (
        "The hosted service did not answer within the timeout on any attempt, so the action was not evaluated and is "
        "not allowed (fail-closed). Do not execute it; check the service's status and the client's timeout and "
        "max_retries; the cause is in the log."),
    "CONTROL_PLANE_UNREACHABLE": (
        "The hosted service could not be reached for a decision (no connection, or a transient failure on every "
        "attempt), so the action was not evaluated and is not allowed (fail-closed). Do not execute it; check "
        "server_url, the network and the service's status; the cause is in the log."),
    "CIRCUIT_BREAKER_OPEN": (
        "The hosted service failed on the client's last consecutive calls, so its circuit breaker is open and this "
        "call was not sent (fail-closed). Do not execute the action; the client sends again after the breaker's reset "
        "interval."),
}


# The outage's warning under FAIL_OPEN, by its cause (Error Handling, "The fail mode", Stop B (ii), ruled 2026-11-06):
# the action was allowed without being evaluated, because the client is configured to fail open.
FAIL_OPEN_MESSAGES = {
    "CONTROL_PLANE_TIMEOUT": (
        "The hosted service did not answer within the timeout on any attempt. The action is allowed without being "
        "evaluated, because this client's fail_mode is FAIL_OPEN: no policy decided it. Check the service's status and "
        "the client's timeout and max_retries; the cause is in the log."),
    "CONTROL_PLANE_UNREACHABLE": (
        "The hosted service could not be reached for a decision. The action is allowed without being evaluated, "
        "because this client's fail_mode is FAIL_OPEN: no policy decided it. Check server_url, the network and the "
        "service's status; the cause is in the log."),
    "CIRCUIT_BREAKER_OPEN": (
        "The hosted service's circuit breaker is open, so this call was not sent. The action is allowed without being "
        "evaluated, because this client's fail_mode is FAIL_OPEN: no policy decided it. The client sends again after "
        "the breaker's reset interval."),
}

# The hosted client's fail modes (decision_response.md, the hosted settings table), FAIL_CLOSED the default.
FAIL_MODES = ("FAIL_CLOSED", "FAIL_OPEN")


def error_decision(action_id: str, decision: str, reason_code: str, message: str, *, policy_version: str = "",
                   envelope_hash: Optional[str] = None, total_ms: float = 0.0,
                   metadata: Optional[DecisionMetadata] = None) -> Decision:
    """The decision an envelope that could not be evaluated answers: `decision` one of ERROR_DECISIONS, `allowed`
    false, its cause the one reason code, and `error` carrying the decision as its code (Example 8). An outage
    carries its fail mode and circuit state as `metadata` (Example 9)."""
    if decision not in ERROR_DECISIONS:
        raise ValueError(f"{decision} is not an error decision; Error Handling lists {sorted(ERROR_DECISIONS)}")
    return Decision(
        action_id=action_id, decision=decision, allowed=False, reason_codes=[reason_code],
        policy_version=policy_version, timing=Timing(ingest_ms=0.0, evaluation_ms=0.0, total_ms=total_ms),
        envelope_hash=envelope_hash, error=ErrorDetail(code=decision, message=message), metadata=metadata,
    )


def audit_write_failed(decision: Decision) -> Decision:
    """An evaluation whose record could not be written is BLOCK / AUDIT_WRITE_FAILED in every mode, never observed
    ("Audit write failures in fail-closed mode must block the action", Infrastructure spec 3; R-1164's form). A copy,
    as a refusal is: no rule decided it. It is the one error decision with no record, because the record is what
    failed."""
    return decision.model_copy(update={
        "decision": "BLOCK", "allowed": False, "reason_codes": ["AUDIT_WRITE_FAILED"],
        "matched_rules": None, "rate_limit": None, "remediation": None,
        "would_be": None, "would_be_reason_codes": None,
        "error": ErrorDetail(code="AUDIT_WRITE_FAILED", message=MESSAGES["AUDIT_WRITE_FAILED"]),
    })


def outage(action_id: str, reason_code: str, fail_mode: str, circuit_breaker_state: str, *,
           envelope_hash: Optional[str] = None, total_ms: float = 0.0) -> Decision:
    """The hosted client's outage decision: CONTROL_PLANE_UNAVAILABLE, its cause the one reason code, with the fail
    mode and circuit state as `metadata` (Example 9). Under FAIL_OPEN, opt-in, it is the one error decision `allowed`
    true, its message the warning (Stop B (ii))."""
    opened = fail_mode == "FAIL_OPEN"
    decision = error_decision(
        action_id, "CONTROL_PLANE_UNAVAILABLE", reason_code, (FAIL_OPEN_MESSAGES if opened else MESSAGES)[reason_code],
        envelope_hash=envelope_hash, total_ms=total_ms,
        metadata=DecisionMetadata(fail_mode=fail_mode, circuit_breaker_state=circuit_breaker_state))
    return decision.model_copy(update={"allowed": True}) if opened else decision


def error_block(action_id: str, reason_code: str, *, policy_version: str = "", envelope_hash: Optional[str] = None,
                total_ms: float = 0.0) -> Decision:
    """A failure once the envelope exists that no error decision names is BLOCK, fail-closed, with `error.code` its
    cause and the authored message (Error Handling; row 193: EVALUATION_FAILED, AUDIT_READ_FAILED)."""
    return Decision(
        action_id=action_id, decision="BLOCK", allowed=False, reason_codes=[reason_code],
        policy_version=policy_version, timing=Timing(ingest_ms=0.0, evaluation_ms=0.0, total_ms=total_ms),
        envelope_hash=envelope_hash, error=ErrorDetail(code=reason_code, message=MESSAGES[reason_code]),
    )
