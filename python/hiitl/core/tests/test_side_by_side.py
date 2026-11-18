"""Tests for Block 1B 9b — side-by-side evaluation.

The architectural keystone. In a single walk through a policy's rules:
- Active rules contend for the binding decision (first match wins).
- Staged rules contend in parallel, producing `staged_observations`
  that record what each *would* have decided. The first staged match
  is flagged `would_be_binding=True`.

These tests prove the keystone by setting up policies that mix active
and staged rules in carefully ordered priority sequences.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import (
    ENVELOPE_SCHEMA_VERSION,
    Condition,
    ConditionOperator,
    DecisionType,
    Envelope,
    Environment,
    Operation,
    PolicySet,
    Rule,
)


def _envelope(tool: str = "send_email", amount: float | None = None) -> Envelope:
    params: dict = {}
    if amount is not None:
        params["amount"] = amount
    return Envelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        org_id="org_test123456789012",
        environment=Environment.DEV,
        agent_id="test-agent",
        action_id="act_sidebysidetest00000123",
        idempotency_key="idem_test",
        action=tool,
        operation=Operation.EXECUTE,
        target={},
        parameters=params,
        timestamp=datetime.now(timezone.utc),
        signature="a" * 64,
    )


def _rule(
    name: str,
    *,
    decision: DecisionType,
    lifecycle_stage: str = "active",
    priority: int = 100,
    condition_field: str = "action",
    condition_op: ConditionOperator = ConditionOperator.EQUALS,
    condition_value: object = "send_email",
    reason_code: str | None = None,
) -> Rule:
    return Rule(
        name=name,
        description=f"Rule {name}",
        lifecycle_stage=lifecycle_stage,
        priority=priority,
        conditions=Condition(
            field=condition_field,
            operator=condition_op,
            value=condition_value,
        ),
        decision=decision,
        reason_code=reason_code or f"{name.upper().replace('-', '_')}_MATCH",
    )


# ============================================================================
# Active-only baseline (unchanged behavior)
# ============================================================================


def test_active_only_no_staged_observations():
    """With no staged rules, staged_observations is an empty list (not None).

    Empty list = "zero observations", which is iterable without null-check.
    """
    policy = PolicySet(
        name="active-only",
        version="v1.0.0",
        description="Active only no staged observations",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[_rule("a", decision=DecisionType.ALLOW)],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    assert decision.decision == DecisionType.ALLOW
    assert decision.staged_observations == []


# ============================================================================
# Pure staged rules — observation without enforcement
# ============================================================================


def test_staged_rule_observes_but_does_not_bind():
    """A staged rule should produce an observation but NOT decide the outcome.

    When the only rule that matches is staged, the binding result falls
    through to the safe-default BLOCK / NO_MATCHING_RULE. The would-be
    BLOCK from staging is captured separately so the regression report
    can compare it.
    """
    policy = PolicySet(
        name="staged-only",
        version="v1.0.0",
        description="Staged rule observes but does not bind",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule("future-block", decision=DecisionType.BLOCK, lifecycle_stage="staged"),
        ],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    # No active rule binds → default BLOCK / NO_MATCHING_RULE.
    assert decision.decision == DecisionType.BLOCK
    assert decision.reason_codes == ["NO_MATCHING_RULE"]
    # But the staged rule *would* have blocked too, with its own reason.
    assert len(decision.staged_observations) == 1
    obs = decision.staged_observations[0]
    assert obs.rule_name == "future-block"
    assert obs.would_be_decision == DecisionType.BLOCK
    assert obs.would_be_reason_codes == ["FUTURE_BLOCK_MATCH"]
    assert obs.would_be_binding is True


# ============================================================================
# Mixed: active binds, staged observes alongside
# ============================================================================


def test_active_allow_with_staged_block_observation():
    """Active ALLOW binds. Staged BLOCK records what would change if promoted.

    This is the canonical pre-promotion shadow: an active permissive rule
    is in production, a tighter staged rule is being evaluated. The
    regression report uses these observations to decide if promoting the
    staged rule is safe.
    """
    policy = PolicySet(
        name="mixed",
        version="v1.0.0",
        description="Active allow with staged block observation",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule("active-allow", decision=DecisionType.ALLOW, priority=100),
            _rule(
                "staged-block",
                decision=DecisionType.BLOCK,
                lifecycle_stage="staged",
                priority=200,
                reason_code="STAGED_TIGHTER_BLOCK",
            ),
        ],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    # Active wins the binding decision regardless of staged priority.
    assert decision.decision == DecisionType.ALLOW
    # Staged rule still produces an observation.
    assert len(decision.staged_observations) == 1
    obs = decision.staged_observations[0]
    assert obs.rule_name == "staged-block"
    assert obs.would_be_decision == DecisionType.BLOCK
    assert obs.would_be_binding is True


def test_multiple_staged_rules_only_first_is_binding():
    """When multiple staged rules match, only the highest-priority one is binding.

    Lower-priority staged matches are still recorded — they're informative
    for regression analysis — but only the first staged match would have
    actually changed the would-be outcome.
    """
    policy = PolicySet(
        name="multi-staged",
        version="v1.0.0",
        description="Multiple staged rules only first is binding",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule(
                "staged-high",
                decision=DecisionType.BLOCK,
                lifecycle_stage="staged",
                priority=300,
                reason_code="STAGED_HIGH",
            ),
            _rule(
                "staged-low",
                decision=DecisionType.REQUIRE_APPROVAL,
                lifecycle_stage="staged",
                priority=100,
                reason_code="STAGED_LOW",
            ),
        ],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    assert len(decision.staged_observations) == 2
    # Highest priority comes first by the sort.
    assert decision.staged_observations[0].rule_name == "staged-high"
    assert decision.staged_observations[0].would_be_binding is True
    assert decision.staged_observations[1].rule_name == "staged-low"
    assert decision.staged_observations[1].would_be_binding is False


def test_active_short_circuits_other_active_but_not_staged():
    """First active match in precedence order wins; remaining active are
    skipped; staged still run.

    Proves the dual-lane semantics: active lane is first-match, staged
    lane walks fully (within the same precedence order). Corrected
    2026-10-08 for DENY wins (R-0846): the shadowed active rule was a
    BLOCK, which now binds over the higher-priority ALLOW — it is a
    REQUIRE_APPROVAL here so the test keeps proving the short-circuit;
    `test_active_block_binds_over_higher_priority_allow` proves DENY wins.
    """
    policy = PolicySet(
        name="short-circuit",
        version="v1.0.0",
        description="Active short circuits other active but not staged",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule(
                "active-high",
                decision=DecisionType.ALLOW,
                priority=300,
                reason_code="ACTIVE_HIGH",
            ),
            _rule(
                "active-low",
                # Would match but is shadowed by active-high (same class).
                decision=DecisionType.REQUIRE_APPROVAL,
                priority=100,
                reason_code="ACTIVE_LOW",
            ),
            _rule(
                "staged-block",
                decision=DecisionType.BLOCK,
                lifecycle_stage="staged",
                priority=50,
                reason_code="STAGED",
            ),
        ],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    assert decision.decision == DecisionType.ALLOW
    # Only the matched active rule is reflected in matched_rules.
    assert decision.matched_rules is not None
    assert len(decision.matched_rules) == 1
    assert decision.matched_rules[0].rule_name == "active-high"
    # Staged rule still observed even though active short-circuited the active lane.
    assert len(decision.staged_observations) == 1
    assert decision.staged_observations[0].rule_name == "staged-block"


# ============================================================================
# Staged rules respect the same filters as active rules
# ============================================================================


def test_staged_rule_with_temporal_window_skipped_outside_window():
    """A staged rule outside its valid_from/valid_to window doesn't observe.

    Staging means "behave as active for observation purposes" — not
    "ignore filters." A staged rule that wouldn't match by temporal
    bounds also shouldn't be observed.
    """
    from datetime import timezone, timedelta
    future = datetime.now(timezone.utc) + timedelta(days=30)
    policy = PolicySet(
        name="future-staged",
        version="v1.0.0",
        description="Staged rule with temporal window skipped outside window",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule(
                "future-rule",
                decision=DecisionType.BLOCK,
                lifecycle_stage="staged",
                priority=100,
            ),
        ],
    )
    # Manually set valid_from on the rule object (Rule may not accept it
    # as a constructor kwarg directly, but it's a model field).
    policy.rules[0].valid_from = future
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    # No staged observations because the rule is out of its window.
    assert decision.staged_observations == []


def test_draft_disabled_archived_never_observed():
    """Lifecycle stages other than active/staged don't participate in either lane."""
    for stage in ("draft", "disabled", "archived"):
        policy = PolicySet(
            name=f"{stage}-only",
            version="v1.0.0",
            description="Draft disabled archived never observed",
            scope={"org_id": "org_test123456789012", "environment": "dev"},
            rules=[_rule("r", decision=DecisionType.ALLOW, lifecycle_stage=stage)],
        )
        decision = PolicyEvaluator().evaluate(_envelope(), policy)
        # Defaults to BLOCK with NO_MATCHING_RULE — no rule participated.
        assert decision.decision == DecisionType.BLOCK
        assert decision.reason_codes == ["NO_MATCHING_RULE"]
        assert decision.staged_observations == []


def test_active_block_binds_over_higher_priority_allow():
    """DENY wins (policy_format.md "Rule Precedence"; R-0846): an active BLOCK
    binds over a matching active ALLOW of higher priority; a staged rule is
    still observed."""
    policy = PolicySet(
        name="deny-wins",
        version="v1.0.0",
        description="Active block binds over higher priority allow",
        scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule("active-high", decision=DecisionType.ALLOW, priority=300, reason_code="ACTIVE_HIGH"),
            _rule("active-low", decision=DecisionType.BLOCK, priority=100, reason_code="ACTIVE_LOW"),
            _rule("staged-allow", decision=DecisionType.ALLOW, lifecycle_stage="staged", priority=50,
                  reason_code="STAGED"),
        ],
    )
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    assert decision.decision == DecisionType.BLOCK
    assert decision.reason_codes == ["ACTIVE_LOW"]
    assert [m.rule_name for m in decision.matched_rules] == ["active-low"]
    assert [o.rule_name for o in decision.staged_observations] == ["staged-allow"]


def test_an_uncalibrated_rule_is_skipped_before_its_conditions_are_read():
    """C6 (policy_format.md "Uncalibrated bounds"): a rule carrying the placeholder never matches — even where its
    condition, read, would match (a none_of over a placeholder would otherwise be true)."""
    from hiitl.core.types import LogicalCondition
    placeholder_gate = Rule(
        name="gate", description="gate", priority=900, decision=DecisionType.BLOCK, reason_code="GATE",
        conditions=LogicalCondition(none_of=[Condition(field="action", operator=ConditionOperator.EQUALS,
                                                       value={"$uncalibrated": "the action this gates"})]))
    policy = PolicySet(name="p", version="v1.0.0", description="An uncalibrated rule is skipped before its conditions are read", scope={"org_id": "org_test123456789012", "environment": "dev"}, rules=[
        placeholder_gate, _rule("allow", decision=DecisionType.ALLOW, priority=1, reason_code="OK")])
    decision = PolicyEvaluator().evaluate(_envelope(), policy)
    assert decision.decision == DecisionType.ALLOW and decision.reason_codes == ["OK"]
