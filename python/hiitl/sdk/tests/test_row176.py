"""Row 176 (HTL-22): the hosted client reads `missing_fields` into the decision.

The evaluate spec's Resolved Design Decision 2: "skip the policy, flag it in the audit trail ("policy X exists but
couldn't evaluate — envelope missing field Y")". decision_response.md 1.11 declares `missing_fields`, and the service
sends it (the hosted service's own row 176 cell). Design: the HTL-22 test design, row 176, behavior 10.
"""

from __future__ import annotations

from hiitl.core.canonical import envelope_signature
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.http_client import HostedClient

ORG_ID = "org_test000000000000000"
SERVER_URL = "https://ecp.example.com"
SIGNING_SECRET = "test-signing-secret-0123456789abcdef"

FLAG = [{"rule_name": "approve_large_payments", "policy_set": "payments_policy", "field": "parameters.amount"}]


def _envelope() -> dict:
    env = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "org_id": ORG_ID, "environment": "dev", "agent_id": "agent_finance_bot",
        "action_id": "act_0123456789abcdefghij", "idempotency_key": "idem_row176", "action": "process_payment",
        "operation": "execute", "timestamp": "2026-11-05T10:00:00Z", "target": {"account_id": "acct_123"},
        "parameters": {"currency": "usd"}, "signature_version": "hmac-sha256-v1",
    }
    env["signature"] = envelope_signature(SIGNING_SECRET, env)
    return env


def test_the_hosted_client_reads_the_flag_into_the_decision(httpx_mock):
    httpx_mock.add_response(url=f"{SERVER_URL}/v1/evaluate", method="POST", status_code=200, json={
        "action_id": "act_0123456789abcdefghij", "decision": "ALLOW", "allowed": True,
        "reason_codes": ["KNOWN_ACCOUNT"], "policy_version": "v1.0.0", "timing": {"total_ms": 2.0},
        "missing_fields": FLAG,
    })
    client = HostedClient(HostedModeConfig(
        environment="dev", agent_id="agent_finance_bot", org_id=ORG_ID, api_key="sk_test_1234567890abcdef",
        server_url=SERVER_URL))

    decision = client.evaluate(_envelope())

    assert [m.model_dump() for m in decision.missing_fields or []] == FLAG
    client.close()
