"""Policy evaluator - deterministic rule evaluation engine.

This is the core runtime enforcement engine. It evaluates policies (JSON objects)
against execution envelopes and returns decisions.

Source of truth:
- docs/specs/envelope_schema.json
- docs/specs/policy_format.md
- docs/specs/decision_response.md

Design principles:
- Deterministic: same (envelope, policy) always produces same decision
- Side-effect free: evaluation does not modify state
- Fast: sub-millisecond evaluation for typical policies
- Language-neutral: behavior validated by conformance test suite
"""

import hashlib
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from hiitl.core import date_time
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

from .precedence import as_block, keyed
from .numeric_domain import validate_numeric_domain, admitted_numbers
from .json_values import json_equal
from .operator_kinds import OperatorKindError, require_operand_kinds
from .input_types import supplied, model_shape
from .input_declarations import policy_shape

# The evaluation's enrichment context (policy_format.md 2.7; TICKET-046): {source: {field: value}}, beside the envelope —
# never inside it. Per call, so a shared evaluator stays safe across threads and tasks.
_ENRICHMENT: ContextVar[Dict[str, Dict[str, Any]]] = ContextVar("hiitl_enrichment", default={})
# Where the SDK's evaluate() started, when the SDK is the caller: its clock covers the call's admission, envelope build and
# signature check, and the evaluation's timing counts from there (decision_response.md Timing Metadata; HTL-43 gap 303).
_STARTED: ContextVar[Optional[float]] = ContextVar("hiitl_started", default=None)
ENRICHMENT_ROOT = "external"
from pydantic import BaseModel

from .types import (
    Condition,
    ConditionOperator,
    Decision,
    DecisionType,
    Envelope,
    LogicalCondition,
    MatchedRule,
    MissingField,
    PolicySet,
    RateLimitRule,
    Remediation,
    Rule,
    RuleScope,
    StagedObservation,
    Timing,
    conforms,
    field_ref,
    schema_error,
)


def _in_envelope(path: str) -> bool:
    """A path the envelope carries or lacks, not the enrichment context beside it (policy_format.md 2.7)."""
    return path.split(".", 1)[0] != ENRICHMENT_ROOT


def observe(decision: Decision) -> Decision:
    """Observe mode (ecp_evaluate_spec.md **Observe Mode**): "A decision that allows (ALLOW, SANDBOX) comes back as
    itself. Any other decision comes back as `OBSERVE` with `would_be` set to it". The evaluator returns it under
    OBSERVE_ALL, and each SDK after its limiter, so a limit, a kill switch and a failed limiter are observed alike; the
    rule, the counter state, the missing fields and an `error` are kept, and nothing that would hold the call (a resume
    token, a route, a remediation) is."""
    if decision.allowed:
        return decision
    return decision.model_copy(update={
        "decision": "OBSERVE", "allowed": True, "reason_codes": ["OBSERVED"],
        "would_be": decision.decision, "would_be_reason_codes": list(decision.reason_codes),
        "resume_token": None, "route_ref": None, "remediation": None, "escalation_context": None,
    })


def _unread(rule_name: str, policy_set: str, fields: List[str]) -> Remediation:
    """A missing-field BLOCK's remediation (policy_format.md "A field the call does not carry"): "treat as BLOCK,
    include remediation telling the developer which field is needed". `custom`, the type for guidance no other fits;
    the rule's own remediation is for the decision it makes when it matches."""
    named = ", ".join(fields)
    return Remediation(
        message=f"Rule '{rule_name}' in policy set '{policy_set}' reads {named}, which the call does not carry, and "
                f"the set's on_missing is fail_closed.",
        suggestion=f"Add {named} to the call and evaluate it again.",
        type="custom",
        details={"fields": list(fields)},
    )


def _utc_ms(ts: datetime) -> str:
    """An instant as UTC ISO 8601 to the millisecond, `Z`-suffixed — the string both languages render. The instant
    carries its offset (hiitl.core.date_time)."""
    return ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


class PolicyEvaluator:
    """Policy evaluator - evaluates policies against envelopes.

    This evaluator works on JSON policy objects (Python dicts/Pydantic models).
    It does not handle YAML parsing - that's a separate concern.

    Example:
        >>> evaluator = PolicyEvaluator()
        >>> policy = PolicySet(**policy_dict)  # From JSON
        >>> envelope = Envelope(**envelope_dict)  # From JSON
        >>> decision = evaluator.evaluate(envelope, policy)
    """

    def __init__(self):
        """Initialize the policy evaluator."""
        pass

    def evaluate(
        self,
        envelope: Union[Envelope, Dict[str, Any]],
        policy: Union[PolicySet, Dict[str, Any]],
        mode: str = "RESPECT_POLICY",
        enrichment: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Decision:
        """Evaluate an envelope against a policy and return a decision.

        `enrichment` is the evaluation's enrichment context (policy_format.md 2.7; TICKET-046): the sync routes'
        answers, `{route: {field: value}}`, read by conditions as `external.<route>.<field>`. A ROUTE rule whose route
        has answered (its name is a key) does not match again. None or {} — no route has answered.

        Args:
            envelope: Execution envelope (Envelope model or dict)
            policy: Policy set (PolicySet model or dict)
            mode: Evaluation mode. "OBSERVE_ALL" wraps all blocking decisions
                in OBSERVE (allowed=True). "RESPECT_POLICY" respects per-rule
                mode field (default).

        Returns:
            Decision object with outcome, reason codes, and timing metadata

        Raises:
            ValidationError: If envelope or policy doesn't match schema
        """
        # The clock starts where evaluate() starts, so the admission of the call's trees is counted in ingest_ms and
        # total_ms (decision_response.md timing; HTL-43 gap 303, ruled b88dd3e3).
        start_time = _STARTED.get()
        if start_time is None:
            start_time = time.perf_counter()
        for name, value in (("envelope", envelope), ("policy", policy), ("enrichment", enrichment)):
            shape = model_shape(Envelope) if name == 'envelope' else policy_shape(PolicySet, Envelope) if name == 'policy' else None
            validate_numeric_domain(value, (name,), shape=shape)
        with admitted_numbers():
            if not enrichment:                     # the hot path: no route has answered, nothing to set
                return self._evaluate(envelope, policy, mode, start_time)
            token = _ENRICHMENT.set(enrichment)
            try:
                return self._evaluate(envelope, policy, mode, start_time)
            finally:
                _ENRICHMENT.reset(token)

    def _evaluate_admitted_envelope(self, envelope, policy, mode="RESPECT_POLICY", enrichment=None, ingested_ms=0.0):
        """The SDK's entry: its envelope is built and admitted in this call, and the policy it holds was admitted where
        it was supplied (its file at load, a pull or the disk cache at receipt, a kill-switch tick at receipt), so
        neither is walked again (sync_engine.md Numeric domain; HTL-43 gap 295). A route's answer is still input.
        `ingested_ms` is the SDK's own ingest for the call, from its evaluate() through the envelope's signature check;
        the evaluation's clock starts that far back (HTL-43 gap 303)."""
        token = _STARTED.set(time.perf_counter() - ingested_ms / 1000)
        try:
            validate_numeric_domain(enrichment, ('enrichment',))
            with admitted_numbers():
                return self.evaluate(envelope, policy, mode=mode, enrichment=enrichment)
        finally:
            _STARTED.reset(token)

    def _evaluate(self, envelope, policy, mode: str, start_time: float) -> Decision:
        # Validate and convert to Pydantic models
        if not isinstance(envelope, Envelope):
            envelope = Envelope(**envelope)

        if not isinstance(policy, PolicySet):
            policy = PolicySet(**policy)

        ingest_end = time.perf_counter()
        ingest_ms = (ingest_end - start_time) * 1000

        # Evaluate policy rules
        eval_start = time.perf_counter()
        (
            decision_type,
            reason_codes,
            matched_rules,
            matched_rule_obj,
            staged_observations,
            rate_limit_rules,
            unread_remediation,
            missing_fields,
        ) = self._evaluate_rules(envelope, policy, mode)
        eval_end = time.perf_counter()
        evaluation_ms = (eval_end - eval_start) * 1000

        # Build decision response
        total_ms = (eval_end - start_time) * 1000

        # Escalation fields: resume_token + route_ref
        escalation_types = {DecisionType.REQUIRE_APPROVAL, DecisionType.PAUSE, DecisionType.ESCALATE}
        resume_token = None
        route_ref = None
        if decision_type in escalation_types:
            resume_token = f"rtk_{uuid.uuid4().hex}"
            if matched_rule_obj and matched_rule_obj.route:
                route_ref = matched_rule_obj.route
        elif decision_type == DecisionType.ROUTE and matched_rule_obj and matched_rule_obj.route:
            route_ref = matched_rule_obj.route          # the sync route the rule asks (decision_response.md 1.7)

        # Remediation: the matched rule's, details computed from the call (only for blocking decisions)
        allowed = decision_type in [DecisionType.ALLOW, DecisionType.SANDBOX]
        remediation = unread_remediation
        if not allowed and remediation is None and matched_rule_obj and matched_rule_obj.remediation:
            remediation = self._resolve_remediation(envelope, matched_rule_obj.remediation)

        decision = Decision(
            action_id=envelope.action_id,
            decision=decision_type,
            allowed=allowed,
            reason_codes=reason_codes,
            policy_version=policy.version,
            timing=Timing(
                ingest_ms=ingest_ms,
                evaluation_ms=evaluation_ms,
                total_ms=total_ms,
            ),
            matched_rules=matched_rules if matched_rules else None,
            resume_token=resume_token,
            route_ref=route_ref,
            remediation=remediation,
            staged_observations=staged_observations,
            rate_limit_rules=rate_limit_rules,
            missing_fields=missing_fields or None,
        )

        # Per-rule observe (the old `mode: "observe"` field) is `lifecycle_stage: "staged"` — staged rules never bind
        # (Block 1B). So the only path to OBSERVE here is the global OBSERVE_ALL toggle.
        return observe(decision) if mode == "OBSERVE_ALL" else decision

    def _evaluate_rules(
        self, envelope: Envelope, policy: PolicySet, mode: str = "RESPECT_POLICY"
    ) -> tuple[
        DecisionType,
        List[str],
        List[MatchedRule],
        Optional[Rule],
        List[StagedObservation],
        List[RateLimitRule],
        Optional[Remediation],
        List[MissingField],
    ]:
        """Evaluate rules in precedence order and return the binding match.

        Precedence is DENY wins (policy_format.md "Rule Precedence"; R-0846;
        `hiitl.core.precedence`): the walk is ordered by (class, −priority,
        definition order) — KILL_SWITCH, then BLOCK, then every other
        decision — so the first match in the walk is the binding one.

        Block 1B (9b) — side-by-side evaluation. In one ordered walk:
        - Active rules contend for the binding decision (first match in
          precedence order wins).
        - Staged rules contend in parallel for a *would-be* decision; every
          staged match is recorded as a `StagedObservation`. The first
          staged match in the same order is marked `would_be_binding=True`
          — it's the decision the staged rules would have produced if they
          were active. Later staged matches are still recorded as
          informative observations (e.g., they would catch envelopes the
          binding staged rule's narrower scope misses).

        `draft`, `disabled`, and `archived` rules are skipped entirely, and
        so is a rule carrying the uncalibrated placeholder — it never
        matches (policy_format.md "Uncalibrated bounds").
        Temporal / scope / percentage filters apply identically to both
        active and staged rules — staging means "behave as active for
        observation purposes," not "ignore filters."

        A RATE_LIMIT rule with a window meters, it never binds (R-0852):
        when active and matching it is listed in `rate_limit_rules` —
        wherever it ranks, so a limit applies to every call it matches —
        and when staged it is observed with would_be_binding=False.

        A rule whose outcome an envelope path the call does not carry leaves
        open (policy_format.md "A field the call does not carry") is read by
        its set's `on_missing`. Under `skip`, the default, it reads as today
        (a condition on an absent field is false, `exists` excepted) and is
        named in `missing_fields`; so is any such rule in observe mode or in
        the staged lane. Under `fail_closed` an active one decides BLOCK
        (MISSING_FIELD) at its own priority and place — the BLOCK class
        (DENY wins) — so the walk reads every active rule that could still
        bind below the binding key.

        Args:
            envelope: Validated envelope
            policy: Validated policy set
            mode: OBSERVE_ALL reads `fail_closed` as `skip` ("In observe mode:
                skip the policy, flag it")

        Returns:
            Tuple of (decision_type, reason_codes, matched_rules,
            matched_rule_obj, staged_observations, rate_limit_rules,
            the missing-field BLOCK's remediation, missing_fields).
        """
        fail_closed = policy.on_missing == "fail_closed" and mode != "OBSERVE_ALL"

        binding_result: Optional[
            tuple[DecisionType, List[str], List[MatchedRule], Optional[Rule], Optional[Remediation]]
        ] = None
        binding_key: Optional[tuple] = None
        missing_fields: List[MissingField] = []
        staged_observations: List[StagedObservation] = []
        rate_limit_rules: List[RateLimitRule] = []
        staged_binding_seen = False
        now = datetime.now(timezone.utc)
        answered = _ENRICHMENT.get()

        # Precedence order: DENY wins, then priority, then definition order.
        for key, rule in keyed(policy.rules):
            stage = rule.lifecycle_stage
            stage_value = stage.value if hasattr(stage, "value") else stage

            # Skip lifecycle stages that don't participate in either lane,
            # and rules with an uncalibrated bound (they never match).
            if stage_value not in ("active", "staged") or rule.uncalibrated:
                continue
            # A ROUTE rule whose route has answered in this evaluation does not match again (policy_format.md 2.7)
            if rule.route and rule.route in answered and _value(rule.decision) == DecisionType.ROUTE.value:
                continue
            meters = rule.meters

            # Active short-circuit: if we already bound an active decision,
            # the only reason to keep iterating is to capture staged
            # observations from rules later in the order. Skip remaining
            # active rules — except, under fail_closed, one whose missing-field
            # BLOCK would bind below the binding key.
            reach = min(key, as_block(key)) if fail_closed else key
            if binding_result is not None and stage_value == "active" and not meters and reach >= binding_key:
                continue

            # Temporal validity: skip rules outside their valid_from / valid_to window.
            # Each carries its offset (hiitl.core.date_time), so each is compared as the instant it writes.
            if rule.valid_from is not None and now < rule.valid_from:
                continue
            if rule.valid_to is not None and now > rule.valid_to:
                continue

            # Scope filters: agents, users, environments whitelist.
            if rule.scope is not None:
                if not self._rule_in_scope(envelope, rule.scope):
                    continue
                # Percentage rollout: deterministic hash on a configurable field.
                if not self._rule_passes_percentage(envelope, rule.scope):
                    continue

            # Match conditions (most expensive — only run after cheap filters pass).
            matched, unread = self._evaluate_condition(envelope, rule.conditions)
            if unread and fail_closed and stage_value == "active":
                if binding_key is None or as_block(key) < binding_key:
                    binding_result = (
                        DecisionType.BLOCK,
                        ["MISSING_FIELD"],
                        [MatchedRule(rule_name=rule.name, policy_set=policy.name, priority=rule.priority)],
                        None,
                        _unread(rule.name, policy.name, unread),
                    )
                    binding_key = as_block(key)
                continue
            missing_fields.extend(
                MissingField(rule_name=rule.name, policy_set=policy.name, field=f) for f in unread
            )
            if not matched:
                continue

            if stage_value == "active" and meters:
                rl = rule.rate_limit
                rate_limit_rules.append(RateLimitRule(
                    rule_name=rule.name,
                    policy_set=policy.name,
                    priority=rule.priority,
                    reason_code=rule.reason_code,
                    limit=rl.limit,
                    window_seconds=rl.window_seconds,
                    scope=rl.scope,
                    remediation=self._resolve_remediation(envelope, rule.remediation) if rule.remediation else None,
                ))
                continue

            if stage_value == "active":
                if binding_key is not None and key >= binding_key:
                    continue        # read for a missing-field BLOCK below the binding key; it matched above it
                matched_rule = MatchedRule(
                    rule_name=rule.name,
                    policy_set=policy.name,
                    priority=rule.priority,
                )
                binding_result = (
                    rule.decision,
                    [rule.reason_code],
                    [matched_rule],
                    rule,
                    None,
                )
                binding_key = key
                # Don't break — continue walking so we capture staged
                # observations from lower-priority staged rules.
                continue

            # stage_value == "staged"
            decision_value = (
                rule.decision.value
                if hasattr(rule.decision, "value")
                else rule.decision
            )
            staged_observations.append(StagedObservation(
                rule_name=rule.name,
                policy_set=policy.name,
                priority=rule.priority,
                would_be_decision=decision_value,
                would_be_reason_codes=[rule.reason_code],
                would_be_binding=not staged_binding_seen and not meters,
            ))
            staged_binding_seen = staged_binding_seen or not meters

        if binding_result is not None:
            decision_type, reason_codes, matched_rules, matched_rule_obj, unread_remediation = binding_result
            return (
                decision_type,
                reason_codes,
                matched_rules,
                matched_rule_obj,
                staged_observations,
                rate_limit_rules,
                unread_remediation,
                missing_fields,
            )

        # No active rules matched - default to BLOCK (safe by default).
        # Staged observations are still surfaced so the regression report
        # can show what staged rules *would* have done when no active rule
        # bound a decision.
        return (
            DecisionType.BLOCK,
            ["NO_MATCHING_RULE"],
            [],
            None,
            staged_observations,
            rate_limit_rules,
            None,
            missing_fields,
        )

    def _rule_in_scope(self, envelope: "Envelope", scope: "RuleScope") -> bool:
        """Check whether envelope passes the rule's scope whitelists.

        Each scope filter is an optional whitelist. If a filter is set and
        the envelope's corresponding field is not in the whitelist, the rule
        is skipped. If a filter is unset (None), it doesn't constrain anything.
        """
        if scope.environments is not None:
            env_value = envelope.environment
            # Pydantic may store enum or string depending on use_enum_values
            env_str = env_value.value if hasattr(env_value, "value") else env_value
            if env_str not in scope.environments:
                return False
        if scope.agents is not None:
            if envelope.agent_id not in scope.agents:
                return False
        if scope.users is not None:
            user_id = getattr(envelope, "user_id", None)
            if user_id is None or user_id not in scope.users:
                return False
        return True

    def _rule_passes_percentage(self, envelope: "Envelope", scope: "RuleScope") -> bool:
        """Deterministic percentage rollout check.

        Hashes a configurable envelope field (default: action_id) and applies
        the rule only if hash bucket < percentage. Deterministic so retries of
        the same envelope produce the same decision.

        If the configured hash field is missing from the envelope, the rule is
        skipped (safe default) with a logged warning.
        """
        pct = scope.percentage
        if pct is None or pct >= 100:
            return True
        if pct <= 0:
            return False

        hash_field = scope.rollout_hash_field or "action_id"
        # a field the envelope holds as data, never a model's method (policy_format.md 2.17)
        field_value = getattr(envelope, hash_field) if hash_field in type(envelope).model_fields else None
        if field_value is None:
            logger.warning(
                "Rule scope.percentage set but envelope missing field %r; skipping rule",
                hash_field,
            )
            return False

        # SHA-256 of the field value, truncate to 32 bits, mod 100.
        digest = hashlib.sha256(str(field_value).encode("utf-8")).digest()
        int_val = int.from_bytes(digest[:4], "big")
        bucket = int_val % 100
        return bucket < pct

    def _evaluate_condition(
        self, envelope: Envelope, condition: Union[Condition, LogicalCondition]
    ) -> tuple[bool, List[str]]:
        """Evaluate a condition (atomic or logical) against an envelope.

        Args:
            envelope: Envelope to evaluate against
            condition: Condition to evaluate (atomic or logical)

        Returns:
            Whether the condition matches, read as today (an absent field
            makes a condition false, `exists` excepted), and the envelope
            paths the call does not carry that leave its outcome open — empty
            when the fields the call carries decide it (policy_format.md "A
            field the call does not carry").
        """
        if isinstance(condition, Condition):
            return self._evaluate_atomic_condition(envelope, condition)
        elif isinstance(condition, LogicalCondition):
            return self._evaluate_logical_condition(envelope, condition)
        else:
            raise ValueError(f"Unknown condition type: {type(condition)}")

    def _evaluate_logical_condition(
        self, envelope: Envelope, condition: LogicalCondition
    ) -> tuple[bool, List[str]]:
        """Evaluate a logical condition (all_of, any_of, none_of).

        A child the call's fields decide settles the parent the way the
        operator does: `all_of` by a false child, `any_of` and `none_of` by a
        true one. Otherwise a child left open leaves the parent open, with
        each open child's paths.

        Args:
            envelope: Envelope to evaluate against
            condition: Logical condition

        Returns:
            (matches, the paths that leave it open), as _evaluate_condition
        """
        if condition.all_of is not None:
            children, settles = condition.all_of, False     # AND: all conditions must be true
        elif condition.any_of is not None:
            children, settles = condition.any_of, True      # OR: at least one condition must be true
        elif condition.none_of is not None:
            children, settles = condition.none_of, True     # NOT: none of the conditions may be true
        else:
            raise ValueError("Logical condition must have one of: all_of, any_of, none_of")

        values: List[bool] = []
        unread: List[str] = []
        failures: List[OperatorKindError] = []
        for cond in children:
            try:
                value, paths = self._evaluate_condition(envelope, cond)
            except OperatorKindError as error:
                failures.append(error)
                continue
            if value == settles and not paths:
                values, unread, failures = [value], [], []
                break
            values.append(value)
            unread += [p for p in paths if p not in unread]
        if failures:
            raise min(failures, key=str)
        if condition.all_of is not None:
            return all(values), unread
        return (any(values) if condition.any_of is not None else not any(values)), unread

    def _evaluate_atomic_condition(
        self, envelope: Envelope, condition: Condition
    ) -> tuple[bool, List[str]]:
        """Evaluate an atomic condition (field comparison).

        A comparison on an envelope path the call does not carry is left
        open, `exists` excepted (it reads the absence); `external.*` is the
        enrichment context beside the envelope, never counted (policy_format.md
        2.7).

        Args:
            envelope: Envelope to evaluate against
            condition: Atomic condition

        Returns:
            (matches, the paths that leave it open), as _evaluate_condition
        """
        # Resolve field path (supports dot notation)
        field_value = self._resolve_field_path(envelope, condition.field)
        unread = [condition.field] if (
            field_value is None and condition.operator != ConditionOperator.EXISTS and _in_envelope(condition.field)
        ) else []

        # A field reference as the value resolves against the same envelope (policy_format.md 2.6); one that resolves to
        # nothing makes the condition false, like an absent field
        compare_value = condition.value
        ref = field_ref(compare_value)
        if isinstance(ref, str):
            compare_value = self._resolve_field_path(envelope, ref)
            if compare_value is None:
                return False, unread + ([ref] if _in_envelope(ref) and ref not in unread else [])

        # Evaluate operator
        try:
            return self._evaluate_operator(field_value, condition.operator, compare_value), unread
        except OperatorKindError as error:
            raise OperatorKindError(condition.operator, condition.field, ref if isinstance(ref, str) else None, error.requirement) from None

    def _resolve_remediation(self, envelope: Envelope, rem: Remediation) -> Remediation:
        """A rule's remediation, each detail that states a fact of the call computed from the call (policy_format.md
        **Remediation on Rules**, the table; R-0059); every other field as written."""
        details = dict(rem.details or {})
        if rem.type == "field_restriction" and isinstance(details.get("blocked_fields"), dict):
            ref, blocked_values = details["blocked_fields"]["ref"], details["blocked_fields"]["filter"]
            found = self._resolve_field_path(envelope, ref)
            values = found if isinstance(found, list) else ([] if found is None else [found])
            blocked: List[Any] = []
            for v in values:
                if v in blocked_values and v not in blocked:
                    blocked.append(v)
            details.update(blocked_fields=blocked, field_ref=ref)
        elif rem.type == "threshold" and "field" in details:
            value = self._resolve_field_path(envelope, details["field"])
            if value is None:
                details.pop("current_value", None)
            else:
                details["current_value"] = value
        elif rem.type == "temporal":
            details["current_time"] = _utc_ms(date_time.read(envelope.timestamp))
        else:
            return rem
        return rem.model_copy(update={"details": details})

    def _resolve_field_path(self, envelope: Envelope, field_path: str) -> Any:
        """Resolve a field path (dot notation) in the envelope.

        Examples:
            action -> envelope.action
            parameters.amount -> envelope.parameters["amount"]
            target.account_id -> envelope.target["account_id"]

        Args:
            envelope: Envelope to resolve field in
            field_path: Dot-notation field path

        Returns:
            Field value, or None if field doesn't exist
        """
        parts = field_path.split(".")
        current = envelope
        if parts[0] == ENRICHMENT_ROOT:
            # the enrichment context, never the envelope (policy_format.md 2.7)
            current, parts = _ENRICHMENT.get(), parts[1:]

        for part in parts:                                # read as written, at every part (policy_format.md 2.17)
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, BaseModel) and part in type(current).model_fields:
                current = getattr(current, part)       # a field, never a method or __class__ (2.17)
            else:
                return None

            if current is None:
                return None

        return current

    def _evaluate_operator(
        self, field_value: Any, operator: ConditionOperator, compare_value: Any
    ) -> bool:
        """Evaluate a comparison operator.

        Args:
            field_value: Value from envelope
            operator: Comparison operator
            compare_value: Value to compare against

        Returns:
            True if comparison matches, False otherwise
        """
        # Handle None/null fields
        if operator == ConditionOperator.EXISTS:
            require_operand_kinds(field_value, operator, compare_value)
            return (field_value is not None) == compare_value

        # If field doesn't exist and operator isn't EXISTS, return False
        if field_value is None:
            return False

        if operator == ConditionOperator.CONFORMS_TO:
            # Declared model objects carry JSON members on either side; Python
            # mode preserves the separately held date representation.
            field_value = supplied(field_value)
            compare_value = supplied(compare_value)
        require_operand_kinds(field_value, operator, compare_value)
        if operator == ConditionOperator.CONFORMS_TO and schema_error(compare_value):
            raise OperatorKindError(operator, requirement="parameter-schema form")

        # Equality operators
        if operator == ConditionOperator.EQUALS:
            return json_equal(field_value, compare_value)
        elif operator == ConditionOperator.NOT_EQUALS:
            return not json_equal(field_value, compare_value)

        # Numeric comparison operators
        elif operator == ConditionOperator.GREATER_THAN:
            return field_value > compare_value
        elif operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            return field_value >= compare_value
        elif operator == ConditionOperator.LESS_THAN:
            return field_value < compare_value
        elif operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            return field_value <= compare_value

        # String/array operators
        elif operator == ConditionOperator.CONTAINS:
            if isinstance(field_value, str):
                return compare_value in field_value
            elif isinstance(field_value, list):
                return any(json_equal(compare_value, item) for item in field_value)
            else:
                return False
        elif operator == ConditionOperator.NOT_CONTAINS:
            if isinstance(field_value, str):
                return compare_value not in field_value
            elif isinstance(field_value, list):
                return not any(json_equal(compare_value, item) for item in field_value)
            else:
                return True

        elif operator == ConditionOperator.STARTS_WITH:
            return isinstance(field_value, str) and field_value.startswith(
                compare_value
            )
        elif operator == ConditionOperator.ENDS_WITH:
            return isinstance(field_value, str) and field_value.endswith(
                compare_value
            )
        elif operator == ConditionOperator.MATCHES:
            # Regex match (use sparingly - can be slow)
            if not isinstance(field_value, str):
                return False
            try:
                pattern = re.compile(compare_value)
                return pattern.search(field_value) is not None
            except re.error:
                return False

        # Set operators — an array on the left is a subset test (policy_format.md 2.6)
        elif operator == ConditionOperator.IN:
            if isinstance(field_value, list):
                return all(any(json_equal(x, item) for item in compare_value) for x in field_value)
            return any(json_equal(field_value, item) for item in compare_value)
        elif operator == ConditionOperator.NOT_IN:
            if isinstance(field_value, list):
                return not all(any(json_equal(x, item) for item in compare_value) for x in field_value)
            return not any(json_equal(field_value, item) for item in compare_value)

        # Schema conformance (policy_format.md 2.6) — never a regex
        elif operator == ConditionOperator.CONFORMS_TO:
            return conforms(field_value, compare_value)

        else:
            raise ValueError(f"Unknown operator: {operator}")


# Convenience function
def evaluate(
    envelope: Union[Envelope, Dict[str, Any]],
    policy: Union[PolicySet, Dict[str, Any]],
    mode: str = "RESPECT_POLICY",
    enrichment: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Decision:
    """Evaluate an envelope against a policy (convenience function).

    Args:
        envelope: Execution envelope (Envelope model or dict)
        policy: Policy set (PolicySet model or dict)
        mode: Evaluation mode ("OBSERVE_ALL" or "RESPECT_POLICY")

    Returns:
        Decision object

    Example:
        >>> from hiitl.core import evaluate
        >>> decision = evaluate(envelope_dict, policy_dict)
        >>> if decision.allowed:
        >>>     execute_action()
    """
    evaluator = PolicyEvaluator()
    return evaluator.evaluate(envelope, policy, mode=mode, enrichment=enrichment)


def live_kill_switches(policy: PolicySet) -> List[str]:
    """The kill switches the version makes live, by name, sorted: each `KILL_SWITCH` rule the evaluator binds, the
    `active` stage carrying no placeholder (sync_engine.md 2.4; HTL-29 row 131). The service's tick returns them and
    builds its `policy_set` from them, and an SDK names them in its logs; the version decides, never the list."""
    return sorted(r.name for r in policy.rules if _value(r.decision) == DecisionType.KILL_SWITCH.value
                  and _value(r.lifecycle_stage) == "active" and not r.uncalibrated)


def _value(x: Any) -> Any:
    return x.value if hasattr(x, "value") else x
