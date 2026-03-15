"""Tests for the assertion validation engine."""

import pytest

from hiitl.synthetic.assertions import resolve_field_path, validate_assertion, validate_all_assertions
from hiitl.synthetic.types import ScenarioAssertion


class TestResolveFieldPath:
    """Tests for dot-notation field path resolution."""

    def test_simple_key(self):
        value, found = resolve_field_path({"foo": "bar"}, "foo")
        assert found is True
        assert value == "bar"

    def test_nested_key(self):
        obj = {"decision": {"allowed": True}}
        value, found = resolve_field_path(obj, "decision.allowed")
        assert found is True
        assert value is True

    def test_deeply_nested(self):
        obj = {"decision": {"timing": {"evaluation_ms": 0.5}}}
        value, found = resolve_field_path(obj, "decision.timing.evaluation_ms")
        assert found is True
        assert value == 0.5

    def test_missing_key(self):
        value, found = resolve_field_path({"foo": "bar"}, "missing")
        assert found is False

    def test_missing_nested_key(self):
        obj = {"decision": {"allowed": True}}
        value, found = resolve_field_path(obj, "decision.missing")
        assert found is False

    def test_array_index(self):
        obj = {"rules": [{"name": "rule1"}, {"name": "rule2"}]}
        value, found = resolve_field_path(obj, "rules[0].name")
        assert found is True
        assert value == "rule1"

    def test_array_index_out_of_bounds(self):
        obj = {"rules": [{"name": "rule1"}]}
        value, found = resolve_field_path(obj, "rules[5].name")
        assert found is False

    def test_none_intermediate(self):
        obj = {"decision": None}
        value, found = resolve_field_path(obj, "decision.allowed")
        assert found is False

    def test_empty_dict(self):
        value, found = resolve_field_path({}, "anything")
        assert found is False

    def test_boolean_false_is_found(self):
        """False values should be found (not confused with None)."""
        obj = {"decision": {"allowed": False}}
        value, found = resolve_field_path(obj, "decision.allowed")
        assert found is True
        assert value is False

    def test_zero_is_found(self):
        """Zero should be found (not confused with None)."""
        obj = {"count": 0}
        value, found = resolve_field_path(obj, "count")
        assert found is True
        assert value == 0


class TestValidateAssertion:
    """Tests for individual assertion types."""

    def test_equals_pass(self):
        a = ScenarioAssertion(field="decision.allowed", equals=False)
        result = validate_assertion(a, {"decision": {"allowed": False}})
        assert result.passed is True

    def test_equals_fail(self):
        a = ScenarioAssertion(field="decision.allowed", equals=True)
        result = validate_assertion(a, {"decision": {"allowed": False}})
        assert result.passed is False
        assert "Expected" in result.error_message

    def test_equals_missing_field(self):
        a = ScenarioAssertion(field="decision.missing", equals=True)
        result = validate_assertion(a, {"decision": {"allowed": False}})
        assert result.passed is False

    def test_not_equals_pass(self):
        a = ScenarioAssertion(field="decision.decision", not_equals="ALLOW")
        result = validate_assertion(a, {"decision": {"decision": "BLOCK"}})
        assert result.passed is True

    def test_not_equals_fail(self):
        a = ScenarioAssertion(field="decision.decision", not_equals="BLOCK")
        result = validate_assertion(a, {"decision": {"decision": "BLOCK"}})
        assert result.passed is False

    def test_exists_true_pass(self):
        a = ScenarioAssertion(field="decision.resume_token", exists=True)
        result = validate_assertion(a, {"decision": {"resume_token": "rtk_123"}})
        assert result.passed is True

    def test_exists_true_fail(self):
        a = ScenarioAssertion(field="decision.resume_token", exists=True)
        result = validate_assertion(a, {"decision": {}})
        assert result.passed is False

    def test_exists_false_pass(self):
        a = ScenarioAssertion(field="decision.error", exists=False)
        result = validate_assertion(a, {"decision": {}})
        assert result.passed is True

    def test_greater_than_pass(self):
        a = ScenarioAssertion(field="decision.timing.evaluation_ms", greater_than=0)
        result = validate_assertion(a, {"decision": {"timing": {"evaluation_ms": 0.5}}})
        assert result.passed is True

    def test_greater_than_fail(self):
        a = ScenarioAssertion(field="decision.timing.evaluation_ms", greater_than=10)
        result = validate_assertion(a, {"decision": {"timing": {"evaluation_ms": 0.5}}})
        assert result.passed is False

    def test_less_than_pass(self):
        a = ScenarioAssertion(field="decision.timing.evaluation_ms", less_than=10)
        result = validate_assertion(a, {"decision": {"timing": {"evaluation_ms": 0.5}}})
        assert result.passed is True

    def test_less_than_fail(self):
        a = ScenarioAssertion(field="decision.timing.evaluation_ms", less_than=0.1)
        result = validate_assertion(a, {"decision": {"timing": {"evaluation_ms": 0.5}}})
        assert result.passed is False

    def test_contains_string_pass(self):
        a = ScenarioAssertion(field="decision.reason_codes", contains="HIGH_VALUE")
        result = validate_assertion(a, {"decision": {"reason_codes": ["HIGH_VALUE", "OTHER"]}})
        assert result.passed is True

    def test_contains_string_fail(self):
        a = ScenarioAssertion(field="decision.reason_codes", contains="MISSING")
        result = validate_assertion(a, {"decision": {"reason_codes": ["HIGH_VALUE"]}})
        assert result.passed is False

    def test_no_assertion_type(self):
        a = ScenarioAssertion(field="decision.allowed")
        result = validate_assertion(a, {"decision": {"allowed": True}})
        assert result.passed is False
        assert "No assertion type" in result.error_message


class TestValidateAllAssertions:
    """Tests for batch assertion validation."""

    def test_all_pass(self):
        assertions = [
            ScenarioAssertion(field="decision.allowed", equals=True),
            ScenarioAssertion(field="decision.decision", equals="ALLOW"),
        ]
        results = validate_all_assertions(assertions, {"decision": {"allowed": True, "decision": "ALLOW"}})
        assert all(r.passed for r in results)
        assert len(results) == 2

    def test_mixed_pass_fail(self):
        assertions = [
            ScenarioAssertion(field="decision.allowed", equals=True),
            ScenarioAssertion(field="decision.decision", equals="BLOCK"),
        ]
        results = validate_all_assertions(assertions, {"decision": {"allowed": True, "decision": "ALLOW"}})
        assert results[0].passed is True
        assert results[1].passed is False
