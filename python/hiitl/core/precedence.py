"""Rule precedence — DENY wins (docs/specs/policy_format.md "Rule Precedence").

Among the rules that match, the binding rule is the first by (class, −priority, definition order): a matching
KILL_SWITCH or BLOCK binds over a matching rule of any other decision whatever their priorities, a kill switch over a
block, and within a class the higher priority binds, then the rule defined first. One definition, read by the
evaluator and by the lint.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple

# The forbid class and its internal order; every other decision is class 2.
FORBID_CLASS = {"KILL_SWITCH": 0, "BLOCK": 1}
ALLOW_CLASS = frozenset({"ALLOW", "SANDBOX", "OBSERVE"})


def decision_value(d: Any) -> str:
    return d.value if hasattr(d, "value") else d


def precedence_key(rule: Any, index: int) -> tuple:
    return (FORBID_CLASS.get(decision_value(rule.decision), 2), -rule.priority, index)


def keyed(rules: Iterable[Any]) -> List[Tuple[tuple, Any]]:
    """Each rule with its precedence key, in precedence order (stable on definition order)."""
    return sorted(((precedence_key(r, i), r) for i, r in enumerate(rules)), key=lambda p: p[0])


def as_block(key: tuple) -> tuple:
    """The key a rule binds at when it decides BLOCK (a rule its set's `on_missing: fail_closed` could not read): the
    BLOCK class, at the rule's own priority and place in the definition order."""
    return (FORBID_CLASS["BLOCK"],) + tuple(key[1:])


def ordered(rules: Iterable[Any]) -> List[Any]:
    """The rules in precedence order (stable on definition order)."""
    return [r for _, r in keyed(rules)]
