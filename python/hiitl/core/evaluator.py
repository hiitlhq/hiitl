"""Policy evaluator - deterministic rule evaluation engine.

This is the core runtime enforcement engine. It evaluates policies (JSON objects)
against execution envelopes and returns decisions.

Source of truth:
- specs/envelope_schema.json
- docs/specs/policy_format.md
- docs/specs/decision_response.md

Design principles:
- Deterministic: same (envelope, policy) always produces same decision
- Side-effect free: evaluation does not modify state
- Fast: sub-millisecond evaluation for typical policies
- Language-neutral: behavior validated by conformance test suite
"""

import re
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from .types import (
    Condition,
    ConditionOperator,
    Decision,
    DecisionType,
    Envelope,
    LogicalCondition,
    MatchedRule,
    PolicySet,
    Rule,
    Timing,
)


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
    ) -> Decision:
        """Evaluate an envelope against a policy and return a decision.

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
        start_time = time.perf_counter()

        # Validate and convert to Pydantic models
        if not isinstance(envelope, Envelope):
            envelope = Envelope(**envelope)

        if not isinstance(policy, PolicySet):
            policy = PolicySet(**policy)

        ingest_end = time.perf_counter()
        ingest_ms = (ingest_end - start_time) * 1000

        # Evaluate policy rules
        eval_start = time.perf_counter()
        decision_type, reason_codes, matched_rules, matched_rule_obj = (
            self._evaluate_rules(envelope, policy)
        )
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

        # Remediation: pass through from matched rule (only for blocking decisions)
        allowed = decision_type in [DecisionType.ALLOW, DecisionType.SANDBOX]
        remediation = None
        if not allowed and matched_rule_obj and matched_rule_obj.remediation:
            remediation = matched_rule_obj.remediation

        # Check if this decision should be wrapped in OBSERVE mode
        should_observe = False
        if mode == "OBSERVE_ALL" and not allowed:
            should_observe = True
        elif (mode == "RESPECT_POLICY" and matched_rule_obj is not None
              and matched_rule_obj.mode == "observe" and not allowed):
            should_observe = True

        if should_observe:
            return Decision(
                action_id=envelope.action_id,
                decision=DecisionType.OBSERVE,
                allowed=True,
                reason_codes=["OBSERVED"],
                would_be=decision_type,
                would_be_reason_codes=reason_codes,
                policy_version=policy.version,
                timing=Timing(
                    ingest_ms=ingest_ms,
                    evaluation_ms=evaluation_ms,
                    total_ms=total_ms,
                ),
                matched_rules=matched_rules if matched_rules else None,
            )

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
        )

        return decision

    def _evaluate_rules(
        self, envelope: Envelope, policy: PolicySet
    ) -> tuple[DecisionType, List[str], List[MatchedRule], Optional[Rule]]:
        """Evaluate rules in priority order and return first match.

        Args:
            envelope: Validated envelope
            policy: Validated policy set

        Returns:
            Tuple of (decision_type, reason_codes, matched_rules, matched_rule_obj)
        """
        # Sort rules by priority (highest first)
        sorted_rules = sorted(
            policy.rules, key=lambda r: r.priority, reverse=True
        )

        # Evaluate rules in priority order (first match wins)
        for rule in sorted_rules:
            # Skip disabled rules
            if not rule.enabled:
                continue

            # Evaluate rule conditions
            if self._evaluate_condition(envelope, rule.conditions):
                # Rule matched!
                matched_rule = MatchedRule(
                    rule_name=rule.name,
                    policy_set=policy.name,
                    priority=rule.priority,
                )
                return (
                    rule.decision,
                    [rule.reason_code],
                    [matched_rule],
                    rule,
                )

        # No rules matched - default to BLOCK (safe by default)
        return (DecisionType.BLOCK, ["NO_MATCHING_RULE"], [], None)

    def _evaluate_condition(
        self, envelope: Envelope, condition: Union[Condition, LogicalCondition]
    ) -> bool:
        """Evaluate a condition (atomic or logical) against an envelope.

        Args:
            envelope: Envelope to evaluate against
            condition: Condition to evaluate (atomic or logical)

        Returns:
            True if condition matches, False otherwise
        """
        if isinstance(condition, Condition):
            return self._evaluate_atomic_condition(envelope, condition)
        elif isinstance(condition, LogicalCondition):
            return self._evaluate_logical_condition(envelope, condition)
        else:
            raise ValueError(f"Unknown condition type: {type(condition)}")

    def _evaluate_logical_condition(
        self, envelope: Envelope, condition: LogicalCondition
    ) -> bool:
        """Evaluate a logical condition (all_of, any_of, none_of).

        Args:
            envelope: Envelope to evaluate against
            condition: Logical condition

        Returns:
            True if logical condition matches, False otherwise
        """
        if condition.all_of is not None:
            # AND: all conditions must be true
            return all(
                self._evaluate_condition(envelope, cond)
                for cond in condition.all_of
            )
        elif condition.any_of is not None:
            # OR: at least one condition must be true
            return any(
                self._evaluate_condition(envelope, cond)
                for cond in condition.any_of
            )
        elif condition.none_of is not None:
            # NOT: none of the conditions may be true
            return not any(
                self._evaluate_condition(envelope, cond)
                for cond in condition.none_of
            )
        else:
            raise ValueError("Logical condition must have one of: all_of, any_of, none_of")

    def _evaluate_atomic_condition(
        self, envelope: Envelope, condition: Condition
    ) -> bool:
        """Evaluate an atomic condition (field comparison).

        Args:
            envelope: Envelope to evaluate against
            condition: Atomic condition

        Returns:
            True if condition matches, False otherwise
        """
        # Resolve field path (supports dot notation)
        field_value = self._resolve_field_path(envelope, condition.field)

        # Evaluate operator
        return self._evaluate_operator(
            field_value, condition.operator, condition.value
        )

    def _resolve_field_path(self, envelope: Envelope, field_path: str) -> Any:
        """Resolve a field path (dot notation) in the envelope.

        Examples:
            tool_name -> envelope.tool_name
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

        for part in parts:
            # Backward compat: tool_name → action
            if part == "tool_name":
                part = "action"
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
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
            return (field_value is not None) == compare_value

        # If field doesn't exist and operator isn't EXISTS, return False
        if field_value is None:
            return False

        # Equality operators
        if operator == ConditionOperator.EQUALS:
            return field_value == compare_value
        elif operator == ConditionOperator.NOT_EQUALS:
            return field_value != compare_value

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
                return compare_value in field_value
            else:
                return False
        elif operator == ConditionOperator.NOT_CONTAINS:
            if isinstance(field_value, str):
                return compare_value not in field_value
            elif isinstance(field_value, list):
                return compare_value not in field_value
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

        # Set operators
        elif operator == ConditionOperator.IN:
            return field_value in compare_value
        elif operator == ConditionOperator.NOT_IN:
            return field_value not in compare_value

        else:
            raise ValueError(f"Unknown operator: {operator}")


# Convenience function
def evaluate(
    envelope: Union[Envelope, Dict[str, Any]],
    policy: Union[PolicySet, Dict[str, Any]],
    mode: str = "RESPECT_POLICY",
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
    return evaluator.evaluate(envelope, policy, mode=mode)
