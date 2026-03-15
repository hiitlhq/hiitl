"""Policy grading engine — coverage, effectiveness, gap analysis.

Two-layer design:
1. PolicyGrader: Collects raw data (always deterministic)
2. GradingStrategy: Analyzes data and produces report (pluggable)

Phase 1: DeterministicGradingStrategy (coverage %, rules matched, gaps)
Future: LLMGradingStrategy (pattern analysis, recommendations, standards assessment)
"""

from typing import Dict, List, Optional, Protocol

from hiitl.core.types import Decision, PolicySet

from .types import (
    CoverageGap,
    GradingData,
    GradingReport,
    PolicyRecommendation,
    RuleEffectiveness,
)


class GradingStrategy(Protocol):
    """Protocol for grading strategy implementations.

    Phase 1: DeterministicGradingStrategy
    Future: LLMGradingStrategy, StandardsGradingStrategy
    """

    def analyze(self, data: GradingData) -> GradingReport:
        """Analyze raw grading data and produce a report."""
        ...


class DeterministicGradingStrategy:
    """Phase 1 grading: deterministic coverage-based analysis.

    Calculates:
    - Coverage %: rules matched at least once / total enabled rules
    - Rule effectiveness: per-rule match counts
    - Gaps: unmatched rules, uncovered actions
    - Decision distribution: count per decision type
    """

    def analyze(self, data: GradingData) -> GradingReport:
        """Analyze raw grading data deterministically."""
        total_enabled = data.total_enabled_rules
        matched = sum(1 for count in data.rule_match_counts.values() if count > 0)
        unmatched = total_enabled - matched
        coverage_pct = (matched / total_enabled * 100) if total_enabled > 0 else 0.0

        # Per-rule effectiveness
        effectiveness = [
            RuleEffectiveness(
                rule_name=name,
                policy_set=data.policy_name,
                matched_count=count,
                total_evaluations=data.total_evaluations,
                effectiveness_pct=(
                    (count / data.total_evaluations * 100)
                    if data.total_evaluations > 0
                    else 0.0
                ),
            )
            for name, count in data.rule_match_counts.items()
        ]

        # Gaps
        gaps: List[CoverageGap] = []
        for name, count in data.rule_match_counts.items():
            if count == 0:
                gaps.append(
                    CoverageGap(
                        gap_type="unmatched_rule",
                        description=f"Rule '{name}' never matched any evaluation",
                        details={"rule_name": name, "policy_set": data.policy_name},
                    )
                )
        for action_id in data.no_match_action_ids:
            gaps.append(
                CoverageGap(
                    gap_type="uncovered_action",
                    description=f"Action '{action_id}' had no matching rule (defaulted to BLOCK)",
                    details={"action_id": action_id},
                )
            )

        return GradingReport(
            coverage_pct=round(coverage_pct, 1),
            total_rules=total_enabled,
            rules_matched=matched,
            rules_unmatched=unmatched,
            rule_effectiveness=effectiveness,
            gaps=gaps,
            total_evaluations=data.total_evaluations,
            decision_distribution=data.decision_type_counts,
            recommendations=[],  # Empty in Phase 1
        )


class PolicyGrader:
    """Collects evaluation data and delegates analysis to a grading strategy.

    The data collection is always deterministic. The interpretation of that
    data is delegated to the strategy, which can be swapped (deterministic now,
    LLM-powered later).

    Args:
        policy: PolicySet being graded
        strategy: GradingStrategy implementation (defaults to DeterministicGradingStrategy)
    """

    def __init__(
        self,
        policy: PolicySet,
        strategy: Optional[GradingStrategy] = None,
    ):
        self._policy = policy
        self._strategy = strategy or DeterministicGradingStrategy()

        # Initialize tracking for all enabled rules
        self._rule_match_counts: Dict[str, int] = {
            rule.name: 0 for rule in policy.rules if rule.enabled
        }
        self._evaluation_count = 0
        self._decision_counts: Dict[str, int] = {}
        self._no_match_actions: List[str] = []

    def record(self, decision: Decision) -> None:
        """Record a decision for grading.

        This is the deterministic data collection layer — it only counts
        and categorizes, never interprets.
        """
        self._evaluation_count += 1

        # Track decision type
        dec_type = (
            decision.decision
            if isinstance(decision.decision, str)
            else decision.decision.value
        )
        self._decision_counts[dec_type] = self._decision_counts.get(dec_type, 0) + 1

        # Track matched rules
        if decision.matched_rules:
            for mr in decision.matched_rules:
                if mr.rule_name in self._rule_match_counts:
                    self._rule_match_counts[mr.rule_name] += 1

        # Track no-match
        if "NO_MATCHING_RULE" in decision.reason_codes:
            self._no_match_actions.append(decision.action_id)

    def grade(self) -> GradingReport:
        """Produce the grading report by delegating to the strategy."""
        data = GradingData(
            rule_match_counts=dict(self._rule_match_counts),
            no_match_action_ids=list(self._no_match_actions),
            decision_type_counts=dict(self._decision_counts),
            total_evaluations=self._evaluation_count,
            policy_name=self._policy.name,
            total_enabled_rules=len(self._rule_match_counts),
        )
        return self._strategy.analyze(data)
