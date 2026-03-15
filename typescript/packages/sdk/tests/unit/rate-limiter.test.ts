/**
 * Tests for RateLimiter - in-memory sliding window rate limiting.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { RateLimiter } from '../../src/rate-limiter.js';
import type { RateLimitConfig } from '../../src/rate-limiter.js';
import type { Envelope, Decision } from '@hiitl/core';

// Test envelope
const testEnvelope: Envelope = {
  schema_version: 'v1.0',
  org_id: 'org_test000000000000000',
  environment: 'dev',
  agent_id: 'test-agent',
  action_id: 'act_test123',
  idempotency_key: 'idem_test123',
  action: 'test_tool',
  operation: 'execute',
  target: { resource: 'test' },
  parameters: { amount: 100 },
  timestamp: '2024-01-15T10:30:00Z',
  signature: '0'.repeat(64),
  user_id: 'user_alice',
};

// Test decision (ALLOW)
const testDecision: Decision = {
  action_id: 'act_test123',
  decision: 'ALLOW',
  allowed: true,
  reason_codes: ['TEST_REASON'],
  policy_version: '1.0',
  timing: {
    ingest_ms: 0.1,
    evaluation_ms: 0.2,
    total_ms: 0.3,
  },
};

describe('RateLimiter', () => {
  let limiter: RateLimiter;

  beforeEach(() => {
    limiter = new RateLimiter();
  });

  describe('Basic Rate Limiting', () => {
    it('should allow when under limit', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 10,
        window_seconds: 60,
      };

      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).toBeNull(); // No rate limiting
    });

    it('should return RATE_LIMIT decision when at limit', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 3,
        window_seconds: 60,
      };

      // Make 3 calls (at limit)
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // 4th call should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).not.toBeNull();
      expect(result!.decision).toBe('RATE_LIMIT');
      expect(result!.allowed).toBe(false);
      expect(result!.reason_codes).toContain('RATE_LIMIT_EXCEEDED');
    });

    it('should include rate limit metadata in response', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).not.toBeNull();
      expect(result!.rate_limit).toBeDefined();
      expect(result!.rate_limit!.scope).toBe('org');
      expect(result!.rate_limit!.window).toBe('60s');
      expect(result!.rate_limit!.limit).toBe(1);
      expect(result!.rate_limit!.current).toBe(1);
      expect(result!.rate_limit!.reset_at).toBeDefined();
    });

    it('should calculate reset_at correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      const start = new Date();
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      const resetAt = new Date(result!.rate_limit!.reset_at);
      const expectedReset = new Date(start.getTime() + 60 * 1000);

      // Should be within 1 second of expected
      expect(Math.abs(resetAt.getTime() - expectedReset.getTime())).toBeLessThan(
        1000
      );
    });
  });

  describe('Sliding Window', () => {
    it('should allow after window expires (sliding window)', (context) => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 2,
        window_seconds: 1, // 1 second window
      };

      // Make 2 calls (at limit)
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // 3rd call should be rate limited
      const rateLimited = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(rateLimited).not.toBeNull();

      // Wait for window to expire
      return new Promise((resolve) => {
        setTimeout(() => {
          // 4th call should succeed (window expired)
          const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
            rate_limits: [rateConfig],
          });
          expect(result).toBeNull();
          resolve(undefined);
        }, 1100); // Wait 1.1 seconds
      });
    }, 3000); // 3 second test timeout
  });

  describe('Scope Keys', () => {
    it('should use org scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // Same org_id should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).not.toBeNull();
    });

    it('should use user scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // Same user should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(result).not.toBeNull();

      // Different user should not be rate limited
      const envelopeDifferentUser = {
        ...testEnvelope,
        user_id: 'user_bob',
      };
      const resultDifferentUser = limiter.checkAndIncrement(
        envelopeDifferentUser,
        testDecision,
        { rate_limits: [rateConfig] }
      );
      expect(resultDifferentUser).toBeNull();
    });

    it('should use tool scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'tool',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // Same tool should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(result).not.toBeNull();

      // Different tool should not be rate limited
      const envelopeDifferentTool = {
        ...testEnvelope,
        action: 'different_tool',
      };
      const resultDifferentTool = limiter.checkAndIncrement(
        envelopeDifferentTool,
        testDecision,
        { rate_limits: [rateConfig] }
      );
      expect(resultDifferentTool).toBeNull();
    });

    it('should use user:tool scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user:tool',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // Same user+tool should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(result).not.toBeNull();

      // Different user, same tool should not be rate limited
      const envelopeDifferentUser = {
        ...testEnvelope,
        user_id: 'user_bob',
      };
      const resultDifferentUser = limiter.checkAndIncrement(
        envelopeDifferentUser,
        testDecision,
        { rate_limits: [rateConfig] }
      );
      expect(resultDifferentUser).toBeNull();

      // Same user, different tool should not be rate limited
      const envelopeDifferentTool = {
        ...testEnvelope,
        action: 'different_tool',
      };
      const resultDifferentTool = limiter.checkAndIncrement(
        envelopeDifferentTool,
        testDecision,
        { rate_limits: [rateConfig] }
      );
      expect(resultDifferentTool).toBeNull();
    });

    it('should handle missing user_id (use "anonymous")', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 1,
        window_seconds: 60,
      };

      const envelopeNoUser = { ...testEnvelope };
      delete (envelopeNoUser as any).user_id;

      limiter.checkAndIncrement(envelopeNoUser, testDecision, {
        rate_limits: [rateConfig],
      });

      const result = limiter.checkAndIncrement(envelopeNoUser, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).not.toBeNull();
    });
  });

  describe('Multiple Counters', () => {
    it('should maintain independent counters for different scopes', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 1,
        window_seconds: 60,
      };

      // User Alice
      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      // User Bob (different counter)
      const envelopeBob = { ...testEnvelope, user_id: 'user_bob' };
      const resultBob = limiter.checkAndIncrement(envelopeBob, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(resultBob).toBeNull(); // Bob not rate limited

      // Alice should still be rate limited
      const resultAlice = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(resultAlice).not.toBeNull();
    });
  });

  describe('Non-ALLOW Decisions', () => {
    it('should not rate limit BLOCK decisions', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      const blockDecision: Decision = {
        ...testDecision,
        decision: 'BLOCK',
        allowed: false,
      };

      const result = limiter.checkAndIncrement(testEnvelope, blockDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).toBeNull(); // No rate limiting for BLOCK
    });

    it('should not rate limit PAUSE decisions', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      const pauseDecision: Decision = {
        ...testDecision,
        decision: 'PAUSE',
        allowed: false,
      };

      const result = limiter.checkAndIncrement(testEnvelope, pauseDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).toBeNull();
    });
  });

  describe('Missing Config', () => {
    it('should not rate limit when config is missing', () => {
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {});

      expect(result).toBeNull();
    });

    it('should not rate limit when rate_limits array is empty', () => {
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [],
      });

      expect(result).toBeNull();
    });
  });

  describe('Counter Stats', () => {
    it('should retrieve counter stats', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 10,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      const stats = limiter.getCounterStats(testEnvelope.org_id);

      expect(stats).toBeDefined();
      expect(stats!.events).toHaveLength(1);
      expect(stats!.limit).toBe(10);
      expect(stats!.windowSeconds).toBe(60);
    });

    it('should return undefined for nonexistent scope', () => {
      const stats = limiter.getCounterStats('nonexistent_scope');

      expect(stats).toBeUndefined();
    });
  });

  describe('Reset', () => {
    it('should reset all counters', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      limiter.resetAll();

      // Should allow again after reset
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).toBeNull();
    });

    it('should reset specific counter', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      limiter.reset(testEnvelope.org_id);

      // Should allow again after reset
      const result = limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });

      expect(result).toBeNull();
    });

    it('should count active scopes', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 10,
        window_seconds: 60,
      };

      expect(limiter.getActiveScopeCount()).toBe(0);

      limiter.checkAndIncrement(testEnvelope, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(limiter.getActiveScopeCount()).toBe(1);

      const envelopeBob = { ...testEnvelope, user_id: 'user_bob' };
      limiter.checkAndIncrement(envelopeBob, testDecision, {
        rate_limits: [rateConfig],
      });
      expect(limiter.getActiveScopeCount()).toBe(2);
    });
  });
});
