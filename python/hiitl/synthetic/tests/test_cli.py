"""CLI smoke tests for the synthetic test runner."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI and capture output."""
    return subprocess.run(
        [sys.executable, "-m", "hiitl.synthetic", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent.parent),
    )


class TestCLIList:
    """Tests for the 'list' subcommand."""

    def test_list_shows_scenarios(self):
        result = _run_cli("list")
        assert result.returncode == 0
        assert "basic-allow-block" in result.stdout
        assert "high-value-payment-approval" in result.stdout

    def test_list_shows_descriptions(self):
        result = _run_cli("list")
        assert "Smoke test" in result.stdout


class TestCLIRun:
    """Tests for the 'run' subcommand."""

    def test_run_passing_scenario(self):
        result = _run_cli("run", "basic-allow-block")
        assert result.returncode == 0
        assert "PASSED" in result.stdout

    def test_run_all(self):
        result = _run_cli("run", "--all")
        assert result.returncode == 0
        assert "Summary" in result.stdout

    def test_run_json_output(self):
        result = _run_cli("run", "basic-allow-block", "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["passed"] == 1
        assert data["summary"]["failed"] == 0

    def test_run_missing_scenario(self):
        result = _run_cli("run", "nonexistent-scenario")
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()

    def test_run_exit_code_zero_on_pass(self):
        result = _run_cli("run", "basic-allow-block")
        assert result.returncode == 0

    def test_run_with_policy_override(self):
        result = _run_cli(
            "run", "basic-allow-block",
            "--policy", "../synthetic/policies/payment-policy.json",
        )
        assert result.returncode == 0


class TestCLIGenerate:
    """Tests for the 'generate' subcommand."""

    def test_generate_envelopes(self):
        result = _run_cli("generate", "payment-agent", "-n", "3", "--seed", "42")
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(lines) == 3
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert data["agent_id"] == "payment-agent"

    def test_generate_deterministic(self):
        """Same seed produces same tool selection and parameters (timestamps differ)."""
        result1 = _run_cli("generate", "payment-agent", "-n", "2", "--seed", "42")
        result2 = _run_cli("generate", "payment-agent", "-n", "2", "--seed", "42")
        lines1 = [json.loads(l) for l in result1.stdout.strip().split("\n")]
        lines2 = [json.loads(l) for l in result2.stdout.strip().split("\n")]
        for e1, e2 in zip(lines1, lines2):
            assert e1["action_id"] == e2["action_id"]
            assert e1["action"] == e2["action"]
            assert e1["parameters"] == e2["parameters"]


class TestCLIGrade:
    """Tests for the 'grade' subcommand."""

    def test_grade_produces_output(self):
        result = _run_cli(
            "grade", "../synthetic/policies/payment-policy.json",
            "--agent", "payment-agent", "-n", "50", "--seed", "42",
        )
        assert result.returncode == 0
        assert "Coverage" in result.stdout

    def test_grade_json_output(self):
        result = _run_cli(
            "grade", "../synthetic/policies/payment-policy.json",
            "--agent", "payment-agent", "-n", "50", "--seed", "42", "--json",
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "coverage_pct" in data
        assert "rule_effectiveness" in data
