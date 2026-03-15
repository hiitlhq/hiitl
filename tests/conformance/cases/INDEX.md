# Conformance Test Suite Index

**Total Test Cases:** 56

This index catalogs all conformance test cases for HIITL policy evaluators. All tests are in JSON format and are language-neutral.

## Test Categories

### Basic (10 tests)
Tests fundamental policy evaluation behavior.

- `test_001_simple_allow.json` - Simple ALLOW rule that matches
- `test_002_simple_block.json` - Simple BLOCK rule that matches
- `test_003_no_matching_rule.json` - No matching rule (default BLOCK)
- `test_004_disabled_rule.json` - Disabled rule should be skipped
- `test_005_request_approval.json` - REQUEST_APPROVAL decision type
- `test_006_sandbox.json` - SANDBOX decision type
- `test_007_multiple_rules_different_priorities.json` - Multiple rules with different priorities
- `test_008_top_level_field.json` - Top-level envelope field matching
- `test_009_environment_field.json` - Environment field matching
- `test_010_operation_field.json` - Operation field matching

### Condition Operators (17 tests)
Tests all atomic condition operators.

- `test_011_equals_operator.json` - equals operator
- `test_012_not_equals_operator.json` - not_equals operator
- `test_013_greater_than_operator.json` - greater_than operator
- `test_014_less_than_operator.json` - less_than operator
- `test_015_in_operator.json` - in operator (value in list)
- `test_016_contains_operator.json` - contains operator (string/array)
- `test_017_starts_with_operator.json` - starts_with operator
- `test_018_ends_with_operator.json` - ends_with operator
- `test_019_exists_operator.json` - exists operator (field exists)
- `test_020_matches_operator.json` - matches operator (regex)
- `test_024_greater_than_or_equal.json` - greater_than_or_equal operator
- `test_025_less_than_or_equal.json` - less_than_or_equal operator
- `test_026_not_in_operator.json` - not_in operator (value not in list)
- `test_027_not_contains_operator.json` - not_contains operator

### Logical Operators (7 tests)
Tests logical condition operators and combinations.

- `test_021_all_of_operator.json` - all_of (AND) - all conditions must match
- `test_022_any_of_operator.json` - any_of (OR) - at least one condition must match
- `test_023_none_of_operator.json` - none_of (NOT) - none may match
- `test_028_all_of_fails.json` - all_of fails when one condition doesn't match
- `test_029_any_of_succeeds_with_one.json` - any_of succeeds when only one matches
- `test_030_none_of_fails.json` - none_of fails when one condition matches

### Priority (3 tests)
Tests rule priority ordering and first-match behavior.

- `test_031_priority_ordering.json` - Higher priority rule matches first
- `test_032_first_match_wins.json` - First matching rule wins
- `test_033_equal_priority_first_defined.json` - Equal priority ordering (determinism test)

### Nested Conditions (4 tests)
Tests nested and complex logical operator combinations.

- `test_041_nested_logical_operators.json` - Nested all_of with any_of
- `test_042_deeply_nested_conditions.json` - Deeply nested conditions (3 levels)
- `test_043_nested_all_of_and_none_of.json` - Nested all_of with none_of
- `test_044_complex_any_of_with_all_of.json` - any_of where each option is an all_of

### Decision Types (4 tests)
Tests all decision types and their allowed field values.

- `test_061_allow_decision.json` - ALLOW decision (allowed=true)
- `test_062_block_decision.json` - BLOCK decision (allowed=false)
- `test_063_sandbox_decision.json` - SANDBOX decision (allowed=true)
- `test_064_request_approval_decision.json` - REQUEST_APPROVAL decision (allowed=false)

### Edge Cases (13 tests)
Tests edge cases, special values, and data type handling.

- `test_051_null_field_value.json` - Null/missing field values
- `test_052_empty_string.json` - Empty string values
- `test_053_zero_value.json` - Zero as numeric value
- `test_054_negative_numbers.json` - Negative numbers
- `test_055_case_sensitivity.json` - Case-sensitive string comparison
- `test_056_array_in_envelope.json` - contains operator with array field
- `test_057_nested_field_path.json` - Deep field path resolution (3 levels)
- `test_058_special_characters.json` - Special characters in strings
- `test_059_unicode_strings.json` - Unicode characters
- `test_060_floating_point_numbers.json` - Floating point numbers
- `test_065_boolean_field.json` - Boolean field values
- `test_066_very_large_number.json` - Very large numbers
- `test_067_empty_array.json` - Empty arrays

## Coverage Summary

**Operators Covered:**
- ✅ equals, not_equals
- ✅ greater_than, greater_than_or_equal
- ✅ less_than, less_than_or_equal
- ✅ in, not_in
- ✅ contains, not_contains
- ✅ starts_with, ends_with
- ✅ matches (regex)
- ✅ exists

**Logical Operators Covered:**
- ✅ all_of (AND)
- ✅ any_of (OR)
- ✅ none_of (NOT)
- ✅ Nested combinations (2-3 levels deep)

**Decision Types Covered:**
- ✅ ALLOW (allowed=true)
- ✅ BLOCK (allowed=false)
- ✅ REQUEST_APPROVAL (allowed=false)
- ✅ SANDBOX (allowed=true)

**Features Covered:**
- ✅ Rule priority ordering
- ✅ First-match wins
- ✅ Disabled rules
- ✅ Default BLOCK (no matching rule)
- ✅ Field path resolution (dot notation)
- ✅ Top-level and nested fields
- ✅ Multiple data types (string, number, boolean, array)
- ✅ Edge cases (null, empty, zero, unicode, special chars)

## Test File Format

Each test case is a JSON file with this structure:

```json
{
  "test_id": "unique_test_identifier",
  "description": "Human-readable description",
  "envelope": { /* Execution envelope */ },
  "policy_set": { /* Policy to evaluate */ },
  "expected_decision": {
    "decision": "ALLOW|BLOCK|REQUEST_APPROVAL|SANDBOX",
    "allowed": true|false,
    "reason_codes": ["REASON_CODE"]
  }
}
```

## Usage

These test cases are designed to validate that all HIITL policy evaluator implementations (Python, TypeScript, etc.) produce **identical decisions** for the same inputs.

See `tests/conformance/README.md` for instructions on running conformance tests.
