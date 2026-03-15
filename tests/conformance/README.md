# Conformance Test Suite

**Purpose**: Language-neutral conformance tests that validate all policy evaluator implementations produce identical decisions for identical inputs.

**Per CLAUDE.md line 625**: Every evaluator implementation (TypeScript, Python, and future languages) must pass this conformance suite.

---

## Overview

The conformance test suite ensures **behavioral equivalence** across all language implementations of the HIITL policy evaluator.

**Test format**: JSON test cases containing:
- Input envelope
- Policy set
- Expected decision output

**Requirement**: Same (envelope, policy) input → same decision output across all implementations

---

## Test Case Format

Each test case is a JSON file in `cases/`:

```json
{
  "test_id": "unique-test-identifier",
  "test_name": "Human-readable test name",
  "description": "What this test validates",
  "envelope": {
    // Full envelope JSON (per envelope_schema.json)
  },
  "policy_set": {
    // Full policy set (per policy_format.md)
  },
  "expected_decision": {
    "decision": "ALLOW | BLOCK | REQUIRE_APPROVAL | etc.",
    "allowed": true | false,
    "reason_codes": ["REASON_CODE"],
    "matched_rules": [
      {
        "rule_name": "rule-name",
        "policy_set": "policy-set-name",
        "priority": 100
      }
    ],
    "policy_version": "v1.0.0"
  }
}
```

---

## Running Conformance Tests

### TypeScript Implementation

```bash
cd typescript/packages/core
npm test:conformance
```

Expected output:
```
✓ test_001_simple_allow.json
✓ test_002_simple_block.json
✓ test_003_high_value_payment_approval.json
...
All conformance tests passed: 50/50
```

### Python Implementation

```bash
cd python/hiitl/core
pytest tests/conformance
```

Expected output:
```
✓ test_001_simple_allow.json
✓ test_002_simple_block.json
✓ test_003_high_value_payment_approval.json
...
All conformance tests passed: 50/50
```

---

## Test Categories

### Category 1: Basic Decisions (test_001 - test_010)
- Simple allow rules
- Simple block rules
- Default behaviors
- Empty policy sets

### Category 2: Condition Matching (test_011 - test_020)
- Field path references (nested fields)
- Comparison operators (equals, greater_than, etc.)
- Logical operators (all_of, any_of, none_of)
- Set membership (in, not_in)

### Category 3: Priority & Precedence (test_021 - test_030)
- Rule priority ordering
- DENY wins (conflict resolution)
- Multiple matching rules

### Category 4: Approval Workflows (test_031 - test_040)
- REQUIRE_APPROVAL decisions
- Approval metadata inclusion
- SLA expectations

### Category 5: Rate Limiting (test_041 - test_050)
- Rate limit decisions
- Counter state snapshots
- Different scopes (agent_id, user_id, org_id, tool_name)

### Category 6: Kill Switches (test_051 - test_060)
- Kill switch activation
- Different kill switch scopes
- Priority over other rules

### Category 7: Complex Conditions (test_061 - test_070)
- Nested logical operators
- Multiple field references
- Edge cases (null values, missing fields)

### Category 8: Signal References (test_071 - test_080)
- External signal conditions (Layer 4)
- Signal existence checks
- Missing signal handling

---

## Adding New Test Cases

1. Create a new JSON file in `cases/` following the format above
2. Run conformance tests in TypeScript implementation
3. Run conformance tests in Python implementation
4. Both must pass with identical decisions

**Test ID convention**: `test_{category}_{number}.json`

Examples:
- `test_001_simple_allow.json`
- `test_035_high_value_approval.json`
- `test_052_kill_switch_agent_specific.json`

---

## Validation

Conformance test runner validates:

1. **Test case format**: JSON is well-formed, follows schema
2. **Envelope validity**: Envelope matches `envelope_schema.json`
3. **Policy validity**: Policy set is valid per `policy_format.md`
4. **Expected decision format**: Decision response matches `decision_response.md`
5. **Determinism**: Running test multiple times produces identical decision
6. **Cross-language equivalence**: TypeScript and Python produce identical decisions

---

## CI/CD Integration

Conformance tests run in CI/CD pipeline:

```yaml
# .github/workflows/conformance.yml
name: Conformance Tests

on: [push, pull_request]

jobs:
  typescript-conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
      - run: cd typescript/packages/core && npm test:conformance

  python-conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: cd python/hiitl/core && pytest tests/conformance

  cross-language-validation:
    runs-on: ubuntu-latest
    needs: [typescript-conformance, python-conformance]
    steps:
      - run: echo "All conformance tests passed across languages"
```

---

## Test Coverage Goals

**Phase 1 (MVP)**:
- 50+ test cases
- All basic decision types
- All condition operators
- All priority scenarios
- All Layer 1-2 policy features

**Phase 2**:
- 100+ test cases
- Signal-aware conditions (Layer 4)
- Complex nested conditions
- Edge cases and error handling

---

## Current Test Cases

See `cases/` directory for all test cases. Summary:

| Test ID | Name | Description |
|---------|------|-------------|
| test_001 | simple_allow | Basic allow rule |
| test_002 | simple_block | Basic block rule |
| test_003 | high_value_payment_approval | Approval for amount > $500 |
| ... | ... | ... |

(Full test case inventory maintained in `TESTS.md`)

---

## Debugging Failed Tests

If a test fails in one implementation:

1. **Check decision object**: Compare actual vs expected
2. **Check policy evaluation order**: Verify rules evaluated in priority order
3. **Check condition matching**: Verify condition operators work correctly
4. **Check field path resolution**: Verify nested field access works

**Common issues**:
- Floating point precision (use epsilon comparison for floats)
- Timestamp formatting (use ISO 8601 consistently)
- Null vs undefined handling (envelope fields may be optional)

---

## Related Documents

- [Envelope Schema](../../specs/envelope_schema.json) - Input format
- [Policy Format Spec](../../docs/specs/policy_format.md) - Policy structure and evaluation
- [Decision Response Spec](../../docs/specs/decision_response.md) - Expected output format
- [CLAUDE.md](../../CLAUDE.md) - Conformance testing requirement

---

**The conformance test suite is the single source of truth for correct evaluator behavior.**
