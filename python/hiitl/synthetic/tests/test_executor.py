"""Tests for the scenario executor."""

import pytest
from types import SimpleNamespace

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import PolicySet
from hiitl.synthetic.executor import ScenarioExecutor
from hiitl.synthetic.grader import PolicyGrader
from hiitl.synthetic.types import Scenario, ScenarioAssertion, ScenarioStep


SIMPLE_POLICY = PolicySet(
    name="test-policy",
    version="v1.0.0",
    description="The test-policy set",
    scope={"org_id": "org_devlocal0000000000", "environment": "dev"},
    rules=[
        {
            "name": "allow-tool-a",
            "description": "Allow tool_a",
            "priority": 100,
            "conditions": {"field": "action", "operator": "equals", "value": "tool_a"},
            "decision": "ALLOW",
            "reason_code": "ALLOWED",
        },
        {
            "name": "block-tool-b",
            "description": "Block tool_b",
            "priority": 50,
            "conditions": {"field": "action", "operator": "equals", "value": "tool_b"},
            "decision": "BLOCK",
            "reason_code": "BLOCKED",
        },
    ],
)


class TestScenarioExecutor:
    """Tests for ScenarioExecutor."""

    def test_evaluate_step_passes(self):
        """An evaluate step with correct assertions passes."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test scenario",
            steps=[
                ScenarioStep(
                    step=1,
                    name="Allow tool_a",
                    action="evaluate",
                    envelope={
                        "action": "tool_a",
                        "operation": "execute",
                        "target": {"id": "123"},
                        "parameters": {},
                    },
                    expected_decision="ALLOW",
                    assertions=[
                        ScenarioAssertion(field="decision.allowed", equals=True),
                    ],
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.status == "passed"
        assert result.steps_passed == 1
        assert result.steps_failed == 0
        expected_fields = ["decision.decision", "decision.allowed"]
        assert [a.field for a in result.steps[0].assertions if a.passed] == expected_fields
        assert result.assertions_passed == len(expected_fields)

    def test_evaluate_step_fails_wrong_decision(self):
        """Step fails when actual decision doesn't match expected."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test scenario",
            steps=[
                ScenarioStep(
                    step=1,
                    name="Expect BLOCK but get ALLOW",
                    action="evaluate",
                    envelope={
                        "action": "tool_a",
                        "operation": "execute",
                        "target": {"id": "123"},
                        "parameters": {},
                    },
                    expected_decision="BLOCK",  # Wrong - tool_a is ALLOW
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.status == "failed"
        assert result.steps_failed == 1

    def test_phase2_steps_skipped(self):
        """approve, execute, verify_audit steps are skipped."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test scenario",
            steps=[
                ScenarioStep(step=1, name="Evaluate", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}}),
                ScenarioStep(step=2, name="Approve", action="approve"),
                ScenarioStep(step=3, name="Execute", action="execute"),
                ScenarioStep(step=4, name="Verify", action="verify_audit"),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.status == "passed"
        assert result.steps_passed == 1
        assert result.steps_skipped == 3
        assert result.steps[1].status == "skipped"
        assert "not run by the synthetic runner" in result.steps[1].skipped_reason

    def test_assertion_failure_fails_step(self):
        """A failing assertion fails the step."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test scenario",
            steps=[
                ScenarioStep(
                    step=1,
                    name="Wrong assertion",
                    action="evaluate",
                    envelope={
                        "action": "tool_a",
                        "operation": "execute",
                        "target": {"id": "123"},
                        "parameters": {},
                    },
                    assertions=[
                        ScenarioAssertion(field="decision.allowed", equals=False),  # Wrong
                    ],
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.status == "failed"
        expected_fields = [a.field for a in scenario.steps[0].assertions]
        assert [a.field for a in result.steps[0].assertions if not a.passed] == expected_fields
        assert result.assertions_failed == len(expected_fields)

    def test_multiple_evaluate_steps(self, monkeypatch):
        """Multiple evaluate steps work correctly."""
        clock = iter([10.0, 10.125, 20.0, 20.5])
        monkeypatch.setattr("hiitl.synthetic.executor.time", SimpleNamespace(perf_counter=lambda: next(clock)))
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Multi-step test",
            steps=[
                ScenarioStep(
                    step=1, name="Allow", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                    expected_decision="ALLOW",
                ),
                ScenarioStep(
                    step=2, name="Block", action="evaluate",
                    envelope={"action": "tool_b", "operation": "execute",
                              "target": {"id": "2"}, "parameters": {}},
                    expected_decision="BLOCK",
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.status == "passed"
        assert result.steps_passed == 2
        assert [step.latency_ms for step in result.steps] == [125.0, 500.0]
        assert result.total_latency_ms == 625.0

    def test_grader_records_decisions(self):
        """PolicyGrader receives decisions from executed steps."""
        grader = PolicyGrader(SIMPLE_POLICY)
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Test with grader",
            steps=[
                ScenarioStep(
                    step=1, name="Allow", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
            grader=grader,
        )
        executor.run(scenario)

        report = grader.grade()
        assert report.total_evaluations == 1
        assert report.decision_distribution.get("ALLOW", 0) == 1

    def test_latency_tracking(self, monkeypatch):
        """Each step records latency."""
        clock = iter([10.0, 10.125])
        monkeypatch.setattr("hiitl.synthetic.executor.time", SimpleNamespace(perf_counter=lambda: next(clock)))
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Latency test",
            steps=[
                ScenarioStep(
                    step=1, name="Step 1", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)

        assert result.steps[0].latency_ms is not None
        assert result.steps[0].latency_ms == 125.0

    def test_tool_field_mapping(self):
        """Scenario envelope 'tool' maps to Envelope 'action'."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Field mapping test",
            steps=[
                ScenarioStep(
                    step=1, name="Map tool", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                    expected_decision="ALLOW",
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)
        assert result.status == "passed"

    def test_expected_reason_codes(self):
        """expected_reason_codes validation works."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Reason codes test",
            steps=[
                ScenarioStep(
                    step=1, name="Check codes", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                    expected_reason_codes=["ALLOWED"],
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)
        assert result.status == "passed"

    def test_scenario_result_timestamps(self):
        """ScenarioResult has valid start/end timestamps."""
        scenario = Scenario(
            scenario_id="test",
            name="Test",
            description="Timestamp test",
            steps=[
                ScenarioStep(
                    step=1, name="Step", action="evaluate",
                    envelope={"action": "tool_a", "operation": "execute",
                              "target": {"id": "1"}, "parameters": {}},
                ),
            ],
        )

        executor = ScenarioExecutor(
            evaluator=PolicyEvaluator(),
            policy=SIMPLE_POLICY,
        )
        result = executor.run(scenario)
        assert result.started_at <= result.completed_at
