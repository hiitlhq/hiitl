"""HIITL Synthetic Test Runner.

CLI tool for running synthetic test scenarios, generating envelopes
from agent personas, and grading policy effectiveness.

Usage:
    python -m hiitl.synthetic run <scenario-name>
    python -m hiitl.synthetic list
    python -m hiitl.synthetic generate <agent-id> -n 100
    python -m hiitl.synthetic grade <policy-path> --agent <agent-id>
"""

from .assertions import resolve_field_path, validate_all_assertions, validate_assertion
from .envelope_factory import EnvelopeFactory
from .executor import ScenarioExecutor
from .grader import DeterministicGradingStrategy, PolicyGrader
from .scenario_loader import ScenarioLoader

__all__ = [
    "EnvelopeFactory",
    "PolicyGrader",
    "DeterministicGradingStrategy",
    "ScenarioExecutor",
    "ScenarioLoader",
    "resolve_field_path",
    "validate_assertion",
    "validate_all_assertions",
]
