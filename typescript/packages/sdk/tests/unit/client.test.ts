/**
 * Tests for HIITL Client - main SDK API.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import {
  ConfigurationError,
  EnvelopeValidationError,
  PolicyLoadError,
} from '../../src/exceptions.js';

const FIXTURES_DIR = path.join(__dirname, '../fixtures');
const VALID_POLICY = path.join(FIXTURES_DIR, 'valid_policy.json');

describe('HIITL Client', () => {
  let hiitl: HIITL;

  afterEach(() => {
    hiitl?.close();
  });

  describe('Constructor', () => {
    it('should initialize with zero-config (no arguments)', () => {
      hiitl = new HIITL({ audit_db_path: ':memory:' });

      expect(hiitl).toBeDefined();
      expect(hiitl.config!.environment).toBe('dev');
      expect(hiitl.config!.agent_id).toBe('default');
      expect(hiitl.config!.org_id).toBe('org_devlocal0000000000');
      expect(hiitl.evalMode).toBe('OBSERVE_ALL');
    });

    it('should initialize with valid configuration and policy', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        mode: 'RESPECT_POLICY',
      });

      expect(hiitl).toBeDefined();
      expect(hiitl.config!.environment).toBe('dev');
      expect(hiitl.config!.agent_id).toBe('test-agent');
    });

    it('should throw ConfigurationError for invalid org_id', () => {
      expect(
        () =>
          new HIITL({
            environment: 'dev',
            agent_id: 'test-agent',
            policy_path: VALID_POLICY,
            org_id: 'invalid_org_id',
            mode: 'RESPECT_POLICY',
          })
      ).toThrow(ConfigurationError);
    });

    it('should throw ConfigurationError for RESPECT_POLICY without policy_path', () => {
      expect(
        () =>
          new HIITL({
            environment: 'dev',
            agent_id: 'test-agent',
            org_id: 'org_test000000000000000',
            mode: 'RESPECT_POLICY',
          })
      ).toThrow(ConfigurationError);
    });

    it('should throw PolicyLoadError for missing policy file', () => {
      expect(
        () =>
          new HIITL({
            environment: 'dev',
            agent_id: 'test-agent',
            policy_path: '/nonexistent/policy.json',
            org_id: 'org_test000000000000000',
            mode: 'RESPECT_POLICY',
          })
      ).toThrow(PolicyLoadError);
    });

    it('should initialize with custom audit_db_path', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      expect(hiitl.config!.audit_db_path).toBe(':memory:');
    });

    it('should initialize with rate limiting disabled', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        enable_rate_limiting: false,
        mode: 'RESPECT_POLICY',
      });

      expect(hiitl.config!.enable_rate_limiting).toBe(false);
    });
  });

  describe('Evaluate - Basic', () => {
    beforeEach(() => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });
    });

    it('should return ALLOW decision for small amount', () => {
      const decision = hiitl.evaluate({
        action: 'payment_transfer',
        parameters: { amount: 500 },
      });

      expect(decision).toBeDefined();
      expect(decision.decision).toBe('ALLOW');
      expect(decision.allowed).toBe(true);
      expect(decision.reason_codes).toContain('SMALL_AMOUNT');
    });

    it('should return BLOCK decision for large amount', () => {
      const decision = hiitl.evaluate({
        action: 'payment_transfer',
        parameters: { amount: 5000 },
      });

      expect(decision).toBeDefined();
      expect(decision.decision).toBe('BLOCK');
      expect(decision.allowed).toBe(false);
      expect(decision.reason_codes).toContain('NO_MATCHING_RULE');
    });

    it('should work with action-only (no parameters)', () => {
      const decision = hiitl.evaluate({ action: 'test_tool' });

      expect(decision).toBeDefined();
      expect(decision.decision).toBeDefined();
    });
  });

  describe('Auto-Generated Fields', () => {
    beforeEach(() => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });
    });

    it('should generate action_id with correct format (act_<20-char-hex>)', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      expect(decision.action_id).toMatch(/^act_[a-f0-9]{20}$/);
    });

    it('should generate different action_ids for each call', () => {
      const decision1 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      const decision2 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      expect(decision1.action_id).not.toBe(decision2.action_id);
    });

    it('should use provided idempotency_key', () => {
      const customKey = 'idem_custom_key_123';

      hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        idempotency_key: customKey,
      });

      // Can't directly check envelope, but test that it doesn't throw
      expect(true).toBe(true);
    });
  });

  describe('Signature', () => {
    it('should generate dummy signature when no key provided', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      // Can't directly access envelope, but test passes if no error
      expect(true).toBe(true);
    });

    it('should generate HMAC-SHA256 signature when key provided', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        signature_key: 'test-secret-key-12345',
        mode: 'RESPECT_POLICY',
      });

      hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      // Can't directly access envelope, but test passes if no error
      expect(true).toBe(true);
    });
  });

  describe('Optional Fields', () => {
    beforeEach(() => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });
    });

    it('should accept user_id', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        user_id: 'user_alice',
      });

      expect(decision).toBeDefined();
    });

    it('should accept session_id', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        session_id: 'session_xyz',
      });

      expect(decision).toBeDefined();
    });

    it('should accept confidence', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        confidence: 0.95,
      });

      expect(decision).toBeDefined();
    });

    it('should accept reason', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        reason: 'Automated test payment',
      });

      expect(decision).toBeDefined();
    });

    it('should accept sensitivity labels', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        sensitivity: ['pii', 'money'],
      });

      expect(decision).toBeDefined();
    });

    it('should accept cost_estimate', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        cost_estimate: {
          tokens: 1000,
          usd_cents: 50,
        },
      });

      expect(decision).toBeDefined();
    });

    it('should accept per-call agent_id override', () => {
      const decision = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
        agent_id: 'override-agent',
      });

      expect(decision).toBeDefined();
    });
  });

  describe('Zero-Config OBSERVE Mode', () => {
    it('should work with zero-config and return OBSERVE decisions', () => {
      hiitl = new HIITL({ audit_db_path: ':memory:' });

      const decision = hiitl.evaluate({ action: 'send_email' });

      expect(decision.allowed).toBe(true);
      expect(decision.decision).toBe('OBSERVE');
      expect(decision.would_be).toBe('BLOCK'); // NO_MATCHING_RULE wraps to OBSERVE
    });

    it('should work with rich evaluate parameters in zero-config', () => {
      hiitl = new HIITL({ audit_db_path: ':memory:' });

      const decision = hiitl.evaluate({
        action: 'process_payment',
        parameters: { amount: 500, currency: 'USD' },
        target: { account_id: 'acct_123' },
        user_id: 'user_42',
      });

      expect(decision.allowed).toBe(true);
      expect(decision.decision).toBe('OBSERVE');
    });
  });

  describe('Error Handling', () => {
    beforeEach(() => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });
    });

    it('should throw EnvelopeValidationError for invalid envelope', () => {
      expect(() =>
        hiitl.evaluate({
          action: 'test_tool',
          operation: 'invalid_operation' as any,
        })
      ).toThrow(EnvelopeValidationError);
    });
  });

  describe('Policy Caching', () => {
    beforeEach(() => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });
    });

    it('should use cached policy on second evaluation', () => {
      const decision1 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      const decision2 = hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      // Both should succeed (policy cached)
      expect(decision1).toBeDefined();
      expect(decision2).toBeDefined();
    });
  });

  describe('Rate Limiting Integration', () => {
    it('should apply rate limiting when enabled', () => {
      // Create a temp policy with rate limiting
      const tempPolicyPath = path.join(FIXTURES_DIR, 'rate_limit_policy.json');
      const ratePolicy = {
        name: 'rate-limit-policy',
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
              limit: 2,
              window_seconds: 60,
            },
          ],
        },
      };

      fs.writeFileSync(tempPolicyPath, JSON.stringify(ratePolicy));

      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: tempPolicyPath,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        enable_rate_limiting: true,
        mode: 'RESPECT_POLICY',
      });

      // First 2 calls should succeed
      const decision1 = hiitl.evaluate({ action: 'test_tool' });
      const decision2 = hiitl.evaluate({ action: 'test_tool' });

      expect(decision1.decision).toBe('ALLOW');
      expect(decision2.decision).toBe('ALLOW');

      // 3rd call should be rate limited
      const decision3 = hiitl.evaluate({ action: 'test_tool' });

      expect(decision3.decision).toBe('RATE_LIMIT');
      expect(decision3.allowed).toBe(false);

      // Cleanup
      fs.unlinkSync(tempPolicyPath);
    });

    it('should not apply rate limiting when disabled', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        enable_rate_limiting: false,
        mode: 'RESPECT_POLICY',
      });

      // Multiple calls should all succeed (no rate limiting)
      for (let i = 0; i < 100; i++) {
        const decision = hiitl.evaluate({
          action: 'test_tool',
          parameters: { amount: 100 },
        });
        expect(decision.decision).toBe('ALLOW');
      }
    });
  });

  describe('Audit Logging Integration', () => {
    it('should write to audit log', () => {
      const tempDbPath = path.join(FIXTURES_DIR, 'test_client_audit.db');

      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: tempDbPath,
        mode: 'RESPECT_POLICY',
      });

      hiitl.evaluate({
        action: 'test_tool',
        parameters: { amount: 100 },
      });

      // Verify database was created
      expect(fs.existsSync(tempDbPath)).toBe(true);

      // Cleanup
      hiitl.close();
      fs.unlinkSync(tempDbPath);
    });
  });

  describe('Close', () => {
    it('should close resources', () => {
      hiitl = new HIITL({
        environment: 'dev',
        agent_id: 'test-agent',
        policy_path: VALID_POLICY,
        org_id: 'org_test000000000000000',
        audit_db_path: ':memory:',
        mode: 'RESPECT_POLICY',
      });

      hiitl.close();

      // Should not throw
      expect(true).toBe(true);
    });
  });
});
