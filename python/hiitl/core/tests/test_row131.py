"""Row 131 (HTL-29): a kill switch is live when the evaluator binds it; an outbound route reads the record it sends.

policy_format.md "A version identifies what evaluates" and "Uncalibrated bounds"; sync_engine.md 2.4 "kill switches
always return the full active set"; routes.md "filters" and "Outbound routes and filters"; event_format.md "Outbound
Events". Design: the HTL-29 test design, row 131, behaviors 1 and 11-13. Mirrors
typescript/packages/core/tests/unit/row131.test.ts (behaviors 1, 12 and 13).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiitl.core import live_kill_switches, routing
from hiitl.core.route_types import Route, RouteFilters
from hiitl.core.types import DecisionType, PolicySet, Sensitivity

ON_PAY = {"field": "action", "operator": "equals", "value": "pay"}


def _rule(name, decision="KILL_SWITCH", stage="active", conditions=ON_PAY):
    return {"name": name, "description": name, "priority": 100, "conditions": conditions, "decision": decision,
            "reason_code": name.upper().replace("-", "_"), "lifecycle_stage": stage}


def _set(*rules):
    return PolicySet(**{"name": "payments", "version": "v1.0.0", "description": "payments",
                        "scope": {"org_id": "org_test000000000000", "environment": "dev"}, "rules": list(rules)})


# --- Behavior 1: the core reads the live switches ---

def test_a_switch_is_live_when_the_evaluator_binds_it():
    placeholder = {"all_of": [ON_PAY, {"field": "parameters.amount", "operator": "greater_than",
                                       "value": {"$uncalibrated": "the distribution of parameters.amount on pay"}}]}
    policy = _set(_rule("halt-refunds"), _rule("halt-disabled", stage="disabled"), _rule("halt-staged", stage="staged"),
                  _rule("halt-uncalibrated", conditions=placeholder), _rule("block-pay", decision="BLOCK"),
                  _rule("halt-payments"))
    assert live_kill_switches(policy) == ["halt-payments", "halt-refunds"], "active, no placeholder, sorted by name"


def test_a_set_with_no_switch_makes_none_live():
    assert live_kill_switches(_set(_rule("block-pay", decision="BLOCK"))) == []


# --- Behaviors 11-13: an outbound route's filters and fields ---

def _outbound(**fields):
    return {"name": "audit-sink", "version": "v1.0.0", "direction": "outbound", "timing": "async",
            "endpoint": "https://sink.example/v1", **fields}


def _record(decision_type="BLOCK", action="pay", agent_id="payment-agent", sensitivity=("money",)):
    return {"event_id": "evt_1", "decision_type": decision_type, "action": action, "agent_id": agent_id,
            "envelope": {"action": action, "agent_id": agent_id, "sensitivity": list(sensitivity)}}


# One row per filter key: the value the key lists, a record that holds it, and one that does not
KEYS = [
    ("decisions", ["BLOCK"], _record(), _record(decision_type="ALLOW")),
    ("actions", ["pay"], _record(), _record(action="refund")),
    ("agents", ["payment-agent"], _record(), _record(agent_id="support-agent")),
    ("sensitivity", ["pii"], _record(sensitivity=("money", "pii")), _record(sensitivity=("money",))),
]


def test_the_reading_of_each_key_is_the_filter_model_s_own_fields():
    assert set(routing.FILTER_READS) == set(RouteFilters.model_fields)
    assert {key for key, *_ in KEYS} == set(RouteFilters.model_fields), "each key has its row here"


def test_a_filter_naming_tools_is_refused_naming_actions():
    # row 241, ruled 2026-11-09: "the route filter's key is `actions`; `tools` is refused at load naming `actions`"
    with pytest.raises(ValidationError, match=r"filters\.tools is a key the route format does not define: it was "
                                              r"renamed filters\.actions, with no alias\. Write filters\.actions"):
        Route.model_validate(_outbound(filters={"tools": ["pay"]}))


@pytest.mark.parametrize("key,listed,held,not_held", KEYS)
def test_each_filter_key_narrows(key, listed, held, not_held):
    route = Route.model_validate(_outbound(filters={key: listed}))
    assert routing.receives(route, held)
    assert not routing.receives(route, not_held)


def test_two_keys_pass_only_together():
    route = Route.model_validate(_outbound(filters={"decisions": ["BLOCK", "KILL_SWITCH"], "sensitivity": ["money"]}))
    assert routing.receives(route, _record())
    assert not routing.receives(route, _record(decision_type="ALLOW"))
    assert not routing.receives(route, _record(sensitivity=("identity",)))
    assert routing.receives(route, _record(decision_type="KILL_SWITCH", sensitivity=("identity", "money")))


def test_a_route_with_no_filters_receives_every_record():
    route = Route.model_validate(_outbound())
    assert routing.receives(route, _record()) and routing.receives(route, _record(decision_type="ALLOW", sensitivity=()))


def test_a_record_with_no_sensitivity_fails_a_sensitivity_filter():
    route = Route.model_validate(_outbound(filters={"sensitivity": ["money"]}))
    record = _record()
    del record["envelope"]["sensitivity"]
    assert not routing.receives(route, record)


@pytest.mark.parametrize("key,value,allowed", [
    ("decisions", "DENY", [d.value for d in DecisionType]),
    ("sensitivity", "secret", [s.value for s in Sensitivity]),
])
def test_a_filter_value_outside_its_source_is_refused_naming_the_allowed_ones(key, value, allowed):
    with pytest.raises(ValidationError) as e:
        Route.model_validate(_outbound(filters={key: [value]}))
    message = str(e.value)
    assert f"filters.{key}.0" in message and repr(value) in message
    assert all(repr(v) in message for v in allowed), message


def test_the_values_the_old_lists_did_not_hold_are_taken():
    route = Route.model_validate(_outbound(filters={"decisions": ["OBSERVE"], "sensitivity": ["pii"]}))
    assert (route.filters.decisions, route.filters.sensitivity) == (["OBSERVE"], ["pii"])


def test_context_on_an_outbound_route_is_refused_naming_why():
    with pytest.raises(ValidationError) as e:
        Route.model_validate(_outbound(context={"include_policy_ref": True}))
    message = str(e.value)
    assert "outbound routes must not have 'context'" in message and "sends the record" in message, message


def test_context_on_a_bidirectional_route_is_taken():
    route = Route.model_validate({
        "name": "finance-review", "version": "v1.0.0", "direction": "bidirectional", "timing": "sync",
        "endpoint": "https://review.example/v1", "context": {"include_policy_ref": True},
        "response_schema": {"decision_options": ["approve", "deny"]},
        "sla": {"timeout": "5s", "timeout_action": "fail_closed"}})
    assert route.context.include_policy_ref is True
