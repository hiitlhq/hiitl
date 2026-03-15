"""Unit tests for the policy evaluator.

Tests cover:
- Atomic condition evaluation (all operators)
- Logical condition evaluation (all_of, any_of, none_of)
- Field path resolution (dot notation)
- Rule priority ordering
- Decision types
- Timing metadata
"""

import pytest
from datetime import datetime

from hiitl.core import PolicyEvaluator, Envelope, PolicySet, Rule, Decision
from hiitl.core.types import (
    Condition,
    ConditionOperator,
    DecisionType,
    Environment,
    LogicalCondition,
    Operation,
)


class TestPolicyEvaluator:
    """Test suite for PolicyEvaluator."""

    def test_simple_allow_rule(self):
        """Test a simple ALLOW rule with exact match."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="read_data",
            operation=Operation.READ,
            target={"resource": "database"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-reads",
                    description="Allow all read operations",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="operation",
                        operator=ConditionOperator.EQUALS,
                        value="read",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="ALLOWED_READ",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ALLOW
        assert decision.allowed is True
        assert "ALLOWED_READ" in decision.reason_codes
        assert decision.timing.evaluation_ms < 10  # Should be very fast

    def test_block_rule(self):
        """Test a BLOCK rule."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="delete_data",
            operation=Operation.DELETE,
            target={"resource": "production_db"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="block-prod-deletes",
                    description="Block deletes in production",
                    enabled=True,
                    priority=100,
                    conditions=LogicalCondition(
                        all_of=[
                            Condition(
                                field="environment",
                                operator=ConditionOperator.EQUALS,
                                value="prod",
                            ),
                            Condition(
                                field="operation",
                                operator=ConditionOperator.EQUALS,
                                value="delete",
                            ),
                        ]
                    ),
                    decision=DecisionType.BLOCK,
                    reason_code="PROD_DELETE_BLOCKED",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.BLOCK
        assert decision.allowed is False
        assert "PROD_DELETE_BLOCKED" in decision.reason_codes

    def test_greater_than_operator(self):
        """Test greater_than operator with nested field path."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="payment-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 1500.00, "currency": "usd"},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="payment-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-approval-high-value",
                    description="Require approval for payments over $1000",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE_PAYMENT",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.allowed is False
        assert "HIGH_VALUE_PAYMENT" in decision.reason_codes

    def test_contains_operator_array(self):
        """Test contains operator with array field."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 100.00},
            sensitivity=["money", "irreversible"],
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="pause-money-operations",
                    description="Pause operations involving money",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="sensitivity",
                        operator=ConditionOperator.CONTAINS,
                        value="money",
                    ),
                    decision=DecisionType.PAUSE,
                    reason_code="SENSITIVE_OPERATION",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.PAUSE
        assert "SENSITIVE_OPERATION" in decision.reason_codes

    def test_in_operator(self):
        """Test 'in' operator (value in set)."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="send_email",
            operation=Operation.EXECUTE,
            target={"email": "user@example.com"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-safe-tools",
                    description="Allow safe tools",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="tool_name",
                        operator=ConditionOperator.IN,
                        value=["send_email", "read_data", "log_event"],
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="SAFE_TOOL",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ALLOW
        assert "SAFE_TOOL" in decision.reason_codes

    def test_all_of_logical_operator(self):
        """Test all_of (AND) logical operator."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="escalate-high-value-prod",
                    description="Escalate high-value payments in prod",
                    enabled=True,
                    priority=100,
                    conditions=LogicalCondition(
                        all_of=[
                            Condition(
                                field="environment",
                                operator=ConditionOperator.EQUALS,
                                value="prod",
                            ),
                            Condition(
                                field="tool_name",
                                operator=ConditionOperator.EQUALS,
                                value="process_payment",
                            ),
                            Condition(
                                field="parameters.amount",
                                operator=ConditionOperator.GREATER_THAN,
                                value=1000,
                            ),
                        ]
                    ),
                    decision=DecisionType.ESCALATE,
                    reason_code="HIGH_VALUE_PROD_PAYMENT",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ESCALATE
        assert "HIGH_VALUE_PROD_PAYMENT" in decision.reason_codes

    def test_any_of_logical_operator(self):
        """Test any_of (OR) logical operator."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="grant_access",
            operation=Operation.EXECUTE,
            target={"user_id": "user_123"},
            parameters={"role": "admin"},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-approval-sensitive",
                    description="Require approval for sensitive operations",
                    enabled=True,
                    priority=100,
                    conditions=LogicalCondition(
                        any_of=[
                            Condition(
                                field="tool_name",
                                operator=ConditionOperator.EQUALS,
                                value="grant_access",
                            ),
                            Condition(
                                field="tool_name",
                                operator=ConditionOperator.EQUALS,
                                value="revoke_access",
                            ),
                            Condition(
                                field="operation",
                                operator=ConditionOperator.EQUALS,
                                value="delete",
                            ),
                        ]
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="SENSITIVE_OPERATION",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert "SENSITIVE_OPERATION" in decision.reason_codes

    def test_none_of_logical_operator(self):
        """Test none_of (NOT) logical operator."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="read_data",
            operation=Operation.READ,
            target={"resource": "database"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-safe-ops",
                    description="Allow operations that aren't dangerous",
                    enabled=True,
                    priority=100,
                    conditions=LogicalCondition(
                        none_of=[
                            Condition(
                                field="operation",
                                operator=ConditionOperator.EQUALS,
                                value="delete",
                            ),
                            Condition(
                                field="tool_name",
                                operator=ConditionOperator.EQUALS,
                                value="drop_database",
                            ),
                        ]
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="SAFE_OPERATION",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ALLOW
        assert "SAFE_OPERATION" in decision.reason_codes

    def test_priority_ordering(self):
        """Test that higher priority rules are evaluated first."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 100.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                # Lower priority - would allow
                Rule(
                    name="allow-all-payments",
                    description="Allow all payments",
                    enabled=True,
                    priority=10,
                    conditions=Condition(
                        field="tool_name",
                        operator=ConditionOperator.EQUALS,
                        value="process_payment",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="ALLOW_ALL",
                ),
                # Higher priority - should win
                Rule(
                    name="block-prod-payments",
                    description="Block payments in prod",
                    enabled=True,
                    priority=100,
                    conditions=LogicalCondition(
                        all_of=[
                            Condition(
                                field="environment",
                                operator=ConditionOperator.EQUALS,
                                value="prod",
                            ),
                            Condition(
                                field="tool_name",
                                operator=ConditionOperator.EQUALS,
                                value="process_payment",
                            ),
                        ]
                    ),
                    decision=DecisionType.BLOCK,
                    reason_code="PROD_PAYMENT_BLOCKED",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        # Higher priority rule should win
        assert decision.decision == DecisionType.BLOCK
        assert "PROD_PAYMENT_BLOCKED" in decision.reason_codes

    def test_disabled_rule_skipped(self):
        """Test that disabled rules are skipped."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="test_tool",
            operation=Operation.EXECUTE,
            target={},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                # Disabled rule - should be skipped
                Rule(
                    name="allow-test",
                    description="Allow test",
                    enabled=False,  # Disabled!
                    priority=100,
                    conditions=Condition(
                        field="tool_name",
                        operator=ConditionOperator.EQUALS,
                        value="test_tool",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="TEST_ALLOWED",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        # No rules matched, should default to BLOCK
        assert decision.decision == DecisionType.BLOCK
        assert "NO_MATCHING_RULE" in decision.reason_codes

    def test_no_matching_rule_defaults_to_block(self):
        """Test that no matching rule defaults to BLOCK (safe by default)."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="unknown_tool",
            operation=Operation.EXECUTE,
            target={},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-specific-tool",
                    description="Allow specific tool only",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="tool_name",
                        operator=ConditionOperator.EQUALS,
                        value="specific_tool",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="SPECIFIC_TOOL",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        # No rules matched, should default to BLOCK
        assert decision.decision == DecisionType.BLOCK
        assert decision.allowed is False
        assert "NO_MATCHING_RULE" in decision.reason_codes

    def test_exists_operator(self):
        """Test exists operator for optional fields."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="test_tool",
            operation=Operation.EXECUTE,
            target={},
            parameters={},
            user_id="user_123",  # Optional field present
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-user-id",
                    description="Require user_id to be present",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="user_id",
                        operator=ConditionOperator.EXISTS,
                        value=True,
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="USER_ID_PRESENT",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ALLOW
        assert "USER_ID_PRESENT" in decision.reason_codes

    def test_matched_rules_metadata(self):
        """Test that matched_rules metadata is included."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="read_data",
            operation=Operation.READ,
            target={},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="my-policy",
            version="v2.1.0",
            rules=[
                Rule(
                    name="allow-reads",
                    description="Allow reads",
                    enabled=True,
                    priority=50,
                    conditions=Condition(
                        field="operation",
                        operator=ConditionOperator.EQUALS,
                        value="read",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="READ_ALLOWED",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.matched_rules is not None
        assert len(decision.matched_rules) == 1
        assert decision.matched_rules[0].rule_name == "allow-reads"
        assert decision.matched_rules[0].policy_set == "my-policy"
        assert decision.matched_rules[0].priority == 50

    def test_timing_metadata_present(self):
        """Test that timing metadata is present and reasonable."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="test_tool",
            operation=Operation.EXECUTE,
            target={},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-all",
                    description="Allow all",
                    enabled=True,
                    priority=1,
                    conditions=Condition(
                        field="tool_name",
                        operator=ConditionOperator.EXISTS,
                        value=True,
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="ALLOW_ALL",
                ),
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        # Timing metadata should be present
        assert decision.timing is not None
        assert decision.timing.ingest_ms >= 0
        assert decision.timing.evaluation_ms >= 0
        assert decision.timing.total_ms >= 0
        assert decision.timing.total_ms >= decision.timing.evaluation_ms

        # For such a simple policy, evaluation should be very fast
        assert decision.timing.total_ms < 100  # Should be < 100ms
        assert decision.timing.evaluation_ms < 10  # Should be < 10ms


    def test_resume_token_generated_for_require_approval(self):
        """Test that resume_token is generated for REQUIRE_APPROVAL decisions."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="payment-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-approval-high-value",
                    description="Require approval for high-value payments",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE_PAYMENT",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.resume_token is not None
        assert decision.resume_token.startswith("rtk_")
        assert len(decision.resume_token) == 36  # "rtk_" + 32 hex chars

    def test_resume_token_generated_for_pause(self):
        """Test that resume_token is generated for PAUSE decisions."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 100.00},
            sensitivity=["money"],
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="pause-money-operations",
                    description="Pause operations involving money",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="sensitivity",
                        operator=ConditionOperator.CONTAINS,
                        value="money",
                    ),
                    decision=DecisionType.PAUSE,
                    reason_code="SENSITIVE_OPERATION",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.PAUSE
        assert decision.resume_token is not None
        assert decision.resume_token.startswith("rtk_")

    def test_resume_token_generated_for_escalate(self):
        """Test that resume_token is generated for ESCALATE decisions."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="escalate-high-value",
                    description="Escalate high-value payments",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.ESCALATE,
                    reason_code="HIGH_VALUE_ESCALATION",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ESCALATE
        assert decision.resume_token is not None
        assert decision.resume_token.startswith("rtk_")

    def test_no_resume_token_for_allow(self):
        """Test that resume_token is NOT generated for ALLOW decisions."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.DEV,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="read_data",
            operation=Operation.READ,
            target={"resource": "database"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="allow-reads",
                    description="Allow all read operations",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="operation",
                        operator=ConditionOperator.EQUALS,
                        value="read",
                    ),
                    decision=DecisionType.ALLOW,
                    reason_code="ALLOWED_READ",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.ALLOW
        assert decision.resume_token is None
        assert decision.route_ref is None

    def test_no_resume_token_for_block(self):
        """Test that resume_token is NOT generated for BLOCK decisions."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="delete_data",
            operation=Operation.DELETE,
            target={"resource": "production_db"},
            parameters={},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="block-prod-deletes",
                    description="Block deletes in production",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="operation",
                        operator=ConditionOperator.EQUALS,
                        value="delete",
                    ),
                    decision=DecisionType.BLOCK,
                    reason_code="DELETE_BLOCKED",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.BLOCK
        assert decision.resume_token is None
        assert decision.route_ref is None

    def test_route_ref_passed_from_rule(self):
        """Test that route from matched rule is passed to Decision.route_ref."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="payment-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="payment-policy",
            version="v2.0.0",
            rules=[
                Rule(
                    name="require-approval-high-value",
                    description="Require approval for high-value payments",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE_PAYMENT",
                    route="finance-review",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.route_ref == "finance-review"
        assert decision.resume_token is not None

    def test_route_ref_none_when_rule_has_no_config(self):
        """Test that route_ref is None when matched rule has no route."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="test-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-approval-no-config",
                    description="Require approval without HITL config",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE_PAYMENT",
                    # No route specified
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.route_ref is None
        assert decision.resume_token is not None  # Still gets a resume token

    def test_escalation_context_is_none_from_evaluator(self):
        """Test that escalation_context is NOT populated by the evaluator.

        Per spec: escalation_context is populated by the SDK/server which
        resolves the HITL config, not by the evaluator itself.
        """
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="payment-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="payment-policy",
            version="v2.0.0",
            rules=[
                Rule(
                    name="require-approval-high-value",
                    description="Require approval for high-value payments",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE_PAYMENT",
                    route="finance-review",
                )
            ],
        )

        decision = evaluator.evaluate(envelope, policy)

        assert decision.escalation_context is None

    def test_resume_token_unique_per_evaluation(self):
        """Test that each evaluation generates a unique resume_token."""
        evaluator = PolicyEvaluator()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test123456789012",
            environment=Environment.PROD,
            agent_id="payment-agent",
            action_id="act_01234567890123456789",
            idempotency_key="idem_test",
            tool_name="process_payment",
            operation=Operation.EXECUTE,
            target={"account_id": "acct_123"},
            parameters={"amount": 5000.00},
            timestamp=datetime.now(),
            signature="a" * 64,
        )

        policy = PolicySet(
            name="test-policy",
            version="v1.0.0",
            rules=[
                Rule(
                    name="require-approval",
                    description="Require approval",
                    enabled=True,
                    priority=100,
                    conditions=Condition(
                        field="parameters.amount",
                        operator=ConditionOperator.GREATER_THAN,
                        value=1000,
                    ),
                    decision=DecisionType.REQUIRE_APPROVAL,
                    reason_code="HIGH_VALUE",
                )
            ],
        )

        decision1 = evaluator.evaluate(envelope, policy)
        decision2 = evaluator.evaluate(envelope, policy)

        assert decision1.resume_token != decision2.resume_token


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
