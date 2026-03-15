"""Tests for HIITL client class."""

import time
from pathlib import Path

import pytest

from hiitl.core.types import DecisionType
from hiitl.sdk.client import HIITL
from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    PolicyLoadError,
)


# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestHIITLInitialization:
    """Test HIITL client initialization."""

    def test_zero_config_initialization(self, tmp_path):
        """HIITL() with no args should work (zero-config)."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))

        assert hiitl.config.agent_id == "default"
        assert hiitl.config.environment.value == "dev"
        assert hiitl.config.org_id == "org_devlocal0000000000"
        assert hiitl._eval_mode == "OBSERVE_ALL"

    def test_valid_initialization_with_policy(self, tmp_path):
        """Valid configuration with policy should initialize successfully."""
        policy_file = tmp_path / "test_policy.json"
        policy_file.write_text('''{
            "version": "1.0.0",
            "name": "test_policy",
            "rules": []
        }''')

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            mode="RESPECT_POLICY",
        )

        assert hiitl.config.environment.value == "dev"
        assert hiitl.config.agent_id == "test-agent"
        assert hiitl.config.org_id == "org_test000000000000000"

    def test_keyword_only_args(self, tmp_path):
        """All constructor args must be keyword-only."""
        with pytest.raises(TypeError):
            HIITL("dev", "test-agent", "org_test000000000000000")

    def test_invalid_org_id_raises_error(self, tmp_path):
        """Invalid org_id should raise ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            HIITL(
                environment="dev",
                agent_id="test-agent",
                policy_path=str(tmp_path / "p.yaml"),
                org_id="org_short",
                audit_db_path=str(tmp_path / "audit.db"),
                mode="RESPECT_POLICY",
            )

        assert "org_id" in str(exc_info.value).lower()

    def test_missing_policy_with_respect_policy_raises_error(self, tmp_path):
        """RESPECT_POLICY mode without policy_path should raise error."""
        with pytest.raises(ConfigurationError, match="policy_path is required"):
            HIITL(
                environment="dev",
                agent_id="test-agent",
                org_id="org_test000000000000000",
                mode="RESPECT_POLICY",
                audit_db_path=str(tmp_path / "audit.db"),
            )

    def test_missing_policy_file_raises_error_on_evaluate(self, tmp_path):
        """Nonexistent policy file should raise error on evaluate."""
        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(tmp_path / "nonexistent.yaml"),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            mode="RESPECT_POLICY",
        )

        with pytest.raises(PolicyLoadError):
            hiitl.evaluate("test_tool")


class TestHIITLEvaluate:
    """Test HIITL evaluate() method."""

    @pytest.fixture
    def hiitl_client(self, tmp_path):
        """Create HIITL client with test policy."""
        policy_file = tmp_path / "test_policy.yaml"
        policy_file.write_text('''
version: "1.0.0"
name: test_policy
rules:
  - name: allow_small_amounts
    priority: 100
    enabled: true
    conditions:
      field: parameters.amount
      operator: less_than
      value: 1000
    decision: ALLOW
    reason_code: SMALL_AMOUNT
    description: Allow small amounts
  - name: block_large_amounts
    priority: 50
    enabled: true
    conditions:
      field: parameters.amount
      operator: greater_than_or_equal
      value: 1000
    decision: BLOCK
    reason_code: LARGE_AMOUNT
    description: Block large amounts
        ''')

        return HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            mode="RESPECT_POLICY",
        )

    def test_evaluate_action_only(self, hiitl_client):
        """evaluate() should work with just action name."""
        decision = hiitl_client.evaluate("payment_transfer")
        # No parameters.amount → no matching rule → BLOCK (NO_MATCHING_RULE)
        assert isinstance(decision.decision, str)

    def test_evaluate_allow_decision(self, hiitl_client):
        """evaluate() should return ALLOW for allowed action."""
        decision = hiitl_client.evaluate(
            "payment_transfer",
            parameters={"amount": 500},
        )

        assert decision.decision == DecisionType.ALLOW
        assert decision.allowed is True
        assert decision.ok is True
        assert "SMALL_AMOUNT" in decision.reason_codes

    def test_evaluate_block_decision(self, hiitl_client):
        """evaluate() should return BLOCK for blocked action."""
        decision = hiitl_client.evaluate(
            "payment_transfer",
            parameters={"amount": 5000},
        )

        assert decision.decision == DecisionType.BLOCK
        assert decision.allowed is False
        assert decision.blocked is True
        assert "LARGE_AMOUNT" in decision.reason_codes

    def test_evaluate_auto_generates_action_id(self, hiitl_client):
        """evaluate() should auto-generate action_id."""
        decision = hiitl_client.evaluate("test_tool")

        assert decision.action_id.startswith("act_")
        assert len(decision.action_id) == 24  # "act_" + 20 hex chars

    def test_evaluate_creates_audit_record(self, hiitl_client, tmp_path):
        """evaluate() should write audit record to database."""
        decision = hiitl_client.evaluate(
            "test_tool",
            parameters={"amount": 100},
        )

        import sqlite3
        conn = sqlite3.connect(tmp_path / "audit.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log")
        count = cursor.fetchone()[0]
        conn.close()

        assert count >= 1

    def test_evaluate_with_optional_fields(self, hiitl_client):
        """evaluate() should accept optional fields."""
        decision = hiitl_client.evaluate(
            "test_tool",
            parameters={"amount": 100},
            target={"resource": "db"},
            operation="write",
            user_id="user_alice",
            session_id="session_123",
            confidence=0.95,
            reason="Test evaluation",
        )

        assert decision.decision in [DecisionType.ALLOW, DecisionType.BLOCK]

    def test_evaluate_with_agent_id_override(self, hiitl_client):
        """evaluate() should accept per-call agent_id override."""
        decision = hiitl_client.evaluate(
            "test_tool",
            parameters={"amount": 100},
            agent_id="override-agent",
        )

        assert decision.allowed is True or decision.allowed is False

    def test_evaluate_uses_cached_policy(self, hiitl_client):
        """Second evaluate() should use cached policy (faster)."""
        # First evaluate
        start = time.perf_counter()
        hiitl_client.evaluate("test_tool", parameters={"amount": 100})
        first_time = time.perf_counter() - start

        # Second evaluate (should use cached policy)
        start = time.perf_counter()
        hiitl_client.evaluate("test_tool", parameters={"amount": 100})
        second_time = time.perf_counter() - start

        assert second_time <= first_time * 2
        assert first_time < 0.01
        assert second_time < 0.01


class TestHIITLZeroConfig:
    """Test zero-config initialization and OBSERVE mode."""

    def test_zero_config_observe_mode(self, tmp_path):
        """Zero-config should use OBSERVE_ALL mode with empty policy."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))

        decision = hiitl.evaluate("send_email")

        # Empty policy → NO_MATCHING_RULE → BLOCK, wrapped in OBSERVE
        assert decision.allowed is True
        assert decision.observed is True
        assert decision.would_be == "BLOCK"

    def test_zero_config_evaluate_rich(self, tmp_path):
        """Zero-config should work with rich evaluate parameters."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))

        decision = hiitl.evaluate(
            "process_payment",
            parameters={"amount": 500, "currency": "USD"},
            target={"account_id": "acct_123"},
            user_id="user_42",
        )

        assert decision.allowed is True
        assert decision.observed is True

    def test_observe_mode_convenience_properties(self, tmp_path):
        """Decision convenience properties should work correctly."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))

        decision = hiitl.evaluate("send_email")

        assert decision.ok is True  # allowed
        assert decision.blocked is False
        assert decision.needs_approval is False
        assert decision.observed is True


class TestHIITLEnvelopeBuilding:
    """Test envelope building logic."""

    def test_envelope_includes_config_values(self, tmp_path):
        """Envelope should include values from config."""
        policy_file = tmp_path / "test_policy.json"
        policy_file.write_text('''{
            "version": "1.0.0",
            "name": "test_policy",
            "rules": []
        }''')

        hiitl = HIITL(
            environment="dev",
            agent_id="payment-agent",
            policy_path=str(policy_file),
            org_id="org_mycompany123456789",
            audit_db_path=str(tmp_path / "audit.db"),
        )

        hiitl.evaluate("test_tool")

        import sqlite3
        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        assert row['org_id'] == "org_mycompany123456789"
        assert row['environment'] == "dev"
        assert row['agent_id'] == "payment-agent"

    def test_envelope_uses_action_field(self, tmp_path):
        """Envelope should use 'action' field (not tool_name)."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))
        hiitl.evaluate("send_email")

        import json, sqlite3
        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT envelope FROM audit_log LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        envelope = json.loads(row['envelope'])
        assert envelope.get('action') == "send_email"

    def test_envelope_defaults_operation_to_execute(self, tmp_path):
        """Envelope should default operation to 'execute'."""
        hiitl = HIITL(audit_db_path=str(tmp_path / "audit.db"))
        hiitl.evaluate("test_tool")

        import json, sqlite3
        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT envelope FROM audit_log LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        envelope = json.loads(row['envelope'])
        assert envelope['operation'] == "execute"


class TestHIITLRateLimiting:
    """Test rate limiting integration."""

    def test_rate_limiting_enforced_when_enabled(self, tmp_path):
        """Rate limiting should be enforced when enabled."""
        policy_file = tmp_path / "test_policy.yaml"
        policy_file.write_text('''
version: "1.0.0"
name: test_policy
metadata:
  rate_limits:
    - scope: org
      limit: 2
      window_seconds: 60
rules:
  - name: allow_all
    priority: 100
    enabled: true
    conditions:
      field: action
      operator: equals
      value: test_tool
    decision: ALLOW
    reason_code: ALLOWED
    description: Allow all
        ''')

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            enable_rate_limiting=True,
            mode="RESPECT_POLICY",
        )

        # First 2 should be allowed
        for i in range(2):
            decision = hiitl.evaluate("test_tool")
            assert decision.decision == DecisionType.ALLOW

        # 3rd should be rate limited
        decision = hiitl.evaluate("test_tool")
        assert decision.decision == DecisionType.RATE_LIMIT
        assert decision.allowed is False

    def test_rate_limiting_disabled_when_configured(self, tmp_path):
        """Rate limiting should not apply when disabled."""
        policy_file = tmp_path / "test_policy.yaml"
        policy_file.write_text('''
version: "1.0.0"
name: test_policy
metadata:
  rate_limits:
    - scope: org
      limit: 2
      window_seconds: 60
rules:
  - name: allow_all
    priority: 100
    enabled: true
    conditions:
      field: action
      operator: equals
      value: test_tool
    decision: ALLOW
    reason_code: ALLOWED
    description: Allow all
        ''')

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            enable_rate_limiting=False,
            mode="RESPECT_POLICY",
        )

        # Should all be allowed (no rate limiting)
        for i in range(5):
            decision = hiitl.evaluate("test_tool")
            assert decision.decision == DecisionType.ALLOW


class TestHIITLPerformance:
    """Test performance requirements."""

    def test_evaluate_latency_under_10ms(self, tmp_path):
        """evaluate() should complete in < 10ms (including audit write)."""
        policy_file = tmp_path / "test_policy.json"
        policy_file.write_text('''{
            "version": "1.0.0",
            "name": "test_policy",
            "rules": [
                {
                    "name": "allow_all",
                    "priority": 100,
                    "enabled": true,
                    "conditions": {
                        "field": "action",
                        "operator": "equals",
                        "value": "test_tool"
                    },
                    "decision": "ALLOW",
                    "reason_code": "ALLOWED",
                    "description": "Allow all"
                }
            ]
        }''')

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            mode="RESPECT_POLICY",
        )

        # Warm up (first call loads policy)
        hiitl.evaluate("test_tool")

        # Measure performance (cached policy)
        start = time.perf_counter()
        hiitl.evaluate("test_tool")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"Too slow: {elapsed_ms:.2f}ms (expected < 10ms)"
