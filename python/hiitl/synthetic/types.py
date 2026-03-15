"""Data types for the synthetic test runner.

Defines Pydantic models for:
- Scenario input format (scenarios, steps, assertions)
- Execution results (step results, scenario results)
- Grading output (coverage, effectiveness, gaps, recommendations)
- Run reports (top-level JSON output for UI consumption)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Scenario Input Types
# ============================================================================


class StepAction(str, Enum):
    """Valid step action types."""

    EVALUATE = "evaluate"
    APPROVE = "approve"  # Phase 2 — skipped in Phase 1
    EXECUTE = "execute"  # Phase 2 — skipped in Phase 1
    VERIFY_AUDIT = "verify_audit"  # Phase 2 — skipped in Phase 1


class ScenarioAssertion(BaseModel):
    """A single assertion on a step result.

    Supports field path resolution (dot notation) and multiple comparison types.

    Examples:
        {"field": "decision.allowed", "equals": false}
        {"field": "decision.decision", "equals": "REQUIRE_APPROVAL"}
        {"field": "decision.timing.evaluation_ms", "less_than": 10}
        {"field": "decision.resume_token", "exists": true}
    """

    field: str
    equals: Optional[Any] = None
    not_equals: Optional[Any] = None
    exists: Optional[bool] = None
    greater_than: Optional[float] = None
    less_than: Optional[float] = None
    contains: Optional[Any] = None


class ScenarioStep(BaseModel):
    """A single step in a scenario."""

    step: int
    name: str
    action: StepAction
    agent_id: Optional[str] = None
    envelope: Optional[Dict[str, Any]] = None
    expected_decision: Optional[str] = None
    expected_reason_codes: Optional[List[str]] = None
    expected_approval_metadata: Optional[Dict[str, Any]] = None
    assertions: Optional[List[ScenarioAssertion]] = None
    # Phase 2 fields (present in scenario JSON but skipped in Phase 1)
    approval_id: Optional[str] = None
    approver: Optional[Dict[str, Any]] = None
    approval_decision: Optional[str] = None
    approval_reason: Optional[str] = None
    approval_notes: Optional[str] = None
    action_id: Optional[str] = None
    expected_result: Optional[str] = None
    expected_audit_records: Optional[int] = None
    expected_events: Optional[List[Dict[str, Any]]] = None


class ScenarioVariation(BaseModel):
    """A variation of a scenario (alternative paths)."""

    description: str
    change_at_step: int
    change: Dict[str, Any]
    expected_outcome: str


class Scenario(BaseModel):
    """A complete test scenario."""

    scenario_id: str
    name: str
    description: str
    category: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_duration_seconds: Optional[int] = None
    policy_path: Optional[str] = None
    policy_set: Optional[Dict[str, Any]] = None
    steps: List[ScenarioStep]
    success_criteria: Optional[Dict[str, Any]] = None
    cleanup: Optional[Dict[str, Any]] = None
    narrative: Optional[Dict[str, Any]] = None
    variations: Optional[Dict[str, ScenarioVariation]] = None


# ============================================================================
# Execution Result Types
# ============================================================================


class AssertionResult(BaseModel):
    """Result of a single assertion check."""

    field: str
    passed: bool
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    check_type: Optional[str] = None  # equals, exists, greater_than, etc.
    error_message: Optional[str] = None


class StepResult(BaseModel):
    """Result of executing a single step."""

    step: int
    name: str
    action: str
    status: str  # "passed", "failed", "skipped", "error"
    decision: Optional[Dict[str, Any]] = None
    assertions: List[AssertionResult] = Field(default_factory=list)
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


class ScenarioResult(BaseModel):
    """Result of executing a complete scenario."""

    scenario_id: str
    scenario_name: str
    status: str  # "passed", "failed", "error"
    steps: List[StepResult]
    total_steps: int
    steps_passed: int
    steps_failed: int
    steps_skipped: int
    total_assertions: int
    assertions_passed: int
    assertions_failed: int
    total_latency_ms: float
    started_at: datetime
    completed_at: datetime


# ============================================================================
# Grading Types
# ============================================================================


class RuleEffectiveness(BaseModel):
    """Effectiveness data for a single rule."""

    rule_name: str
    policy_set: str
    matched_count: int
    total_evaluations: int
    effectiveness_pct: float


class CoverageGap(BaseModel):
    """An identified gap in policy coverage."""

    gap_type: str  # "unmatched_rule", "uncovered_action"
    description: str
    details: Dict[str, Any] = Field(default_factory=dict)


class PolicyRecommendation(BaseModel):
    """A suggested policy change.

    Phase 1: Empty (not populated).
    Future (LLM strategy): Populated with AI-generated rule suggestions.
    """

    type: str  # "add_rule", "modify_rule", "remove_rule"
    description: str
    rule_diff: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None


class GradingData(BaseModel):
    """Raw grading data collected during evaluation.

    This is the input to the grading strategy. The data collection is always
    deterministic; the interpretation/analysis is delegated to the strategy.
    """

    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    rule_match_counts: Dict[str, int] = Field(default_factory=dict)
    no_match_action_ids: List[str] = Field(default_factory=list)
    decision_type_counts: Dict[str, int] = Field(default_factory=dict)
    total_evaluations: int = 0
    policy_name: str = ""
    total_enabled_rules: int = 0


class GradingReport(BaseModel):
    """Policy grading results.

    Produced by a GradingStrategy from raw GradingData.
    """

    coverage_pct: float
    total_rules: int
    rules_matched: int
    rules_unmatched: int
    rule_effectiveness: List[RuleEffectiveness]
    gaps: List[CoverageGap]
    total_evaluations: int
    decision_distribution: Dict[str, int]
    recommendations: List[PolicyRecommendation] = Field(default_factory=list)


# ============================================================================
# Run Report (Top-level JSON output for UI)
# ============================================================================


class RunReport(BaseModel):
    """Complete run report — JSON output consumable by UI Testing page."""

    runner_version: str = "0.1.0"
    run_id: str
    mode: str  # "local" or "hosted"
    timestamp: datetime
    scenarios: List[ScenarioResult]
    grading: Optional[GradingReport] = None
    summary: Dict[str, Any]
