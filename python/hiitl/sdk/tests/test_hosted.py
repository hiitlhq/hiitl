"""Tests for hosted mode SDK functionality.

Tests cover:
- HostedModeConfig validation
- HIITL client in hosted mode initialization
- HTTP client request/response handling
- Retry logic on transient failures
- Error handling (server errors; an unreachable service is CONTROL_PLANE_UNAVAILABLE, row 174)
- Escalation fields in response
- Context manager support
- The body is the signed envelope (row 134): hosted mode needs the signing secret
"""

import json

import httpx
import pytest

from hiitl.core.canonical import envelope_signature, envelope_verifies
from hiitl.core.types import DecisionType, ENVELOPE_SCHEMA_VERSION
from hiitl.sdk.client import HIITL
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import (
    ConfigurationError,
    ServerError,
)
from hiitl.sdk.http_client import HostedClient, _backoff_delay


# -- Shared test constants --

TEST_ORG_ID = "org_test000000000000000"
TEST_SERVER_URL = "https://ecp.example.com"
TEST_API_KEY = "sk_test_1234567890abcdef"
TEST_AGENT_ID = "test-agent"
TEST_SIGNING_SECRET = "test-signing-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _store_in_tmp(monkeypatch, tmp_path):
    """An outage is recorded at `audit_db_path` and pushed before the next call (HTL-23 row 192), whose default is in
    the working directory: each test's is its own, so one test's outage is never another's push."""
    monkeypatch.chdir(tmp_path)


def _envelope(**fields) -> dict:
    """A signed envelope as HIITL._build_envelope records it (the HostedClient's input)."""
    env = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "org_id": TEST_ORG_ID, "environment": "dev", "agent_id": TEST_AGENT_ID,
        "action_id": "act_0123456789abcdefghij", "idempotency_key": "idem_test", "action": "test",
        "operation": "read", "timestamp": "2026-11-04T12:00:00Z", "target": {}, "parameters": {},
        "signature_version": "hmac-sha256-v1", **fields,
    }
    env["signature"] = envelope_signature(TEST_SIGNING_SECRET, env)
    return env

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
        with pytest.raises(Exception, match=r"server_url \(HIITL_SERVER_URL\) is 'not-a-url'\. hiitl sends only to an https URL"):
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
    # Hosted mode (evaluation="remote") is the EXPLICIT opt-in path for
    # network-only evaluation. Without `evaluation="remote"`, providing
    # `api_key` alone yields hybrid mode (local eval + background sync) —
    # see `test_auto_detect_hybrid` below. These tests pin the hosted
    # behavior specifically.

    def test_hosted_mode_init(self):
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
        try:
            assert hiitl.mode == "local"
        finally:
            hiitl.close()

    def test_evaluation_remote_yields_hosted_mode(self):
        """api_key + server_url + evaluation='remote' -> hosted mode.

        Renamed from `test_auto_detect_hosted` — hosted mode is no longer
        auto-detected from server_url presence; it requires an explicit
        opt-in via `evaluation="remote"`. The implicit path (api_key
        alone) is now hybrid mode (see next test).
        """
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
        )
        assert hiitl.mode == "hosted"
        hiitl.close()

    def test_auto_detect_hybrid(self, tmp_path):
        """api_key without server_url -> hybrid mode.

        IMPORTANT: hybrid mode spawns a background sync engine. The
        `try/finally hiitl.close()` is load-bearing for test isolation —
        without it, the sync engine's retry loop continues across test
        boundaries and makes spurious HTTP requests that pollute later
        httpx_mock-based tests (notably TestHostedClientRetry, which
        asserts on exact request counts).
        """
        policy_file = tmp_path / "policy.json"
        policy_file.write_text('{"version":"v1.0.0","name":"test","description":"No rules","scope":{"org_id":"org_test000000000000000","environment":"dev"},"rules":[]}')
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            policy_path=str(policy_file),
            audit_db_path=str(tmp_path / "audit.db"),
        )
        try:
            assert hiitl.mode == "hybrid"
        finally:
            hiitl.close()

    def test_auto_detect_local(self, tmp_path):
        """No api_key -> local mode."""
        policy_file = tmp_path / "policy.json"
        policy_file.write_text('{"version":"v1.0.0","name":"test","description":"No rules","scope":{"org_id":"org_test000000000000000","environment":"dev"},"rules":[]}')
        hiitl = HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            policy_path=str(policy_file),
            audit_db_path=str(tmp_path / "audit.db"),
        )
        try:
            assert hiitl.mode == "local"
        finally:
            hiitl.close()

    # NOTE: `test_sync_false_forces_local` was deleted. The original test
    # passed `sync=False` to the HIITL constructor expecting hybrid →
    # local downgrade behavior. That parameter was never implemented;
    # the test errored out with TypeError. If "API key present but sync
    # disabled = pure local mode" becomes a real product need, design
    # and add the parameter intentionally (and re-add a test against
    # the actual feature). For now, the path to local mode is "don't
    # pass an api_key".

    def test_hosted_mode_without_the_signing_secret_is_a_configuration_error(self, monkeypatch):
        """Every key holds a signing secret and the service refuses an unsigned envelope (row 134): hosted mode
        refuses to start without it, naming where the secret is shown."""
        monkeypatch.delenv("HIITL_SIGNATURE_KEY", raising=False)
        with pytest.raises(ConfigurationError, match="signature_key") as e:
            HIITL(environment="dev", agent_id=TEST_AGENT_ID, org_id=TEST_ORG_ID, api_key=TEST_API_KEY,
                  server_url=TEST_SERVER_URL, evaluation="remote")
        assert "signing_secret" in str(e.value)

    def test_context_manager(self):
        with HIITL(
            environment="dev",
            agent_id=TEST_AGENT_ID,
            org_id=TEST_ORG_ID,
            api_key=TEST_API_KEY,
            server_url=TEST_SERVER_URL,
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
        decision = client.evaluate(_envelope(
            action="read_file", operation="read", target={"path": "/tmp/test"}, parameters={}))

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
        decision = client.evaluate(_envelope(action="process_payment", operation="execute",
                                             target={"account_id": "acct_123"}, parameters={"amount": 10000}))

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
        decision = client.evaluate(_envelope(action="process_payment", operation="execute",
                                             target={"account_id": "acct_123"}, parameters={"amount": 5000}))

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
        client.evaluate(_envelope(action="test_tool", operation="read", target={}, parameters={}))

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
        envelope = _envelope(action="process_payment", operation="execute", target={"account_id": "acct_123"},
                             parameters={"amount": 100}, user_id="user_42", session_id="sess_99",
                             reason="Monthly subscription")
        client.evaluate(envelope)

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        # The body is the envelope, its signature under envelope_signature (the security architecture §1.3)
        assert body == {**{k: v for k, v in envelope.items() if k != "signature"},
                        "envelope_signature": envelope["signature"]}
        # The version is the envelope's own signature_version; no header names it (row 171)
        assert "X-Hiitl-Signature-Version" not in request.headers
        client.close()

    def test_optional_fields_omitted_when_none(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        with HIITL(environment="dev", agent_id=TEST_AGENT_ID, org_id=TEST_ORG_ID, api_key=TEST_API_KEY,
                   server_url=TEST_SERVER_URL, evaluation="remote", signature_key=TEST_SIGNING_SECRET) as hiitl:
            hiitl.evaluate("test", operation="read")

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert "principal" not in body
        assert "user_id" not in body
        assert "session_id" not in body
        assert "reason" not in body
        assert "sensitivity" not in body
        assert "cost_estimate" not in body

    def test_sensitivity_enum_serialized(self, httpx_mock):
        from hiitl.core.types import Sensitivity

        httpx_mock.add_response(
            url=f"{TEST_SERVER_URL}/v1/evaluate",
            method="POST",
            json=ALLOW_RESPONSE,
            status_code=200,
        )

        with HIITL(environment="dev", agent_id=TEST_AGENT_ID, org_id=TEST_ORG_ID, api_key=TEST_API_KEY,
                   server_url=TEST_SERVER_URL, evaluation="remote", signature_key=TEST_SIGNING_SECRET) as hiitl:
            hiitl.evaluate("test", operation="read", sensitivity=[Sensitivity.MONEY, Sensitivity.PII])

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["sensitivity"] == ["money", "pii"]


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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

        assert "Insufficient permissions" in str(exc_info.value)
        client.close()

    def test_network_error_connect_failure(self, httpx_mock):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url=f"{TEST_SERVER_URL}/v1/evaluate",
        )

        client = self._make_client()
        decision = client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

        # An error is a decision (row 174): fail-closed, the cause logged, not put in the message.
        assert decision.decision == DecisionType.CONTROL_PLANE_UNAVAILABLE
        assert decision.allowed is False
        assert decision.reason_codes == ["CONTROL_PLANE_UNREACHABLE"]
        assert "Connection refused" not in decision.error.message
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
        decision = client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

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
            client.evaluate(_envelope(action="test", operation="read", target={}, parameters={}))

        assert len(httpx_mock.get_requests()) == 1
        client.close()


# -- Signature Tests --


class TestHostedClientSignature:
    def test_the_sent_body_verifies_under_the_signing_secret(self, httpx_mock):
        """What HIITL sends is the envelope it built and signed over the one signed form (row 127): renamed back to
        `signature`, the body verifies under the secret through hiitl.core.canonical, and a changed value does not."""
        httpx_mock.add_response(url=f"{TEST_SERVER_URL}/v1/evaluate", method="POST", json=ALLOW_RESPONSE,
                                status_code=200)
        with HIITL(environment="dev", agent_id=TEST_AGENT_ID, org_id=TEST_ORG_ID, api_key=TEST_API_KEY,
                   server_url=TEST_SERVER_URL, evaluation="remote", signature_key=TEST_SIGNING_SECRET) as hiitl:
            hiitl.evaluate("process_payment", parameters={"amount": 150.0, "items": [{"sku": "a"}]},
                           target={"account_id": "acct_123"}, user_id="user_42")

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert "X-Hiitl-Signature-Version" not in request.headers    # row 171: the envelope names its version
        assert body.get("signature_version") == "hmac-sha256-v1"
        envelope = {**{k: v for k, v in body.items() if k != "envelope_signature"},
                    "signature": body["envelope_signature"]}
        assert envelope_verifies(TEST_SIGNING_SECRET, envelope)
        assert not envelope_verifies("another-secret-0123456789abcdef0123", envelope)
        envelope["parameters"]["items"][0]["sku"] = "b"
        assert not envelope_verifies(TEST_SIGNING_SECRET, envelope)


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

    # All evaluate-flow tests below pin hosted mode explicitly via
    # `evaluation="remote"`. Without it, providing api_key+server_url
    # yields hybrid mode — which would start a background sync engine
    # that hits unregistered URLs in httpx_mock, blowing up the test.

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
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
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
            evaluation="remote",
            signature_key=TEST_SIGNING_SECRET,
        )
        assert hiitl.mode == "hosted"
        hiitl.close()
