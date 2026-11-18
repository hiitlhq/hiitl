/**
 * Performance benchmarks for PolicyEvaluator.
 *
 * Goal: Record the public typical-core target, asserting it at release (matching Python).
 * Each cell runs its warmup, then the run whose p95 is read; the timing catalogue declares both (HTL-17 19d576ee).
 *
 * Benchmarks:
 * 1. Simple atomic condition
 * 2. Logical operators (all_of, any_of, none_of)
 * 3. Multiple rules with priority sorting
 * 4. Nested conditions
 */

import { describe, it, expect, vi } from 'vitest';
import { latencyRun, latencyStatistic, recordLatency, timeCalls } from '../../../../test-support/latency.js';
import { recordMeasurement } from '../../../../test-support/measurements.js';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { DecisionType, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';
import type { Envelope, PolicySet } from '../../src/types.js';

const SOURCE = 'typescript/packages/core/tests/unit/performance.test.ts';

describe('Performance Benchmarks', () => {
  // Base envelope for testing
  const baseEnvelope: Envelope = {
    schema_version: ENVELOPE_SCHEMA_VERSION,
    org_id: 'org_abc123def456ghi789',
    environment: 'dev',
    agent_id: 'payment-agent',
    action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK',
    idempotency_key: 'idem_test123456789',
    action: 'process_payment',
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

  it('simple atomic condition meets the declared typical-core budget', () => {
    const policy: PolicySet = {
      name: 'simple-policy',
      version: 'v1.0.0',
      description: 'Evaluate a simple atomic condition',
      scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
      rules: [
        {
          name: 'allow-small-amounts',
          description: 'Allow small transactions',
          priority: 100,
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
    const run = latencyRun('core/simple-atomic');

    // Warmup run (to avoid JIT compilation overhead), timed so the record shows it ran
    const warmup = timeCalls(run.warmup, () => evaluator.evaluate(baseEnvelope, policy));

    // Benchmark run
    const samples = timeCalls(run.count, () => evaluator.evaluate(baseEnvelope, policy));
    const p95 = latencyStatistic(samples);

    // Log performance for visibility
    console.log(`Simple atomic condition: ${p95.toFixed(4)}ms p95 (${samples.length} iterations after ${warmup.length} warmup)`);

    recordMeasurement({ metric: 'core evaluation duration', unit: 'ms', source: `${SOURCE}#simple-atomic`,
      value: p95, samples, sample_count: samples.length, statistic: 'p95' });
    recordLatency('core/simple-atomic', samples, 'core', warmup);
  });

  it('logical operators meet the declared typical-core budget', () => {
    const policy: PolicySet = {
      name: 'logical-policy',
      version: 'v1.0.0',
      description: 'Evaluate logical operators (all_of)',
      scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
      rules: [
        {
          name: 'complex-rule',
          description: 'Complex logical rule',
          priority: 100,
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
    const run = latencyRun('core/logical-all-of');

    // Warmup run (to avoid JIT compilation overhead), timed so the record shows it ran
    const warmup = timeCalls(run.warmup, () => evaluator.evaluate(baseEnvelope, policy));

    // Benchmark run
    const samples = timeCalls(run.count, () => evaluator.evaluate(baseEnvelope, policy));
    const p95 = latencyStatistic(samples);

    console.log(`Logical operators (all_of): ${p95.toFixed(4)}ms p95 (${samples.length} iterations after ${warmup.length} warmup)`);

    recordMeasurement({ metric: 'core evaluation duration', unit: 'ms', source: `${SOURCE}#logical-all-of`,
      value: p95, samples, sample_count: samples.length, statistic: 'p95' });
    recordLatency('core/logical-all-of', samples, 'core', warmup);
  });

  it('priority sorting meets the declared typical-core budget', () => {
    const policy: PolicySet = {
      name: 'multi-rule-policy',
      version: 'v1.0.0',
      description: 'Evaluate multiple rules with priority sorting',
      scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
      rules: [
        {
          name: 'low-priority',
          description: 'Low priority rule',
          priority: 50,
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
    const run = latencyRun('core/priority-sorting');

    // Warmup run (to avoid JIT compilation overhead), timed so the record shows it ran
    const warmup = timeCalls(run.warmup, () => evaluator.evaluate(baseEnvelope, policy));

    // Benchmark run
    const samples = timeCalls(run.count, () => evaluator.evaluate(baseEnvelope, policy));
    const p95 = latencyStatistic(samples);

    console.log(`Multiple rules (priority sorting): ${p95.toFixed(4)}ms p95 (${samples.length} iterations after ${warmup.length} warmup)`);

    recordMeasurement({ metric: 'core evaluation duration', unit: 'ms', source: `${SOURCE}#priority-sorting`,
      value: p95, samples, sample_count: samples.length, statistic: 'p95' });
    recordLatency('core/priority-sorting', samples, 'core', warmup);
  });

  it('nested conditions meet the declared typical-core budget', () => {
    const policy: PolicySet = {
      name: 'nested-policy',
      version: 'v1.0.0',
      description: 'Evaluate nested conditions',
      scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
      rules: [
        {
          name: 'nested-rule',
          description: 'Nested logical conditions',
          priority: 100,
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
    const run = latencyRun('core/nested-conditions');

    // Warmup run (to avoid JIT compilation overhead), timed so the record shows it ran
    const warmup = timeCalls(run.warmup, () => evaluator.evaluate(baseEnvelope, policy));

    // Benchmark run
    const samples = timeCalls(run.count, () => evaluator.evaluate(baseEnvelope, policy));
    const p95 = latencyStatistic(samples);

    console.log(`Nested conditions: ${p95.toFixed(4)}ms p95 (${samples.length} iterations after ${warmup.length} warmup)`);

    recordMeasurement({ metric: 'core evaluation duration', unit: 'ms', source: `${SOURCE}#nested-conditions`,
      value: p95, samples, sample_count: samples.length, statistic: 'p95' });
    recordLatency('core/nested-conditions', samples, 'core', warmup);
  });

  it('should report timing metadata accurately', () => {
    const policy: PolicySet = {
      name: 'timing-test',
      version: 'v1.0.0',
      description: 'Report timing metadata accurately',
      scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
      rules: [
        {
          name: 'simple-rule',
          description: 'Simple rule for timing test',
          priority: 100,
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
    // These are interval facts, not latency budgets. Zero elapsed time is valid too.
    for (const trace of [
      { start: 100, validated: 102, rulesStarted: 103, rulesDone: 108, complete: 111 },
      { start: 100, validated: 100, rulesStarted: 100, rulesDone: 100, complete: 100 },
    ]) {
      const readings = Object.values(trace);
      const clock = vi.spyOn(performance, 'now').mockImplementation(() => readings.shift()!);
      try {
        expect(evaluator.evaluate(baseEnvelope, policy).timing).toEqual({
          ingest_ms: trace.validated - trace.start,
          evaluation_ms: trace.rulesDone - trace.rulesStarted,
          total_ms: trace.complete - trace.start,
        });
        expect(readings).toEqual([]);
      } finally {
        clock.mockRestore();
      }
    }
  });
});
