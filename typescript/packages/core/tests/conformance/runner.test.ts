/**
 * Conformance test runner.
 *
 * Validates 100% behavioral parity with Python evaluator by running
 * the language-neutral conformance cases.
 *
 * Tests are located in: tests/conformance/cases/ (repository root)
 *
 * Each test JSON file contains:
 * - test_id: Unique identifier
 * - description: What the test validates
 * - envelope: Execution envelope (input)
 * - policy_set: Policy set (input)
 * - expected_decision: Expected decision response
 *
 * We validate exact matches on:
 * - decision (ALLOW, BLOCK, etc.)
 * - allowed (boolean)
 * - reason_codes (array equality)
 *
 * A refusal case carries one artifact (envelope, policy_set or route) and `expected_refusal` in place of
 * `expected_decision`: the artifact is refused where the case says, naming what it says (R-0872, "no field is
 * ever silently dropped"), and nothing is evaluated.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { z } from 'zod';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { RouteSchema } from '../../src/route-types.js';
import { EnvelopeSchema, PolicySetSchema } from '../../src/types.js';

/**
 * Conformance test case structure (language-neutral).
 */
interface ConformanceTest {
  test_id: string;
  description: string;
  envelope: any;
  policy_set: any;
  mode?: string; // OBSERVE_ALL or RESPECT_POLICY (default)
  enrichment?: Record<string, Record<string, unknown>>; // TICKET-046: the enrichment context beside the envelope
  expected_decision: {
    decision: string;
    allowed: boolean;
    reason_codes: string[];
    matched_rules?: Array<{
      rule_name: string;
      policy_set: string;
      priority: number;
    }>;
    resume_token?: string | null; // "PRESENT" means non-null, null means absent
    route_ref?: string | null;
    remediation?: {
      message: string;
      suggestion: string;
      type: string;
      details?: Record<string, any>;
    };
    would_be?: string;
    would_be_reason_codes?: string[];
    staged_observations?: Array<{
      rule_name: string;
      policy_set: string;
      priority: number;
      would_be_decision: string;
      would_be_reason_codes: string[];
      would_be_binding: boolean;
    }>;
    rate_limit_rules?: Array<{
      rule_name: string;
      policy_set: string;
      priority: number;
      reason_code: string;
      limit: number;
      window_seconds: number;
      scope: string;
    }>;
    // HTL-22 row 176: each rule an absent field left unread; null means the decision carries none
    missing_fields?: Array<{ rule_name: string; policy_set: string; field: string }> | null;
  };
}

/**
 * A refusal case: the artifact is refused at exactly the paths in `at` (dotted; an undefined key's path ends in the
 * key), and the refusal names each of `names`.
 */
interface RefusalCase {
  test_id: string;
  description: string;
  envelope?: unknown;
  policy_set?: unknown;
  route?: unknown;
  expected_refusal: { artifact: 'envelope' | 'policy_set' | 'route'; at: string[]; names?: string[] };
}

/** The artifacts a refusal case reads, each through its model. */
const ARTIFACTS: Record<RefusalCase['expected_refusal']['artifact'], z.ZodTypeAny> = {
  envelope: EnvelopeSchema,
  policy_set: PolicySetSchema,
  route: RouteSchema,
};

/**
 * Load all conformance tests from the shared test suite: every case in every category directory under
 * tests/conformance/cases/, the categories read from the directory, never listed.
 *
 * @returns Array of conformance test cases
 */
function loadConformanceTests(): Array<ConformanceTest | RefusalCase> {
  const tests: Array<ConformanceTest | RefusalCase> = [];

  // This file is at: typescript/packages/core/tests/conformance/runner.test.ts
  // Tests are at: tests/conformance/cases/
  const casesPath = join(__dirname, '../../../../../tests/conformance/cases');
  const categories = readdirSync(casesPath, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);

  for (const category of categories) {
    const categoryPath = join(casesPath, category);
    for (const file of readdirSync(categoryPath).filter((f) => f.endsWith('.json'))) {
      tests.push(JSON.parse(readFileSync(join(categoryPath, file), 'utf-8')));
    }
  }

  return tests;
}

describe('Conformance Tests', () => {
  const evaluator = new PolicyEvaluator();
  const tests = loadConformanceTests();

  // Group tests by category for better output
  const testsByCategory = tests.reduce((acc, test) => {
    const category = test.test_id.split('_')[0];
    if (!acc[category]) {
      acc[category] = [];
    }
    acc[category].push(test);
    return acc;
  }, {} as Record<string, Array<ConformanceTest | RefusalCase>>);

  // Run tests by category
  for (const [category, categoryTests] of Object.entries(testsByCategory)) {
    describe(category, () => {
      for (const test of categoryTests) {
        it(`${test.test_id}: ${test.description}`, () => {
          if ('expected_refusal' in test) {
            const { artifact, at, names } = test.expected_refusal;
            const result = ARTIFACTS[artifact].safeParse(test[artifact]);
            expect(result.success).toBe(false);
            const issues = result.success ? [] : result.error.issues;
            const located = issues.flatMap((i) =>
              i.code === z.ZodIssueCode.unrecognized_keys ? i.keys.map((k) => [...i.path, k].join('.')) : [i.path.join('.')],
            );
            expect([...new Set(located)].sort()).toEqual([...at].sort());
            for (const name of names ?? []) expect(JSON.stringify(issues)).toContain(name);
            return;
          }
          const mode = (test.mode ?? 'RESPECT_POLICY') as 'OBSERVE_ALL' | 'RESPECT_POLICY';
          let decision!: ReturnType<PolicyEvaluator['evaluate']>;
          // the case's inputs parse (the Python runner fails a case it cannot parse, naming the case)
          expect(() => {
            decision = evaluator.evaluate(test.envelope, test.policy_set, mode, test.enrichment);
          }).not.toThrow();

          // Assert exact behavioral parity with Python
          expect(decision.decision).toBe(test.expected_decision.decision);
          expect(decision.allowed).toBe(test.expected_decision.allowed);
          expect(decision.reason_codes).toEqual(test.expected_decision.reason_codes);

          // Validate matched_rules if present in expected output
          if (test.expected_decision.matched_rules) {
            expect(decision.matched_rules).toEqual(test.expected_decision.matched_rules);
          }

          // Validate resume_token if specified in expected output
          if ('resume_token' in test.expected_decision) {
            if (test.expected_decision.resume_token === 'PRESENT') {
              // Assert resume_token is non-null (exact value is random)
              expect(decision.resume_token).toBeDefined();
              expect(decision.resume_token).toMatch(/^rtk_[a-f0-9]{32}$/);
            } else if (test.expected_decision.resume_token === null) {
              expect(decision.resume_token).toBeUndefined();
            }
          }

          // Validate route_ref if specified in expected output
          if ('route_ref' in test.expected_decision) {
            if (test.expected_decision.route_ref === null) {
              expect(decision.route_ref).toBeUndefined();
            } else {
              expect(decision.route_ref).toBe(test.expected_decision.route_ref);
            }
          }

          // Validate remediation if specified in expected output
          if ('remediation' in test.expected_decision) {
            const expectedRem = test.expected_decision.remediation;
            expect(decision.remediation).toEqual(expectedRem);
          } else {
            // If remediation not in expected, ensure it's absent
            expect(decision.remediation).toBeUndefined();
          }

          // Validate would_be if specified in expected output (OBSERVE mode)
          if ('would_be' in test.expected_decision) {
            expect(decision.would_be).toBe(test.expected_decision.would_be);
          }

          // Validate would_be_reason_codes if specified in expected output
          if ('would_be_reason_codes' in test.expected_decision) {
            expect(decision.would_be_reason_codes).toEqual(test.expected_decision.would_be_reason_codes);
          }

          // Validate staged_observations element-for-element if present
          // in expected output (TICKET-109 / Sprint item 4). The
          // evaluator always emits this field as an array, so equality
          // is straightforward — but only checked when the test
          // explicitly specifies it. Block 5b fixtures still work as
          // before because they don't set this field.
          if ('staged_observations' in test.expected_decision) {
            expect(decision.staged_observations).toEqual(
              test.expected_decision.staged_observations
            );
          }

          // rate_limit_rules (R-0852): matching windowed RATE_LIMIT rules
          if ('rate_limit_rules' in test.expected_decision) {
            expect(decision.rate_limit_rules).toEqual(test.expected_decision.rate_limit_rules);
          }

          // missing_fields (HTL-22 row 176): element for element; null means absent
          if ('missing_fields' in test.expected_decision) {
            expect(decision.missing_fields ?? null).toEqual(test.expected_decision.missing_fields);
          }
        });
      }
    });
  }

  // Verify we loaded all conformance tests:
  // 54 original + 6 escalation + 3 kill_switch + 4 remediation + 8 observe
  // + Block 5b: 4 lifecycle + 3 scope + 3 temporal + 2 percentage = 87
  // + Sprint TICKET-109: 3 staged-observation fixtures (121, 122, 123) = 90
  // + T-130 A2 (DENY wins, R-0846): 124–128 = 95
  // + T-130 A3/C6/A7 (rate-limit windows, placeholder, principal): 129–136 = 103
  // + T-130 follow-up H1 (set-level rate limits compiled to rules): 137–138 = 105
  // + T-130 §K6 (field references, array-left in / not_in, conforms_to — policy_format.md 2.6): 140–147 = 113
  // + TICKET-046 (the enrichment context — policy_format.md 2.7): 148–157 = 123
  // + HTL-20 row 146 (remediation details computed from the call; a windowed rule listed with its remediation): 158–161 = 127
  // + HTL-20 row 147 (five refusals, R-0872; a fractional token estimate): 162–167 = 133
  // + HTL-22 row 176 (on_missing: eleven evaluated cases and one refusal): 168–179 = 145
  // + HTL-22 row 165 (a set's scope, description and semver version: seven refusals): 180–186 = 152
  // + HTL-27 row 225 (the tool_name alias leaves: test_107 is the refusal test_187, and test_188): 152 - 1 + 2 = 153
  // + HTL-27, Codex's review (an absent tool_name, 189-191; a name an object inherits, 192-194): 189–194 = 159
  // + HTL-45 d0640d7a, gap 322 (a condition carries its value, 195-196; a condition is one of its two forms, 197-198): 195–198 = 163
  it('should have loaded all 163 conformance tests', () => {
    expect(tests.length).toBe(163);
  });
});
