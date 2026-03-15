"""Assertion validation engine for scenario steps.

Validates assertions against Decision objects (serialized as dicts).
Supports field path resolution with dot notation and array indexing.

Assertion types:
- equals: exact equality
- not_equals: inequality
- exists: non-None check
- greater_than / less_than: numeric comparison
- contains: string/list containment
"""

import re
from typing import Any, List, Optional, Tuple

from .types import AssertionResult, ScenarioAssertion

# Pattern to match array index in field path: "matched_rules[0]"
_INDEX_PATTERN = re.compile(r"^(.+)\[(\d+)\]$")


def _tokenize_path(path: str) -> List[Any]:
    """Split a dot-notation path into tokens, handling array indices.

    Examples:
        "decision.allowed" -> ["decision", "allowed"]
        "matched_rules[0].rule_name" -> ["matched_rules", 0, "rule_name"]
    """
    tokens: List[Any] = []
    for part in path.split("."):
        match = _INDEX_PATTERN.match(part)
        if match:
            tokens.append(match.group(1))
            tokens.append(int(match.group(2)))
        else:
            tokens.append(part)
    return tokens


def resolve_field_path(obj: Any, path: str) -> Tuple[Any, bool]:
    """Resolve a dot-notation field path against a dict or object.

    Args:
        obj: Dict or object to traverse
        path: Dot-notation path (e.g., "decision.allowed", "matched_rules[0].rule_name")

    Returns:
        Tuple of (resolved_value, found). found=False if path cannot be resolved.
    """
    tokens = _tokenize_path(path)
    current = obj

    for token in tokens:
        if current is None:
            return None, False

        if isinstance(token, int):
            # Array index
            if isinstance(current, (list, tuple)) and token < len(current):
                current = current[token]
            else:
                return None, False
        elif isinstance(current, dict):
            if token in current:
                current = current[token]
            else:
                return None, False
        elif hasattr(current, token):
            current = getattr(current, token)
        else:
            return None, False

    return current, True


def validate_assertion(
    assertion: ScenarioAssertion,
    context: dict,
) -> AssertionResult:
    """Validate a single assertion against a result context.

    Args:
        assertion: The assertion to validate
        context: Dict representation of the step result (e.g., {"decision": {...}})

    Returns:
        AssertionResult with pass/fail and details
    """
    value, found = resolve_field_path(context, assertion.field)

    # exists check
    if assertion.exists is not None:
        passed = found == assertion.exists
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else None,
            expected_value=f"exists={assertion.exists}",
            check_type="exists",
            error_message=None if passed else (
                f"Expected field '{assertion.field}' to {'exist' if assertion.exists else 'not exist'}, "
                f"but it {'exists' if found else 'does not exist'}"
            ),
        )

    # equals check
    if assertion.equals is not None:
        passed = found and value == assertion.equals
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else "<missing>",
            expected_value=assertion.equals,
            check_type="equals",
            error_message=None if passed else (
                f"Expected {assertion.field} == {assertion.equals!r}, got {value!r}"
                if found else f"Field '{assertion.field}' not found"
            ),
        )

    # not_equals check
    if assertion.not_equals is not None:
        passed = found and value != assertion.not_equals
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else "<missing>",
            expected_value=f"!= {assertion.not_equals!r}",
            check_type="not_equals",
            error_message=None if passed else (
                f"Expected {assertion.field} != {assertion.not_equals!r}, got {value!r}"
                if found else f"Field '{assertion.field}' not found"
            ),
        )

    # greater_than check
    if assertion.greater_than is not None:
        passed = found and isinstance(value, (int, float)) and value > assertion.greater_than
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else "<missing>",
            expected_value=f"> {assertion.greater_than}",
            check_type="greater_than",
            error_message=None if passed else (
                f"Expected {assertion.field} > {assertion.greater_than}, got {value!r}"
                if found else f"Field '{assertion.field}' not found"
            ),
        )

    # less_than check
    if assertion.less_than is not None:
        passed = found and isinstance(value, (int, float)) and value < assertion.less_than
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else "<missing>",
            expected_value=f"< {assertion.less_than}",
            check_type="less_than",
            error_message=None if passed else (
                f"Expected {assertion.field} < {assertion.less_than}, got {value!r}"
                if found else f"Field '{assertion.field}' not found"
            ),
        )

    # contains check
    if assertion.contains is not None:
        if found:
            if isinstance(value, str):
                passed = assertion.contains in value
            elif isinstance(value, list):
                passed = assertion.contains in value
            else:
                passed = False
        else:
            passed = False
        return AssertionResult(
            field=assertion.field,
            passed=passed,
            actual_value=value if found else "<missing>",
            expected_value=f"contains {assertion.contains!r}",
            check_type="contains",
            error_message=None if passed else (
                f"Expected {assertion.field} to contain {assertion.contains!r}, got {value!r}"
                if found else f"Field '{assertion.field}' not found"
            ),
        )

    # No assertion type specified
    return AssertionResult(
        field=assertion.field,
        passed=False,
        error_message="No assertion type specified (equals, exists, greater_than, less_than, contains, not_equals)",
        check_type="unknown",
    )


def validate_all_assertions(
    assertions: List[ScenarioAssertion],
    context: dict,
) -> List[AssertionResult]:
    """Validate all assertions in a list."""
    return [validate_assertion(a, context) for a in assertions]
