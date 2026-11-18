"""Conformance test runner for HIITL Python evaluator.

Loads language-neutral JSON test cases from tests/conformance/cases/ and validates
that the Python evaluator produces the expected decisions.

Each test case contains:
- envelope: Input execution envelope
- policy_set: Policy to evaluate
- expected_decision: Expected decision output

The runner validates that actual decision matches expected decision exactly.

A refusal case carries one artifact (envelope, policy_set or route) and `expected_refusal` in place of
`expected_decision`: the artifact is refused where the case says, naming what it says (R-0872, "no field is
ever silently dropped"), and nothing is evaluated.
"""

import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.route_types import Route
from hiitl.core.types import Decision, Envelope, PolicySet


# Path to conformance test cases
CONFORMANCE_CASES_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "tests" / "conformance" / "cases"


def load_test_cases() -> List[tuple[Path, Dict[str, Any]]]:
    """Load all conformance test case JSON files.

    Returns:
        List of (file_path, test_case_dict) tuples
    """
    test_cases = []

    if not CONFORMANCE_CASES_DIR.exists():
        pytest.skip(f"Conformance cases directory not found: {CONFORMANCE_CASES_DIR}")
        return test_cases

    # Recursively find all .json files (excluding INDEX.md)
    for json_file in sorted(CONFORMANCE_CASES_DIR.rglob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            test_case = json.load(f)
        test_cases.append((json_file, test_case))

    return test_cases


def get_test_category(test_file: Path) -> str:
    """Extract category from test file path.

    Args:
        test_file: Path to test case file

    Returns:
        Category name (e.g., "basic", "conditions", "logical_operators")
    """
    # Get parent directory name as category
    return test_file.parent.name


def compare_decisions(actual: Decision, expected: Dict[str, Any]) -> tuple[bool, str]:
    """Compare actual decision with expected decision.

    Args:
        actual: Actual decision from evaluator
        expected: Expected decision from test case

    Returns:
        Tuple of (matches: bool, error_message: str)
    """
    errors = []

    # Compare decision type (decision is already a string due to use_enum_values=True)
    actual_decision_str = actual.decision.value if hasattr(actual.decision, 'value') else actual.decision
    if actual_decision_str != expected["decision"]:
        errors.append(f"decision: expected '{expected['decision']}', got '{actual_decision_str}'")

    # Compare allowed flag
    if actual.allowed != expected["allowed"]:
        errors.append(f"allowed: expected {expected['allowed']}, got {actual.allowed}")

    # Compare reason codes
    actual_codes = sorted(actual.reason_codes)
    expected_codes = sorted(expected["reason_codes"])
    if actual_codes != expected_codes:
        errors.append(f"reason_codes: expected {expected_codes}, got {actual_codes}")

    # Optional: Compare policy version if present in expected
    if "policy_version" in expected:
        if actual.policy_version != expected["policy_version"]:
            errors.append(f"policy_version: expected '{expected['policy_version']}', got '{actual.policy_version}'")

    # Optional: Compare matched rules if present in expected
    if "matched_rules" in expected and expected["matched_rules"]:
        if not actual.matched_rules:
            errors.append(f"matched_rules: expected rules but got None")
        else:
            expected_rules = expected["matched_rules"]
            actual_rules = [
                {
                    "rule_name": r.rule_name,
                    "policy_set": r.policy_set,
                    "priority": r.priority,
                }
                for r in actual.matched_rules
            ]

            if len(actual_rules) != len(expected_rules):
                errors.append(f"matched_rules count: expected {len(expected_rules)}, got {len(actual_rules)}")
            else:
                for i, (expected_rule, actual_rule) in enumerate(zip(expected_rules, actual_rules)):
                    if expected_rule != actual_rule:
                        errors.append(f"matched_rules[{i}]: expected {expected_rule}, got {actual_rule}")

    # Optional: Compare resume_token presence if specified in expected
    if "resume_token" in expected:
        if expected["resume_token"] == "PRESENT":
            # Assert resume_token is non-null (exact value is random)
            if not actual.resume_token:
                errors.append("resume_token: expected non-null token, got None")
        elif expected["resume_token"] is None:
            if actual.resume_token is not None:
                errors.append(f"resume_token: expected None, got '{actual.resume_token}'")

    # Optional: Compare route_ref if present in expected
    if "route_ref" in expected:
        if actual.route_ref != expected["route_ref"]:
            errors.append(f"route_ref: expected '{expected['route_ref']}', got '{actual.route_ref}'")

    # Optional: Compare remediation if present in expected
    if "remediation" in expected:
        expected_rem = expected["remediation"]
        if actual.remediation is None:
            errors.append(f"remediation: expected {expected_rem}, got None")
        else:
            actual_rem = {
                "message": actual.remediation.message,
                "suggestion": actual.remediation.suggestion,
                "type": actual.remediation.type if isinstance(actual.remediation.type, str) else actual.remediation.type.value,
            }
            if actual.remediation.details is not None:
                actual_rem["details"] = actual.remediation.details
            if actual_rem != expected_rem:
                errors.append(f"remediation: expected {expected_rem}, got {actual_rem}")
    elif "remediation" not in expected:
        # If remediation is not in expected, ensure it's absent
        if actual.remediation is not None:
            errors.append(f"remediation: expected absent, got {actual.remediation}")

    # Optional: Compare would_be if present in expected (OBSERVE mode)
    if "would_be" in expected:
        if actual.would_be != expected["would_be"]:
            errors.append(f"would_be: expected '{expected['would_be']}', got '{actual.would_be}'")

    # Optional: Compare would_be_reason_codes if present in expected
    if "would_be_reason_codes" in expected:
        actual_wb_codes = sorted(actual.would_be_reason_codes or [])
        expected_wb_codes = sorted(expected["would_be_reason_codes"])
        if actual_wb_codes != expected_wb_codes:
            errors.append(f"would_be_reason_codes: expected {expected_wb_codes}, got {actual_wb_codes}")

    # Optional: Compare staged_observations if present in expected.
    # Block 5b conformance fixtures validated binding behavior but not
    # the staged_observations payload itself — both runners just
    # ignored the field. TICKET-109 / Sprint item 4 closes that gap:
    # when `expected_decision.staged_observations` is present, the
    # actual decision must match it element-for-element. This is the
    # only cross-language guarantee for side-by-side staged-rule
    # behavior — without it, would_be_binding semantics could diverge
    # silently between Python and TS.
    if "staged_observations" in expected:
        expected_obs = expected["staged_observations"]
        actual_obs_raw = actual.staged_observations or []
        # Normalize actual to plain dicts for comparison (Python model
        # uses Pydantic; would_be_decision is a DecisionType enum or
        # str depending on use_enum_values config).
        actual_obs = []
        for o in actual_obs_raw:
            decision_val = o.would_be_decision
            if hasattr(decision_val, "value"):
                decision_val = decision_val.value
            actual_obs.append({
                "rule_name": o.rule_name,
                "policy_set": o.policy_set,
                "priority": o.priority,
                "would_be_decision": decision_val,
                "would_be_reason_codes": list(o.would_be_reason_codes),
                "would_be_binding": o.would_be_binding,
            })
        if len(actual_obs) != len(expected_obs):
            errors.append(
                f"staged_observations count: expected {len(expected_obs)}, got {len(actual_obs)}"
            )
        else:
            for i, (e, a) in enumerate(zip(expected_obs, actual_obs)):
                if e != a:
                    errors.append(f"staged_observations[{i}]: expected {e}, got {a}")

    # rate_limit_rules (R-0852): matching windowed RATE_LIMIT rules, in walk order, element-for-element.
    if "rate_limit_rules" in expected:
        actual_rl = [r.model_dump(exclude_none=True) for r in (actual.rate_limit_rules or [])]
        if actual_rl != expected["rate_limit_rules"]:
            errors.append(f"rate_limit_rules: expected {expected['rate_limit_rules']}, got {actual_rl}")

    # missing_fields (HTL-22 row 176): each rule an absent field left unread, element-for-element; null means absent
    if "missing_fields" in expected:
        actual_mf = None if actual.missing_fields is None else [m.model_dump() for m in actual.missing_fields]
        if actual_mf != expected["missing_fields"]:
            errors.append(f"missing_fields: expected {expected['missing_fields']}, got {actual_mf}")

    if errors:
        return False, "\n  ".join(errors)
    return True, ""


# The artifacts a refusal case reads, each through its model
ARTIFACTS = {"envelope": Envelope, "policy_set": PolicySet, "route": Route}


def check_refusal(test_case: Dict[str, Any]) -> None:
    """The case's artifact is refused at exactly the paths it names (dotted; an undefined key's path ends in the
    key), and the refusal names each of its `names`."""
    refusal = test_case["expected_refusal"]
    artifact = refusal["artifact"]
    with pytest.raises(ValidationError) as caught:
        ARTIFACTS[artifact].model_validate(test_case[artifact])
    located = sorted({".".join(str(p) for p in e["loc"]) for e in caught.value.errors()})
    assert located == sorted(refusal["at"]), f"{test_case['test_id']}: refused at {located}, expected {refusal['at']}"
    for name in refusal.get("names", []):
        assert name in str(caught.value), f"{test_case['test_id']}: the refusal does not name {name!r}"


# Load all test cases
TEST_CASES = load_test_cases()

# Extract test IDs for parametrization
TEST_IDS = [test_case["test_id"] for _, test_case in TEST_CASES]


@pytest.mark.parametrize("test_file,test_case", TEST_CASES, ids=TEST_IDS)
def test_conformance(test_file: Path, test_case: Dict[str, Any]):
    """Run a single conformance test case.

    Args:
        test_file: Path to test case file
        test_case: Test case dictionary
    """
    if "expected_refusal" in test_case:
        check_refusal(test_case)
        return

    # Extract test data
    test_id = test_case["test_id"]
    description = test_case.get("description", "")
    envelope_dict = test_case["envelope"]
    policy_dict = test_case["policy_set"]
    expected_decision = test_case["expected_decision"]

    # Extract optional mode (for OBSERVE tests)
    mode = test_case.get("mode", "RESPECT_POLICY")

    # Parse envelope and policy
    try:
        envelope = Envelope(**envelope_dict)
        policy = PolicySet(**policy_dict)
    except Exception as e:
        pytest.fail(f"Failed to parse test case {test_id}: {e}")

    # Run evaluator
    evaluator = PolicyEvaluator()
    try:
        actual_decision = evaluator.evaluate(envelope, policy, mode=mode, enrichment=test_case.get("enrichment"))
    except Exception as e:
        pytest.fail(f"Evaluator raised exception for test {test_id}: {e}")

    # Check performance requirement (< 1ms evaluation time)
    if actual_decision.timing.evaluation_ms > 1.0:
        warnings.warn(
            f"Performance requirement violated for test {test_id}: "
            f"evaluation took {actual_decision.timing.evaluation_ms:.3f}ms (expected < 1.0ms)",
            UserWarning
        )

    # Compare decisions
    matches, error_msg = compare_decisions(actual_decision, expected_decision)

    if not matches:
        # Build detailed failure message
        actual_decision_str = actual_decision.decision.value if hasattr(actual_decision.decision, 'value') else actual_decision.decision
        failure_msg = f"""
Conformance test failed: {test_id}
Description: {description}

Expected decision:
  decision: {expected_decision['decision']}
  allowed: {expected_decision['allowed']}
  reason_codes: {expected_decision['reason_codes']}

Actual decision:
  decision: {actual_decision_str}
  allowed: {actual_decision.allowed}
  reason_codes: {actual_decision.reason_codes}

Differences:
  {error_msg}

Test file: {test_file}
"""
        pytest.fail(failure_msg)


# Category markers for filtering
def pytest_configure(config):
    """Register custom markers for test categories."""
    categories = [
        "basic",
        "conditions",
        "logical_operators",
        "priority",
        "nested",
        "decisions",
        "edge_cases",
        "escalation",
        "kill_switch",
        "remediation",
    ]

    for category in categories:
        config.addinivalue_line(
            "markers",
            f"{category}: Tests in the {category} category"
        )


def pytest_collection_modifyitems(config, items):
    """Add category markers to tests based on file path."""
    for item in items:
        # Get test file path from item
        if hasattr(item, "callspec") and "test_file" in item.callspec.params:
            test_file = item.callspec.params["test_file"]
            category = get_test_category(test_file)

            # Add marker for category
            item.add_marker(getattr(pytest.mark, category))
