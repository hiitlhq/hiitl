/**
 * Conformance test runner.
 *
 * Validates 100% behavioral parity with Python evaluator by running
 * 54 language-neutral conformance tests.
 *
 * Tests are located in: tests/conformance/cases/ (relative to repo root)
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
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { PolicyEvaluator } from '../../src/evaluator.js';

/**
 * Conformance test case structure (language-neutral).
 */
interface ConformanceTest {
  test_id: string;
  description: string;
  envelope: any;
  policy_set: any;
  mode?: string; // OBSERVE_ALL or RESPECT_POLICY (default)
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
  };
}

/**
 * Load all conformance tests from the shared test suite.
 *
 * Conformance tests are organized by category:
 * - basic: Simple ALLOW/BLOCK cases
 * - conditions: All 14 operators (equals, greater_than, contains, etc.)
 * - logical_operators: all_of, any_of, none_of
 * - nested: Nested logical conditions
 * - edge_cases: Null handling, missing fields, edge cases
 * - priority: Rule priority ordering
 * - decisions: All decision types
 *
 * @returns Array of conformance test cases
 */
function loadConformanceTests(): ConformanceTest[] {
  const tests: ConformanceTest[] = [];

  // Path to shared conformance tests (relative from this file's location)
  // This file is at: typescript/packages/core/tests/conformance/runner.test.ts
  // Tests are at: tests/conformance/cases/
  const basePath = '../../../../../tests/conformance/cases';

  // Categories of conformance tests
  const categories = [
    'basic',
    'conditions',
    'logical_operators',
    'nested',
    'edge_cases',
    'priority',
    'decisions',
    'escalation',
    'kill_switch',
    'remediation',
    'observe',
  ];

  for (const category of categories) {
    const categoryPath = join(__dirname, basePath, category);

    try {
      const files = readdirSync(categoryPath).filter((f) => f.endsWith('.json'));

      for (const file of files) {
        const filePath = join(categoryPath, file);
        const content = readFileSync(filePath, 'utf-8');
        const test = JSON.parse(content) as ConformanceTest;
        tests.push(test);
      }
    } catch (error) {
      // Category directory may not exist - skip it
      console.warn(`Warning: Could not load tests from category: ${category}`, error);
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
  }, {} as Record<string, ConformanceTest[]>);

  // Run tests by category
  for (const [category, categoryTests] of Object.entries(testsByCategory)) {
    describe(category, () => {
      for (const test of categoryTests) {
        it(`${test.test_id}: ${test.description}`, () => {
          const mode = (test.mode ?? 'RESPECT_POLICY') as 'OBSERVE_ALL' | 'RESPECT_POLICY';
          const decision = evaluator.evaluate(test.envelope, test.policy_set, mode);

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
        });
      }
    });
  }

  // Verify we loaded all conformance tests (54 original + 6 escalation + 3 kill_switch + 4 remediation + 8 observe)
  it('should have loaded all 75 conformance tests', () => {
    expect(tests.length).toBe(75);
  });
});
