"""Error handling tests for HIITL Python evaluator.

Tests validation and error handling for invalid inputs.
These are separate from conformance tests because error messages and handling
are implementation-specific (Python vs TypeScript may differ).

Tests cover:
1. Schema validation errors (Pydantic rejects invalid inputs)
2. Runtime errors during evaluation
3. Edge cases that might cause exceptions
"""

import pytest
from pydantic import ValidationError

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import (
    Condition,
    ConditionOperator,
    Decision,
    DecisionType,
    Envelope,
    ErrorDetail,
    LogicalCondition,
    PolicySet,
    Remediation,
    Rule,
    Timing,
)


class TestSchemaValidation:
    """Test that Pydantic properly validates input schemas."""

    def test_envelope_missing_required_field(self):
        """Missing required field in envelope should raise ValidationError."""
        invalid_envelope = {
            "schema_version": "v1.0",
            "org_id": "org_test000000000000",
            # Missing action_id, environment, agent_id, etc.
        }

        with pytest.raises(ValidationError) as exc_info:
            Envelope(**invalid_envelope)

        # Verify error message mentions missing fields
        assert "action_id" in str(exc_info.value) or "Field required" in str(exc_info.value)

    def test_envelope_invalid_environment(self):
        """Invalid environment value should raise ValidationError."""
        invalid_envelope = {
            "schema_version": "v1.0",
            "org_id": "org_test000000000000",
            "environment": "production",  # Must be "prod", not "production"
            "agent_id": "agent_test",
            "action_id": "act_test00000000000000000",
            "timestamp": "2026-02-15T10:00:00Z",
            "tool_name": "test_tool",
            "operation": "execute",
            "parameters": {},
            "idempotency_key": "idem_test",
            "target": {},
            "signature": "0" * 64,
        }

        with pytest.raises(ValidationError) as exc_info:
            Envelope(**invalid_envelope)

        # Verify error message mentions valid values
        assert "dev" in str(exc_info.value) or "prod" in str(exc_info.value)

    def test_envelope_invalid_action_id_format(self):
        """Invalid action_id format should raise ValidationError."""
        invalid_envelope = {
            "schema_version": "v1.0",
            "org_id": "org_test000000000000",
            "environment": "dev",
            "agent_id": "agent_test",
            "action_id": "act_short",  # Too short (< 20 chars after "act_")
            "timestamp": "2026-02-15T10:00:00Z",
            "tool_name": "test_tool",
            "operation": "execute",
            "parameters": {},
            "idempotency_key": "idem_test",
            "target": {},
            "signature": "0" * 64,
        }

        with pytest.raises(ValidationError) as exc_info:
            Envelope(**invalid_envelope)

        assert "action_id" in str(exc_info.value) or "pattern" in str(exc_info.value)

    def test_policy_invalid_operator(self):
        """Invalid operator in condition should raise ValidationError."""
        invalid_policy = {
            "version": "1.0.0",
            "name": "test_policy",
            "rules": [
                {
                    "name": "test_rule",
                    "priority": 100,
                    "enabled": True,
                    "conditions": {
                        "field": "parameters.amount",
                        "operator": "greater_or_equal",  # Invalid (should be "greater_than_or_equal")
                        "value": 100,
                    },
                    "decision": "ALLOW",
                    "reason_code": "TEST",
                    "description": "Test rule",
                }
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            PolicySet(**invalid_policy)

        assert "operator" in str(exc_info.value)

    def test_policy_invalid_decision_type(self):
        """Invalid decision type should raise ValidationError."""
        invalid_policy = {
            "version": "1.0.0",
            "name": "test_policy",
            "rules": [
                {
                    "name": "test_rule",
                    "priority": 100,
                    "enabled": True,
                    "conditions": {
                        "field": "parameters.amount",
                        "operator": "less_than",
                        "value": 100,
                    },
                    "decision": "APPROVE",  # Invalid (should be "REQUIRE_APPROVAL")
                    "reason_code": "TEST",
                    "description": "Test rule",
                }
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            PolicySet(**invalid_policy)

        assert "decision" in str(exc_info.value)

    def test_policy_missing_required_rule_fields(self):
        """Missing required fields in rule should raise ValidationError."""
        invalid_policy = {
            "version": "1.0.0",
            "name": "test_policy",
            "rules": [
                {
                    "name": "test_rule",
                    # Missing priority, enabled, conditions, decision, reason_code
                }
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            PolicySet(**invalid_policy)

        # Should complain about missing fields
        assert "Field required" in str(exc_info.value)


class TestRuntimeErrorHandling:
    """Test runtime error handling during evaluation."""

    def test_invalid_regex_pattern_handled_gracefully(self):
        """Invalid regex pattern should return False, not raise exception."""
        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={"query": "SELECT * FROM users"},
            idempotency_key="idem_test_regex",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[
                Rule(
                    name="invalid_regex_rule",
                    priority=100,
                    enabled=True,
                    conditions=Condition(
                        field="parameters.query",
                        operator=ConditionOperator.MATCHES,
                        value="[invalid(regex",  # Invalid regex pattern
                    ),
                    decision=DecisionType.BLOCK,
                    reason_code="INVALID_REGEX",
                    description="Rule with invalid regex",
                )
            ],
        )

        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(envelope, policy)

        # Should not raise exception - invalid regex returns False, so no match
        assert decision.decision == "BLOCK"
        assert "NO_MATCHING_RULE" in decision.reason_codes

    def test_type_mismatch_in_numeric_comparison(self):
        """Type mismatch in numeric comparison should raise TypeError.

        Note: This documents current behavior. Future versions might handle
        this gracefully by returning False instead of raising.
        """
        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={"amount": "100"},  # String, not number
            idempotency_key="idem_test_type_mismatch",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[
                Rule(
                    name="numeric_comparison_rule",
                    priority=100,
                    enabled=True,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=50,  # Comparing string "100" > number 50
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="LARGE_AMOUNT",
                    description="Rule with type mismatch",
                )
            ],
        )

        evaluator = PolicyEvaluator()

        # Current behavior: raises TypeError
        # Future behavior might: return False gracefully
        with pytest.raises(TypeError):
            evaluator.evaluate(envelope, policy)

    def test_nonexistent_field_comparison(self):
        """Comparing nonexistent field should return False (no match)."""
        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={},  # No 'amount' field
            idempotency_key="idem_test_nonexistent",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[
                Rule(
                    name="nonexistent_field_rule",
                    priority=100,
                    enabled=True,
                    conditions=Condition(
                        field="parameters.amount",  # Field doesn't exist
                        operator=ConditionOperator.GREATER_THAN,
                        value=100,
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="LARGE_AMOUNT",
                    description="Rule checking nonexistent field",
                )
            ],
        )

        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(envelope, policy)

        # Nonexistent field returns None, comparison returns False, no match
        assert decision.decision == "BLOCK"
        assert "NO_MATCHING_RULE" in decision.reason_codes

    def test_deeply_nested_logical_conditions(self):
        """Very deeply nested logical conditions should not cause stack overflow."""
        # Create 50 levels of nested all_of conditions
        def create_nested_condition(depth: int) -> LogicalCondition:
            if depth == 0:
                return Condition(
                    field="parameters.amount",
                    operator=ConditionOperator.GREATER_THAN,
                    value=0,
                )
            return LogicalCondition(all_of=[create_nested_condition(depth - 1)])

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={"amount": 100},
            idempotency_key="idem_test_deep_nesting",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[
                Rule(
                    name="deeply_nested_rule",
                    priority=100,
                    enabled=True,
                    conditions=create_nested_condition(50),
                    decision=DecisionType.ALLOW,
                    reason_code="DEEP_NESTING",
                    description="Rule with 50 levels of nesting",
                )
            ],
        )

        evaluator = PolicyEvaluator()

        # Should not raise RecursionError
        decision = evaluator.evaluate(envelope, policy)

        # Should match (all conditions are true)
        assert decision.decision == "ALLOW"
        assert "DEEP_NESTING" in decision.reason_codes


class TestEdgeCaseErrorHandling:
    """Test edge cases that might cause unexpected behavior."""

    def test_empty_policy_rules(self):
        """Policy with no rules should return BLOCK with NO_MATCHING_RULE."""
        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test_empty_rules",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[],  # No rules
        )

        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(envelope, policy)

        # Safe by default: no rules → BLOCK
        assert decision.decision == "BLOCK"
        assert "NO_MATCHING_RULE" in decision.reason_codes

    def test_all_rules_disabled(self):
        """Policy with all rules disabled should return BLOCK."""
        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="agent_test",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            tool_name="test_tool",
            operation="execute",
            parameters={"amount": 100},
            idempotency_key="idem_test_all_disabled",
            target={},
            signature="0" * 64,
        )

        policy = PolicySet(
            version="1.0.0",
            name="test_policy",
            rules=[
                Rule(
                    name="disabled_rule",
                    priority=100,
                    enabled=False,  # Disabled
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.LESS_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="ALLOWED",
                    description="Disabled rule",
                )
            ],
        )

        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(envelope, policy)

        # All rules disabled → no match → BLOCK
        assert decision.decision == "BLOCK"
        assert "NO_MATCHING_RULE" in decision.reason_codes


class TestErrorDetailStructuredErrors:
    """Test structured error field on Decision per decision_response.md spec.

    Validates:
    - ErrorDetail has code + message (spec-aligned)
    - Backward compat: string auto-wraps to ErrorDetail
    - Backward compat: dict coerces to ErrorDetail
    - Error/remediation mutual exclusivity
    """

    def _minimal_decision(self, **overrides):
        """Create a minimal Decision with defaults for required fields."""
        defaults = {
            "action_id": "act_test00000000000000000",
            "decision": DecisionType.BLOCK,
            "allowed": False,
            "reason_codes": ["TEST_ERROR"],
            "policy_version": "1.0.0",
            "timing": Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        }
        defaults.update(overrides)
        return Decision(**defaults)

    def test_error_detail_structured_object(self):
        """error field accepts ErrorDetail with code and message."""
        d = self._minimal_decision(
            error=ErrorDetail(
                code="RATE_LIMIT_SERVICE_ERROR",
                message="Rate limiting unavailable. Action blocked (fail-closed).",
            ),
        )
        assert d.error is not None
        assert d.error.code == "RATE_LIMIT_SERVICE_ERROR"
        assert d.error.message == "Rate limiting unavailable. Action blocked (fail-closed)."

    def test_error_backward_compat_string(self):
        """error field accepts a plain string and wraps to ErrorDetail."""
        d = self._minimal_decision(error="Something went wrong")
        assert d.error is not None
        assert isinstance(d.error, ErrorDetail)
        assert d.error.code == "UNKNOWN"
        assert d.error.message == "Something went wrong"

    def test_error_backward_compat_dict(self):
        """error field accepts a dict and coerces to ErrorDetail."""
        d = self._minimal_decision(
            error={"code": "POLICY_INTEGRITY_VIOLATION", "message": "Hash mismatch"},
        )
        assert d.error is not None
        assert isinstance(d.error, ErrorDetail)
        assert d.error.code == "POLICY_INTEGRITY_VIOLATION"
        assert d.error.message == "Hash mismatch"

    def test_error_none_by_default(self):
        """error is None when not set."""
        d = self._minimal_decision()
        assert d.error is None

    def test_error_remediation_mutually_exclusive(self):
        """Cannot have both error and remediation on a Decision."""
        with pytest.raises(ValidationError, match="error.*remediation|remediation.*error"):
            self._minimal_decision(
                error=ErrorDetail(code="TEST", message="test error"),
                remediation=Remediation(
                    message="test", suggestion="fix it", type="custom"
                ),
            )

    def test_error_with_convenience_properties(self):
        """Decision with error still has correct convenience properties."""
        d = self._minimal_decision(
            error=ErrorDetail(code="EVALUATION_TIMEOUT", message="Timed out"),
        )
        assert d.blocked is True
        assert d.ok is False
        assert d.allowed is False

    def test_error_detail_serialization(self):
        """ErrorDetail round-trips through serialization."""
        d = self._minimal_decision(
            error=ErrorDetail(
                code="SIGNATURE_INVALID",
                message="Envelope signature verification failed.",
            ),
        )
        dumped = d.model_dump(mode="json")
        assert dumped["error"] == {
            "code": "SIGNATURE_INVALID",
            "message": "Envelope signature verification failed.",
        }

        # Round-trip: reconstruct from serialized form
        d2 = Decision(**dumped)
        assert d2.error.code == "SIGNATURE_INVALID"
        assert d2.error.message == "Envelope signature verification failed."
