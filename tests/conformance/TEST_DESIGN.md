# Conformance Test Suite - Design Document

**Purpose**: Language-neutral validation that all policy evaluator implementations produce identical decisions for identical inputs.

**Status**: ✅ Complete (60 tests: 54 original + 6 escalation, 100% pass rate)

**Date**: 2026-02-15

---

## Testing Philosophy

**"Test it, don't trust it."** Every feature needs tests and synthetic data to prove it works.

Conformance tests validate **behavioral equivalence** across all language implementations (Python, TypeScript, future languages).

---

## Critical Behaviors Being Validated

### 1. **Determinism** ✅ VALIDATED
**Requirement**: Same (envelope, policy) → same decision, always

**How Validated**:
- Every test case runs the same envelope + policy through the evaluator
- Expected decision is defined in the test case
- Test runner compares actual vs expected using deep equality
- Tests are **idempotent** - running them multiple times produces identical results
- No randomness, no external calls, no time-dependent behavior in evaluator

**Test Evidence**:
- All 54 tests pass consistently across multiple runs
- No flaky tests observed
- Decision comparison includes: decision type, allowed flag, reason_codes, matched_rules

**Validation Status**: ✅ **PROVEN** - Evaluator is deterministic

---

### 2. **Performance Requirements** ✅ VALIDATED
**Requirement**: < 1ms evaluation time for typical policies

**How Validated**:
- Evaluator includes timing instrumentation (evaluation_ms in Decision response)
- TICKET-001 unit tests confirmed < 1ms evaluation time
- Timing metadata included in every decision response
- ✅ Conformance runner checks timing and warns if > 1ms (added 2026-02-15)

**Test Evidence**:
- All 54 conformance tests complete in 0.36s total (~6.67ms/test including overhead)
- No performance warnings issued (all evaluations < 1ms)
- Timing check uses `actual_decision.timing.evaluation_ms > 1.0` threshold

**What's Still Missing**:
- ❌ No load testing / benchmark suite yet (deferred to TICKET-018)
- ❌ No validation of "typical policy" definition (deferred to TICKET-018)

**Next Steps**:
- Create performance benchmark suite (TICKET-018: Synthetic Test Runner)
- Define "typical policy" size/complexity baseline
- Test with large policy sets (100+ rules)

**Validation Status**: ✅ **PROVEN** - Sub-millisecond confirmed in both unit and conformance tests

---

### 3. **Disabled Rules Are Skipped** ✅ VALIDATED
**Requirement**: Rules with `enabled: false` must not affect decisions

**How Validated**:
- **test_004_disabled_rule.json** - Disabled rule that would ALLOW is skipped, result is BLOCK (NO_MATCHING_RULE)

**Test Design**: the envelope transfers 100. The case's policy and expected decision:
```json
{
  "policy_set": {
    "name": "test_policy",
    "version": "v1.0.0",
    "description": "A disabled rule is skipped",
    "scope": {
      "org_id": "org_devlocal0000000000",
      "environment": "dev"
    },
    "rules": [{
      "name": "allow_small_transfers",
      "description": "Rule: allow_small_transfers",
      "priority": 100,
      "conditions": {"field": "parameters.amount", "operator": "less_than_or_equal", "value": 1000},
      "decision": "ALLOW",
      "reason_code": "SMALL_TRANSFER_ALLOWED",
      "lifecycle_stage": "disabled"
    }]
  },
  "expected_decision": {"decision": "BLOCK", "allowed": false, "reason_codes": ["NO_MATCHING_RULE"]}
}
```

**Validation Status**: ✅ **PROVEN** - test_004 confirms disabled rules are skipped

---

### 4. **Boundary Conditions** ✅ VALIDATED
**Requirement**: Edge cases and boundary values must be handled correctly

**How Validated**:

| Boundary Type | Test Case | What It Validates |
|--------------|-----------|-------------------|
| **Null/missing fields** | test_051_null_field_value.json | `exists: false` detects missing fields |
| **Empty strings** | test_052_empty_string.json | Empty string matches `equals: ""` |
| **Zero values** | test_053_zero_value.json | Zero is a valid numeric value |
| **Negative numbers** | test_054_negative_numbers.json | Negative values work in comparisons |
| **Empty arrays** | test_067_empty_array.json | Empty array matches `equals: []` |
| **Very large numbers** | test_066_very_large_number.json | Large numbers (999999999) work correctly |
| **Float precision** | test_060_floating_point_numbers.json | Floating point comparison (99.99 < 100.00) |
| **Fractional token estimate** | test_167_fractional_token_estimate.json | `cost_estimate.tokens` 1250.5 is read as written, over a 1250 budget |
| **Case sensitivity** | test_055_case_sensitivity.json | String comparison is case-sensitive ("usd" ≠ "USD") |
| **Unicode/special chars** | test_058, test_059 | Unicode and special characters handled correctly |
| **Deep nesting** | test_057_nested_field_path.json | 4-level deep field paths resolve correctly |
| **Threshold boundaries** | test_024, test_025 | `>=` and `<=` boundary conditions |

**Validation Status**: ✅ **PROVEN** - Comprehensive edge case coverage (14 dedicated edge case tests)

### Field references and schema conformance (policy_format.md 2.6)

**Purpose:** a condition may compare a field with another field of the same envelope, an array on the left of `in` /
`not_in` is a subset test, and `conforms_to` checks parameters against a parameter schema — identically in both
evaluators. **Success:** the decision and reason codes the case names, in both languages. Designed from the spec's
sentences, not the implementation: each behavior has a case that must match and one that must not.

| Behavior | Case | What it validates |
|---|---|---|
| A reference resolves against the same envelope | test_140, test_141 | not-subset matches; subset does not |
| A reference to nothing is false | test_142 | no principal → the condition does not match |
| Any operator takes a reference where types fit | test_143 | equals between two parameters |
| Array-left `in` is a subset test | test_144 | every element in the set matches |
| `conforms_to` — undeclared name, wrong type, conforming | test_145–147 | departs / departs / conforms |

**Validation Status:** ✅ PROVEN in both languages (113 / 113). **Gaps:** `conforms_to` with `additionalProperties`
true and nested object properties are unit-tested, not conformance cases; enrichment context (`external.*`) is the next
section's.

### Enrichment context — a sync route's answer (policy_format.md 2.7; TICKET-046)

**Purpose:** prove that both evaluators resolve `external.<source>.<field>` against the enrichment context the case
supplies beside the envelope (`"enrichment"`), never against the envelope, and that a ROUTE rule whose route has
answered does not match again. The loop that asks the route is the SDK's and the server's, unit-tested per language
(`hiitl/core/tests/TEST_DESIGN_route_enrichment.md`).

| Behavior | Case | What it validates |
|---|---|---|
| An answered field decides | test_148, test_149 | `rejected` blocks; `accepted` does not |
| An absent field is false, `exists = false` excepted | test_150, test_151 | the reading rule does not match; `exists false` does |
| A ROUTE decision carries its rule's route | test_152 | `route_ref = content-check`, not allowed |
| An answered route's rule does not match again | test_153, test_157 | the rule reading the answer decides; an answer no rule refuses allows, never routes again |
| Routes compose by data flow | test_154, test_155 | one answer routes on; both answers decide |
| No enrichment, no reading | test_156 | a rule reading `external.*` without a context never matches |

**Validation Status:** ✅ PROVEN in both languages (127 / 127).

### Refusals — no field is ever silently dropped (R-0872; HTL-20 row 147)

**Purpose:** prove that both languages refuse an artifact naming a field its spec does not define, at the same
place and naming the same thing: the envelope (envelope_schema.json v1.4), a policy set (policy_format.md 2.10) and a
route (routes.md 1.3). A refusal case carries the one artifact and `expected_refusal`; the runner reads the artifact
through its model and evaluates nothing. The located path and the names are the claim; the message wording is each
language's own.

| Behavior | Case | What it validates |
|---|---|---|
| An envelope refuses an undefined field | test_162 | `amount_usd` at the top level, refused at `amount_usd` |
| A cost estimate refuses an undefined key | test_163 | `usd_cents`, refused at `cost_estimate.usd_cents` |
| A rule never writes a decision only the evaluator or the control point produces | test_164 | `OBSERVE`, refused at `rules.0.decision`, naming the rule and the value |
| A scope takes only the envelope's environments | test_165 | `staging`, refused at `rules.0.scope.environments.1` |
| A route refuses an undefined field at depth | test_166 | `sla.escalate_after` |
| A fractional token estimate is read as written | test_167 | 1250.5 is over a 1250-token budget: `BLOCK` |
| A policy set's `on_missing` is one of two | test_177 | `fail_open`, refused at `on_missing`, naming it |
| A policy naming `matches` is refused at load (policy_format.md 2.22; R-1380) | test_020 | refused at `rules.0.conditions.operator`, naming `matches` and the operators to use in its place: `starts_with`, `ends_with`, `contains`, `in` |
| A condition carries its `value` (policy_format.md 2.23; gap 322) | test_195, test_196 | a condition with no `value`, bare and nested in `any_of`, refused at its `value` path, naming `value` |
| A condition is one of its two forms (2.23; gap 322) | test_197, test_198 | `{}`, and an object setting both `all_of` and `any_of`, refused at `rules.0.conditions`, naming "Exactly one of all_of, any_of, or none_of must be set" |

**Validation Status:** ✅ PROVEN in both languages (133 / 133). **Gaps:** an undefined field on each nested route
object, a rule's undefined key (R-0881) and the other produced decisions are unit-tested per language
(`hiitl/core/tests/test_row147.py`, `core/tests/unit/row147.test.ts`), not conformance cases.

**`matches` (HTL-45 `8613a7bc`, CC, 2026-11-17).** test_020 was the operator's decision case; it is now its load
refusal, moved to `refusals/` under its number. Each SDK's file loader refuses the same policy in both file forms
with its authored message (`python/hiitl/sdk/tests/test_matches_removal.py`,
`typescript/packages/sdk/tests/unit/matches-removal.test.ts`); those cells read the policy from test_020 and the
operators to name from policy_format.md's sentence, so neither list is retyped. A condition is a union of an atomic
arm and a logical arm. Zod's union reports the one arm that did not abort: the enum's refusal of an operator aborts
and the logical arm's undefined keys do not, so TypeScript returned the logical arm's refusal at `rules.0.conditions`
and lost the authored operator message. Python's declared-input reader already reads the arm closest to the data
(`input_types.py`: an arm of the input's JSON kind, then the fewest undefined members, then the fewest errors).
TypeScript's condition unions read the same rule (`closestArm`, `own-data.ts`), so the same input is located at the
same path in both languages, which is test_020's claim; the TypeScript refusals that rule moves are listed at the
hand-off. Its mutation restores `z.union` and test_020 must fail in TypeScript alone.

**Gap 322 (HTL-45 `d0640d7a`, CC, 2026-11-17).** CC generated 138 malformed conditions (the condition schema's members × the JSON kinds × the logical forms). After `closestArm`, 130 were located alike in both languages. The 8 left were two classes: four conditions with no `value`, which TypeScript admitted, and four objects that are neither form, which Python located at pydantic's union labels. test_195–198 are those classes. Each SDK's file loader refuses a policy with no `value` in both file forms at the same path (`python/hiitl/sdk/tests/test_condition_value.py`, `typescript/packages/sdk/tests/unit/condition-value.test.ts`). Python's declared-input reader reads the exactly-one rule once the logical object's own members hold, as the model's after-validator and zod's `refine` do, and the reader and the model share one statement of the rule. TypeScript reads a `value` set to `undefined` as absent, since JSON has no `undefined` (`.nonoptional()`). The HTL-37 dependency migration's condition-value cell recorded TypeScript admitting both, so `d0640d7a` supersedes those two rows, and the fixture bytes stay historical. Its mutations: TypeScript's `value` made optional again (test_195 and test_196 fail in TypeScript alone); TypeScript without `.nonoptional()` (an absent value is still refused, and the migration cell's `undefined` row fails); Python's `value` given a default (test_195 and test_196 fail in Python alone); and Python's reader without the rule (test_197 and test_198 fail in Python alone). Beyond the cases, a 1,536-input multi-fault probe found no input loaded in one language and refused in the other, and 890 located differently in four pre-existing classes. That is gap 324, an open condition, and no case here asserts those inputs.

### On missing — a field the call does not carry (HTL-22 row 176)

**Purpose:** prove that both languages read a rule the call cannot read by its set's `on_missing` (policy_format.md
**A field the call does not carry**): under `fail_closed` it decides `BLOCK` (`MISSING_FIELD`) at its own priority,
and under `skip`, in observe mode and in the staged lane it is read as before and named in `missing_fields`. The
behaviors and their reasons are in the HTL-22 test design, row 176.

| Behavior | Case | What it validates |
|---|---|---|
| `fail_closed` blocks | test_168 | `BLOCK` / `MISSING_FIELD`, the `custom` remediation, over a matching `ALLOW` of higher priority |
| `skip` passes to the next rule | test_169 | the next rule decides; the flag names the rule and the field |
| A negated condition under `skip` decides as today | test_170 | a `none_of` `BLOCK` still blocks, and is flagged |
| Observe skips and flags | test_171 | `OBSERVE_ALL` over a `fail_closed` set: the next rule decides, flagged |
| A staged rule skips and flags | test_172 | no `BLOCK`, no observation, flagged |
| `external.*` is not counted | test_173 | no `BLOCK`, no flag |
| What the call's fields settle is read as before | test_174 | either condition order; `exists` reads the absence |
| The missing-field `BLOCK` contends at its priority | test_175 | a higher-priority matching `BLOCK` binds over it |
| A windowed rule is a rule | test_176 | a `RATE_LIMIT` rule the call cannot read blocks |
| A field reference is a read | test_178 | a `$field` the call does not carry blocks, naming the referenced field |
| Observe keeps the flag | test_179 | an observed `BLOCK` keeps `missing_fields` |

**Validation Status:** ✅ PROVEN in both languages (145 / 145); the cases before row 176 pass unchanged, so no
decision moves under the default.

### A set's scope, description and version (HTL-22 row 165)

**Purpose:** prove that both languages refuse a policy set missing a field policy_format.md's Policy Set Fields
requires, or carrying a version that is not `v{major}.{minor}.{patch}`, at the field and naming it (R-0872). Every set
the repository carries loads (`hiitl/core/tests/test_row165.py`); the behaviors and their reasons are in the HTL-22
test design, row 165.

| Behavior | Case | What it validates |
|---|---|---|
| `scope` is required | test_180 | refused at `scope` |
| `description` is required | test_181 | refused at `description` |
| `version` is required | test_182 | refused at `version` |
| `version` is semver with its `v` | test_183 | `1.0.0` refused at `version` |
| A scope names its org | test_184 | refused at `scope.org_id` |
| A scope's org is in the envelope's form | test_186 | `acme-finance` refused at `scope.org_id` |
| A renamed envelope field names the field it became (row 225) | test_187, test_188 | `tool_name` alone, refused at `action` and `tool_name`; beside `action`, at `tool_name`; each naming `action` |
| A scope's keys are the format's | test_185 | `region` refused at `scope.region`, naming it |

**Validation Status:** ✅ PROVEN in both languages (153 / 153).

---

## Test Coverage Analysis

### Operators Covered (100%)

**Comparison Operators (8/8):**
- ✅ equals, not_equals (test_011, test_012)
- ✅ greater_than, greater_than_or_equal (test_013, test_024)
- ✅ less_than, less_than_or_equal (test_014, test_025)
- ✅ in, not_in (test_015, test_026)

**String Operators (4/4):**
- ✅ contains, not_contains (test_016, test_027)
- ✅ starts_with (test_017)
- ✅ ends_with (test_018)
- `matches` left the format at 2.22 (R-1380); test_020 is its load refusal

**Field Operators (1/1):**
- ✅ exists (test_019)

**Logical Operators (3/3):**
- ✅ all_of (AND) - success: test_021, failure: test_028
- ✅ any_of (OR) - success: test_022, test_029
- ✅ none_of (NOT) - success: test_023, failure: test_030

### Decision Types Covered (4/4)
- ✅ ALLOW (allowed=true) - test_061
- ✅ BLOCK (allowed=false) - test_062
- ✅ SANDBOX (allowed=true) - test_063
- ✅ REQUIRE_APPROVAL (allowed=false) - test_064

### Escalation & Route (6 tests) — Added TICKET-003.1
- ✅ REQUIRE_APPROVAL with route → route_ref in decision (test_071)
- ✅ PAUSE with route → route_ref in decision (test_072)
- ✅ ESCALATE with route → route_ref in decision (test_073)
- ✅ REQUIRE_APPROVAL without route → null route_ref (test_074)
- ✅ Multiple rules with different routes → correct config selected (test_075)
- ✅ Escalation decisions include resume_token (test_076)

### Critical Behaviors Covered

**Priority & Ordering:**
- ✅ Higher priority evaluated first (test_031)
- ✅ First-match wins (test_032)
- ✅ Equal priority determinism (test_033)

**Safe-by-Default:**
- ✅ No matching rule → BLOCK (test_003)

**Field Path Resolution:**
- ✅ Top-level fields (test_008, test_009, test_010)
- ✅ Nested parameters (all tests use parameters.*)
- ✅ Deep nesting (test_057: 4 levels)

**Logical Operator Composition:**
- ✅ Nested all_of with any_of (test_041)
- ✅ Deeply nested (3 levels) (test_042)
- ✅ all_of with none_of (test_043)
- ✅ any_of with multiple all_of branches (test_044)

---

## Test Categories

### Escalation (6 tests) — Added TICKET-003.1
**Purpose**: Validate three-artifact model escalation fields (route, resume_token, route_ref)

- test_071: REQUIRE_APPROVAL with route reference
- test_072: PAUSE with route reference
- test_073: ESCALATE with route reference
- test_074: Escalation without route (null reference)
- test_075: Multiple rules, different routes (priority selects correct one)
- test_076: Resume token present on all escalation types

**Validation approach**: `route_ref` is exact-matched. `resume_token` uses "PRESENT" sentinel since value is random. Both runners updated to handle these assertions.

### Basic (10 tests)
**Purpose**: Core functionality and common scenarios

- test_001-002: Simple allow/block rules
- test_003: No matching rule → BLOCK (safe-by-default)
- test_004: Disabled rules are skipped
- test_005-006: REQUIRE_APPROVAL and SANDBOX decisions
- test_007: Multiple rules with different priorities
- test_008-010: Top-level field matching (action, environment, operation)

### Conditions (17 tests)
**Purpose**: Validate all atomic condition operators

- test_011-027: All 14 operators with positive test cases

### Logical Operators (7 tests)
**Purpose**: Validate logical composition and nesting

- test_021-023: Basic all_of, any_of, none_of (success cases)
- test_028-030: Failure cases for logical operators

### Priority (3 tests)
**Purpose**: Validate rule evaluation order and first-match behavior

- test_031: Priority ordering (highest first)
- test_032: First-match wins
- test_033: Equal priority determinism

### Nested (4 tests)
**Purpose**: Validate complex nested logical conditions

- test_041-044: 2-3 levels of nesting with various combinations

### Decisions (4 tests)
**Purpose**: Validate all decision types and allowed flag mapping

- test_061-064: One test per decision type

### Edge Cases (14 tests)
**Purpose**: Validate boundary conditions and special values

- test_051-060, test_065-067, test_167: Comprehensive edge case coverage

---

## What's NOT Tested (Gaps)

### 1. Error Handling ✅ ADDRESSED
**Status**: Implemented as separate test suite (2026-02-15)

**What's Covered** (in `python/hiitl/core/tests/test_error_handling.py`):
- ✅ Schema validation errors (6 tests):
  - Missing required envelope fields
  - Invalid environment values
  - Invalid action_id format
  - Invalid operators in conditions
  - Invalid decision types
  - Missing required rule fields
- ✅ Runtime error handling (3 tests):
  - Type mismatches in numeric comparisons (raises TypeError)
  - Nonexistent field comparisons (returns False)
  - Deeply nested logical conditions (no stack overflow)
- ✅ Edge case error handling (2 tests):
  - Empty policy rules (safe-by-default: BLOCK)
  - All rules disabled (safe-by-default: BLOCK)

**Rationale for Separate Test Suite**:
- Error handling is implementation-specific (Python vs TypeScript differ)
- Conformance tests assume valid inputs, except the refusal cases (`refusals/`, HTL-20 row 147), which assert where a
  refusal is located and what it names: the same in both languages, while the message wording stays each language's
- Error messages and validation libraries vary by language
- 12/12 tests passing validates Python implementation error handling

### 2. Performance Benchmarks (Deferred)
**Status**: Deferred to TICKET-018 (Synthetic Test Runner)

**What's Missing**:
- ❌ Large policy sets (100+ rules)
- ❌ Complex nested conditions (10+ levels)
- ❌ High-frequency evaluation (1000+ decisions/sec)
- ❌ Memory usage under load

### 3. Concurrency (Not Applicable)
**Status**: Not in scope - evaluator is stateless and side-effect free

**Not Tested**:
- Concurrent evaluations (evaluator is stateless, so this is safe by design)
- Thread safety (Python implementation uses no shared state)

---

## Test Design Principles Applied

### 1. **One Thing Per Test**
Each test validates a single operator, decision type, or behavior in isolation.

**Example**: test_013 validates `greater_than` operator only, not multiple operators in one test.

### 2. **Positive AND Negative Cases**
Where applicable, test both success and failure scenarios.

**Example**:
- test_021: `all_of` succeeds when all conditions match
- test_028: `all_of` fails when one condition doesn't match

### 3. **Minimal Test Cases**
Each test uses the simplest envelope/policy that validates the behavior.

**Example**: test_011 (equals operator) uses a 2-field envelope, not a complex 20-field envelope.

### 4. **Descriptive Naming**
Test IDs and descriptions clearly indicate what's being tested.

**Example**: `test_013_greater_than_operator.json` - clear what operator is being tested.

### 5. **Independence**
Tests don't depend on each other. Each can run in isolation.

**Example**: Tests don't share state or assume execution order.

---

## Validation Summary

| Critical Behavior | Status | Evidence |
|------------------|--------|----------|
| **Determinism** | ✅ PROVEN | 60/60 tests pass consistently, deep equality comparison |
| **Performance** | ✅ PROVEN | < 1ms confirmed in unit tests + conformance (with timing assertions) |
| **Disabled Rules** | ✅ PROVEN | test_004 explicitly validates |
| **Boundary Conditions** | ✅ PROVEN | 14 edge case tests cover comprehensive boundaries |
| **Safe-by-Default** | ✅ PROVEN | test_003 validates NO_MATCHING_RULE → BLOCK |
| **Priority Ordering** | ✅ PROVEN | test_031-033 validate priority and first-match |
| **Logical Composition** | ✅ PROVEN | test_041-044 validate complex nesting |
| **All Operators** | ✅ PROVEN | 17 condition tests + 7 logical tests = 100% coverage |
| **All Decisions** | ✅ PROVEN | 4 decision type tests cover all types |
| **Field Paths** | ✅ PROVEN | test_057 validates deep nesting, all tests use dot notation |

---

## Next Steps

### Immediate (TICKET-005)
- [x] Python conformance test runner ✅ COMPLETE (54/54 passing)
- [x] Add performance assertions to conformance runner ✅ COMPLETE (2026-02-15)
- [x] Add error case tests ✅ COMPLETE (12/12 passing, 2026-02-15)
- [ ] TypeScript conformance test runner (TICKET-004)

### Short-Term
- [ ] Validate TypeScript evaluator passes 100% of conformance tests

### Long-Term (TICKET-018)
- [ ] Performance benchmark suite (large policies, high frequency)
- [ ] Synthetic test data (realistic agent personas, action sequences)
- [ ] Load testing (1000+ decisions/sec)
- [ ] Define "typical policy" size/complexity baseline

---

## Lessons Learned

### What Worked Well
1. **Category organization** - Easy to find and understand tests
2. **Comprehensive operator coverage** - All 14 operators + all logical ops tested
3. **Edge case focus** - 13 dedicated edge case tests caught potential bugs
4. **Schema-first approach** (eventually) - Fixing tests to match schema, not vice versa

### What Could Be Improved
1. **Design-first, implement-second** - Should have designed test purpose BEFORE creating 56 tests
2. **Validate early** - Should have tested 2-3 cases end-to-end before creating all 56
3. **Performance validation** - Should have added timing assertions to conformance runner
4. **Error case coverage** - Should have included error handling tests from the start

### Process Improvements for Future Test Suites
1. **Create test design doc FIRST** - Document purpose and critical behaviors BEFORE writing tests
2. **Validate 2-3 tests end-to-end** - Prove the approach works before scaling up
3. **Tests conform to specs** - Never change code to pass tests; fix tests to match requirements
4. **Establish working directory** - Set clear pwd and stick to it to avoid path confusion
5. **Performance is a requirement** - Include timing/performance validation in test suite, not just unit tests

---

**Document Status**: ✅ Complete

**Next Review**: After TICKET-004 (TypeScript conformance runner) completes
