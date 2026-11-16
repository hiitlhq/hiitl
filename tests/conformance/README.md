# Conformance Test Suite

**Purpose**: Language-neutral conformance tests that validate all policy evaluator implementations produce identical decisions for identical inputs.

Every evaluator implementation (TypeScript, Python, and future languages) must pass this conformance suite.

---

## Overview

The conformance test suite ensures **behavioral equivalence** across all language implementations of the hiitl policy evaluator.

**Test format**: JSON test cases containing:
- Input envelope
- Policy set
- Expected decision output

**Requirement**: Same (envelope, policy) input → same decision output across all implementations

---

## Test Case Format

Each test case is a JSON file in a category directory under `cases/`:

```jsonc
{
  "test_id": "test_001_simple_allow",
  "description": "What this test validates",
  "envelope": {
    // Full envelope JSON (per envelope_schema.json)
  },
  "policy_set": {
    // Full policy set (per policy_format.md)
  },
  "expected_decision": {
    "decision": "ALLOW | BLOCK | REQUIRE_APPROVAL | etc.",
    "allowed": true,  // or false
    "reason_codes": ["REASON_CODE"]
  }
}
```

`test_id` is the file name without `.json`. `decision`, `allowed` and `reason_codes` are always checked. List `reason_codes` in the order the evaluator returns them.

A case may also set:

| Field | Meaning |
|-------|---------|
| `mode` | `OBSERVE_ALL` or `RESPECT_POLICY` (the default) |
| `enrichment` | Sync-route answers, read by conditions as `external.<route>.<field>` |

`expected_decision` may also set these. Each one is checked only when the case sets it:

| Field | Checked as |
|-------|------------|
| `matched_rules` | `[{ "rule_name", "policy_set", "priority" }]`, element for element |
| `resume_token` | `"PRESENT"` (a token is returned) or `null` (none) |
| `route_ref` | The route name, or `null` |
| `would_be`, `would_be_reason_codes` | What enforcement would decide, under `OBSERVE_ALL` |
| `staged_observations` | The staged rules that matched, element for element |
| `rate_limit_rules` | The windowed `RATE_LIMIT` rules that matched, element for element |
| `missing_fields` | Each rule skipped for a field the call does not carry, element for element; `null` means none |
| `remediation` | `{ "message", "suggestion", "type", "details" }`. When a case does not set it, the decision must carry no remediation |

A refusal case carries one artifact, `envelope`, `policy_set` or `route`, and `expected_refusal` in place of `expected_decision`:

```jsonc
"expected_refusal": { "artifact": "envelope", "at": ["cost_estimate.usd_cents"], "names": ["usd_cents"] }
```

The artifact must be refused at exactly the dotted paths in `at` (an undefined key's path ends in the key), and the refusal must name each string in `names`. Nothing is evaluated. Where a refusal is located and what it names are the same in every language; the wording of the message is each language's own.

---

## Running Conformance Tests

### TypeScript Implementation

```bash
cd typescript/packages/core
npm install
npm run test:conformance
```

Expected output:
```
 ✓ tests/conformance/envelope-signature.test.ts  (3 tests)
 ✓ tests/conformance/audit-hash.test.ts  (2 tests)
 ✓ tests/conformance/policy-hash.test.ts  (2 tests)
 ✓ tests/conformance/runner.test.ts  (146 tests)

 Test Files  4 passed (4)
      Tests  153 passed (153)
```

`runner.test.ts` runs the 159 cases, every category directory under `cases/`, and checks that it loaded all of them. `audit-hash.test.ts` runs the audit content hash case in `audit_hash/`.

### Python Implementation

```bash
cd python
pip install -r requirements.txt
python -m pytest hiitl/core/tests/conformance/
```

Expected output:
```
153 passed
```

The audit content hash case runs in Python with `python -m pytest hiitl/core/tests/test_audit_hash_conformance.py` (2 passed).

---

## Test Categories

159 cases in 22 categories, one directory per category under `cases/`. [`cases/INDEX.md`](cases/INDEX.md) lists every case.

| Category | Cases | What it covers |
|----------|-------|----------------|
| `basic` | 10 | Single rules, the default `BLOCK` (`NO_MATCHING_RULE`), the envelope's top-level fields |
| `conditions` | 14 | Each atomic condition operator |
| `logical_operators` | 6 | `all_of`, `any_of`, `none_of` |
| `nested` | 4 | Logical operators inside logical operators |
| `priority` | 7 | DENY wins: `KILL_SWITCH`, then `BLOCK`, then every other decision; then priority; then definition order |
| `decisions` | 4 | Decision types and their `allowed` value |
| `edge_cases` | 14 | Null, empty, zero, negative, Unicode, large and floating-point values, a fractional token estimate |
| `escalation` | 6 | `route_ref` and `resume_token` on `REQUIRE_APPROVAL`, `PAUSE` and `ESCALATE` |
| `kill_switch` | 3 | `KILL_SWITCH` rules |
| `remediation` | 7 | A rule's remediation on the decision |
| `observe` | 7 | `OBSERVE_ALL`, sparse envelopes |
| `lifecycle` | 8 | `lifecycle_stage` and `staged_observations` |
| `scope` | 3 | Scope whitelists on environments, agents and users |
| `temporal` | 3 | `valid_from` / `valid_to` windows |
| `percentage` | 2 | Percentage rollouts at 0 and 100 |
| `rate_limit` | 7 | Windowed `RATE_LIMIT` rules and set-level `metadata.rate_limits` |
| `uncalibrated` | 2 | Rules with an `$uncalibrated` bound |
| `principal` | 2 | Conditions on the verified principal |
| `references` | 8 | Field references as values, array-left `in` / `not_in`, `conforms_to` |
| `enrichment` | 10 | Sync-route answers as `external.*`, and `ROUTE` decisions |
| `on_missing` | 11 | A field the call does not carry: `on_missing` (`skip`, `fail_closed`), observe and staged rules, `missing_fields` |
| `refusals` | 15 | An envelope, a policy set and a route refuse a field their spec does not define, and a set one it requires, naming it; a renamed envelope field names the field it became |

---

## Adding New Test Cases

1. Create a new JSON file in its category's directory under `cases/`, following the format above
2. Run conformance tests in TypeScript implementation
3. Run conformance tests in Python implementation
4. Both must pass with identical decisions
5. Add the case to [`cases/INDEX.md`](cases/INDEX.md)

The TypeScript runner reads a fixed list of category directories and checks the total number of cases it loaded. A new case changes that total, and a new category directory must be added to the list, both in `typescript/packages/core/tests/conformance/runner.test.ts`.

**Test ID convention**: `test_<number>_<what_it_checks>.json`, with the next unused number. The `test_id` inside is the file name without `.json`.

Examples:
- `test_001_simple_allow.json`
- `test_071_require_approval_with_route.json`
- `test_082_kill_switch_overrides_allow.json`

---

## Validation

Each conformance test runner validates:

1. **Test case format**: JSON is well-formed
2. **Envelope validity**: The envelope parses in the language's envelope model (Python: Pydantic; TypeScript: Zod)
3. **Policy validity**: The policy set parses in the language's policy model
4. **Expected decision**: The evaluator's decision matches `expected_decision`, field by field as above

**Cross-language equivalence**: TypeScript and Python each pass every case, so they produce the same decision for every case's inputs.

---

## CI/CD Integration

Run both runners in CI. Both must pass:

```yaml
# Example CI steps
- name: Run Python conformance
  working-directory: python
  run: |
    pip install -r requirements.txt
    python -m pytest hiitl/core/tests/conformance/ -v --tb=short

- name: Run TypeScript conformance
  working-directory: typescript/packages/core
  run: |
    npm ci
    npx vitest run tests/conformance --reporter=verbose
```

---

## Current Test Cases

See `cases/` directory for all test cases. Summary:

| Test ID | Name | Description |
|---------|------|-------------|
| test_001 | simple_allow | Basic allow rule |
| test_002 | simple_block | Basic block rule |
| test_003 | no_matching_rule | No rule matches: `BLOCK`, `NO_MATCHING_RULE` |
| ... | ... | ... |

(Full test case inventory maintained in [`cases/INDEX.md`](cases/INDEX.md))

---

## Debugging Failed Tests

If a test fails in one implementation:

1. **Check decision object**: Compare actual vs expected
2. **Check precedence**: DENY wins (`KILL_SWITCH`, then `BLOCK`, then every other decision), then priority, then definition order
3. **Check condition matching**: Verify condition operators work correctly
4. **Check field path resolution**: Verify nested field access works

**Common issues**:
- Floating point precision (both evaluators compare numbers exactly, with no epsilon)
- Timestamp formatting (use ISO 8601 consistently)
- Null vs undefined handling (envelope fields may be optional)

---

## Related Documents

- [Envelope Schema](../../docs/specs/envelope_schema.json) - Input format
- [Policy Format Spec](../../docs/specs/policy_format.md) - Policy structure and evaluation
- [Decision Response Spec](../../docs/specs/decision_response.md) - Expected output format

---

**The specs define correct evaluator behavior. Every evaluator must pass this suite.**
