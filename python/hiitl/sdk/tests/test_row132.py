"""Row 132 (HTL-20): observe never blocks, and a failing limiter never allows.

Under OBSERVE_ALL a call past its limit comes back OBSERVE with `would_be: RATE_LIMIT` (ecp_evaluate_spec.md
**Observe Mode**). A limiter that raises blocks the call (safe by default), observed under OBSERVE_ALL. The limiter
reads every window before it counts any, so a call one window refuses is counted in none (policy_format.md
**Evaluation is Side-Effect Free**, "on an ALLOW", R-0056). Design: the HTL-20 test design, row 132.
"""

import json

import pytest

from hiitl import HIITL

ORG = "org_test000000000000000"


def _client(tmp_path, rules, mode):
    policy = tmp_path / "payments.json"
    policy.write_text(json.dumps({"version": "v1.0.0", "description": "The payments set", "scope": {"org_id": "org_test000000000000000", "environment": "dev"}, "name": "payments", "rules": rules}))
    return HIITL(environment="dev", agent_id="payments-agent", org_id=ORG, policy_path=str(policy),
                 audit_db_path=str(tmp_path / f"audit_{mode}.db"), enable_rate_limiting=True, mode=mode)


ALLOW_PAYMENTS = {"name": "allow_payments", "priority": 100, "description": "Payments and refunds are allowed",
                  "conditions": {"field": "action", "operator": "in", "value": ["pay", "refund"]},
                  "decision": "ALLOW", "reason_code": "PAYMENT_ALLOWED"}
PAY_RATE = {"name": "pay_rate", "priority": 600, "description": "At most 2 payments a minute per agent",
            "conditions": {"field": "action", "operator": "equals", "value": "pay"},
            "decision": "RATE_LIMIT", "reason_code": "PAY_RATE",
            "rate_limit": {"limit": 2, "window_seconds": 60, "scope": "agent"}}


def test_observe_all_past_the_limit_is_observed_not_blocked(tmp_path):
    hiitl = _client(tmp_path, [PAY_RATE, ALLOW_PAYMENTS], "OBSERVE_ALL")
    hiitl.evaluate("pay")
    hiitl.evaluate("pay")
    d = hiitl.evaluate("pay")
    assert (d.decision, d.allowed) == ("OBSERVE", True)
    assert (d.would_be, d.would_be_reason_codes) == ("RATE_LIMIT", ["RATE_LIMIT_EXCEEDED"])
    assert [m.rule_name for m in d.matched_rules] == ["pay_rate"]
    assert (d.rate_limit.scope, d.rate_limit.window, d.rate_limit.limit, d.rate_limit.current) == ("agent", "60s", 2, 2)


def test_each_would_be_is_what_enforcing_the_same_calls_decides(tmp_path):
    runs = {}
    for mode in ("RESPECT_POLICY", "OBSERVE_ALL"):
        hiitl = _client(tmp_path, [PAY_RATE, ALLOW_PAYMENTS], mode)
        runs[mode] = [hiitl.evaluate("pay") for _ in range(5)]
    enforced, observed = runs["RESPECT_POLICY"], runs["OBSERVE_ALL"]
    assert [d.decision for d in enforced] == ["ALLOW", "ALLOW", "RATE_LIMIT", "RATE_LIMIT", "RATE_LIMIT"]
    assert [d.rate_limit.current for d in enforced] == [1, 2, 2, 2, 2]   # a refused call is counted in no window
    assert all(d.allowed for d in observed)
    assert [d.would_be or d.decision for d in observed] == [d.decision for d in enforced]
    assert [d.rate_limit.current for d in observed] == [d.rate_limit.current for d in enforced]


class _UnreadableStore:
    """The in-process form of a limiter whose store cannot be read."""

    def check_and_increment(self, envelope, decision):
        raise RuntimeError("counter store unreadable")


@pytest.mark.parametrize("mode", ["RESPECT_POLICY", "OBSERVE_ALL"])
def test_a_failing_limiter_does_not_let_the_call_through(tmp_path, mode, caplog):
    """The message is authored; the cause is logged, never said (HTL-22 row 159)."""
    hiitl = _client(tmp_path, [PAY_RATE, ALLOW_PAYMENTS], mode)
    hiitl._rate_limiter = _UnreadableStore()
    d = hiitl.evaluate("pay")
    if mode == "RESPECT_POLICY":
        assert (d.decision, d.allowed, d.reason_codes) == ("BLOCK", False, ["RATE_LIMIT_SERVICE_ERROR"])
    else:
        assert (d.decision, d.allowed) == ("OBSERVE", True)
        assert (d.would_be, d.would_be_reason_codes) == ("BLOCK", ["RATE_LIMIT_SERVICE_ERROR"])
    assert d.error is not None and d.error.code == "RATE_LIMIT_SERVICE_ERROR"
    assert "counter store unreadable" not in d.error.message
    assert "counter store unreadable" in caplog.text


def test_a_call_one_window_refuses_is_counted_in_no_window(tmp_path):
    """The wider window is listed first: 2 calls a minute across the org, then 1 payment a minute."""
    org_rate = {"name": "org_rate", "priority": 700, "description": "At most 2 money movements a minute",
                "conditions": {"field": "action", "operator": "in", "value": ["pay", "refund"]},
                "decision": "RATE_LIMIT", "reason_code": "ORG_RATE",
                "rate_limit": {"limit": 2, "window_seconds": 60, "scope": "org"}}
    one_pay = {**PAY_RATE, "name": "one_pay", "rate_limit": {"limit": 1, "window_seconds": 60, "scope": "agent"}}
    hiitl = _client(tmp_path, [org_rate, one_pay, ALLOW_PAYMENTS], "RESPECT_POLICY")
    first, refused, refund, over = (hiitl.evaluate(a) for a in ("pay", "pay", "refund", "refund"))
    assert first.decision == "ALLOW"
    assert refused.decision == "RATE_LIMIT" and [m.rule_name for m in refused.matched_rules] == ["one_pay"]
    assert refund.decision == "ALLOW", "the refused payment was counted in the org window"
    assert refund.rate_limit.current == 2
    assert over.decision == "RATE_LIMIT" and [m.rule_name for m in over.matched_rules] == ["org_rate"]
