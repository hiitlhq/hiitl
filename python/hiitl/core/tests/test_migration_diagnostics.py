"""Existing migration guidance survives strict supplied-input validation.

Design: .github/public/TEST_DESIGN_final_migration_diagnostics.md.
Expected names come from routes.md row241, envelope_schema.json row225 and
policy_format.md's retired lifecycle fields, not from observed validator output.
"""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from hiitl.core.route_types import Route, RouteFilters
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, Envelope, PolicySet, Rule


def route(filters, **extras):
    return {"name": "audit-sink", "version": "v1.0.0", "direction": "outbound",
            "timing": "async", "endpoint": "https://sink.example/v1", "filters": filters, **extras}


def rule(**extras):
    return {"name": "pay-rule", "description": "Pay rule", "priority": 1,
            "conditions": {"field": "action", "operator": "equals", "value": "pay"},
            "decision": "ALLOW", "reason_code": "PAY", **extras}


def policy(member):
    return {"name": "payments", "version": "v1.0.0", "description": "Payments",
            "scope": {"org_id": "org_test000000000000", "environment": "dev"}, "rules": [member]}


@pytest.mark.parametrize("boundary", ["filter", "route", "existing-route"])
def test_filter_rename_guidance_survives_each_model_boundary(boundary):
    raw = {"tools": ["pay"]}
    before = deepcopy(raw)
    if boundary == "filter":
        read, value = RouteFilters.model_validate, raw
    elif boundary == "route":
        read, value = Route.model_validate, route(raw)
    else:
        value = Route.model_validate(route({"actions": ["pay"]}))
        value.filters = raw
        read = Route.model_validate
    with pytest.raises(ValidationError) as caught:
        read(value)
    assert ("filters.tools is a key the route format does not define: it was renamed "
            "filters.actions, with no alias. Write filters.actions") in str(caught.value)
    assert raw == before


def test_unknown_filter_has_no_invented_rename_guidance():
    with pytest.raises(ValidationError) as caught:
        Route.model_validate(route({"unfamiliar": ["pay"]}))
    errors = caught.value.errors()
    assert [(error["loc"], error["type"]) for error in errors] == [
        (("filters", "unfamiliar"), "extra_forbidden")]
    assert "renamed" not in errors[0]["msg"]
    assert "actions" not in errors[0]["msg"]


def test_route_rename_keeps_unrelated_unknown_field_refusals():
    with pytest.raises(ValidationError) as caught:
        Route.model_validate(route({"tools": ["pay"], "unfamiliar": 1}, another_unknown=2))
    unknown = {error["loc"]: error for error in caught.value.errors() if error["type"] == "extra_forbidden"}
    assert set(unknown) == {("filters", "tools"), ("filters", "unfamiliar"), ("another_unknown",)}
    assert "Write filters.actions" in str(caught.value)
    assert "renamed" not in unknown[("filters", "unfamiliar")]["msg"]
    assert "renamed" not in unknown[("another_unknown",)]["msg"]


@pytest.mark.parametrize("boundary", ["rule", "policy"])
def test_sparse_test_envelope_keeps_rename_and_other_unknown_errors(boundary):
    member = rule(tests=[{"envelope": {"tool_name": "pay", "unfamiliar": 1}, "expect": "ALLOW"}])
    raw = member if boundary == "rule" else policy(member)
    before = deepcopy(raw)
    read = Rule.model_validate if boundary == "rule" else PolicySet.model_validate
    prefix = () if boundary == "rule" else ("rules", 0)
    with pytest.raises(ValidationError) as caught:
        read(raw)
    errors = caught.value.errors()
    assert "tool_name is a field the envelope schema does not define: the schema renamed it action" in str(caught.value)
    unknown = {error["loc"]: error for error in errors if error["type"] == "extra_forbidden"}
    assert set(unknown) == {(*prefix, "tests", 0, "envelope", "tool_name"),
                            (*prefix, "tests", 0, "envelope", "unfamiliar")}
    assert "renamed" not in unknown[(*prefix, "tests", 0, "envelope", "unfamiliar")]["msg"]
    assert raw == before


def test_old_spellings_in_open_data_remain_data():
    held = {"tools": ["pay"], "tool_name": None, "enabled": False, "mode": "observe"}
    error = None
    try:
        route_value = Route.model_validate(route({"actions": ["pay"]}, metadata=deepcopy(held)))
        member = Rule.model_validate(rule(tests=[{"envelope": {"parameters": deepcopy(held)}, "expect": "ALLOW"}]))
    except ValidationError as caught:
        error = caught
    assert error is None, f"open values must remain data: {error}"
    assert route_value.metadata == held
    assert member.tests[0].envelope["parameters"] == held


@pytest.mark.parametrize("boundary", ["rule", "policy"])
@pytest.mark.parametrize("old,value", [("enabled", False), ("mode", "observe")])
def test_existing_retired_rule_guidance_survives_strict_validation(boundary, old, value):
    member = rule(**{old: value})
    with pytest.raises(ValidationError) as caught:
        (Rule.model_validate(member) if boundary == "rule" else PolicySet.model_validate(policy(member)))
    assert f"`{old}` was replaced by `lifecycle_stage`" in str(caught.value)


def test_existing_envelope_rename_preserves_other_unknown_refusals():
    raw = {"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": "org_test000000000000", "environment": "dev",
           "agent_id": "agent", "action_id": "act_migration000000000000", "idempotency_key": "idem_migration",
           "action": "pay", "timestamp": "2026-11-15T00:00:00Z", "signature": "a" * 64,
           "tool_name": "pay", "unfamiliar": 1}
    with pytest.raises(ValidationError) as caught:
        Envelope.model_validate(raw)
    errors = {error["loc"]: error for error in caught.value.errors()}
    assert {path: error["type"] for path, error in errors.items()} == {
        ("tool_name",): "extra_forbidden", ("unfamiliar",): "extra_forbidden"}
    assert "schema renamed it action" in errors[("tool_name",)]["msg"]
    assert "renamed" not in errors[("unfamiliar",)]["msg"]
