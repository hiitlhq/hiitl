"""Tests for hosted mode SDK functionality.

Tests cover:
- HostedModeConfig validation
- HIITL client in hosted mode initialization
- HTTP client request/response handling
- Retry logic on transient failures
- Error handling (server errors, network errors)
- Escalation fields in response
- Context manager support
"""

import json

import httpx
import pytest

from hiitl.core.types import DecisionType
from hiitl.sdk.client import HIITL
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import (
    ConfigurationError,
    NetworkError,
    ServerError,
)
from hiitl.sdk.http_client import HostedClient, _backoff_delay


# -- Shared test constants --

TEST_ORG_ID = "org_test000000000000000"
TEST_SERVER_URL = "https://ecp.example.com"
TEST_API_KEY = "sk_test_1234567890abcdef"
TEST_AGENT_ID = "test-agent"

ALLOW_RESPONSE = {
    "decision": "ALLOW",
    "allowed": True,
    "reason_codes": ["DEFAULT_ALLOW"],
    "policy_version": "v1.0.0",
    "timing": {"total_ms": 2.5},
    "envelope_hash": "a" * 64,
}

BLOCK_RESPONSE = {
    "decision": "BLOCK",
    "allowed": False,
    "reason_codes": ["PAYMENT_TOO_HIGH"],
    "policy_version": "v1.0.0",
    "timing": {"total_ms": 1.8},
    "envelope_hash": "b" * 64,
}

ESCALATION_RESPONSE = {
    "decision": "REQUIRE_APPROVAL",
    "allowed": False,
    "reason_codes": ["NEEDS_APPROVAL"],
    "policy_version": "v1.0.0",
    "timing": {"total_ms": 3.1},
    "envelope_hash": "c" * 64,
    "resume_token": "rt_test123",
    "route_ref": "high-value-payment-review",
    "escalation_context": {
        "description": "High-value payment requires manager approval",
        "response_schema": {"type": "object"},
        "routing": {"strategy": "round_robin"},
    },
}


# -- HostedModeConfig Tests --


class TestHostedModeConfig:
    def test_valid_config(self):
        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        )
        assert config.server_url == TEST_SERVER_URL
        assert config.timeout == 5.0
        assert config.max_retries == 3

    def test_server_url_trailing_slash_stripped(self):
        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url="https://ecp.example.com/",
        )
        assert config.server_url == "https://ecp.example.com"

    def test_invalid_server_url(self):
        with pytest.raises(Exception, match="Must start with"):
            HostedModeConfig(
                environment="dev",
                agent_id=TEST_AGENT_ID,
                org_id=TEST_ORG_ID,
                api_key=TEST_API_KEY,
                server_url="not-a-url",
            )

    def test_short_api_key_rejected(self):
        with pytest.raises(Exception, match="too short"):
            HostedModeConfig(
                environment="dev",
                agent_id=TEST_AGENT_ID,
                org_id=TEST_ORG_ID,
                api_key="short",
                server_url=TEST_SERVER_URL,
            )

    def test_invalid_org_id(self):
        with pytest.raises(Exception, match="Invalid org_id"):
            HostedModeConfig(
                environment="dev",
                agent_id=TEST_AGENT_ID,
                org_id="bad_org",
                api_key=TEST_API_KEY,
                server_url=TEST_SERVER_URL,
            )

    def test_custom_timeout_and_retries(self):
        config = HostedModeConfig(
            environment="prod",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            timeout=10.0,
            max_retries=5,
        )
        assert config.timeout == 10.0
        assert config.max_retries == 5


# -- HIITL Client Hosted Mode Init Tests --


class TestHIITLHostedInit:
    def test_hosted_mode_init(self):
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        )
        assert hiitl.mode == "hosted"
        assert isinstance(hiitl.config, HostedModeConfig)
        hiitl.close()

    def test_local_mode_missing_policy_path_respect_policy(self):
        """RESPECT_POLICY mode without policy_path -> ConfigurationError."""
        with pytest.raises(ConfigurationError, match="policy_path is required"):
            HIITL(
                environment="dev",
                agent_id=TEST_AGENT_ID,
                org_id=TEST_ORG_ID,
                mode="RESPECT_POLICY",
            )

    def test_local_mode_zero_config_works(self, tmp_path):
        """OBSERVE_ALL (default) without policy_path should work."""
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            audit_db_path=str(tmp_path / "audit.db"),
        )
        assert hiitl.mode == "local"

    def test_auto_detect_hosted(self):
        """api_key + server_url -> hosted mode."""
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        )
        assert hiitl.mode == "hosted"
        hiitl.close()

    def test_auto_detect_hybrid(self, tmp_path):
        """api_key without server_url -> hybrid mode."""
        policy_file = tmp_path / "policy.json"
        policy_file.write_text('{"version":"1.0.0","name":"test","rules":[]}')
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            policy_path=str(policy_file),
            audit_db_path=str(tmp_path / "audit.db"),
        )
        assert hiitl.mode == "hybrid"

    def test_auto_detect_local(self, tmp_path):
        """No api_key -> local mode."""
        policy_file = tmp_path / "policy.json"
        policy_file.write_text('{"version":"1.0.0","name":"test","rules":[]}')
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            policy_path=str(policy_file),
            audit_db_path=str(tmp_path / "audit.db"),
        )
        assert hiitl.mode == "local"

    def test_sync_false_forces_local(self, tmp_path):
        """sync=False with api_key -> local mode."""
        policy_file = tmp_path / "policy.json"
        policy_file.write_text('{"version":"1.0.0","name":"test","rules":[]}')
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            policy_path=str(policy_file),
            audit_db_path=str(tmp_path / "audit.db"),
            sync=False,
        )
        assert hiitl.mode == "local"

    def test_context_manager(self):
        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        ) as hiitl:
            assert hiitl.mode == "hosted"


# -- HTTP Client Tests (with httpx mocking) --


class TestHostedClientEvaluate:
    """Test HostedClient.evaluate() with mocked HTTP responses."""

    def _make_client(self, **overrides) -> HostedClient:
        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            **overrides,
        )
        return HostedClient(config)

    def test_allow_decision(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        decision = client.evaluate(
            action="read_file",
            operation="read",
            target={"path": "/tmp/test"},
            parameters={},
        )

        assert decision.decision == DecisionType.ALLOW
        assert decision.allowed is True
        assert "DEFAULT_ALLOW" in decision.reason_codes
        assert decision.policy_version == "v1.0.0"
        assert decision.envelope_hash == "a" * 64
        client.close()

    def test_block_decision(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=BLOCK_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        decision = client.evaluate(
            action="process_payment",
            operation="execute",
            target={"account_id": "acct_123"},
            parameters={"amount": 10000},
        )

        assert decision.decision == DecisionType.BLOCK
        assert decision.allowed is False
        assert "PAYMENT_TOO_HIGH" in decision.reason_codes
        client.close()

    def test_escalation_decision(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ESCALATION_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        decision = client.evaluate(
            action="process_payment",
            operation="execute",
            target={"account_id": "acct_123"},
            parameters={"amount": 5000},
        )

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.allowed is False
        assert decision.resume_token == "rt_test123"
        assert decision.route_ref == "high-value-payment-review"
        assert decision.escalation_context is not None
        assert "description" in decision.escalation_context
        client.close()

    def test_request_includes_bearer_auth(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        client.evaluate(
            action="test_tool",
            operation="read",
            target={},
            parameters={},
        )

        request = httpx_mock.get_request()
        assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
        client.close()

    def test_request_body_structure(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        client.evaluate(
            action="process_payment",
            operation="execute",
            target={"account_id": "acct_123"},
            parameters={"amount": 100},
            user_id="user_42",
            session_id="sess_99",
            reason="Monthly subscription",
        )

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["action"] == "process_payment"
        assert body["operation"] == "execute"
        assert body["target"] == {"account_id": "acct_123"}
        assert body["parameters"] == {"amount": 100}
        assert body["agent_id"] == TEST_AGENT_ID
        assert body["user_id"] == "user_42"
        assert body["session_id"] == "sess_99"
        assert body["reason"] == "Monthly subscription"
        client.close()

    def test_optional_fields_omitted_when_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        client.evaluate(
            action="test",
            operation="read",
            target={},
            parameters={},
        )

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert "user_id" not in body
        assert "session_id" not in body
        assert "reason" not in body
        assert "sensitivity" not in body
        assert "cost_estimate" not in body
        client.close()

    def test_sensitivity_enum_serialized(self, httpx_mock):
        from hiitl.core.types import Sensitivity

        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client()
        client.evaluate(
            action="test",
            operation="read",
            target={},
            parameters={},
            sensitivity=[Sensitivity.MONEY, Sensitivity.PII],
        )

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["sensitivity"] == ["money", "pii"]
        client.close()


# -- Error Handling Tests --


class TestHostedClientErrors:
    def _make_client(self, **overrides) -> HostedClient:
        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            max_retries=0,
            **overrides,
        )
        return HostedClient(config)

    def test_server_error_401(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "AUTHENTICATION_FAILED", "message": "Invalid API key"}},
            status_code=401,
        )

        client = self._make_client()
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == "AUTHENTICATION_FAILED"
        assert "Invalid API key" in exc_info.value.server_message
        client.close()

    def test_server_error_403(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "INSUFFICIENT_SCOPE", "message": "Requires evaluate scope"}},
            status_code=403,
        )

        client = self._make_client()
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == "INSUFFICIENT_SCOPE"
        client.close()

    def test_server_error_404_policy_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "POLICY_NOT_FOUND", "message": "No active policy found"}},
            status_code=404,
        )

        client = self._make_client()
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "POLICY_NOT_FOUND"
        client.close()

    def test_server_error_500(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "INTERNAL_ERROR", "message": "Database error"}},
            status_code=500,
        )

        client = self._make_client()
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 500
        client.close()

    def test_server_error_string_detail(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": "Insufficient permissions: evaluate scope required"},
            status_code=403,
        )

        client = self._make_client()
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert "Insufficient permissions" in str(exc_info.value)
        client.close()

    def test_network_error_connect_failure(self, httpx_mock):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url=f"{TEST_SERVER_URL}/v1/evaluate",
        )

        client = self._make_client()
        with pytest.raises(NetworkError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert TEST_SERVER_URL in str(exc_info.value)
        assert "Troubleshooting" in str(exc_info.value)
        client.close()


# -- Retry Tests --


class TestHostedClientRetry:
    def _make_client(self, max_retries=2) -> HostedClient:
        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            max_retries=max_retries,
        )
        return HostedClient(config)

    def test_retry_on_503(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            status_code=503,
        )
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        client = self._make_client(max_retries=1)
        decision = client.evaluate(
            action="test", operation="read", target={}, parameters={}
        )

        assert decision.allowed is True
        assert len(httpx_mock.get_requests()) == 2
        client.close()

    def test_retry_exhausted_raises_server_error(self, httpx_mock):
        for _ in range(3):
            httpx_mock.add_response(
                url=f"{TEST_SERVER_URL}/v1/evaluate",
                method="POST",
                json={"detail": {"error": "SERVICE_UNAVAILABLE", "message": "Server overloaded"}},
                status_code=503,
            )

        client = self._make_client(max_retries=2)
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 503
        assert len(httpx_mock.get_requests()) == 3
        client.close()

    def test_no_retry_on_400(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "VALIDATION_ERROR", "message": "Invalid request"}},
            status_code=400,
        )

        client = self._make_client(max_retries=2)
        with pytest.raises(ServerError) as exc_info:
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert exc_info.value.status_code == 400
        assert len(httpx_mock.get_requests()) == 1
        client.close()

    def test_no_retry_on_404(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "POLICY_NOT_FOUND", "message": "No policy"}},
            status_code=404,
        )

        client = self._make_client(max_retries=2)
        with pytest.raises(ServerError):
            client.evaluate(action="test", operation="read", target={}, parameters={})

        assert len(httpx_mock.get_requests()) == 1
        client.close()


# -- Signature Tests --


class TestHostedClientSignature:
    def test_signature_computed_when_key_provided(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            signature_key="my_secret_key",
        )
        client = HostedClient(config)
        client.evaluate(
            action="test", operation="read", target={}, parameters={}
        )

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert "envelope_signature" in body
        assert len(body["envelope_signature"]) == 64
        client.close()

    def test_no_signature_without_key(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        config = HostedModeConfig(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        )
        client = HostedClient(config)
        client.evaluate(
            action="test", operation="read", target={}, parameters={}
        )

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert "envelope_signature" not in body
        client.close()


# -- Backoff Tests --


class TestBackoffDelay:
    def test_exponential_backoff(self):
        assert _backoff_delay(0) == 0.5
        assert _backoff_delay(1) == 1.0
        assert _backoff_delay(2) == 2.0
        assert _backoff_delay(3) == 4.0

    def test_capped_at_4_seconds(self):
        assert _backoff_delay(4) == 4.0
        assert _backoff_delay(10) == 4.0


# -- Integration via HIITL class --


class TestHIITLHostedEvaluate:
    """Test evaluate() through the HIITL class (end-to-end with mocked HTTP)."""

    def test_evaluate_allow(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        ) as hiitl:
            decision = hiitl.evaluate(
                "read_file",
                operation="read",
                target={"path": "/tmp/test"},
            )

        assert decision.allowed is True
        assert decision.decision == DecisionType.ALLOW

    def test_evaluate_block(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=BLOCK_RESPONSE,
            status_code=200,
        )

        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        ) as hiitl:
            decision = hiitl.evaluate(
                "process_payment",
                operation="execute",
                target={"account_id": "acct_123"},
                parameters={"amount": 10000},
            )

        assert decision.allowed is False
        assert decision.decision == DecisionType.BLOCK

    def test_evaluate_escalation(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ESCALATION_RESPONSE,
            status_code=200,
        )

        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        ) as hiitl:
            decision = hiitl.evaluate(
                "process_payment",
                operation="execute",
                target={"account_id": "acct_123"},
                parameters={"amount": 5000},
            )

        assert decision.decision == DecisionType.REQUIRE_APPROVAL
        assert decision.resume_token == "rt_test123"
        assert decision.escalation_context is not None

    def test_evaluate_server_error_raises(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json={"detail": {"error": "POLICY_NOT_FOUND", "message": "No policy found"}},
            status_code=404,
        )

        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            max_retries=0,
        ) as hiitl:
            with pytest.raises(ServerError) as exc_info:
                hiitl.evaluate("test", operation="read")

        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "POLICY_NOT_FOUND"

    def test_mode_property(self):
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
        )
        assert hiitl.mode == "hosted"
        hiitl.close()
