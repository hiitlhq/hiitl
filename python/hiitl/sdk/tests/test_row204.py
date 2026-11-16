"""Row 204 (HTL-23): every member the decision model declares reaches the hosted caller.

Ruled 2026-11-06 as the row reads: "the lists are generated from the decision model, the class swept, by R-0872 and
item 13". R-0872: "no field is ever silently dropped". The members are read from `Decision.model_fields`, never from a
list in the cell: a member the model gains fails the completeness assertion here until its value is written below,
and needs no edit to the client. Design: the HTL-23 test design, row 204. Mirrors
typescript/packages/sdk/tests/unit/row204.test.ts.
"""

from __future__ import annotations

import gzip
import json
import os

import httpx
import pytest

from hiitl.core.types import Decision
from hiitl.sdk.client import HIITL

ORG_ID = "org_r204everymember0000"
SERVER = "https://ecp.r204.example.com"

REMEDIATION = {"message": "Refunds over 500 need a manager", "suggestion": "Lower the amount to 500 or less",
               "type": "threshold", "details": {"field": "parameters.amount", "limit": 500}}

# A hosted decision carrying a value for each member. `error` and `remediation` never ride together (the model's
# own refusal), so the error decision carries `error` and the rest of the members as the full one does.
FULL = {
    "action_id": "", "decision": "BLOCK", "allowed": False, "reason_codes": ["REFUND_CAPPED"],
    "policy_version": "v1.4.0", "timing": {"ingest_ms": 0.25, "evaluation_ms": 0.5, "total_ms": 1.25},
    "matched_rules": [{"rule_name": "cap_refunds", "policy_set": "refunds", "priority": 500}],
    "rate_limit": {"scope": "agent", "window": "60s", "limit": 10, "current": 3,
                   "reset_at": "2026-11-06T12:00:00Z"},
    "resume_token": "rt_r204resume00000000", "route_ref": "finance-review",
    "escalation_context": {"queue": "finance", "sla_minutes": 15},
    "envelope_hash": "a" * 64,
    "remediation": REMEDIATION,
    "would_be": "BLOCK", "would_be_reason_codes": ["REFUND_CAPPED"],
    "staged_observations": [{"rule_name": "hold_refunds", "policy_set": "refunds", "priority": 400,
                             "would_be_decision": "REQUIRE_APPROVAL", "would_be_reason_codes": ["REFUND_HELD"],
                             "would_be_binding": False}],
    "rate_limit_rules": [{"rule_name": "meter_refunds", "policy_set": "refunds", "priority": 300,
                          "reason_code": "REFUNDS_METERED", "limit": 100, "window_seconds": 3600,
                          "scope": "agent", "remediation": REMEDIATION}],
    "enrichment": {"fraud": {"score": 0.12}},
    "routes": [{"rule_name": "score_refunds", "route": "fraud-score", "outcome": "answered", "fields": ["score"]}],
    "missing_fields": [{"rule_name": "cap_by_region", "policy_set": "refunds", "field": "parameters.region"}],
    "cache_status": "synced",
    "metadata": {"fail_mode": "FAIL_CLOSED", "circuit_breaker_state": "closed"},
}
ERRORED = {**{k: v for k, v in FULL.items() if k != "remediation"},
           "error": {"code": "RATE_LIMIT_SERVICE_ERROR", "message": "The rate limit counter could not be read."}}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hiitl(tmp_path) -> HIITL:
    return HIITL(environment="dev", agent_id="r204-agent", org_id=ORG_ID, api_key="sk_test_r204everymember",
                 server_url=SERVER, evaluation="remote", signature_key="r204-signing-secret-0123456789abcdef",
                 audit_db_path=str(tmp_path / "audit.db"), max_retries=0)


def _answers(decision: dict):
    def answer(request: httpx.Request) -> httpx.Response:
        content = request.content
        sent = json.loads(gzip.decompress(content) if request.headers.get("content-encoding") == "gzip" else content)
        return httpx.Response(200, json={**decision, "action_id": sent["action_id"]})
    return answer


def test_the_cells_decisions_carry_every_member():
    """Behavior 2: the members the cells send are the model's own, so a member the model gains is sent here."""
    assert set(FULL) | set(ERRORED) == set(Decision.model_fields)
    for decision in (FULL, ERRORED):
        dumped = Decision.model_validate(decision).model_dump(mode="json")
        assert [m for m in decision if dumped[m] in (None, [], {})] == [], "each member carries a value"


@pytest.mark.parametrize("decision", [FULL, ERRORED], ids=["remediation", "error"])
def test_each_member_reaches_the_caller(httpx_mock, tmp_path, decision):
    """Behavior 1: the caller's decision holds each member the hosted response carried, equal."""
    httpx_mock.add_callback(_answers(decision), url=f"{SERVER}/v1/evaluate")
    h = _hiitl(tmp_path)
    d = h.evaluate("refund", parameters={"amount": 900})
    h.close()
    sent = Decision.model_validate({**decision, "action_id": d.action_id}).model_dump(mode="json")
    got = d.model_dump(mode="json")
    assert {m: got[m] for m in Decision.model_fields if got[m] != sent[m]} == {}
