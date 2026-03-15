"""Scenario executor — runs scenario steps and collects results.

Phase 1 implementation:
- "evaluate" steps: Execute via PolicyEvaluator, validate assertions
- "approve", "execute", "verify_audit" steps: SKIPPED (Phase 2 Reviewer Cockpit)

Uses PolicyEvaluator directly (not the HIITL SDK client) for fast, lightweight
testing without audit DB creation or rate limiter state.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import Decision, Envelope, PolicySet

from .assertions import validate_all_assertions
from .grader import PolicyGrader
from .types import (
    AssertionResult,
    Scenario,
    ScenarioAssertion,
    ScenarioResult,
    ScenarioStep,
    StepResult,
)

# Phase 2 step types that are skipped in Phase 1
_PHASE2_ACTIONS = {"approve", "execute", "verify_audit"}

# Variable reference pattern: ${step_N_response.field.path}
_VAR_PATTERN = re.compile(r"\$\{step_(\d+)_response\.(.+?)\}")


class ScenarioExecutor:
    """Executes a scenario against a policy.

    Args:
        evaluator: PolicyEvaluator instance
        policy: PolicySet to evaluate against
        grader: Optional PolicyGrader for recording decisions
        org_id: Org ID for envelope generation
        environment: Environment for envelope generation
    """

    def __init__(
        self,
        evaluator: PolicyEvaluator,
        policy: PolicySet,
        grader: Optional[PolicyGrader] = None,
        org_id: str = "org_synthetictest00001",
        environment: str = "dev",
    ):
        self._evaluator = evaluator
        self._policy = policy
        self._grader = grader
        self._org_id = org_id
        self._environment = environment
        self._step_results: Dict[int, Dict[str, Any]] = {}

    def run(self, scenario: Scenario) -> ScenarioResult:
        """Execute all steps in a scenario, collecting results."""
        started_at = datetime.now(timezone.utc)
        step_results: List[StepResult] = []
        total_latency = 0.0

        for step in scenario.steps:
            result = self._execute_step(step)
            step_results.append(result)
            if result.latency_ms:
                total_latency += result.latency_ms

        completed_at = datetime.now(timezone.utc)

        # Calculate stats
        passed = sum(1 for r in step_results if r.status == "passed")
        failed = sum(1 for r in step_results if r.status == "failed")
        skipped = sum(1 for r in step_results if r.status == "skipped")
        errored = sum(1 for r in step_results if r.status == "error")

        total_assertions = sum(len(r.assertions) for r in step_results)
        assertions_passed = sum(
            sum(1 for a in r.assertions if a.passed) for r in step_results
        )
        assertions_failed = total_assertions - assertions_passed

        # Overall status: passed if no failures/errors among executed steps
        if errored > 0:
            status = "error"
        elif failed > 0:
            status = "failed"
        else:
            status = "passed"

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            status=status,
            steps=step_results,
            total_steps=len(step_results),
            steps_passed=passed,
            steps_failed=failed,
            steps_skipped=skipped,
            total_assertions=total_assertions,
            assertions_passed=assertions_passed,
            assertions_failed=assertions_failed,
            total_latency_ms=round(total_latency, 3),
            started_at=started_at,
            completed_at=completed_at,
        )

    def _execute_step(self, step: ScenarioStep) -> StepResult:
        """Execute a single step based on its action type."""
        action = step.action if isinstance(step.action, str) else step.action.value

        if action == "evaluate":
            return self._execute_evaluate_step(step)
        elif action in _PHASE2_ACTIONS:
            return self._skip_step(
                step,
                f"Phase 2: '{action}' action requires Reviewer Cockpit API (not available in Phase 1)",
            )
        else:
            return StepResult(
                step=step.step,
                name=step.name,
                action=action,
                status="error",
                error=f"Unknown action type: '{action}'",
            )

    def _execute_evaluate_step(self, step: ScenarioStep) -> StepResult:
        """Execute an 'evaluate' step."""
        try:
            # Build envelope from step data
            envelope = self._build_envelope_from_step(step)

            # Time the evaluation
            start = time.perf_counter()
            decision = self._evaluator.evaluate(envelope, self._policy)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Serialize decision for assertion context
            decision_dict = self._serialize_decision(decision)
            context = {"decision": decision_dict}

            # Store for variable substitution in later steps
            self._step_results[step.step] = decision_dict

            # Record with grader
            if self._grader:
                self._grader.record(decision)

            # Validate assertions
            assertion_results: List[AssertionResult] = []
            step_failed = False

            # Check expected_decision
            if step.expected_decision:
                dec_value = (
                    decision.decision
                    if isinstance(decision.decision, str)
                    else decision.decision.value
                )
                if dec_value != step.expected_decision:
                    assertion_results.append(
                        AssertionResult(
                            field="decision.decision",
                            passed=False,
                            actual_value=dec_value,
                            expected_value=step.expected_decision,
                            check_type="expected_decision",
                            error_message=f"Expected decision '{step.expected_decision}', got '{dec_value}'",
                        )
                    )
                    step_failed = True
                else:
                    assertion_results.append(
                        AssertionResult(
                            field="decision.decision",
                            passed=True,
                            actual_value=dec_value,
                            expected_value=step.expected_decision,
                            check_type="expected_decision",
                        )
                    )

            # Check expected_reason_codes
            if step.expected_reason_codes:
                actual_codes = sorted(decision.reason_codes)
                expected_codes = sorted(step.expected_reason_codes)
                if actual_codes != expected_codes:
                    assertion_results.append(
                        AssertionResult(
                            field="decision.reason_codes",
                            passed=False,
                            actual_value=actual_codes,
                            expected_value=expected_codes,
                            check_type="expected_reason_codes",
                            error_message=f"Expected reason codes {expected_codes}, got {actual_codes}",
                        )
                    )
                    step_failed = True
                else:
                    assertion_results.append(
                        AssertionResult(
                            field="decision.reason_codes",
                            passed=True,
                            actual_value=actual_codes,
                            expected_value=expected_codes,
                            check_type="expected_reason_codes",
                        )
                    )

            # Check explicit assertions
            if step.assertions:
                results = validate_all_assertions(
                    [ScenarioAssertion(**a.model_dump()) for a in step.assertions],
                    context,
                )
                assertion_results.extend(results)
                if any(not r.passed for r in results):
                    step_failed = True

            status = "failed" if step_failed else "passed"
            return StepResult(
                step=step.step,
                name=step.name,
                action="evaluate",
                status=status,
                decision=decision_dict,
                assertions=assertion_results,
                latency_ms=round(elapsed_ms, 3),
            )

        except Exception as e:
            return StepResult(
                step=step.step,
                name=step.name,
                action="evaluate",
                status="error",
                error=str(e),
            )

    def _build_envelope_from_step(self, step: ScenarioStep) -> Envelope:
        """Build a complete Envelope from the partial fields in a scenario step.

        Scenario steps use developer-facing field names (tool, operation, target, parameters).
        This method fills in all required Envelope fields.
        """
        env_data = step.envelope or {}

        # Map scenario field names to Envelope field names
        # Prefer "action", fall back to "tool" or "tool_name" for backward compat
        action_name = env_data.get("action") or env_data.get("tool") or env_data.get("tool_name", "unknown_tool")
        operation = env_data.get("operation", "execute")
        target = env_data.get("target", {})
        parameters = env_data.get("parameters", {})
        sensitivity = env_data.get("sensitivity")
        reason = env_data.get("reason")

        # Resolve variable references in values
        target = self._substitute_variables(target)
        parameters = self._substitute_variables(parameters)

        agent_id = step.agent_id or "synthetic-agent"

        return Envelope(
            schema_version="v1.0",
            org_id=self._org_id,
            environment=self._environment,
            agent_id=agent_id,
            action_id=f"act_{uuid4().hex[:20]}",
            idempotency_key=f"idem_scenario_step_{step.step}_{uuid4().hex[:8]}",
            action=action_name,
            operation=operation,
            target=target,
            parameters=parameters,
            timestamp=datetime.now(timezone.utc),
            signature="0" * 64,
            sensitivity=sensitivity,
            reason=reason,
        )

    def _substitute_variables(self, value: Any) -> Any:
        """Resolve ${step_N_response.field.path} variable references."""
        if isinstance(value, str):
            match = _VAR_PATTERN.match(value)
            if match:
                step_num = int(match.group(1))
                field_path = match.group(2)
                if step_num in self._step_results:
                    # Resolve the field path in the stored step result
                    from .assertions import resolve_field_path

                    resolved, found = resolve_field_path(
                        self._step_results[step_num], field_path
                    )
                    return resolved if found else value
            return value
        elif isinstance(value, dict):
            return {k: self._substitute_variables(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._substitute_variables(v) for v in value]
        return value

    def _serialize_decision(self, decision: Decision) -> Dict[str, Any]:
        """Serialize a Decision to dict for assertion context and storage."""
        d = decision.model_dump()
        # Ensure enum values are strings
        if isinstance(d.get("decision"), str):
            pass
        elif hasattr(d.get("decision"), "value"):
            d["decision"] = d["decision"].value
        return d

    def _skip_step(self, step: ScenarioStep, reason: str) -> StepResult:
        """Return a skipped StepResult for Phase 2 step types."""
        action = step.action if isinstance(step.action, str) else step.action.value
        return StepResult(
            step=step.step,
            name=step.name,
            action=action,
            status="skipped",
            skipped_reason=reason,
        )
