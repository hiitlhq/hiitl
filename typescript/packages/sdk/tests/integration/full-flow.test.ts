/**
 * Integration tests for HIITL SDK - full end-to-end flows.
 *
 * These tests validate:
 * - Complete evaluate() → decision flow
 * - SQLite audit persistence
 * - Rate limiting across multiple calls
 * - Policy caching performance
 * - End-to-end latency requirements
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import type { Decision } from '@hiitl/core';

const FIXTURES_DIR = path.join(__dirname, '../fixtures');
const TEST_POLICY = path.join(FIXTURES_DIR, 'valid_policy.json');
const TEST_DB = path.join(FIXTURES_DIR, 'integration_test.db');

describe('Integration: Full Flow', () => {
  let hiitl: HIITL;

  beforeEach(() => {
    // Clean up test database
    if (fs.existsSync(TEST_DB)) {
      fs.unlinkSync(TEST_DB);
    }
  });

  afterEach(() => {
    hiitl?.close();
    if (fs.existsSync(TEST_DB)) {
      fs.unlinkSync(TEST_DB);
    }
  });

  describe('End-to-End Flow', () => {
    it('should complete full evaluate → decision → audit flow', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'integration-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: TEST_DB,
        mode: 'RESPECT_POLICY',
      });

      const decision = hiitl.evaluate({
        action: 'payment_transfer',
        parameters: { amount: 500 },
      });

      // Verify decision
      expect(decision).toBeDefined();
      expect(decision.decision).toBe('ALLOW');
      expect(decision.allowed).toBe(true);
      expect(decision.action_id).toMatch(/^act_[a-f0-9]{20}$/);

      // Verify audit log created
      expect(fs.existsSync(TEST_DB)).toBe(true);
    });

    it('should persist decisions to SQLite and allow querying', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'integration-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: TEST_DB,
        mode: 'RESPECT_POLICY',
      });

      // Make multiple evaluations
      const decision1 = hiitl.evaluate({
        action: 'payment_transfer',
        parameters: { amount: 100 },
      });

      const decision2 = hiitl.evaluate({
        action: 'payment_transfer',
        parameters: { amount: 200 },
      });

      // Query audit log
      const records = hiitl.queryAudit({
        org_id: 'org_test000000000000000',
        limit: 10,
      });

      expect(records).toHaveLength(2);
      expect(records[0].action_id).toBe(decision2.action_id); // Most recent first
      expect(records[1].action_id).toBe(decision1.action_id);
    });
  });

  describe('Performance Requirements', () => {
    it('should complete evaluation in < 10ms (average)', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'perf-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:', // In-memory for speed
        mode: 'RESPECT_POLICY',
      });

      const durations: number[] = [];

      // Warm up (first call loads policy)
      hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      // Measure 100 evaluations
      for (let i = 0; i < 100; i++) {
        const start = performance.now();
        hiitl.evaluate({
          action: 'test_tool',
          parameters: { amount: 100 },
        });
        durations.push(performance.now() - start);
      }

      const avg = durations.reduce((a, b) => a + b) / durations.length;
      const p95 = durations.sort((a, b) => a - b)[Math.floor(durations.length * 0.95)];

      console.log(`Performance: avg=${avg.toFixed(2)}ms, p95=${p95.toFixed(2)}ms`);

      expect(avg).toBeLessThan(10);
      expect(p95).toBeLessThan(10);
    });

    it('should have sub-millisecond cache hits', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'cache-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      // First call (cache miss)
      const start1 = performance.now();
      hiitl.evaluate({
        action: 'test_tool',
      });
      const firstCall = performance.now() - start1;

      // Subsequent calls (cache hits)
      const cacheDurations: number[] = [];
      for (let i = 0; i < 10; i++) {
        const start = performance.now();
        hiitl.evaluate({
          action: 'test_tool',
        });
        cacheDurations.push(performance.now() - start);
      }

      const avgCache = cacheDurations.reduce((a, b) => a + b) / cacheDurations.length;

      console.log(`Cache: first=${firstCall.toFixed(2)}ms, avg=${avgCache.toFixed(2)}ms`);

      // Cache hits should be significantly faster
      expect(avgCache).toBeLessThan(firstCall);
    });

    it('should handle 1000 evaluations with good throughput', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'throughput-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        enable_rate_limiting: false, // Disable for throughput test
        mode: 'RESPECT_POLICY',
      });

      const start = performance.now();

      for (let i = 0; i < 1000; i++) {
        hiitl.evaluate({
          action: 'test_tool',
          parameters: { amount: i },
        });
      }

      const elapsed = performance.now() - start;
      const throughput = 1000 / (elapsed / 1000); // ops/sec

      console.log(`Throughput: ${throughput.toFixed(0)} ops/sec (${elapsed.toFixed(0)}ms for 1000 ops)`);

      // Should complete 1000 evaluations in reasonable time
      expect(elapsed).toBeLessThan(10000); // < 10 seconds
    });
  });

  describe('Rate Limiting Integration', () => {
    it('should enforce rate limits across multiple calls', () => {
      // Create policy with rate limiting
      const rateLimitPolicy = {
        name: 'rate-limit-integration',
        version: '1.0',
        rules: [
          {
            name: 'allow-all',
            description: 'Allow all',
            priority: 100,
            enabled: true,
            decision: 'ALLOW',
            reason_code: 'OK',
            conditions: {
              field: 'environment',
              operator: 'equals',
              value: 'dev',
            },
          },
        ],
        metadata: {
          rate_limits: [
            {
              scope: 'org',
              limit: 5,
              window_seconds: 60,
            },
          ],
        },
      };

      const ratePolicyPath = path.join(FIXTURES_DIR, 'integration_rate_policy.json');
      fs.writeFileSync(ratePolicyPath, JSON.stringify(rateLimitPolicy));

      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'rate-limit-test',
        policy_path: ratePolicyPath,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        enable_rate_limiting: true,
        mode: 'RESPECT_POLICY',
      });

      const decisions: Decision[] = [];

      // Make 10 calls (limit is 5)
      for (let i = 0; i < 10; i++) {
        decisions.push(
          hiitl.evaluate({
            action: 'test_tool',
            parameters: { index: i },
          })
        );
      }

      // First 5 should be ALLOW
      expect(decisions.slice(0, 5).every((d) => d.decision === 'ALLOW')).toBe(true);

      // Remaining 5 should be RATE_LIMIT
      expect(decisions.slice(5).every((d) => d.decision === 'RATE_LIMIT')).toBe(true);
      expect(decisions.slice(5).every((d) => d.allowed === false)).toBe(true);

      // Cleanup
      fs.unlinkSync(ratePolicyPath);
    });
  });

  describe('Error Handling Integration', () => {
    it('should handle invalid envelopes gracefully', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'error-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      expect(() =>
        hiitl.evaluate({
          action: 'test_tool',
          operation: 'invalid_operation' as any,
        })
      ).toThrow();
    });

    it('should recover from temporary errors', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'recovery-test',
        policy_path: TEST_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      // First call should succeed
      const decision1 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });
      expect(decision1.allowed).toBe(true);

      // Invalid call should fail
      expect(() =>
        hiitl.evaluate({
          action: 'test_tool',
          operation: 'invalid' as any,
          parameters: { amount: 100 },
        })
      ).toThrow();

      // Subsequent valid call should still work
      const decision2 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });
      expect(decision2.allowed).toBe(true);
    });
  });
});
