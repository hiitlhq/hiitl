"""Tests for SDK configuration."""

import pytest
from pydantic import ValidationError

from hiitl.core.types import Environment
from hiitl.sdk.config import LocalModeConfig


class TestLocalModeConfig:
    """Test LocalModeConfig validation and defaults."""

    def test_valid_config(self):
        """Valid configuration should succeed."""
        config = LocalModeConfig(
            environment="dev",
            agent_id="test-agent",
            org_id="org_mycompany123456789",
            policy_path="./policy.yaml",
        )

        assert config.environment == Environment.DEV
        assert config.agent_id == "test-agent"
        assert config.org_id == "org_mycompany123456789"
        assert config.policy_path == "./policy.yaml"
        assert config.audit_db_path == "./hiitl_audit.db"  # Default
        assert config.enable_rate_limiting is True  # Default
        assert config.signature_key is None  # Default
        assert config.api_key is None  # Default

    def test_environment_enum_validation(self):
        """Environment must be valid enum value."""
        # Valid environments
        for env in ["dev", "stage", "prod"]:
            config = LocalModeConfig(
                environment=env,
                agent_id="test-agent",
                org_id="org_mycompany123456789",
                policy_path="./policy.yaml",
            )
            assert config.environment in [Environment.DEV, Environment.STAGE, Environment.PROD]

        # Invalid environment
        with pytest.raises(ValidationError) as exc_info:
            LocalModeConfig(
                environment="production",  # Invalid: should be "prod"
                agent_id="test-agent",
                org_id="org_mycompany123456789",
                policy_path="./policy.yaml",
            )
        assert "environment" in str(exc_info.value).lower()

    def test_org_id_pattern_validation(self):
        """org_id must match pattern org_[a-z0-9]{18,}."""
        # Valid org_ids
        valid_org_ids = [
            "org_mycompany123456789",
            "org_test000000000000000",
            "org_abc123def456ghi789",
            "org_" + "x" * 18,  # Exactly 18 chars
            "org_" + "y" * 100,  # Much longer
        ]

        for org_id in valid_org_ids:
            config = LocalModeConfig(
                environment="dev",
                agent_id="test-agent",
                org_id=org_id,
                policy_path="./policy.yaml",
            )
            assert config.org_id == org_id

        # Invalid org_ids
        invalid_org_ids = [
            "org_short",  # Too short (< 18 chars)
            "org_",  # No chars after prefix
            "mycompany12345678",  # Missing org_ prefix
            "ORG_UPPERCASE00000000",  # Uppercase not allowed
            "org_has-dashes-000000",  # Dashes not allowed
            "org_has_underscores00",  # Underscores not allowed (except prefix)
        ]

        for org_id in invalid_org_ids:
            with pytest.raises(ValidationError) as exc_info:
                LocalModeConfig(
                    environment="dev",
                    agent_id="test-agent",
                    org_id=org_id,
                    policy_path="./policy.yaml",
                )
            error_msg = str(exc_info.value)
            assert "org_id" in error_msg or "pattern" in error_msg.lower()

    def test_api_key_stored(self):
        """api_key should be stored when provided."""
        config = LocalModeConfig(
            environment="dev",
            agent_id="test-agent",
            org_id="org_mycompany123456789",
            policy_path="./policy.yaml",
            api_key="sk_test_abc123456789",
        )
        assert config.api_key == "sk_test_abc123456789"

    def test_missing_required_fields(self):
        """Missing required fields should raise ValidationError."""
        # Missing environment
        with pytest.raises(ValidationError) as exc_info:
            LocalModeConfig(
                agent_id="test-agent",
                org_id="org_mycompany123456789",
                policy_path="./policy.yaml",
            )
        assert "environment" in str(exc_info.value).lower()

        # Missing agent_id
        with pytest.raises(ValidationError) as exc_info:
            LocalModeConfig(
                environment="dev",
                org_id="org_mycompany123456789",
                policy_path="./policy.yaml",
            )
        assert "agent_id" in str(exc_info.value).lower()

        # Missing org_id
        with pytest.raises(ValidationError) as exc_info:
            LocalModeConfig(
                environment="dev",
                agent_id="test-agent",
                policy_path="./policy.yaml",
            )
        assert "org_id" in str(exc_info.value).lower()

        # policy_path is optional (zero-config: OBSERVE_ALL without policies)
        config = LocalModeConfig(
            environment="dev",
            agent_id="test-agent",
            org_id="org_mycompany123456789",
        )
        assert config.policy_path is None

    def test_optional_fields_with_defaults(self):
        """Optional fields should have correct defaults."""
        config = LocalModeConfig(
            environment="dev",
            agent_id="test-agent",
            org_id="org_mycompany123456789",
            policy_path="./policy.yaml",
        )

        assert config.audit_db_path == "./hiitl_audit.db"
        assert config.enable_rate_limiting is True
        assert config.signature_key is None
        assert config.api_key is None

    def test_optional_fields_can_be_overridden(self):
        """Optional fields can be overridden from defaults."""
        config = LocalModeConfig(
            environment="dev",
            agent_id="test-agent",
            org_id="org_mycompany123456789",
            policy_path="./policy.yaml",
            audit_db_path="/var/log/hiitl/audit.db",
            enable_rate_limiting=False,
            signature_key="my-secret-key-for-testing",
        )

        assert config.audit_db_path == "/var/log/hiitl/audit.db"
        assert config.enable_rate_limiting is False
        assert config.signature_key == "my-secret-key-for-testing"

    def test_helpful_error_messages(self):
        """Error messages should be helpful and point to documentation."""
        # Invalid org_id should have helpful message
        with pytest.raises(ValidationError) as exc_info:
            LocalModeConfig(
                environment="dev",
                agent_id="test-agent",
                org_id="org_short",
                policy_path="./policy.yaml",
            )
        error_msg = str(exc_info.value)
        assert "org_" in error_msg
        assert "18" in error_msg  # Mentions length requirement
        assert "example" in error_msg.lower() or "mycompany" in error_msg
