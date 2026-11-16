"""Row 146 (HTL-20), the rate-limit members in core: the counter state, the rule's own remediation, and the
remediation details that state a fact of the call, computed from the call.

R-0008: "Decisions must include current counter state snapshot". R-0059: remediation lets the developer "refine and
proceed with the adjusted tool call". policy_format.md **Remediation on Rules** (the computed-details table) and
**Rate-limit rules**. Design: the HTL-20 test design, row 146.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from hiitl.core import Envelope, PolicyEvaluator
from hiitl.core.rate_limits import counter_state, limit_exceeded, tightest
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, RateLimitRule

STAMP = datetime(2026, 2, 14, 15, 30, 0, 250000, tzinfo=timezone.utc)
RATE_REMEDIATION = {"type": "rate_limit", "message": "Refunds are limited to 2 a minute per agent",
                    "suggestion": "Queue the refund and retry after reset_at", "details": {"retry": "after reset_at"}}


def _envelope(action="refund", parameters=None):
    return Envelope(schema_version=ENVELOPE_SCHEMA_VERSION,
                    org_id="org_test123456789012", environment="dev", agent_id="payments-agent",
                    action_id="act_01234567890123456789", idempotency_key="idem_row146", action=action,
                    operation="execute", target={}, parameters=parameters or {}, timestamp=STAMP, signature="a" * 64)


def _policy(*rules):
    return {"name": "refund_policy", "version": "v1.0.0", "description": "The refund_policy set", "scope": {"org_id": "org_test123456789012", "environment": "dev"}, "rules": list(rules)}


ALLOW_REFUNDS = {"name": "allow_refunds", "description": "Refunds are allowed", "priority": 100,
                 "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                 "decision": "ALLOW", "reason_code": "REFUND_ALLOWED"}
LIMIT_REFUNDS = {"name": "limit_refunds", "description": "2 refunds a minute per agent", "priority": 600,
                 "conditions": {"field": "action", "operator": "equals", "value": "refund"},
                 "decision": "RATE_LIMIT", "reason_code": "REFUND_RATE",
                 "rate_limit": {"limit": 2, "window_seconds": 60, "scope": "agent"}, "remediation": RATE_REMEDIATION}


def _window(name, limit):
    return RateLimitRule(rule_name=name, policy_set="refund_policy", priority=600, reason_code="RATE",
                         limit=limit, window_seconds=60, scope="agent")


def test_tightest_is_the_least_headroom_first_listed_on_a_tie():
    reset_at = STAMP + timedelta(seconds=60)
    wide, narrow = counter_state(_window("wide", 10), 3, reset_at), counter_state(_window("narrow", 5), 3, reset_at)
    assert tightest([wide, narrow]) is narrow
    first, second = counter_state(_window("first", 5), 3, reset_at), counter_state(_window("second", 4), 2, reset_at)
    assert tightest([first, second]) is first


def test_limit_exceeded_keeps_the_decision_and_names_the_rule():
    staged = {"name": "staged_block", "description": "A staged hold on refunds", "priority": 500,
              "lifecycle_stage": "staged", "conditions": {"field": "action", "operator": "equals", "value": "refund"},
              "decision": "BLOCK", "reason_code": "REFUND_HOLD"}
    decision = PolicyEvaluator().evaluate(_envelope(), _policy(LIMIT_REFUNDS, staged, ALLOW_REFUNDS))
    assert decision.decision == "ALLOW" and decision.staged_observations and decision.rate_limit_rules
    rule = decision.rate_limit_rules[0]
    reset_at = STAMP + timedelta(seconds=60)
    refused = limit_exceeded(decision, rule, 2, reset_at)
    assert (refused.decision, refused.allowed, refused.reason_codes) == ("RATE_LIMIT", False, ["RATE_LIMIT_EXCEEDED"])
    assert [m.rule_name for m in refused.matched_rules] == ["limit_refunds"]
    assert refused.staged_observations == decision.staged_observations
    assert refused.rate_limit_rules == decision.rate_limit_rules
    assert refused.action_id == decision.action_id and refused.policy_version == decision.policy_version
    assert refused.rate_limit == counter_state(rule, 2, reset_at)
    rem = refused.remediation
    assert rem is not None, "the refusal carries no remediation"
    assert (rem.type, rem.message, rem.suggestion) == ("rate_limit", RATE_REMEDIATION["message"],
                                                       RATE_REMEDIATION["suggestion"])
    assert rem.details == {"retry": "after reset_at", **refused.rate_limit.model_dump(mode="json")}


def test_a_windowed_rule_is_listed_with_its_remediation():
    decision = PolicyEvaluator().evaluate(_envelope(), _policy(LIMIT_REFUNDS, ALLOW_REFUNDS))
    [listed] = decision.rate_limit_rules
    assert (listed.rule_name, listed.reason_code) == ("limit_refunds", "REFUND_RATE")
    assert listed.remediation is not None, "the windowed rule is listed without its remediation"
    assert listed.remediation.model_dump(exclude_none=True) == RATE_REMEDIATION


def _blocked(parameters, blocked_fields):
    rule = {"name": "restrict_fields", "description": "Identity numbers are not exported", "priority": 900,
            "conditions": {"field": "action", "operator": "equals", "value": "export"},
            "decision": "BLOCK", "reason_code": "FIELD_RESTRICTED",
            "remediation": {"type": "field_restriction", "message": "Identity numbers are not exported",
                            "suggestion": "Drop the blocked fields and retry",
                            "details": {"blocked_fields": blocked_fields}}}
    return PolicyEvaluator().evaluate(_envelope("export", parameters), _policy(rule)).remediation.details


COMPUTED = {"ref": "parameters.fields", "filter": ["dob", "ssn", "tax_id"]}


@pytest.mark.parametrize("parameters, written, expected", [
    ({"fields": ["name", "ssn", "email", "dob", "ssn"]}, COMPUTED,
     {"blocked_fields": ["ssn", "dob"], "field_ref": "parameters.fields"}),            # envelope order, each once
    ({"fields": "ssn"}, COMPUTED, {"blocked_fields": ["ssn"], "field_ref": "parameters.fields"}),   # a single value
    ({}, COMPUTED, {"blocked_fields": [], "field_ref": "parameters.fields"}),           # nothing at ref
    ({"fields": ["ssn"]}, ["ssn", "dob"], {"blocked_fields": ["ssn", "dob"]}),          # a list, copied as written
], ids=["order-and-once", "single-value", "nothing-at-ref", "list-as-written"])
def test_blocked_fields_are_the_calls_values_in_the_filter(parameters, written, expected):
    assert _blocked(parameters, written) == expected


@pytest.mark.parametrize("written, shape", [
    ("ssn", "a string"),
    ({"ref": "parameters.fields"}, "an object with keys ['ref']"),
    ({"ref": "", "filter": ["ssn"]}, "an object with keys ['filter', 'ref']"),
    ({"ref": "parameters.fields", "filter": "ssn"}, "an object with keys ['filter', 'ref']"),
], ids=["string", "no-filter", "empty-ref", "filter-not-a-list"])
def test_a_blocked_fields_shape_outside_the_two_is_refused_naming_it(written, shape):
    with pytest.raises(ValidationError) as refused:
        _blocked({}, written)
    message = str(refused.value)
    assert f"remediation.details.blocked_fields is {shape}." in message
    assert "a list of field names" in message and "{ref, filter}" in message


def _threshold(parameters):
    rule = {"name": "refund_ceiling", "description": "Refunds above 10000 are blocked", "priority": 900,
            "conditions": {"field": "action", "operator": "equals", "value": "refund"},
            "decision": "BLOCK", "reason_code": "REFUND_CEILING",
            "remediation": {"type": "threshold", "message": "Refunds above 10000 are blocked",
                            "suggestion": "Split the refund", "details": {"field": "parameters.amount",
                                                                         "limit": 10000, "current_value": 0}}}
    return PolicyEvaluator().evaluate(_envelope("refund", parameters), _policy(rule)).remediation.details


def test_threshold_current_value_is_the_calls_value():
    assert _threshold({"amount": 12500}) == {"field": "parameters.amount", "limit": 10000, "current_value": 12500}
    assert _threshold({}) == {"field": "parameters.amount", "limit": 10000}


def test_temporal_current_time_is_the_calls_timestamp():
    rule = {"name": "refund_hours", "description": "Refunds wait for business hours", "priority": 900,
            "conditions": {"field": "action", "operator": "equals", "value": "refund"},
            "decision": "BLOCK", "reason_code": "OUTSIDE_HOURS",
            "remediation": {"type": "temporal", "message": "Refunds run in business hours",
                            "suggestion": "Retry at 09:00", "details": {"current_time": "the author's guess"}}}
    details = PolicyEvaluator().evaluate(_envelope(), _policy(rule)).remediation.details
    assert details == {"current_time": "2026-02-14T15:30:00.250Z"}
