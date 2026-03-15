"""Tests for SDK exceptions."""

import pytest

from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    HIITLError,
    PolicyLoadError,
)


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_all_exceptions_inherit_from_hiitl_error(self):
        """All SDK exceptions should inherit from HIITLError."""
        exceptions = [
            PolicyLoadError,
            AuditLogError,
            ConfigurationError,
            EnvelopeValidationError,
        ]

        for exc_class in exceptions:
            assert issubclass(exc_class, HIITLError)
            assert issubclass(exc_class, Exception)

    def test_hiitl_error_is_exception(self):
        """HIITLError should inherit from Exception."""
        assert issubclass(HIITLError, Exception)

    def test_can_catch_all_sdk_errors_with_hiitl_error(self):
        """HIITLError can catch all SDK exceptions."""
        # PolicyLoadError
        with pytest.raises(HIITLError):
            raise PolicyLoadError("Policy load failed")

        # AuditLogError
        with pytest.raises(HIITLError):
            raise AuditLogError("Audit log failed")

        # ConfigurationError
        with pytest.raises(HIITLError):
            raise ConfigurationError("Config invalid")

        # EnvelopeValidationError
        with pytest.raises(HIITLError):
            raise EnvelopeValidationError("Envelope invalid", ["field error"])


class TestEnvelopeValidationError:
    """Test EnvelopeValidationError with validation_errors attribute."""

    def test_envelope_validation_error_has_validation_errors(self):
        """EnvelopeValidationError should store validation errors."""
        validation_errors = [
            "action_id: Field required",
            "timestamp: Invalid ISO 8601 format",
        ]

        exc = EnvelopeValidationError(
            "Envelope validation failed",
            validation_errors=validation_errors
        )

        assert exc.validation_errors == validation_errors
        assert str(exc) == "Envelope validation failed"

    def test_envelope_validation_error_can_be_raised_and_caught(self):
        """EnvelopeValidationError can be raised and caught."""
        validation_errors = ["field: error"]

        with pytest.raises(EnvelopeValidationError) as exc_info:
            raise EnvelopeValidationError(
                "Validation failed",
                validation_errors=validation_errors
            )

        assert exc_info.value.validation_errors == validation_errors
        assert "Validation failed" in str(exc_info.value)


class TestExceptionMessages:
    """Test that exceptions can carry helpful messages."""

    def test_policy_load_error_message(self):
        """PolicyLoadError should carry error message."""
        with pytest.raises(PolicyLoadError) as exc_info:
            raise PolicyLoadError("Failed to load policy.yaml: File not found")

        assert "policy.yaml" in str(exc_info.value)
        assert "File not found" in str(exc_info.value)

    def test_audit_log_error_message(self):
        """AuditLogError should carry error message."""
        with pytest.raises(AuditLogError) as exc_info:
            raise AuditLogError("Cannot write to audit.db: Permission denied")

        assert "audit.db" in str(exc_info.value)
        assert "Permission denied" in str(exc_info.value)

    def test_configuration_error_message(self):
        """ConfigurationError should carry error message."""
        with pytest.raises(ConfigurationError) as exc_info:
            raise ConfigurationError("Invalid org_id: too short")

        assert "org_id" in str(exc_info.value)
        assert "too short" in str(exc_info.value)
