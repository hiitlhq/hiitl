/**
 * Tests for RateLimiter - in-memory sliding window rate limiting.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { RateLimiter } from '../../src/rate-limiter.js';
import { PolicySetSchema, ENVELOPE_SCHEMA_VERSION } from '@hiitl/core';
import type { Envelope, Decision } from '@hiitl/core';

/** A set-level entry (`metadata.rate_limits`) — compiled by core's loader to a windowed RATE_LIMIT rule (T47). */
type SetLimit = { scope: string; limit: number; window_seconds: number };
type RateLimitConfig = SetLimit;

/** The decision with the entries' compiled rules listed, as the evaluator lists the matching ones (T47: the limiter
 * reads rules only). */
function limited(decision: Decision, ...entries: SetLimit[]): Decision {
  const ps = PolicySetSchema.parse({ name: 'p', version: 'v1.0.0', description: 'The p set', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, rules: [], metadata: { rate_limits: entries } });
  return {
    ...decision,
    rate_limit_rules: ps.rules.map((r) => ({
      rule_name: r.name,
      policy_set: 'p',
      priority: r.priority,
      reason_code: r.reason_code,
      limit: r.rate_limit!.limit as number,
      window_seconds: r.rate_limit!.window_seconds as number,
      scope: r.rate_limit!.scope,
    })),
  };
}
/** The counter key a compiled set-level entry counts under. */
const key = (scopeKey: string, i = 0) => `rule:metadata.rate_limits[${i}]:${scopeKey}`;

// Test envelope
const testEnvelope: Envelope = {
  schema_version: ENVELOPE_SCHEMA_VERSION,
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

      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      expect(result).toBeNull(); // No rate limiting
    });

    it('should return RATE_LIMIT decision when at limit', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 3,
        window_seconds: 60,
      };

      // Make 3 calls (at limit)
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // 4th call should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      expect(result).not.toBeNull();
      expect(result!.decision).toBe('RATE_LIMIT');
      expect(result!.allowed).toBe(false);
      expect(result!.reason_codes).toEqual(['RATE_LIMIT_EXCEEDED']);
    });

    it('should include rate limit metadata in response', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

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

      const firstCall = new Date('2026-11-09T12:00:00Z');
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(firstCall);
      try {
        limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
        // A later refused call still resets when the oldest counted call leaves its window.
        vi.setSystemTime(new Date(firstCall.getTime() + 500));
        const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
        expect(new Date(result!.rate_limit!.reset_at)).toEqual(
          new Date(firstCall.getTime() + rateConfig.window_seconds * 1000)
        );
      } finally {
        vi.useRealTimers();
      }
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
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // 3rd call should be rate limited
      const rateLimited = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      expect(rateLimited).not.toBeNull();

      // Wait for window to expire
      return new Promise((resolve) => {
        setTimeout(() => {
          // 4th call should succeed (window expired)
          const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
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

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // Same org_id should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      expect(result).not.toBeNull();
    });

    it('should use user scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // Same user should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      expect(result).not.toBeNull();

      // Different user should not be rate limited
      const envelopeDifferentUser = {
        ...testEnvelope,
        user_id: 'user_bob',
      };
      const resultDifferentUser = limiter.checkAndIncrement(envelopeDifferentUser, limited(testDecision, rateConfig));
      expect(resultDifferentUser).toBeNull();
    });

    it('should use tool scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'tool',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // Same tool should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      expect(result).not.toBeNull();

      // Different tool should not be rate limited
      const envelopeDifferentTool = {
        ...testEnvelope,
        action: 'different_tool',
      };
      const resultDifferentTool = limiter.checkAndIncrement(envelopeDifferentTool, limited(testDecision, rateConfig));
      expect(resultDifferentTool).toBeNull();
    });

    it('should use user:tool scope correctly', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user:tool',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // Same user+tool should be rate limited
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      expect(result).not.toBeNull();

      // Different user, same tool should not be rate limited
      const envelopeDifferentUser = {
        ...testEnvelope,
        user_id: 'user_bob',
      };
      const resultDifferentUser = limiter.checkAndIncrement(envelopeDifferentUser, limited(testDecision, rateConfig));
      expect(resultDifferentUser).toBeNull();

      // Same user, different tool should not be rate limited
      const envelopeDifferentTool = {
        ...testEnvelope,
        action: 'different_tool',
      };
      const resultDifferentTool = limiter.checkAndIncrement(envelopeDifferentTool, limited(testDecision, rateConfig));
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

      limiter.checkAndIncrement(envelopeNoUser, limited(testDecision, rateConfig));

      const result = limiter.checkAndIncrement(envelopeNoUser, limited(testDecision, rateConfig));

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
      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      // User Bob (different counter)
      const envelopeBob = { ...testEnvelope, user_id: 'user_bob' };
      const resultBob = limiter.checkAndIncrement(envelopeBob, limited(testDecision, rateConfig));

      expect(resultBob).toBeNull(); // Bob not rate limited

      // Alice should still be rate limited
      const resultAlice = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
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

      const result = limiter.checkAndIncrement(testEnvelope, limited(blockDecision, rateConfig));

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

      const result = limiter.checkAndIncrement(testEnvelope, limited(pauseDecision, rateConfig));

      expect(result).toBeNull();
    });
  });

  describe('Missing Config', () => {
    it('should not rate limit when config is missing', () => {
      const result = limiter.checkAndIncrement(testEnvelope, testDecision);

      expect(result).toBeNull();
    });

    it('should not rate limit when rate_limits array is empty', () => {
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision));

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

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      const stats = limiter.getCounterStats(key(testEnvelope.org_id));

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

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      limiter.resetAll();

      // Should allow again after reset
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      expect(result).toBeNull();
    });

    it('should reset specific counter', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'org',
        limit: 1,
        window_seconds: 60,
      };

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      limiter.reset(key(testEnvelope.org_id));

      // Should allow again after reset
      const result = limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));

      expect(result).toBeNull();
    });

    it('should count active scopes', () => {
      const rateConfig: RateLimitConfig = {
        scope: 'user',
        limit: 10,
        window_seconds: 60,
      };

      expect(limiter.getActiveScopeCount()).toBe(0);

      limiter.checkAndIncrement(testEnvelope, limited(testDecision, rateConfig));
      expect(limiter.getActiveScopeCount()).toBe(1);

      const envelopeBob = { ...testEnvelope, user_id: 'user_bob' };
      limiter.checkAndIncrement(envelopeBob, limited(testDecision, rateConfig));
      expect(limiter.getActiveScopeCount()).toBe(2);
    });
  });
});

// A windowed RATE_LIMIT rule meters (policy_format.md "Rate-limit rules";
// R-0852): the evaluator lists it in rate_limit_rules; the limiter counts it
// on an ALLOW binding under rule:<name>:<scope key>. Mirrors the Python cells.
describe('RateLimiter — rate-limit rules', () => {
  const withRules = (
    rules: Array<[string, number, 'action' | 'agent' | 'user' | 'org']>,
    decision = 'ALLOW'
  ): Decision =>
    ({
      ...testDecision,
      decision,
      allowed: decision === 'ALLOW',
      rate_limit_rules: rules.map(([name, limit, scope]) => ({
        rule_name: name,
        policy_set: 'p',
        priority: 600,
        reason_code: name.toUpperCase(),
        limit,
        window_seconds: 3600,
        scope,
      })),
    }) as Decision;
  const env = (agent: string): Envelope => ({ ...testEnvelope, agent_id: agent });

  it('counts a matched rule window and names the rule when exceeded', () => {
    const limiter = new RateLimiter();
    const d = withRules([['refund_rate', 2, 'agent']]);
    expect(limiter.checkAndIncrement(env('a'), d)).toBeNull();
    expect(limiter.checkAndIncrement(env('a'), d)).toBeNull();
    const out = limiter.checkAndIncrement(env('a'), d);
    expect(out).not.toBeNull();
    expect(out?.decision).toBe('RATE_LIMIT');
    expect(out?.reason_codes).toEqual(['RATE_LIMIT_EXCEEDED']);
    expect(out?.matched_rules?.map((m) => m.rule_name)).toEqual(['refund_rate']);
    expect(out?.rate_limit).toMatchObject({ scope: 'agent', window: '3600s', limit: 2 });
  });

  it('keys the counter by the rule scope', () => {
    const limiter = new RateLimiter();
    const d = withRules([['refund_rate', 1, 'agent']]);
    expect(limiter.checkAndIncrement(env('a1'), d)).toBeNull();
    expect(limiter.checkAndIncrement(env('a2'), d)).toBeNull();
    expect(limiter.checkAndIncrement(env('a1'), d)?.decision).toBe('RATE_LIMIT');
  });

  it('does not count a non-ALLOW binding', () => {
    const limiter = new RateLimiter();
    expect(limiter.checkAndIncrement(env('a'), withRules([['r', 1, 'agent']], 'BLOCK'))).toBeNull();
    expect(limiter.checkAndIncrement(env('a'), withRules([['r', 1, 'agent']]))).toBeNull();
  });

  it('checks every listed rule, not only the first — compiled set-level limits included (parity with Python)', () => {
    const limiter = new RateLimiter();
    const d = limited(testDecision, { scope: 'org', limit: 100, window_seconds: 60 }, { scope: 'tool', limit: 1, window_seconds: 60 });
    expect(limiter.checkAndIncrement(testEnvelope, d)).toBeNull();
    const out = limiter.checkAndIncrement(testEnvelope, d);
    expect(out?.decision).toBe('RATE_LIMIT');
    expect(out?.matched_rules?.[0].rule_name).toBe('metadata.rate_limits[1]');
    expect(out?.rate_limit?.scope).toBe('action');
  });
});
