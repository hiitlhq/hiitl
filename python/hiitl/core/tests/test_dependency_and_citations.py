"""A folded rule cites a list; a dependency rides on the rule and gates promotion (policy_format.md 2.3). The
Python twin of the TypeScript cells in t130-followup.test.ts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiitl.core.lint import promotion_refusal
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, PolicySet

ALLOW_ALL = {"name": "allow_all", "description": "d", "priority": 1,
             "conditions": {"field": "action", "operator": "exists", "value": True},
             "decision": "ALLOW", "reason_code": "OK"}
GATE = {"name": "gate", "description": "d", "priority": 900, "decision": "BLOCK", "reason_code": "G",
        "lifecycle_stage": "staged", "waits_on": {"kind": "verifier", "target": "principal"},
        "conditions": {"all_of": [{"field": "action", "operator": "equals", "value": "refund"},
                                  {"none_of": [{"field": "principal.sub", "operator": "exists", "value": True}]}]}}


def _set(*rules):
    return {"name": "t", "version": "v1.0.0", "description": "The t set", "scope": {"org_id": "org_1234567890abcdef", "environment": "prod"}, "rules": list(rules)}


def _cite(atom):
    return {"atom_id": atom, "standard": "owasp_agentic_top_10"}


def test_a_rule_cites_one_determination_or_a_list():
    ps = PolicySet(**_set({**ALLOW_ALL, "requirement_citation": [_cite("at-0002"), _cite("at-0023")]},
                          {**ALLOW_ALL, "name": "one", "requirement_citation": _cite("at-0002")}))
    assert [c.atom_id for c in ps.rules[0].requirement_citation] == ["at-0002", "at-0023"]
    assert ps.rules[1].requirement_citation.atom_id == "at-0002"


@pytest.mark.parametrize("waits,named", [({"kind": "instrument", "target": "x"}, "kind"),
                                         ({"kind": "verifier", "target": "principal", "colour": "red"}, "colour")])
def test_a_dependency_outside_the_format_is_refused(waits, named):
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set({**ALLOW_ALL, "waits_on": waits}))
    assert named in str(e.value)


def test_an_unmet_dependency_refuses_promotion_naming_it_and_a_met_one_does_not():
    refused = promotion_refusal(_set(ALLOW_ALL, GATE), "gate")
    assert refused is not None, "an unmet dependency refuses promotion"
    code, message = refused
    assert code == "RULE_DEPENDENCY_UNMET" and "verifier `principal`" in message and "principal_verifier" in message
    assert promotion_refusal(_set(ALLOW_ALL, GATE), "gate", met=frozenset({("envelope_field", "principal")})) \
        is not None, "met by the dependency it names, of its kind"
    assert promotion_refusal(_set(ALLOW_ALL, GATE), "gate", met=frozenset({("verifier", "principal")})) is None


@pytest.mark.parametrize("field,ok", [("external.content_check", True), ("external.crowdstrike.risk_score", True),
                                      ("external.hiitl.prior_actions", True), ("session.prior_actions", False),
                                      ("external.a.b.c", False), ("sessions.prior", False)])
def test_the_lint_reads_the_formats_enrichment_namespaces(field, ok):
    from hiitl.core.lint import lint
    rule = {**ALLOW_ALL, "conditions": {"field": field, "operator": "exists", "value": True}}
    found = [f.code for f in lint(_set(rule))]
    assert ("UNDEFINED_FIELD" not in found) == ok


@pytest.mark.parametrize("kind", ["route", "hiitl_record"])
def test_the_new_dependency_kinds_load(kind):
    PolicySet(**_set({**ALLOW_ALL, "waits_on": {"kind": kind, "target": "x"}}))


def test_the_session_kind_is_removed():
    with pytest.raises(ValidationError):
        PolicySet(**_set({**ALLOW_ALL, "waits_on": {"kind": "session", "target": "x"}}))


def test_a_declared_value_never_matches_and_is_refused_promotion_naming_it():
    from hiitl.core.lint import lint
    rule = {**ALLOW_ALL, "name": "d", "lifecycle_stage": "staged",
            "conditions": {"field": "agent_id", "operator": "equals", "value": {"$declared": "the component"}}}
    refused = promotion_refusal(_set(rule), "d")
    assert refused is not None, "a declared value refuses promotion"
    code, message = refused
    assert code == "RULE_UNDECLARED" and "the component" in message
    assert "UNDECLARED" in [f.code for f in lint(_set(rule))]
    active = PolicySet(**_set({**rule, "lifecycle_stage": "active"}))
    assert active.rules[0].uncalibrated, "a rule carrying a placeholder never matches"


# ── policy_format.md 2.6: field references, array-left in / not_in, conforms_to ───────────────────────────────

def _env(**kw):
    e = {"schema_version": ENVELOPE_SCHEMA_VERSION,
         "org_id": "org_1234567890abcdef", "environment": "prod", "agent_id": "a",
         "action_id": "act_00000000000000000000", "idempotency_key": "k", "action": "x",
         "timestamp": "2026-10-09T00:00:00Z", "signature": "0" * 64, "target": {}, "parameters": {}}
    e.update(kw)
    return e


def _matches(cond, envelope) -> bool:
    from hiitl.core.evaluator import PolicyEvaluator
    rule = {**ALLOW_ALL, "name": "t", "decision": "BLOCK", "reason_code": "T", "conditions": cond}
    try:
        d = PolicyEvaluator().evaluate(envelope, PolicySet(**_set(rule)))
    except Exception as e:                                   # the semantics under test decide the cell, never a crash
        pytest.fail(f"evaluation stopped: {type(e).__name__}: {e}")
    return d.reason_codes == ["T"]


PRINCIPAL = {"sub": "u", "scopes": ["read", "write"], "verified_by": "sdk_verifier"}
SCOPES = {"field": "requested_scopes", "operator": "not_in", "value": {"$field": "principal.scopes"}}
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "n": {"type": "number"}}, "required": ["id"],
          "additionalProperties": False}


def test_a_field_reference_resolves_against_the_same_envelope():
    assert _matches(SCOPES, _env(requested_scopes=["read", "admin"], principal=PRINCIPAL))
    assert not _matches(SCOPES, _env(requested_scopes=["read"], principal=PRINCIPAL))
    assert _matches({"field": "parameters.a", "operator": "equals", "value": {"$field": "parameters.b"}},
                    _env(parameters={"a": 1, "b": 1}))


def test_a_reference_that_resolves_to_nothing_is_false():
    assert not _matches(SCOPES, _env(requested_scopes=["admin"]))


def test_an_array_on_the_left_of_in_is_a_subset_test():
    c = {"field": "sensitivity", "operator": "in", "value": ["money", "identity"]}
    assert _matches(c, _env(sensitivity=["money"])) and not _matches(c, _env(sensitivity=["money", "regulated"]))


@pytest.mark.parametrize("params,ok", [({"id": "a", "n": 2}, True), ({"id": "a", "x": 1}, False),
                                       ({"id": "a", "n": "two"}, False), ({"n": 2}, False)])
def test_conforms_to_reads_the_parameter_schema(params, ok):
    c = {"field": "parameters", "operator": "conforms_to", "value": SCHEMA}
    assert _matches(c, _env(parameters=params)) == ok


@pytest.mark.parametrize("cond,named", [
    ({"field": "parameters", "operator": "conforms_to", "value": {**SCHEMA, "pattern": "x"}}, "pattern"),
    ({"field": "parameters", "operator": "conforms_to", "value": {"properties": {"id": {"type": "uuid"}}}}, "id"),
    ({"field": "action", "operator": "exists", "value": {"$field": "agent_id"}}, "never a field reference"),
    ({"field": "action", "operator": "equals", "value": {"$field": ""}}, "a field reference is")])
def test_a_malformed_reference_or_schema_is_refused_at_load(cond, named):
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set({**ALLOW_ALL, "conditions": cond}))
    assert named in str(e.value)
