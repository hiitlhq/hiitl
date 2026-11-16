"""`requested_scopes` on the Python SDK's evaluate() (TICKET-138).

§9.15 (Trevor, 2026-10-11): a field the SDK's evaluate() has no argument for is hiitl's own requirement. The argument
now exists: it reaches the evaluated envelope (local and hybrid), the audit record and its content hash, and the
hosted request body.
"""

from __future__ import annotations

import json

from hiitl.core.canonical import audit_content_hash
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL

# at-0009's generated gate, as generate renders it (requested_scopes ⊄ principal.scopes → BLOCK)
GATE = {"name": "p", "version": "v1.0.0", "description": "The p set", "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"}, "rules": [
    {"name": "gen-at-0009-system", "description": "d", "priority": 900, "decision": "BLOCK",
     "reason_code": "AT_0009_BLOCK",
     "conditions": {"all_of": [{"field": "action", "operator": "exists", "value": True},
                               {"field": "requested_scopes", "operator": "not_in",
                                "value": {"$field": "principal.scopes"}}]}},
    {"name": "allow", "description": "d", "priority": 1, "decision": "ALLOW", "reason_code": "OK",
     "conditions": {"field": "action", "operator": "exists", "value": True}}]}


def _verifier(token: str) -> dict:
    return {"sub": "user_7", "scope": "refunds:write read"}


def _client(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(GATE))
    return HIITL(policy_path=str(p), mode="RESPECT_POLICY", audit_db_path=str(tmp_path / "a.db"),
                 principal_verifier=_verifier)


def test_the_argument_reaches_the_evaluated_envelope(tmp_path):
    h = _client(tmp_path)
    assert h.evaluate("refund", principal_token="t", requested_scopes=["read"]).decision == "ALLOW"
    blocked = h.evaluate("refund", principal_token="t", requested_scopes=["read", "admin"])
    assert (blocked.decision, blocked.reason_codes) == ("BLOCK", ["AT_0009_BLOCK"])


def test_the_audit_record_carries_it_and_its_hash_covers_it(tmp_path):
    _client(tmp_path).evaluate("refund", principal_token="t", requested_scopes=["read"])
    (rec,) = AuditLogger(str(tmp_path / "a.db")).get_unsynced(limit=10)
    assert rec["envelope"]["requested_scopes"] == ["read"]
    assert rec["content_hash"] == audit_content_hash(rec["event_id"], rec["envelope"], rec["decision"])
    without = {k: v for k, v in rec["envelope"].items() if k != "requested_scopes"}
    assert rec["content_hash"] != audit_content_hash(rec["event_id"], without, rec["decision"])


def test_omitted_it_is_absent_not_empty(tmp_path):
    _client(tmp_path).evaluate("refund")
    (rec,) = AuditLogger(str(tmp_path / "a.db")).get_unsynced(limit=10)
    assert rec["envelope"].get("requested_scopes") is None


def test_hosted_mode_forwards_it_in_the_body(monkeypatch):
    sent = {}
    h = HIITL(api_key="sk_test_x", server_url="https://example.invalid", evaluation="remote",
              signature_key="s" * 32)

    class _Resp:
        status_code = 200

        def json(self):
            return {"action_id": "act_x", "decision": "ALLOW", "allowed": True, "reason_codes": ["OK"],
                    "policy_version": "1", "timing": {"total_ms": 1.0}}

    monkeypatch.setattr(h._hosted_client, "_send_with_retry", lambda body, headers=None: sent.update(body) or _Resp())
    h.evaluate("refund", requested_scopes=["refunds:write"])
    assert sent["requested_scopes"] == ["refunds:write"]
