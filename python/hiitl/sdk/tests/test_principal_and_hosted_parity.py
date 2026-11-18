"""A7 and A4 on the Python SDK.

A7: the envelope's `principal` is set only by the configured verifier from a token passed to evaluate(); there is no
free `principal=` argument; a token with no verifier, or on the hosted path (not built), is a configuration error
that says what to do; a token the verifier rejects leaves the envelope with no principal, so an identity gate blocks.
A4: hosted mode forwards confidence, idempotency_key and the per-call agent_id.
"""

from __future__ import annotations

import json

import pytest

from hiitl.sdk.client import HIITL
from hiitl.sdk.exceptions import ConfigurationError

GATE = {"name": "p", "version": "v1.0.0", "description": "The p set", "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"}, "rules": [
    {"name": "verified_only", "description": "d", "priority": 900, "decision": "BLOCK", "reason_code": "UNVERIFIED",
     "conditions": {"none_of": [{"field": "principal.sub", "operator": "exists", "value": True}]}},
    {"name": "refunds_scope", "description": "d", "priority": 800, "decision": "BLOCK", "reason_code": "NO_SCOPE",
     "conditions": {"none_of": [{"field": "principal.scopes", "operator": "contains", "value": "refunds:write"}]}},
    {"name": "allow", "description": "d", "priority": 1, "decision": "ALLOW", "reason_code": "OK",
     "conditions": {"field": "action", "operator": "exists", "value": True}}]}


def _verifier(token: str) -> dict:
    if token != "good":
        raise ValueError("bad signature")
    return {"sub": "user_7", "scope": "refunds:write read", "iss": "https://idp", "aud": "https://api"}


def _client(tmp_path, **kw):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(GATE))
    return HIITL(policy_path=str(p), mode="RESPECT_POLICY", audit_db_path=str(tmp_path / "a.db"), **kw)


def test_a_verified_token_sets_the_principal_and_passes_the_gate(tmp_path):
    d = _client(tmp_path, principal_verifier=_verifier).evaluate("refund", principal_token="good")
    assert d.decision == "ALLOW"


def test_no_token_means_no_principal_and_the_gate_blocks(tmp_path):
    d = _client(tmp_path, principal_verifier=_verifier).evaluate("refund")
    assert d.decision == "BLOCK" and d.reason_codes == ["UNVERIFIED"]


def test_a_rejected_token_leaves_no_principal(tmp_path, caplog):
    d = _client(tmp_path, principal_verifier=_verifier).evaluate("refund", principal_token="forged")
    assert d.decision == "BLOCK" and d.reason_codes == ["UNVERIFIED"]
    assert "failed verification" in caplog.text


def test_a_token_without_a_verifier_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigurationError, match="principal_verifier"):
        _client(tmp_path).evaluate("refund", principal_token="good")


def test_evaluate_takes_no_free_principal_argument(tmp_path):
    with pytest.raises(TypeError):
        _client(tmp_path).evaluate("refund", principal={"sub": "me", "verified_by": "sdk_verifier"})


def test_hosted_mode_forwards_confidence_idempotency_key_and_the_per_call_agent_id(monkeypatch):
    sent = {}
    h = HIITL(api_key="sk_test_x", server_url="https://example.invalid", evaluation="remote", signature_key="s" * 32,
              agent_id="cfg-agent")

    class _Resp:
        status_code = 200

        def json(self):
            return {"action_id": "act_x", "decision": "ALLOW", "allowed": True, "reason_codes": ["OK"],
                    "policy_version": "1", "timing": {"total_ms": 1.0}}

    monkeypatch.setattr(h._hosted_client, "_send_with_retry", lambda body, headers=None: sent.update(body) or _Resp())
    h.evaluate("refund", confidence=0.4, idempotency_key="idem_7", agent_id="call-agent")
    assert (sent.get("confidence"), sent.get("idempotency_key"), sent.get("agent_id")) == (0.4, "idem_7",
                                                                                          "call-agent")


def test_hosted_mode_forwards_a_principal_token_as_its_header_never_in_the_body(monkeypatch):
    """The hosted service verifies the token with the org's configured verifier."""
    sent = {}
    h = HIITL(api_key="sk_test_x", server_url="https://example.invalid", evaluation="remote",
              signature_key="s" * 32)

    class _Resp:
        status_code = 200

        def json(self):
            return {"action_id": "act_x", "decision": "ALLOW", "allowed": True, "reason_codes": ["OK"],
                    "policy_version": "1", "timing": {"total_ms": 1.0}}

    monkeypatch.setattr(h._hosted_client, "_send_with_retry",
                        lambda body, headers=None: sent.update(body=body, headers=headers) or _Resp())
    h.evaluate("refund", principal_token="tok-123")
    assert sent["headers"] == {"X-Hiitl-Principal-Token": "tok-123"}   # no version header (row 171)
    assert "principal" not in sent["body"] and "principal_token" not in sent["body"]
