"""Policy lint — cells.

Each code is proved on a set where it is provable and shown absent where it is not; the analysis claims nothing it
cannot decide (an opaque operator never yields UNREACHABLE).
"""

from __future__ import annotations

from hiitl.core.lint import dnf, implies, lint, satisfiable, _envelope_fields


def _r(name, decision, cond, priority=100, **kw):
    return {"name": name, "description": name, "priority": priority, "conditions": cond, "decision": decision,
            "reason_code": name.upper(), **kw}


def _set(*rules):
    return {"name": "t", "version": "v1.0.0", "description": "The t set", "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"}, "rules": list(rules)}


def _codes(findings, rule=None):
    return sorted(f.code for f in findings if rule is None or f.rule == rule)


A = {"field": "action", "operator": "equals", "value": "pay"}
ALLOW_PAY = _r("allow_pay", "ALLOW", A, 1)
ALWAYS = _envelope_fields()[1]


# ── UNREACHABLE ─────────────────────────────────────────────────────────────────────────────────────────────

def test_contradictory_bounds_are_unreachable():
    c = {"all_of": [{"field": "parameters.amount", "operator": "greater_than", "value": 10},
                    {"field": "parameters.amount", "operator": "less_than", "value": 5}]}
    assert "UNREACHABLE" in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)), "x")


def test_two_equals_on_one_field_are_unreachable():
    c = {"all_of": [A, {"field": "action", "operator": "equals", "value": "refund"}]}
    assert "UNREACHABLE" in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)), "x")


def test_exists_false_on_a_required_field_is_unreachable():
    c = {"field": "action", "operator": "exists", "value": False}
    assert "UNREACHABLE" in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)), "x")


def test_scope_zero_percent_empty_whitelist_and_inverted_window_are_unreachable():
    s = _set(_r("p0", "BLOCK", A, scope={"percentage": 0}), _r("w0", "BLOCK", A, scope={"agents": []}),
             _r("t0", "BLOCK", A, valid_from="2026-02-01T00:00:00Z", valid_to="2026-01-01T00:00:00Z"), ALLOW_PAY)
    f = lint(s)
    assert all("UNREACHABLE" in _codes(f, n) for n in ("p0", "w0", "t0"))


def test_a_satisfiable_rule_is_not_unreachable():
    c = {"all_of": [A, {"field": "parameters.amount", "operator": "greater_than", "value": 5},
                    {"field": "parameters.amount", "operator": "less_than", "value": 10}]}
    assert "UNREACHABLE" not in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)))


def test_an_opaque_operator_is_never_claimed_unreachable():
    c = {"all_of": [{"field": "parameters.to", "operator": "contains", "value": "@"},
                    {"field": "parameters.to", "operator": "not_contains", "value": "@"}]}
    assert "UNREACHABLE" not in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)))


def test_none_of_reads_absence_with_the_evaluators_semantics():
    # none_of [user_id equals u] matches an envelope with no user_id — satisfiable; on the required `action` the
    # negation of equals is not_equals, and together with equals it is a contradiction.
    assert satisfiable(dnf({"none_of": [{"field": "user_id", "operator": "equals", "value": "u"}]})[0], ALWAYS)
    c = {"all_of": [A, {"none_of": [A]}]}
    assert not any(satisfiable(x, ALWAYS) for x in dnf(c))


# ── PRIORITY_SHADOWED (DENY wins decides what ranks above) ─────────────────────────────────────────────────

def test_a_narrower_allow_under_a_matching_block_is_shadowed_whatever_its_priority():
    narrow = {"all_of": [A, {"field": "parameters.amount", "operator": "less_than", "value": 5}]}
    f = lint(_set(_r("allow_small", "ALLOW", narrow, 1000), _r("block_pay", "BLOCK", A, 1)))
    assert "PRIORITY_SHADOWED" in _codes(f, "allow_small")


def test_a_narrower_rule_below_a_broader_rule_of_its_class_is_shadowed():
    broad = {"field": "action", "operator": "in", "value": ["pay", "refund"]}
    f = lint(_set(_r("allow_both", "ALLOW", broad, 100), _r("approve_pay", "REQUIRE_APPROVAL", A, 50)))
    assert "PRIORITY_SHADOWED" in _codes(f, "approve_pay")


def test_a_rule_ranked_above_or_narrower_above_is_not_shadowed():
    broad = {"field": "action", "operator": "in", "value": ["pay", "refund"]}
    f = lint(_set(_r("allow_both", "ALLOW", broad, 50), _r("approve_pay", "REQUIRE_APPROVAL", A, 100)))
    assert "PRIORITY_SHADOWED" not in _codes(f)
    narrow = {"all_of": [A, {"field": "parameters.amount", "operator": "greater_than", "value": 5}]}
    f = lint(_set(_r("block_big", "BLOCK", narrow, 1), _r("allow_pay", "ALLOW", A, 100)))
    assert "PRIORITY_SHADOWED" not in _codes(f)


def test_a_scoped_rule_above_does_not_shadow_an_unscoped_one():
    f = lint(_set(_r("block_pay_bot", "BLOCK", A, scope={"agents": ["bot"]}), _r("allow_pay", "ALLOW", A)))
    assert "PRIORITY_SHADOWED" not in _codes(f)


def test_implication_is_sound_over_numeric_bounds():
    a = dnf({"field": "parameters.amount", "operator": "greater_than", "value": 10})
    b = dnf({"field": "parameters.amount", "operator": "greater_than", "value": 5})
    assert implies(a, b, ALWAYS) and not implies(b, a, ALWAYS)


# ── ALWAYS_ALLOW / ALWAYS_BLOCK ─────────────────────────────────────────────────────────────────────────────

ANY = {"field": "action", "operator": "exists", "value": True}


def test_an_unconditional_allow_with_nothing_above_is_always_allow():
    assert "ALWAYS_ALLOW" in _codes(lint(_set(_r("allow_all", "ALLOW", ANY))))


def test_a_satisfiable_block_anywhere_removes_always_allow():
    assert "ALWAYS_ALLOW" not in _codes(lint(_set(_r("allow_all", "ALLOW", ANY, 1000), _r("b", "BLOCK", A, 1))))


def test_an_unconditional_block_is_always_block():
    env_all = {"field": "environment", "operator": "in", "value": ["dev", "stage", "prod"]}
    assert "ALWAYS_BLOCK" in _codes(lint(_set(_r("stop", "KILL_SWITCH", env_all), ALLOW_PAY)))


def test_a_set_with_no_allowing_rule_is_always_block():
    assert "ALWAYS_BLOCK" in _codes(lint(_set(_r("approve_pay", "REQUIRE_APPROVAL", A))))
    assert "ALWAYS_BLOCK" not in _codes(lint(_set(_r("approve_pay", "REQUIRE_APPROVAL", A), ALLOW_PAY)))


# ── UNDEFINED_FIELD ─────────────────────────────────────────────────────────────────────────────────────────

def test_fields_outside_the_envelope_are_undefined():
    s = _set(_r("a", "BLOCK", {"field": "amount", "operator": "greater_than", "value": 1}),
             _r("b", "BLOCK", {"field": "action.name", "operator": "equals", "value": "x"}),
             _r("c", "BLOCK", {"field": "cost_estimate.euros", "operator": "greater_than", "value": 1}),
             _r("ok", "ALLOW", {"all_of": [{"field": "action", "operator": "equals", "value": "pay"},
                                           {"field": "cost_estimate.dollars", "operator": "less_than", "value": 9},
                                           {"field": "parameters.anything", "operator": "exists", "value": True}]}))
    f = lint(s)
    assert [x.rule for x in f if x.code == "UNDEFINED_FIELD"] == ["a", "b", "c"]


def test_a_parameter_outside_the_actions_informed_envelope_is_undefined():
    c = {"all_of": [A, {"field": "parameters.amount", "operator": "greater_than", "value": 1}]}
    assert "UNDEFINED_FIELD" in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY), parameters=["to", "body"]), "x")
    assert "UNDEFINED_FIELD" not in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY), parameters=["amount"]))


# ── RATE_LIMIT_NO_WINDOW, UNCALIBRATED ──────────────────────────────────────────────────────────────────────

def test_a_rate_limit_rule_without_a_window_is_reported():
    assert "RATE_LIMIT_NO_WINDOW" in _codes(lint(_set(_r("rl", "RATE_LIMIT", A), ALLOW_PAY)), "rl")


def test_a_placeholder_bound_is_reported_uncalibrated():
    c = {"all_of": [A, {"field": "parameters.amount", "operator": "greater_than",
                        "value": {"$uncalibrated": "the distribution of parameters.amount on pay"}}]}
    assert "UNCALIBRATED" in _codes(lint(_set(_r("x", "BLOCK", c), ALLOW_PAY)), "x")


def test_a_none_of_matches_an_absent_field_so_a_rule_requiring_the_field_does_not_shadow_it():
    """The evaluator's semantics: an absent field fails every operator but exists, so none_of[user_id equals u] matches
    an envelope with no user_id, which `user_id not_equals u` does not — no shadowing is provable."""
    req_absent_ok = _r("approve_unless_u", "REQUIRE_APPROVAL",
                       {"none_of": [{"field": "user_id", "operator": "equals", "value": "u"}]}, 10)
    needs_field = _r("allow_not_u", "ALLOW", {"field": "user_id", "operator": "not_equals", "value": "u"}, 100)
    assert "PRIORITY_SHADOWED" not in _codes(lint(_set(needs_field, req_absent_ok)))
