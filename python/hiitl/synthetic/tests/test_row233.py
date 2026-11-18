"""Row 233 (HTL-29): a scenario step names its action once, as the envelope does.

Ruled 2026-11-09: "a scenario step names its action as the envelope does, `action`; `tool` is refused as a field the
step does not define". synthetic/README.md "Step Types" is the format's spec: a step's envelope is a call to
`evaluate()`, its members read from the call's own signature, and the format refuses a member it does not define
(R-0872, "no field is ever silently dropped"). Design: the HTL-29 test design, row 233.
"""

from __future__ import annotations

import inspect
import json
import shutil

import pytest
from pydantic import ValidationError

from hiitl import HIITL
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import Envelope, PolicySet
from hiitl.synthetic import cli
from hiitl.synthetic.executor import ScenarioExecutor
from hiitl.synthetic.scenario_loader import ScenarioLoader, ScenarioLoadError
from hiitl.synthetic.types import Scenario, ScenarioAssertion, ScenarioStep, ScenarioVariation

# What the call takes, read from the call: each keyword evaluate() names that the envelope carries
TAKEN = [n for n in inspect.signature(HIITL.evaluate).parameters if n != "self" and n in Envelope.model_fields]

# A value for each member taken, as JSON writes it; the first cell holds this table to TAKEN
SAMPLES = {
    "action": "tool_a", "parameters": {"amount": 5}, "target": {"id": "t_1"}, "operation": "read",
    "user_id": "user_1", "session_id": "sess_1", "agent_id": "agent_2", "confidence": 0.5, "reason": "a refund",
    "sensitivity": ["money"], "cost_estimate": {"dollars": 1.5}, "requested_scopes": ["payments:write"],
    "idempotency_key": "idem_step_one", "correlation_id": "req_1",
}

POLICY = PolicySet(name="p", version="v1.0.0", description="The p set",
                   scope={"org_id": "org_devlocal0000000000", "environment": "dev"},
                   rules=[{"name": "allow", "description": "allow", "priority": 1, "decision": "ALLOW",
                           "reason_code": "OK", "conditions": {"field": "action", "operator": "exists", "value": True}}])


def _step(envelope, action="evaluate"):
    return {"step": 3, "name": "a step", "action": action, "envelope": envelope}


def _refusal(build) -> str:
    with pytest.raises(ValidationError) as e:
        build()
    return str(e.value)


def test_every_scenario_the_repository_carries_loads_each_evaluate_step_naming_action():
    loader = ScenarioLoader()
    names = loader.list_available()
    assert names, "the repository carries scenarios"
    for name in names:
        evaluates = [s for s in loader.load(name).steps if s.action == "evaluate"]
        assert evaluates and all(s.envelope.get("action") for s in evaluates), name


def test_each_member_the_call_takes_is_carried_into_the_evaluated_envelope():
    assert sorted(SAMPLES) == sorted(TAKEN), "a sample for each member evaluate() takes, and no other"
    assert TAKEN[0] == "action" and "principal_token" not in TAKEN
    env = ScenarioExecutor(PolicyEvaluator(), POLICY)._build_envelope_from_step(ScenarioStep(**_step(SAMPLES)))
    carried = env.model_dump(mode="json", exclude_none=True)
    for name, value in SAMPLES.items():
        assert carried.get(name) == value, name


def test_a_member_the_call_defaults_is_defaulted_as_the_call_defaults_it():
    env = ScenarioExecutor(PolicyEvaluator(), POLICY)._build_envelope_from_step(
        ScenarioStep(**{**_step({"action": "tool_a"}), "agent_id": "step-agent"}))
    defaults = inspect.signature(HIITL.evaluate).parameters
    assert env.operation == defaults["operation"].default
    assert (env.parameters, env.target) == ({}, {})
    assert env.agent_id == "step-agent", "the step's agent_id stands where the call names none"
    env = ScenarioExecutor(PolicyEvaluator(), POLICY)._build_envelope_from_step(
        ScenarioStep(**{**_step({"action": "tool_a", "agent_id": "agent_2"}), "agent_id": "step-agent"}))
    assert env.agent_id == "agent_2", "the call's agent_id overrides the step's"


@pytest.mark.parametrize("member", ["tool", "tool_name", "amount", "principal_token"])
def test_a_step_envelope_naming_a_member_the_call_does_not_take_is_refused(member):
    msg = _refusal(lambda: ScenarioStep(**_step({"action": "tool_a", member: "x"})))
    assert f"step 3's envelope names '{member}'" in msg
    assert ", ".join(TAKEN) in msg, "the refusal lists the members a step takes"
    if member == "tool_name":
        assert "renamed 'action'" in msg
    if member == "principal_token":
        assert "evaluate() takes that the envelope does not carry" in msg, "it names why it is not taken"


def test_through_the_loader_the_refusal_names_the_scenario_the_step_and_the_member(tmp_path):
    bad = json.loads((ScenarioLoader().scenarios_dir / "basic-allow-block.json").read_text())
    bad["steps"][1]["envelope"]["tool"] = bad["steps"][1]["envelope"].pop("action")
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ScenarioLoadError) as e:
        ScenarioLoader(str(tmp_path)).load("bad")
    assert "'bad'" in str(e.value) and f"step {bad['steps'][1]['step']}'s envelope names 'tool'" in str(e.value)


@pytest.mark.parametrize("envelope", [{"operation": "read"}, None])
def test_an_evaluate_step_names_an_action(envelope):
    msg = _refusal(lambda: ScenarioStep(**_step(envelope)))
    assert "step 3" in msg and "'action'" in msg
    try:
        ScenarioStep(**_step(None, action="approve"))
    except ValidationError as e:
        pytest.fail(f"a step the runner does not run needs no action, and was refused: {e}")


@pytest.mark.parametrize("model,data,member", [
    (Scenario, {"scenario_id": "s", "name": "n", "description": "d", "steps": [], "stepz": []}, "stepz"),
    (ScenarioStep, {**_step({"action": "tool_a"}), "expect_decision": "ALLOW"}, "expect_decision"),
    (ScenarioAssertion, {"field": "decision.allowed", "equal": True}, "equal"),
    (ScenarioVariation, {"description": "d", "change_at_step": 1, "change": {}, "expected_outcome": "o", "x": 1}, "x"),
])
def test_the_format_refuses_a_member_it_does_not_define(model, data, member):
    assert member in _refusal(lambda: model(**data))


def test_run_all_stops_on_a_refused_scenario_naming_it_and_runs_none(tmp_path, capsys):
    source = ScenarioLoader().scenarios_dir
    for name in ScenarioLoader().list_available():
        shutil.copy(source / f"{name}.json", tmp_path)
    bad = json.loads((source / "basic-allow-block.json").read_text())
    bad["steps"][0]["envelope"]["tool"] = "process_payment"
    (tmp_path / "zz-refused.json").write_text(json.dumps(bad))
    try:
        code = cli.main(["run", "--all", "--json", "--scenarios-dir", str(tmp_path)])
    except ScenarioLoadError as e:
        pytest.fail(f"the refusal escaped the command, which names it and exits 2: {e}")
    out = capsys.readouterr()
    assert code == 2
    assert "'zz-refused'" in out.err and "envelope names 'tool'" in out.err
    assert out.out == "", "no scenario is run and no report written"
