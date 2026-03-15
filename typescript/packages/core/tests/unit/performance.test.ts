/**
 * Performance benchmarks for PolicyEvaluator.
 *
 * Goal: Sub-millisecond evaluation for simple policies (matching Python).
 *
 * Benchmarks:
 * 1. Simple atomic condition (< 1ms average)
 * 2. Logical operators (all_of, any_of, none_of)
 * 3. Multiple rules with priority sorting
 * 4. Nested conditions
 */

import { describe, it, expect } from 'vitest';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { DecisionType } from '../../src/types.js';
import type { Envelope, PolicySet } from '../../src/types.js';

describe('Performance Benchmarks', () => {
  // Base envelope for testing
  const baseEnvelope: Envelope = {
    schema_version: 'v1.0',
    org_id: 'org_abc123def456ghi789',
    environment: 'dev',
    agent_id: 'payment-agent',
    action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK',
    idempotency_key: 'idem_test123456789',
    tool_name: 'process_payment',
    operation: 'execute',
    target: {
      account_id: 'acct_source',
    },
    parameters: {
      amount: 1000,
      currency: 'USD',
      recipient_account_id: 'acct_recipient',
    },
    timestamp: '2024-01-15T10:30:00Z',
    signature: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
  };

  it('should evaluate simple atomic condition in < 1ms (average)', () => {
    const policy: PolicySet = {
      name: 'simple-policy',
      version: '1.0',
      rules: [
        {
          name: 'allow-small-amounts',
          description: 'Allow small transactions',
          priority: 100,
          enabled: true,
          decision: DecisionType.ALLOW,
          reason_code: 'SMALL_AMOUNT',
          conditions: {
            field: 'parameters.amount',
            operator: 'less_than',
            value: 5000,
          },
        },
      ],
    };

    const evaluator = new PolicyEvaluator();
    const iterations = 1000;

    // Warmup run (to avoid JIT compilation overhead)
    for (let i = 0; i < 100; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }

    // Benchmark run
    const start = performance.now();
    for (let i = 0; i < iterations; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }
    const elapsed = performance.now() - start;

    const avgMs = elapsed / iterations;

    // Log performance for visibility
    console.log(`Simple atomic condition: ${avgMs.toFixed(4)}ms average (${iterations} iterations)`);

    // Assert: average evaluation time should be less than 1ms
    expect(avgMs).toBeLessThan(1);
  });

  it('should evaluate logical operators (all_of) in < 2ms (average)', () => {
    const policy: PolicySet = {
      name: 'logical-policy',
      version: '1.0',
      rules: [
        {
          name: 'complex-rule',
          description: 'Complex logical rule',
          priority: 100,
          enabled: true,
          decision: DecisionType.ALLOW,
          reason_code: 'ALL_CONDITIONS_MET',
          conditions: {
            all_of: [
              {
                field: 'parameters.amount',
                operator: 'less_than',
                value: 5000,
              },
              {
                field: 'parameters.currency',
                operator: 'equals',
                value: 'USD',
              },
              {
                field: 'environment',
                operator: 'equals',
                value: 'dev',
              },
            ],
          },
        },
      ],
    };

    const evaluator = new PolicyEvaluator();
    const iterations = 1000;

    // Warmup
    for (let i = 0; i < 100; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }

    // Benchmark
    const start = performance.now();
    for (let i = 0; i < iterations; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }
    const elapsed = performance.now() - start;

    const avgMs = elapsed / iterations;

    console.log(`Logical operators (all_of): ${avgMs.toFixed(4)}ms average (${iterations} iterations)`);

    // Logical operators are slightly slower but should still be < 2ms
    expect(avgMs).toBeLessThan(2);
  });

  it('should evaluate multiple rules with priority sorting in < 2ms (average)', () => {
    const policy: PolicySet = {
      name: 'multi-rule-policy',
      version: '1.0',
      rules: [
        {
          name: 'low-priority',
          description: 'Low priority rule',
          priority: 50,
          enabled: true,
          decision: DecisionType.ALLOW,
          reason_code: 'LOW',
          conditions: {
            field: 'parameters.amount',
            operator: 'greater_than',
            value: 0,
          },
        },
        {
          name: 'medium-priority',
          description: 'Medium priority rule',
          priority: 100,
          enabled: true,
          decision: DecisionType.PAUSE,
          reason_code: 'MEDIUM',
          conditions: {
            field: 'parameters.amount',
            operator: 'greater_than',
            value: 0,
          },
        },
        {
          name: 'high-priority',
          description: 'High priority rule',
          priority: 200,
          enabled: true,
          decision: DecisionType.BLOCK,
          reason_code: 'HIGH',
          conditions: {
            field: 'parameters.amount',
            operator: 'greater_than',
            value: 0,
          },
        },
      ],
    };

    const evaluator = new PolicyEvaluator();
    const iterations = 1000;

    // Warmup
    for (let i = 0; i < 100; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }

    // Benchmark
    const start = performance.now();
    for (let i = 0; i < iterations; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }
    const elapsed = performance.now() - start;

    const avgMs = elapsed / iterations;

    console.log(`Multiple rules (priority sorting): ${avgMs.toFixed(4)}ms average (${iterations} iterations)`);

    expect(avgMs).toBeLessThan(2);
  });

  it('should evaluate nested conditions in < 2ms (average)', () => {
    const policy: PolicySet = {
      name: 'nested-policy',
      version: '1.0',
      rules: [
        {
          name: 'nested-rule',
          description: 'Nested logical conditions',
          priority: 100,
          enabled: true,
          decision: DecisionType.ALLOW,
          reason_code: 'NESTED_MATCH',
          conditions: {
            all_of: [
              {
                field: 'environment',
                operator: 'equals',
                value: 'dev',
              },
              {
                any_of: [
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'USD',
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'EUR',
                  },
                ],
              },
            ],
          },
        },
      ],
    };

    const evaluator = new PolicyEvaluator();
    const iterations = 1000;

    // Warmup
    for (let i = 0; i < 100; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }

    // Benchmark
    const start = performance.now();
    for (let i = 0; i < iterations; i++) {
      evaluator.evaluate(baseEnvelope, policy);
    }
    const elapsed = performance.now() - start;

    const avgMs = elapsed / iterations;

    console.log(`Nested conditions: ${avgMs.toFixed(4)}ms average (${iterations} iterations)`);

    expect(avgMs).toBeLessThan(2);
  });

  it('should report timing metadata accurately', () => {
    const policy: PolicySet = {
      name: 'timing-test',
      version: '1.0',
      rules: [
        {
          name: 'simple-rule',
          description: 'Simple rule for timing test',
          priority: 100,
          enabled: true,
          decision: DecisionType.ALLOW,
          reason_code: 'OK',
          conditions: {
            field: 'parameters.amount',
            operator: 'less_than',
            value: 5000,
          },
        },
      ],
    };

    const evaluator = new PolicyEvaluator();
    const decision = evaluator.evaluate(baseEnvelope, policy);

    // Timing metadata should be present and reasonable
    expect(decision.timing.ingest_ms).toBeGreaterThan(0);
    expect(decision.timing.evaluation_ms).toBeGreaterThan(0);
    expect(decision.timing.total_ms).toBeGreaterThan(0);

    // Total should be sum of ingest + evaluation (with small rounding tolerance)
    expect(decision.timing.total_ms).toBeGreaterThanOrEqual(
      decision.timing.ingest_ms + decision.timing.evaluation_ms - 0.001
    );

    console.log('Timing metadata:', decision.timing);
  });
});
