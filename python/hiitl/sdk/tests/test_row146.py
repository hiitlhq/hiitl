"""Row 146 (HTL-20), the rate-limit members through the SDK: a decision the limiter counted carries the counter state,
and an exceeded rule's own remediation reaches the caller.

R-0008: "Decisions must include current counter state snapshot". R-0059 and decision_response.md 1.2: remediation
on RATE_LIMIT decisions. Design: the HTL-20 test design, row 146.
"""

import json
from datetime import datetime, timedelta, timezone

from hiitl import HIITL

RATE_REMEDIATION = {"type": "rate_limit", "message": "Refunds are limited to 2 a minute per agent",
                    "suggestion": "Queue the refund and retry after reset_at", "details": {"retry": "after reset_at"}}
ALLOW_REFUNDS = {"name": "allow_refunds", "description": "Refunds are allowed", "priority": 100,
                 "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                 "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}
LIMIT_REFUNDS = {"name": "limit_refunds", "description": "2 refunds a minute per agent", "priority": 600,
                 "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                 "decision": "RATE_LIMIT", "reason_code": "REFUND_RATE",
                 "rate_limit": {"limit": 2, "window_seconds": 60, "scope": "agent"}, "remediation": RATE_REMEDIATION}


def _window(name, priority, limit, window_seconds, scope):
    return {"name": name, "description": f"{limit} refunds per {window_seconds}s per {scope}", "priority": priority,
            "conditions": {"field": "action", "operator": "equals", "value": "refund"},
            "decision": "RATE_LIMIT", "reason_code": "REFUND_RATE",
            "rate_limit": {"limit": limit, "window_seconds": window_seconds, "scope": scope}}


def _client(tmp_path, rules):
    policy = tmp_path / "refunds.json"
    policy.write_text(json.dumps({"version": "v1.0.0", "description": "The refund_policy set", "scope": {"org_id": "org_test000000000000000", "environment": "dev"}, "name": "refund_policy", "rules": rules}))
    return HIITL(environment="dev", agent_id="payments-agent", org_id="org_test000000000000000",
                 policy_path=str(policy), audit_db_path=str(tmp_path / "audit.db"), enable_rate_limiting=True,
                 mode="RESPECT_POLICY")


def test_an_allow_the_limiter_counted_carries_the_tightest_window(tmp_path, monkeypatch):
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)
    monkeypatch.setattr("hiitl.sdk.rate_limiter.datetime", Clock)
    tightest = _window("agent_minute", 600, 3, 60, "agent")
    hiitl = _client(tmp_path, [_window("org_hourly", 700, 10, 3600, "org"), tightest, ALLOW_REFUNDS])
    d = hiitl.evaluate("refund")
    assert d.decision == "ALLOW"
    state = d.rate_limit
    assert state is not None, "the ALLOW the limiter counted carries no counter state"
    assert (state.scope, state.window, state.limit, state.current) == ("agent", "60s", 3, 1)
    assert state.reset_at == now + timedelta(seconds=tightest["rate_limit"]["window_seconds"])

    (tmp_path / "tie").mkdir()
    tie = _client(tmp_path / "tie", [_window("org_minute", 700, 3, 60, "org"), _window("agent_two", 600, 3, 120, "agent"),
                                    ALLOW_REFUNDS])
    assert tie.evaluate("refund").rate_limit.window == "60s"   # equal headroom: the first listed


def test_no_windowed_rule_no_counter_state(tmp_path):
    assert _client(tmp_path, [ALLOW_REFUNDS]).evaluate("refund").rate_limit is None


def test_the_exceeded_rules_remediation_reaches_the_caller_with_its_counter_state(tmp_path):
    hiitl = _client(tmp_path, [LIMIT_REFUNDS, ALLOW_REFUNDS])
    hiitl.evaluate("refund")
    hiitl.evaluate("refund")
    d = hiitl.evaluate("refund")
    assert d.decision == "RATE_LIMIT" and [m.rule_name for m in d.matched_rules] == ["limit_refunds"]
    rem = d.remediation
    assert (rem.type, rem.message, rem.suggestion) == ("rate_limit", RATE_REMEDIATION["message"],
                                                       RATE_REMEDIATION["suggestion"])
    assert rem.details == {"retry": "after reset_at", **d.rate_limit.model_dump(mode="json")}
    assert (d.rate_limit.limit, d.rate_limit.current) == (2, 2)


def test_the_refusal_keeps_the_evaluation_record(tmp_path):
    staged = {"name": "staged_hold", "description": "A staged hold on refunds", "priority": 500,
              "lifecycle_stage": "staged", "conditions": {"field": "action", "operator": "equals", "value": "refund"},
              "decision": "BLOCK", "reason_code": "REFUND_HOLD"}
    hiitl = _client(tmp_path, [LIMIT_REFUNDS, staged, ALLOW_REFUNDS])
    allowed = [hiitl.evaluate("refund") for _ in range(2)]
    refused = hiitl.evaluate("refund")
    assert [d.decision for d in allowed] + [refused.decision] == ["ALLOW", "ALLOW", "RATE_LIMIT"]
    assert [o.rule_name for o in refused.staged_observations] == ["staged_hold"]
    assert [(r.rule_name, r.reason_code) for r in refused.rate_limit_rules] == [("limit_refunds", "REFUND_RATE")]
    assert refused.rate_limit_rules == allowed[-1].rate_limit_rules
