"""Unit tests for Route model types.

Tests validation of Route model against docs/specs/routes.md JSON Schema.
Covers: valid construction, direction-aware validation, timing constraints,
enum validation, pattern validation, and nested sub-model validation.
"""

import pytest
from pydantic import ValidationError

from hiitl.core.route_types import Route


# ============================================================================
# Valid Route Fixtures
# ============================================================================


def _bidirectional_route(**overrides) -> dict:
    """Minimal valid bidirectional sync route."""
    base = {
        "name": "finance-review",
        "version": "v1.0.0",
        "direction": "bidirectional",
        "timing": "sync",
        "endpoint": "https://hooks.example.com/review",
        "response_schema": {
            "decision_options": ["approve", "deny"],
        },
        "sla": {
            "timeout": "4h",
            "timeout_action": "fail_closed",
        },
    }
    base.update(overrides)
    return base


def _outbound_route(**overrides) -> dict:
    """Minimal valid outbound async route."""
    base = {
        "name": "datadog-audit",
        "version": "v1.0.0",
        "direction": "outbound",
        "timing": "async",
        "endpoint": "https://intake.logs.datadoghq.com/api/v2/logs",
        "purpose": ["observability"],
    }
    base.update(overrides)
    return base


def _inbound_route(**overrides) -> dict:
    """Minimal valid inbound async route."""
    base = {
        "name": "security-signals",
        "version": "v1.0.0",
        "direction": "inbound",
        "timing": "async",
        "inbound": {
            "permissions": {
                "can_signal": True,
            }
        },
    }
    base.update(overrides)
    return base


# ============================================================================
# Valid Construction Tests
# ============================================================================


class TestValidBidirectionalRoute:
    """Test valid bidirectional sync route construction."""

    def test_minimal_bidirectional(self):
        route = Route.model_validate(_bidirectional_route())
        assert route.name == "finance-review"
        assert route.direction == "bidirectional"
        assert route.timing == "sync"
        assert route.endpoint == "https://hooks.example.com/review"
        assert route.response_schema is not None
        assert route.sla is not None

    def test_full_bidirectional(self):
        data = _bidirectional_route(
            description="Route high-value payments to finance team",
            purpose=["review"],
            scope={"org_id": "org_acmecorp12345678", "environment": "prod"},
            auth={
                "type": "hmac_sha256",
                "secret_ref": "env:WEBHOOK_SECRET",
            },
            protocol="webhook",
            context={
                "fields": [
                    {"field_path": "parameters.amount", "label": "Amount", "format": "currency"},
                    {"field_path": "target.account_id", "label": "Account"},
                ],
                "include_policy_ref": True,
                "risk_framing": {
                    "severity": "high",
                    "summary": "High-value payment requires approval",
                    "consequences": {
                        "if_approved": "Payment processed",
                        "if_denied": "Payment blocked",
                    },
                },
            },
            response_schema={
                "decision_options": ["approve", "deny", "modify"],
                "required_fields": ["decision"],
                "optional_fields": ["reason", "notes"],
                "reason_required_for": ["deny"],
            },
            sla={
                "timeout": "4h",
                "timeout_action": "escalate",
            },
            escalation_ladder={
                "levels": [
                    {"level": 1, "route": "senior-finance", "after": "4h"},
                    {"level": 2, "route": "cfo-review", "after": "2h"},
                ],
                "max_escalation_depth": 2,
                "final_timeout_action": "fail_closed",
            },
            correlation={"token_field": "resume_token"},
            retry={"max_attempts": 3, "backoff": "exponential", "initial_delay_ms": 2000},
            metadata={"author": "finance@example.com", "tags": ["payments"]},
        )
        route = Route.model_validate(data)
        assert route.context.fields[0].field_path == "parameters.amount"
        assert route.context.fields[0].format == "currency"
        assert route.context.risk_framing.severity == "high"
        assert route.escalation_ladder.levels[0].route == "senior-finance"
        assert route.escalation_ladder.final_timeout_action == "fail_closed"
        assert route.correlation.token_field == "resume_token"


class TestValidOutboundRoute:
    """Test valid outbound async route construction."""

    def test_minimal_outbound(self):
        route = Route.model_validate(_outbound_route())
        assert route.name == "datadog-audit"
        assert route.direction == "outbound"
        assert route.timing == "async"
        assert route.endpoint is not None

    def test_outbound_with_queue_and_filters(self):
        data = _outbound_route(
            auth={"type": "api_key", "secret_ref": "env:DD_API_KEY", "header": "DD-API-KEY"},
            context={"fields": [{"field_path": "action_id"}, {"field_path": "agent_id"}]},
            filters={"decisions": ["ALLOW", "BLOCK"]},
            queue={"batch_size": 50, "flush_interval": "10s"},
            retry={"max_attempts": 5, "backoff": "linear", "initial_delay_ms": 500},
        )
        route = Route.model_validate(data)
        assert route.queue.batch_size == 50
        assert route.filters.decisions == ["ALLOW", "BLOCK"]


class TestValidInboundRoute:
    """Test valid inbound async route construction."""

    def test_minimal_inbound(self):
        route = Route.model_validate(_inbound_route())
        assert route.name == "security-signals"
        assert route.direction == "inbound"
        assert route.inbound.permissions.can_signal is True

    def test_inbound_with_enforce(self):
        data = _inbound_route(
            inbound={
                "permissions": {
                    "can_enforce": True,
                    "enforce_scope": ["kill_switch:agent"],
                },
                "payload_mapping": {
                    "signal_type": "$.data.alert_type",
                    "severity": "$.data.severity",
                },
            }
        )
        route = Route.model_validate(data)
        assert route.inbound.permissions.can_enforce is True
        assert route.inbound.permissions.enforce_scope == ["kill_switch:agent"]


# ============================================================================
# Direction-Aware Validation Tests
# ============================================================================


class TestOutboundValidation:
    """Test outbound direction constraints."""

    def test_outbound_requires_endpoint(self):
        data = _outbound_route()
        del data["endpoint"]
        with pytest.raises(ValidationError, match="outbound routes require 'endpoint'"):
            Route.model_validate(data)

    def test_outbound_rejects_response_schema(self):
        data = _outbound_route(response_schema={"decision_options": ["approve", "deny"]})
        with pytest.raises(ValidationError, match="outbound routes must not have 'response_schema'"):
            Route.model_validate(data)

    def test_outbound_rejects_sla(self):
        data = _outbound_route(sla={"timeout": "1h", "timeout_action": "fail_closed"})
        with pytest.raises(ValidationError, match="outbound routes must not have 'sla'"):
            Route.model_validate(data)

    def test_outbound_rejects_inbound(self):
        data = _outbound_route(inbound={"permissions": {"can_signal": True}})
        with pytest.raises(ValidationError, match="outbound routes must not have 'inbound'"):
            Route.model_validate(data)

    def test_outbound_rejects_escalation_ladder(self):
        data = _outbound_route(escalation_ladder={"levels": []})
        with pytest.raises(ValidationError, match="outbound routes must not have 'escalation_ladder'"):
            Route.model_validate(data)

    def test_outbound_rejects_correlation(self):
        data = _outbound_route(correlation={"token_field": "x"})
        with pytest.raises(ValidationError, match="outbound routes must not have 'correlation'"):
            Route.model_validate(data)


class TestBidirectionalValidation:
    """Test bidirectional direction constraints."""

    def test_bidirectional_requires_endpoint(self):
        data = _bidirectional_route()
        del data["endpoint"]
        with pytest.raises(ValidationError, match="bidirectional routes require 'endpoint'"):
            Route.model_validate(data)

    def test_bidirectional_requires_response_schema(self):
        data = _bidirectional_route()
        del data["response_schema"]
        with pytest.raises(ValidationError, match="bidirectional routes require 'response_schema'"):
            Route.model_validate(data)

    def test_bidirectional_requires_sla(self):
        data = _bidirectional_route()
        del data["sla"]
        with pytest.raises(ValidationError, match="bidirectional routes require 'sla'"):
            Route.model_validate(data)

    def test_bidirectional_requires_sync_timing(self):
        data = _bidirectional_route(timing="async")
        with pytest.raises(ValidationError, match="bidirectional routes must use timing 'sync'"):
            Route.model_validate(data)

    def test_bidirectional_rejects_inbound(self):
        data = _bidirectional_route(inbound={"permissions": {"can_signal": True}})
        with pytest.raises(ValidationError, match="bidirectional routes must not have 'inbound'"):
            Route.model_validate(data)


class TestInboundValidation:
    """Test inbound direction constraints."""

    def test_inbound_requires_inbound_field(self):
        data = _inbound_route()
        del data["inbound"]
        with pytest.raises(ValidationError, match="inbound routes require 'inbound'"):
            Route.model_validate(data)

    def test_inbound_rejects_endpoint(self):
        data = _inbound_route(endpoint="https://example.com")
        with pytest.raises(ValidationError, match="inbound routes must not have 'endpoint'"):
            Route.model_validate(data)

    def test_inbound_rejects_context(self):
        data = _inbound_route(context={"fields": [{"field_path": "x"}]})
        with pytest.raises(ValidationError, match="inbound routes must not have 'context'"):
            Route.model_validate(data)

    def test_inbound_rejects_response_schema(self):
        data = _inbound_route(response_schema={"decision_options": ["approve", "deny"]})
        with pytest.raises(ValidationError, match="inbound routes must not have 'response_schema'"):
            Route.model_validate(data)

    def test_inbound_rejects_sla(self):
        data = _inbound_route(sla={"timeout": "1h", "timeout_action": "fail_closed"})
        with pytest.raises(ValidationError, match="inbound routes must not have 'sla'"):
            Route.model_validate(data)


# ============================================================================
# Timing Constraint Tests
# ============================================================================


class TestTimingConstraints:
    """Test timing-related validation rules."""

    def test_sync_rejects_queue(self):
        data = _bidirectional_route(queue={"batch_size": 50})
        with pytest.raises(ValidationError, match="sync routes must not use 'queue'"):
            Route.model_validate(data)

    def test_async_outbound_allows_queue(self):
        data = _outbound_route(queue={"batch_size": 50, "flush_interval": "10s"})
        route = Route.model_validate(data)
        assert route.queue.batch_size == 50

    def test_outbound_sync_allowed(self):
        """Outbound sync is valid (rare but allowed per spec)."""
        data = _outbound_route(timing="sync")
        route = Route.model_validate(data)
        assert route.timing == "sync"


# ============================================================================
# Pattern Validation Tests
# ============================================================================


class TestPatternValidation:
    """Test regex pattern constraints on fields."""

    def test_invalid_name_pattern_uppercase(self):
        data = _outbound_route(name="Finance-Review")
        with pytest.raises(ValidationError, match="name"):
            Route.model_validate(data)

    def test_invalid_name_pattern_too_short(self):
        data = _outbound_route(name="ab")
        with pytest.raises(ValidationError, match="name"):
            Route.model_validate(data)

    def test_invalid_name_pattern_starts_with_hyphen(self):
        data = _outbound_route(name="-bad-name")
        with pytest.raises(ValidationError, match="name"):
            Route.model_validate(data)

    def test_invalid_version_no_v_prefix(self):
        data = _outbound_route(version="1.0.0")
        with pytest.raises(ValidationError, match="version"):
            Route.model_validate(data)

    def test_invalid_version_missing_patch(self):
        data = _outbound_route(version="v1.0")
        with pytest.raises(ValidationError, match="version"):
            Route.model_validate(data)

    def test_invalid_sla_timeout_format(self):
        data = _bidirectional_route(sla={"timeout": "4hours", "timeout_action": "fail_closed"})
        with pytest.raises(ValidationError, match="timeout"):
            Route.model_validate(data)

    def test_valid_sla_timeout_formats(self):
        for timeout in ["30s", "15m", "4h"]:
            data = _bidirectional_route(sla={"timeout": timeout, "timeout_action": "fail_closed"})
            route = Route.model_validate(data)
            assert route.sla.timeout == timeout


# ============================================================================
# Enum Validation Tests
# ============================================================================


class TestEnumValidation:
    """Test invalid enum values are rejected."""

    def test_invalid_direction(self):
        data = _outbound_route(direction="upstream")
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_timing(self):
        data = _outbound_route(timing="deferred")
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_purpose(self):
        data = _outbound_route(purpose=["monitoring"])
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_protocol(self):
        data = _outbound_route(protocol="mqtt")
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_auth_type(self):
        data = _outbound_route(auth={"type": "basic_auth", "secret_ref": "env:X"})
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_timeout_action(self):
        data = _bidirectional_route(sla={"timeout": "1h", "timeout_action": "retry"})
        with pytest.raises(ValidationError):
            Route.model_validate(data)

    def test_invalid_decision_option(self):
        data = _bidirectional_route(
            response_schema={"decision_options": ["approve", "reject"]}
        )
        with pytest.raises(ValidationError):
            Route.model_validate(data)


# ============================================================================
# Nested Sub-Model Validation Tests
# ============================================================================


class TestSubModelValidation:
    """Test validation of nested sub-models."""

    def test_response_schema_requires_min_2_options(self):
        data = _bidirectional_route(
            response_schema={"decision_options": ["approve"]}
        )
        with pytest.raises(ValidationError, match="decision_options"):
            Route.model_validate(data)

    def test_retry_max_attempts_range(self):
        data = _outbound_route(retry={"max_attempts": 15})
        with pytest.raises(ValidationError, match="max_attempts"):
            Route.model_validate(data)

    def test_retry_initial_delay_range(self):
        data = _outbound_route(retry={"initial_delay_ms": 50})
        with pytest.raises(ValidationError, match="initial_delay_ms"):
            Route.model_validate(data)

    def test_queue_batch_size_range(self):
        data = _outbound_route(queue={"batch_size": 5000})
        with pytest.raises(ValidationError, match="batch_size"):
            Route.model_validate(data)

    def test_escalation_level_must_be_positive(self):
        data = _bidirectional_route(
            escalation_ladder={"levels": [{"level": 0, "route": "next-review", "after": "1h"}]}
        )
        with pytest.raises(ValidationError, match="level"):
            Route.model_validate(data)

    def test_scope_org_id_pattern(self):
        data = _outbound_route(scope={"org_id": "bad_org"})
        with pytest.raises(ValidationError, match="org_id"):
            Route.model_validate(data)

    def test_inbound_permissions_all_false_rejected(self):
        data = _inbound_route(
            inbound={"permissions": {"can_enforce": False, "can_propose": False, "can_signal": False}}
        )
        with pytest.raises(ValidationError, match="At least one permission must be true"):
            Route.model_validate(data)

    def test_inbound_enforce_scope_requires_can_enforce(self):
        data = _inbound_route(
            inbound={"permissions": {"can_signal": True, "enforce_scope": ["kill_switch:agent"]}}
        )
        with pytest.raises(ValidationError, match="enforce_scope requires can_enforce=true"):
            Route.model_validate(data)

    def test_inbound_auto_accept_requires_can_propose(self):
        data = _inbound_route(
            inbound={
                "permissions": {"can_signal": True},
                "acceptance_mode": "auto_accept",
            }
        )
        with pytest.raises(ValidationError, match="auto_accept.*requires can_propose=true"):
            Route.model_validate(data)


# ============================================================================
# Serialization Tests
# ============================================================================


class TestSerialization:
    """Test Route model serialization to dict/JSON."""

    def test_model_dump_roundtrip(self):
        data = _bidirectional_route(
            purpose=["review"],
            context={"fields": [{"field_path": "parameters.amount", "format": "currency"}]},
        )
        route = Route.model_validate(data)
        dumped = route.model_dump()
        assert dumped["name"] == "finance-review"
        assert dumped["direction"] == "bidirectional"
        assert dumped["context"]["fields"][0]["format"] == "currency"

    def test_enum_values_are_strings(self):
        route = Route.model_validate(_outbound_route(purpose=["observability"]))
        dumped = route.model_dump()
        assert dumped["direction"] == "outbound"
        assert dumped["timing"] == "async"
        assert dumped["purpose"] == ["observability"]
