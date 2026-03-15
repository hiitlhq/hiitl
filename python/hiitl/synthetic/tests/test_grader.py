"""Tests for the policy grading engine."""

from typing import Dict, List, Optional

import pytest

from hiitl.core.types import Decision, DecisionType, MatchedRule, PolicySet, Rule, Timing
from hiitl.synthetic.grader import DeterministicGradingStrategy, PolicyGrader
from hiitl.synthetic.types import GradingData


def _make_policy(rules: List[Dict]) -> PolicySet:
    """Create a minimal policy for testing."""
    return PolicySet(
        name="test-policy",
        version="1.0.0",
        rules=[Rule(**r) for r in rules],
    )


def _make_decision(
    decision: str = "ALLOW",
    reason_codes: Optional[List[str]] = None,
    matched_rules: Optional[List[Dict]] = None,
    action_id: str = "act_test12345678901234567",
) -> Decision:
    """Create a minimal Decision for testing."""
    return Decision(
        action_id=action_id,
        decision=decision,
        allowed=decision in ("ALLOW", "SANDBOX"),
        reason_codes=reason_codes or ["TEST"],
        policy_version="1.0.0",
        timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        matched_rules=[MatchedRule(**r) for r in matched_rules] if matched_rules else None,
    )


RULES = [
    {
        "name": "rule-a",
        "description": "Rule A",
        "enabled": True,
        "priority": 100,
        "conditions": {"field": "action", "operator": "equals", "value": "tool_a"},
        "decision": "ALLOW",
        "reason_code": "RULE_A",
    },
    {
        "name": "rule-b",
        "description": "Rule B",
        "enabled": True,
        "priority": 50,
        "conditions": {"field": "action", "operator": "equals", "value": "tool_b"},
        "decision": "BLOCK",
        "reason_code": "RULE_B",
    },
    {
        "name": "rule-c-disabled",
        "description": "Disabled rule",
        "enabled": False,
        "priority": 200,
        "conditions": {"field": "action", "operator": "equals", "value": "tool_c"},
        "decision": "BLOCK",
        "reason_code": "RULE_C",
    },
]


class TestPolicyGrader:
    """Tests for PolicyGrader data collection + grading."""

    def test_100_percent_coverage(self):
        """All enabled rules matched = 100% coverage."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(
            decision="ALLOW",
            reason_codes=["RULE_A"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}],
        ))
        grader.record(_make_decision(
            decision="BLOCK",
            reason_codes=["RULE_B"],
            matched_rules=[{"rule_name": "rule-b", "policy_set": "test-policy", "priority": 50}],
        ))

        report = grader.grade()
        assert report.coverage_pct == 100.0
        assert report.total_rules == 2  # Only enabled rules
        assert report.rules_matched == 2
        assert report.rules_unmatched == 0

    def test_partial_coverage(self):
        """Only some rules matched = partial coverage."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(
            decision="ALLOW",
            reason_codes=["RULE_A"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}],
        ))

        report = grader.grade()
        assert report.coverage_pct == 50.0
        assert report.rules_matched == 1
        assert report.rules_unmatched == 1

    def test_zero_coverage(self):
        """No rules matched = 0% coverage with uncovered actions."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(
            decision="BLOCK",
            reason_codes=["NO_MATCHING_RULE"],
            action_id="act_nomatch123456789012",
        ))

        report = grader.grade()
        assert report.coverage_pct == 0.0
        assert report.rules_unmatched == 2

    def test_gap_identification_unmatched_rules(self):
        """Unmatched rules appear in gaps."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(
            decision="ALLOW",
            reason_codes=["RULE_A"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}],
        ))

        report = grader.grade()
        unmatched_gaps = [g for g in report.gaps if g.gap_type == "unmatched_rule"]
        assert len(unmatched_gaps) == 1
        assert unmatched_gaps[0].details["rule_name"] == "rule-b"

    def test_gap_identification_uncovered_actions(self):
        """NO_MATCHING_RULE decisions create uncovered action gaps."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(
            decision="BLOCK",
            reason_codes=["NO_MATCHING_RULE"],
            action_id="act_uncovered1234567890",
        ))

        report = grader.grade()
        uncovered_gaps = [g for g in report.gaps if g.gap_type == "uncovered_action"]
        assert len(uncovered_gaps) == 1
        assert uncovered_gaps[0].details["action_id"] == "act_uncovered1234567890"

    def test_decision_distribution(self):
        """Decision distribution counts are correct."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(decision="ALLOW", reason_codes=["R1"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}]))
        grader.record(_make_decision(decision="ALLOW", reason_codes=["R1"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}]))
        grader.record(_make_decision(decision="BLOCK", reason_codes=["R2"],
            matched_rules=[{"rule_name": "rule-b", "policy_set": "test-policy", "priority": 50}]))

        report = grader.grade()
        assert report.decision_distribution["ALLOW"] == 2
        assert report.decision_distribution["BLOCK"] == 1

    def test_recommendations_empty_in_phase1(self):
        """Phase 1 deterministic strategy produces no recommendations."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        grader.record(_make_decision(decision="ALLOW", reason_codes=["R1"],
            matched_rules=[{"rule_name": "rule-a", "policy_set": "test-policy", "priority": 100}]))

        report = grader.grade()
        assert report.recommendations == []

    def test_disabled_rules_excluded(self):
        """Disabled rules are not counted in coverage."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        # Even if we never match anything, disabled rules don't count
        report = grader.grade()
        assert report.total_rules == 2  # Only enabled rules

    def test_no_evaluations(self):
        """Edge case: no evaluations recorded."""
        policy = _make_policy(RULES)
        grader = PolicyGrader(policy)

        report = grader.grade()
        assert report.coverage_pct == 0.0
        assert report.total_evaluations == 0


class TestDeterministicGradingStrategy:
    """Tests for the deterministic strategy directly."""

    def test_analyze_returns_grading_report(self):
        data = GradingData(
            rule_match_counts={"rule-a": 5, "rule-b": 0},
            decision_type_counts={"ALLOW": 5},
            total_evaluations=5,
            policy_name="test",
            total_enabled_rules=2,
        )
        strategy = DeterministicGradingStrategy()
        report = strategy.analyze(data)

        assert report.coverage_pct == 50.0
        assert report.total_rules == 2
        assert report.rules_matched == 1
