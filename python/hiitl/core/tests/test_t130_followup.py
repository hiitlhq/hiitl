"""The policy models after the T-130 follow-up (policy_format.md 2.2).

H6 (S2): no policy field is dropped — every model of the format refuses a field it does not define; `enabled` and
`mode` are refused naming `lifecycle_stage`, because ignoring `enabled: false` ran disabled kill switches live.
H1 (T47): one rate-window representation, the rule's — a set's `metadata.rate_limits` is compiled to windowed
RATE_LIMIT rules on load, nothing dropped, an entry outside the table refused.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.lint import lint
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION, PolicySet

ALLOW_ALL = {"name": "allow_all", "description": "d", "priority": 1,
             "conditions": {"field": "action", "operator": "exists", "value": True},
             "decision": "ALLOW", "reason_code": "OK"}


def _set(*rules, **kw):
    return {"name": "t", "version": "v1.0.0", "description": "The t set", "scope": {"org_id": "org_1234567890abcdef", "environment": "prod"}, "rules": list(rules), **kw}


def _env(**kw):
    e = {"schema_version": ENVELOPE_SCHEMA_VERSION,
         "org_id": "org_1234567890abcdef", "environment": "prod", "agent_id": "bot",
         "action_id": "act_00000000000000000000", "idempotency_key": "k", "action": "pay",
         "timestamp": "2026-10-08T00:00:00Z", "signature": "0" * 64, "target": {}, "parameters": {}}
    e.update(kw)
    return e


def _message(exc: pytest.ExceptionInfo) -> str:
    return str(exc.value)


# ── H6: no field is dropped ─────────────────────────────────────────────────────────────────────────────────

def test_enabled_false_is_refused_naming_lifecycle_stage():
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set({**ALLOW_ALL, "enabled": False}))
    assert "lifecycle_stage" in _message(e) and "disabled" in _message(e)


def test_mode_is_refused_naming_lifecycle_stage():
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set({**ALLOW_ALL, "mode": "observe"}))
    assert "lifecycle_stage" in _message(e)


@pytest.mark.parametrize("where", ["rule", "set", "condition", "scope", "remediation", "rate_limit"])
def test_an_undefined_field_is_refused_wherever_it_is(where):
    rule = dict(ALLOW_ALL)
    s = _set(rule)
    if where == "rule":
        rule["colour"] = "red"
    elif where == "set":
        s["colour"] = "red"
    elif where == "condition":
        rule["conditions"] = {**rule["conditions"], "colour": "red"}
    elif where == "scope":
        rule["scope"] = {"agents": ["bot"], "colour": "red"}
    elif where == "remediation":
        rule.update(decision="BLOCK", remediation={"message": "m", "suggestion": "s", "type": "custom",
                                                   "colour": "red"})
    else:
        rule.update(decision="RATE_LIMIT", rate_limit={"limit": 1, "window_seconds": 60, "colour": "red"})
    with pytest.raises(ValidationError) as e:
        PolicySet(**s)
    assert "colour" in _message(e)


def test_a_disabled_kill_switch_does_not_bind():
    kill = {"name": "stop", "description": "d", "priority": 1000, "lifecycle_stage": "disabled",
            "conditions": {"field": "action", "operator": "exists", "value": True},
            "decision": "KILL_SWITCH", "reason_code": "STOP"}
    d = PolicyEvaluator().evaluate(_env(), PolicySet(**_set(kill, ALLOW_ALL)))
    assert d.decision == "ALLOW" and d.reason_codes == ["OK"]


# ── H1: metadata.rate_limits compiled to rules on load ─────────────────────────────────────────────────────

def _compiled(entry):
    ps = PolicySet(**_set(ALLOW_ALL, metadata={"rate_limits": [entry], "tags": ["x"]}))
    rule = next(r for r in ps.rules if r.name == "metadata.rate_limits[0]")
    return ps, rule


@pytest.mark.parametrize("scope,want", [("org", "org"), ("agent_id", "agent"), ("agent", "agent"), ("user", "user"),
                                        ("user_id", "user"), ("tool", "action"), ("org:tool", "action"),
                                        ("user:tool", "user_action")])
def test_each_set_level_scope_compiles_to_the_rules_scope(scope, want):
    _, rule = _compiled({"scope": scope, "limit": 5, "window": "minute"})
    assert rule.rate_limit.scope == want and rule.rate_limit.limit == 5 and rule.rate_limit.window_seconds == 60


@pytest.mark.parametrize("window,seconds", [("second", 1), ("minute", 60), ("hour", 3600), ("day", 86400)])
def test_window_names_compile_to_seconds(window, seconds):
    assert _compiled({"scope": "org", "limit": 3, "window": window})[1].rate_limit.window_seconds == seconds


def test_the_compiled_rule_is_the_same_throttle_and_nothing_is_dropped():
    entry = {"scope": "agent_id", "limit": 100}
    ps, rule = _compiled(entry)
    assert rule.decision == "RATE_LIMIT" and rule.lifecycle_stage == "active" and rule.priority == 0
    assert rule.reason_code == "RATE_LIMIT_EXCEEDED"
    assert rule.rate_limit.window_seconds == 3600                     # the limiter's default window, an hour
    assert (rule.metadata or {}).get("compiled_from") == {"path": "metadata.rate_limits[0]", "entry": entry}
    assert "rate_limits" not in ps.metadata and ps.metadata["tags"] == ["x"]
    assert _compiled({})[1].rate_limit.model_dump() == {"limit": 1000, "window_seconds": 3600, "scope": "org"}


def test_the_evaluator_lists_a_compiled_throttle_for_the_limiter():
    ps = PolicySet(**_set(ALLOW_ALL, metadata={"rate_limits": [{"scope": "agent_id", "window": "hour", "limit": 2}]}))
    d = PolicyEvaluator().evaluate(_env(), ps)
    assert d.decision == "ALLOW"
    assert [(r.rule_name, r.limit, r.window_seconds, r.scope) for r in d.rate_limit_rules] == \
        [("metadata.rate_limits[0]", 2, 3600, "agent")]


@pytest.mark.parametrize("entry,named", [({"scope": "team", "limit": 1}, "team"),
                                         ({"scope": "org", "window": "week", "limit": 1}, "week"),
                                         ({"scope": "org", "limit": 1, "burst": 4}, "burst")])
def test_an_entry_outside_the_table_is_refused_with_what_is_allowed(entry, named):
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set(ALLOW_ALL, metadata={"rate_limits": [entry]}))
    assert named in _message(e) and "metadata.rate_limits[0]" in _message(e)


def test_a_single_entry_dict_is_refused_but_the_declared_list_compiles():
    entry = {"scope": "org", "limit": 7}
    ps = PolicySet(**_set(ALLOW_ALL, metadata={"rate_limits": [entry]}))
    assert [r.name for r in ps.rules] == ["allow_all", "metadata.rate_limits[0]"]
    with pytest.raises(ValidationError) as caught:
        PolicySet(**_set(ALLOW_ALL, metadata={"rate_limits": entry}))
    assert "metadata.rate_limits" in _message(caught)


def test_a_rule_already_named_like_a_compiled_one_is_refused():
    taken = {**ALLOW_ALL, "name": "metadata.rate_limits[0]"}
    with pytest.raises(ValidationError) as e:
        PolicySet(**_set(taken, metadata={"rate_limits": [{"limit": 1}]}))
    assert "metadata.rate_limits[0]" in _message(e)


def test_the_lint_reports_a_set_carrying_both_forms():
    windowed = {"name": "pay_rate", "description": "d", "priority": 5,
                "conditions": {"field": "action", "operator": "equals", "value": "pay"},
                "decision": "RATE_LIMIT", "reason_code": "PAY_RATE",
                "rate_limit": {"limit": 3, "window_seconds": 60, "scope": "agent"}}
    both = _set(ALLOW_ALL, windowed, metadata={"rate_limits": [{"limit": 9}]})
    assert "RATE_LIMIT_BOTH_FORMS" in [f.code for f in lint(both)]
    assert "RATE_LIMIT_BOTH_FORMS" not in [f.code for f in lint(_set(ALLOW_ALL, windowed))]
    assert "RATE_LIMIT_BOTH_FORMS" not in [f.code for f in lint(_set(ALLOW_ALL, metadata={"rate_limits": [{}]}))]
