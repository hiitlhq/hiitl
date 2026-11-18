"""Row 220 (HTL-24): a rule's name is unique within its set.

Ruled 2026-11-07: "each core model refuses a set holding two rules of one name, naming it". By policy_format.md,
`name`: "Unique rule identifier within policy set", and row 147's class (each model refuses what its spec refuses).
The refusal follows the compilation of a set's `metadata.rate_limits`, so a compiled rule is held to it too, and the
compiled rule is named by the entry it carries (`metadata.compiled_from`). Design: the HTL-24 test design, row 220,
behavior 1. Mirrors typescript/packages/core/tests/unit/row220.test.ts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiitl.core.types import PolicySet


def _rule(name: str, decision: str = "BLOCK") -> dict:
    return {"name": name, "description": f"{name}, as written", "priority": 10, "decision": decision,
            "reason_code": "PAYOUT_OVER_LIMIT", "conditions": {"field": "parameters.amount", "operator": "greater_than",
                                                                "value": 5000}}


def _set(rules: list, **fields) -> dict:
    return {"name": "payouts", "version": "v1.0.0", "description": "payout limits",
            "scope": {"org_id": "org_test0123456789ab", "environment": "dev"}, "rules": rules, **fields}


def _refusal(data: dict) -> str:
    with pytest.raises(ValidationError) as e:
        PolicySet.model_validate(data)
    [error] = e.value.errors()
    return error["msg"]


def test_a_set_of_distinct_names_loads():
    loaded = PolicySet.model_validate(_set([_rule("over_limit"), _rule("review_large", "REQUIRE_APPROVAL")]))
    assert [r.name for r in loaded.rules] == ["over_limit", "review_large"]


@pytest.mark.parametrize("positions", [(0, 1), (0, 2), (1, 2)])
def test_two_rules_of_one_name_are_refused_naming_the_name_and_both_positions(positions):
    rules = [_rule("over_limit"), _rule("review_large", "REQUIRE_APPROVAL"), _rule("hold_new", "PAUSE")]
    first, second = positions
    rules[second] = {**rules[second], "name": rules[first]["name"]}
    msg = _refusal(_set(rules))
    assert repr(rules[first]["name"]) in msg
    assert f"rules[{first}]" in msg and f"rules[{second}]" in msg
    assert "Unique rule identifier within policy set" in msg


def test_a_compiled_rule_is_held_to_it_named_by_its_entry():
    """A rule written under the name a set-level throttle compiles to: the refusal names the entry the compiled rule
    carries, since the author wrote no rule at the compiled rule's position."""
    msg = _refusal(_set([_rule("metadata.rate_limits[0]")], metadata={"rate_limits": [{"limit": 10}]}))
    assert "'metadata.rate_limits[0]'" in msg and "rules[0]" in msg
    assert "compiled from metadata.rate_limits[0]" in msg


def test_the_refusal_names_each_name_held_twice():
    rules = [_rule("a"), _rule("b"), _rule("a"), _rule("b")]
    msg = _refusal(_set(rules))
    assert "'a'" in msg and "'b'" in msg
    assert all(f"rules[{i}]" in msg for i in range(4))
