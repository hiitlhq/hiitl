"""Tests for route config loader and escalation context resolution.

Tests RouteLoader with the new Route model types (routes.md schema)
and the updated resolve_escalation_context output format.
"""

from pathlib import Path

import pytest

from hiitl.core.route_types import Route
from hiitl.sdk.exceptions import RouteLoadError
from hiitl.sdk.route_loader import RouteLoader, resolve_escalation_context


# ============================================================================
# Valid route config fixture data (new routes.md schema)
# ============================================================================

VALID_ROUTE_YAML = """
name: "finance-review"
version: "v1.0.0"
description: "Route high-value payments to the finance team for approval"
direction: bidirectional
timing: sync
purpose:
  - review

endpoint: "https://hooks.example.com/hiitl/finance-review"
auth:
  type: hmac_sha256
  secret_ref: "env:HIITL_FINANCE_WEBHOOK_SECRET"
protocol: webhook

context:
  fields:
    - field_path: "parameters.amount"
      label: "Transaction Amount"
      format: "currency"
    - field_path: "parameters.currency"
      label: "Currency"
    - field_path: "target.account_id"
      label: "Target Account"
  include_policy_ref: true
  risk_framing:
    severity: "high"
    summary: "High-value payment requires finance team approval"
    consequences:
      if_approved: "Payment will be processed"
      if_denied: "Payment will be blocked"

response_schema:
  decision_options:
    - approve
    - deny
  required_fields:
    - decision
  reason_required_for:
    - deny

sla:
  timeout: "4h"
  timeout_action: escalate

correlation:
  token_field: "resume_token"

metadata:
  author: "finance-team@example.com"
  tags: ["payments", "high-value", "finance"]
"""

VALID_ROUTE_JSON = """{
  "name": "security-review",
  "version": "v1.0.0",
  "description": "Review for permission changes",
  "direction": "bidirectional",
  "timing": "sync",
  "purpose": ["review", "security"],
  "endpoint": "https://hooks.example.com/security",
  "auth": {
    "type": "bearer_token",
    "secret_ref": "env:SECURITY_WEBHOOK_TOKEN"
  },
  "context": {
    "fields": [
      {"field_path": "parameters.role", "label": "Requested Role"},
      {"field_path": "target.user_id", "label": "Target User"}
    ],
    "risk_framing": {
      "severity": "critical"
    }
  },
  "response_schema": {
    "decision_options": ["approve", "deny"]
  },
  "sla": {
    "timeout": "2h",
    "timeout_action": "fail_closed"
  }
}"""


class TestRouteLoaderInit:
    """Test RouteLoader initialization."""

    def test_init_stores_path(self, tmp_path):
        """Loader should store the configs directory path."""
        loader = RouteLoader(str(tmp_path))
        assert loader.configs_path == tmp_path

    def test_nonexistent_directory_returns_none(self, tmp_path):
        """get() on nonexistent directory should return None (warning, not error)."""
        loader = RouteLoader(str(tmp_path / "nonexistent"))
        result = loader.get("finance-review")
        assert result is None


class TestRouteLoaderGet:
    """Test RouteLoader.get() method."""

    def test_load_yaml_config(self, tmp_path):
        """Should load a valid YAML route config and return typed Route."""
        config_file = tmp_path / "finance-review.yaml"
        config_file.write_text(VALID_ROUTE_YAML)

        loader = RouteLoader(str(tmp_path))
        route = loader.get("finance-review")

        assert route is not None
        assert isinstance(route, Route)
        assert route.name == "finance-review"
        assert route.version == "v1.0.0"
        assert route.direction == "bidirectional"
        assert route.timing == "sync"
        assert route.sla.timeout == "4h"
        assert route.sla.timeout_action == "escalate"

    def test_load_json_config(self, tmp_path):
        """Should load a valid JSON route config and return typed Route."""
        config_file = tmp_path / "security-review.json"
        config_file.write_text(VALID_ROUTE_JSON)

        loader = RouteLoader(str(tmp_path))
        route = loader.get("security-review")

        assert route is not None
        assert isinstance(route, Route)
        assert route.name == "security-review"
        assert route.sla.timeout_action == "fail_closed"
        assert route.context.risk_framing.severity == "critical"

    def test_load_yml_extension(self, tmp_path):
        """Should support .yml extension."""
        config_file = tmp_path / "finance-review.yml"
        config_file.write_text(VALID_ROUTE_YAML)

        loader = RouteLoader(str(tmp_path))
        route = loader.get("finance-review")

        assert route is not None
        assert route.name == "finance-review"

    def test_missing_config_returns_none(self, tmp_path):
        """get() for nonexistent config name should return None."""
        loader = RouteLoader(str(tmp_path))
        result = loader.get("nonexistent-config")
        assert result is None

    def test_yaml_preferred_over_json(self, tmp_path):
        """When both .yaml and .json exist, .yaml is tried first."""
        yaml_file = tmp_path / "finance-review.yaml"
        yaml_file.write_text(VALID_ROUTE_YAML)

        json_content = VALID_ROUTE_JSON.replace("security-review", "finance-review")
        json_file = tmp_path / "finance-review.json"
        json_file.write_text(json_content)

        loader = RouteLoader(str(tmp_path))
        route = loader.get("finance-review")

        # Should load YAML (tried first)
        assert route is not None
        assert route.name == "finance-review"
        assert "high-value payments" in route.description


class TestRouteLoaderCaching:
    """Test mtime-based caching."""

    def test_cached_on_second_call(self, tmp_path):
        """Second get() should return cached Route object."""
        config_file = tmp_path / "finance-review.yaml"
        config_file.write_text(VALID_ROUTE_YAML)

        loader = RouteLoader(str(tmp_path))
        route1 = loader.get("finance-review")
        route2 = loader.get("finance-review")

        assert route1 is route2  # Same object (cached)

    def test_invalidate_cache(self, tmp_path):
        """invalidate_cache() should force reload on next get()."""
        config_file = tmp_path / "finance-review.yaml"
        config_file.write_text(VALID_ROUTE_YAML)

        loader = RouteLoader(str(tmp_path))
        route1 = loader.get("finance-review")
        loader.invalidate_cache()
        route2 = loader.get("finance-review")

        # After invalidation, should reload (different object)
        assert route1 is not route2
        assert route1.name == route2.name


class TestRouteLoaderValidation:
    """Test route config validation via Pydantic Route model."""

    def test_missing_required_direction_field(self, tmp_path):
        """Config missing 'direction' should raise RouteLoadError."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
timing: async
endpoint: "https://example.com"
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="validation failed"):
            loader.get("bad-config")

    def test_bidirectional_missing_response_schema(self, tmp_path):
        """Bidirectional route without response_schema should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
direction: bidirectional
timing: sync
endpoint: "https://example.com"
sla:
  timeout: "1h"
  timeout_action: fail_closed
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="response_schema"):
            loader.get("bad-config")

    def test_bidirectional_missing_sla(self, tmp_path):
        """Bidirectional route without sla should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
direction: bidirectional
timing: sync
endpoint: "https://example.com"
response_schema:
  decision_options: ["approve", "deny"]
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="sla"):
            loader.get("bad-config")

    def test_outbound_missing_endpoint(self, tmp_path):
        """Outbound route without endpoint should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
direction: outbound
timing: async
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="endpoint"):
            loader.get("bad-config")

    def test_fewer_than_two_decision_options(self, tmp_path):
        """decision_options with < 2 entries should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
direction: bidirectional
timing: sync
endpoint: "https://example.com"
response_schema:
  decision_options: ["approve"]
sla:
  timeout: "1h"
  timeout_action: fail_closed
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="decision_options"):
            loader.get("bad-config")

    def test_invalid_version_format(self, tmp_path):
        """Version not matching semver pattern should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "1.0"
direction: outbound
timing: async
endpoint: "https://example.com"
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="validation failed"):
            loader.get("bad-config")

    def test_invalid_sla_timeout_format(self, tmp_path):
        """Invalid timeout duration string should fail."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text("""
name: "bad-config"
version: "v1.0.0"
direction: bidirectional
timing: sync
endpoint: "https://example.com"
response_schema:
  decision_options: ["approve", "deny"]
sla:
  timeout: "4hours"
  timeout_action: fail_closed
""")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="validation failed"):
            loader.get("bad-config")

    def test_name_mismatch_raises_error(self, tmp_path):
        """Config name not matching filename should raise error."""
        config_file = tmp_path / "finance-review.yaml"
        config_file.write_text(VALID_ROUTE_YAML.replace(
            'name: "finance-review"', 'name: "wrong-name"'
        ))

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="mismatch"):
            loader.get("finance-review")

    def test_invalid_json_raises_error(self, tmp_path):
        """Invalid JSON should raise RouteLoadError."""
        config_file = tmp_path / "bad-config.json"
        config_file.write_text("{ invalid json }")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="(?i)invalid json"):
            loader.get("bad-config")

    def test_invalid_yaml_raises_error(self, tmp_path):
        """Invalid YAML should raise RouteLoadError."""
        config_file = tmp_path / "bad-config.yaml"
        config_file.write_text(":\n  bad:\n    yaml: [\n")

        loader = RouteLoader(str(tmp_path))
        with pytest.raises(RouteLoadError, match="(?i)invalid yaml"):
            loader.get("bad-config")


class TestResolveEscalationContext:
    """Test resolve_escalation_context() function with typed Route model."""

    def _make_route(self, **overrides) -> Route:
        """Create a valid bidirectional Route for testing."""
        data = {
            "name": "test-route",
            "version": "v1.0.0",
            "direction": "bidirectional",
            "timing": "sync",
            "endpoint": "https://hooks.example.com/test",
            "response_schema": {"decision_options": ["approve", "deny"]},
            "sla": {"timeout": "4h", "timeout_action": "escalate"},
        }
        data.update(overrides)
        return Route.model_validate(data)

    def test_resolves_basic_fields(self):
        """Should extract endpoint, protocol, SLA, and decision_options."""
        route = self._make_route()
        context = resolve_escalation_context(route)

        assert context["endpoint"] == "https://hooks.example.com/test"
        assert context["protocol"] == "webhook"
        assert context["timeout"] == "4h"
        assert context["timeout_action"] == "escalate"
        assert context["decision_options"] == ["approve", "deny"]

    def test_resolves_context_fields(self):
        """Should include context.fields array."""
        route = self._make_route(
            context={
                "fields": [
                    {"field_path": "parameters.amount", "label": "Amount", "format": "currency"},
                    {"field_path": "target.account_id", "label": "Account"},
                ],
            }
        )
        context = resolve_escalation_context(route)

        assert len(context["fields"]) == 2
        assert context["fields"][0]["field_path"] == "parameters.amount"
        assert context["fields"][0]["format"] == "currency"
        assert context["fields"][1]["label"] == "Account"

    def test_resolves_risk_framing(self):
        """Should include severity and summary from risk_framing."""
        route = self._make_route(
            context={
                "risk_framing": {
                    "severity": "high",
                    "summary": "Needs approval",
                },
            }
        )
        context = resolve_escalation_context(route)

        assert context["severity"] == "high"
        assert context["summary"] == "Needs approval"

    def test_resolves_without_risk_framing(self):
        """Should work when risk_framing is not present."""
        route = self._make_route()
        context = resolve_escalation_context(route)

        assert "severity" not in context
        assert "summary" not in context

    def test_resolves_escalation_ladder(self):
        """Should include escalation_ladder if present."""
        route = self._make_route(
            escalation_ladder={
                "levels": [
                    {"level": 1, "route": "senior-review", "after": "2h"},
                ],
                "max_escalation_depth": 1,
                "final_timeout_action": "fail_closed",
            }
        )
        context = resolve_escalation_context(route)

        assert "escalation_ladder" in context
        assert context["escalation_ladder"]["levels"][0]["route"] == "senior-review"
        assert context["escalation_ladder"]["final_timeout_action"] == "fail_closed"

    def test_resolves_correlation(self):
        """Should include token_field from correlation."""
        route = self._make_route(correlation={"token_field": "resume_token"})
        context = resolve_escalation_context(route)

        assert context["token_field"] == "resume_token"


class TestClientEscalationIntegration:
    """Test HIITL client escalation flow end-to-end."""

    @pytest.fixture
    def escalation_setup(self, tmp_path):
        """Create policy + route config for escalation testing."""
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("""
version: "1.0.0"
name: test_policy
rules:
  - name: approve_large_payments
    priority: 100
    enabled: true
    conditions:
      field: parameters.amount
      operator: greater_than
      value: 1000
    decision: REQUIRE_APPROVAL
    reason_code: LARGE_PAYMENT
    route: "finance-review"
    description: Large payments require approval
  - name: allow_small_payments
    priority: 50
    enabled: true
    conditions:
      field: parameters.amount
      operator: less_than_or_equal
      value: 1000
    decision: ALLOW
    reason_code: SMALL_PAYMENT
    description: Small payments allowed
""")

        routes_dir = tmp_path / "routes"
        routes_dir.mkdir()

        finance_config = routes_dir / "finance-review.yaml"
        finance_config.write_text(VALID_ROUTE_YAML)

        return {
            "policy_path": str(policy_file),
            "routes_path": str(routes_dir),
            "audit_db_path": str(tmp_path / "audit.db"),
        }

    def test_escalation_resolves_context(self, escalation_setup):
        """REQUIRE_APPROVAL with route should populate escalation_context."""
        from hiitl.sdk.client import HIITL
        from hiitl.core.types import DecisionType

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            org_id="org_test000000000000000",
            mode="RESPECT_POLICY",
            **escalation_setup,
        )

        decision = hiitl.evaluate(
            action="payment_transfer",
            operation="execute",
            target={"account": "dest123"},
            parameters={"amount": 5000, "currency": "USD"},
        )

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.allowed is False
        assert decision.resume_token is not None
        assert decision.resume_token.startswith("rtk_")
        assert decision.route_ref == "finance-review"

        # escalation_context should be populated with new field names
        assert decision.escalation_context is not None
        ctx = decision.escalation_context
        assert ctx["timeout"] == "4h"
        assert ctx["timeout_action"] == "escalate"
        assert ctx["decision_options"] == ["approve", "deny"]
        assert ctx["endpoint"] == "https://hooks.example.com/hiitl/finance-review"
        assert ctx["protocol"] == "webhook"
        assert len(ctx["fields"]) == 3
        assert ctx["fields"][0]["field_path"] == "parameters.amount"
        assert ctx["severity"] == "high"
        assert ctx["summary"] == "High-value payment requires finance team approval"

    def test_non_escalation_no_context(self, escalation_setup):
        """ALLOW decision should NOT have escalation_context."""
        from hiitl.sdk.client import HIITL
        from hiitl.core.types import DecisionType

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            org_id="org_test000000000000000",
            mode="RESPECT_POLICY",
            **escalation_setup,
        )

        decision = hiitl.evaluate(
            action="payment_transfer",
            operation="execute",
            target={"account": "dest123"},
            parameters={"amount": 100, "currency": "USD"},
        )

        assert decision.decision == DecisionType.ALLOW
        assert decision.allowed is True
        assert decision.resume_token is None
        assert decision.escalation_context is None

    def test_escalation_without_routes_path(self, tmp_path):
        """Escalation without routes_path should still work (no context)."""
        from hiitl.sdk.client import HIITL
        from hiitl.core.types import DecisionType

        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("""
version: "1.0.0"
name: test_policy
rules:
  - name: approve_all
    priority: 100
    enabled: true
    conditions:
      field: action
      operator: equals
      value: "dangerous_tool"
    decision: REQUIRE_APPROVAL
    reason_code: NEEDS_APPROVAL
    route: "some-config"
    description: Needs approval
""")

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            mode="RESPECT_POLICY",
        )

        decision = hiitl.evaluate(
            action="dangerous_tool",
            operation="execute",
            target={},
            parameters={},
        )

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.resume_token is not None
        assert decision.route_ref == "some-config"
        assert decision.escalation_context is None

    def test_escalation_missing_route_config_file(self, tmp_path):
        """Escalation referencing nonexistent route config should warn, not error."""
        from hiitl.sdk.client import HIITL
        from hiitl.core.types import DecisionType

        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("""
version: "1.0.0"
name: test_policy
rules:
  - name: approve_all
    priority: 100
    enabled: true
    conditions:
      field: action
      operator: equals
      value: "dangerous_tool"
    decision: REQUIRE_APPROVAL
    reason_code: NEEDS_APPROVAL
    route: "nonexistent-config"
    description: Needs approval
""")

        routes_dir = tmp_path / "routes"
        routes_dir.mkdir()

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            policy_path=str(policy_file),
            org_id="org_test000000000000000",
            audit_db_path=str(tmp_path / "audit.db"),
            routes_path=str(routes_dir),
            mode="RESPECT_POLICY",
        )

        decision = hiitl.evaluate(
            action="dangerous_tool",
            operation="execute",
            target={},
            parameters={},
        )

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.resume_token is not None
        assert decision.route_ref == "nonexistent-config"
        assert decision.escalation_context is None

    def test_escalation_audit_record_written(self, escalation_setup, tmp_path):
        """Escalation decisions should be written to audit log."""
        from hiitl.sdk.client import HIITL
        import sqlite3
        import json

        hiitl = HIITL(
            environment="dev",
            agent_id="test-agent",
            org_id="org_test000000000000000",
            mode="RESPECT_POLICY",
            **escalation_setup,
        )

        decision = hiitl.evaluate(
            action="payment_transfer",
            operation="execute",
            target={"account": "dest123"},
            parameters={"amount": 5000},
        )

        conn = sqlite3.connect(escalation_setup["audit_db_path"])
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        decision_data = json.loads(row["decision"])
        assert decision_data["decision"] == "REQUIRE_APPROVAL"
        assert decision_data["resume_token"] is not None
        assert decision_data["route_ref"] == "finance-review"
