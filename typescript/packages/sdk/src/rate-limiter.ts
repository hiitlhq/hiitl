/**
 * Rate limiter - in-memory sliding window rate limiting for HIITL.
 *
 * Design:
 * - Sliding window algorithm (stores event timestamps)
 * - In-memory Map (suitable for local/edge mode, single process)
 * - Scope-based limits (org, user, tool, user:tool)
 * - Automatic cleanup of expired events
 * - No locks needed (Node.js is single-threaded)
 *
 * Sliding Window Algorithm:
 * 1. Store timestamps of all events in array
 * 2. On check: filter out events older than window
 * 3. Compare count to limit
 * 4. If under limit: add event, allow
 * 5. If at/over limit: return RATE_LIMIT decision
 *
 * @example
 * ```typescript
 * import { RateLimiter } from '@hiitl/sdk';
 *
 * const limiter = new RateLimiter();
 * const rateLimited = limiter.checkAndIncrement(envelope, decision, rateConfig);
 * if (rateLimited) {
 *   console.log('Rate limited!', rateLimited.rate_limit.reset_at);
 * }
 * ```
 */

import type { Envelope, Decision } from '@hiitl/core';

/**
 * Counter for a specific scope (tracks event timestamps).
 */
interface Counter {
  events: Date[]; // Timestamps of events in window
  limit: number; // Max events allowed in window
  windowSeconds: number; // Window duration in seconds
}

/**
 * Rate limit configuration from policy metadata.
 */
export interface RateLimitConfig {
  scope: string; // "org", "user", "tool", "user:tool"
  limit: number; // Max events in window
  window_seconds: number; // Window duration
}

/**
 * Rate limit metadata in decision response.
 */
export interface RateLimitMetadata {
  scope: string;
  window: string; // e.g., "60s"
  limit: number;
  current: number;
  reset_at: string; // ISO 8601 timestamp
}

/**
 * In-memory sliding window rate limiter.
 *
 * This limiter:
 * - Tracks event timestamps per scope
 * - Enforces rate limits via sliding window algorithm
 * - Automatically cleans up expired events
 * - Requires no locks (Node.js single-threaded)
 *
 * Suitable for local/edge mode (single process).
 * For multi-process deployments, use Redis-based rate limiter.
 *
 * @example
 * ```typescript
 * const limiter = new RateLimiter();
 *
 * const rateConfig = {
 *   scope: 'user',
 *   limit: 100,
 *   window_seconds: 60,
 * };
 *
 * const rateLimited = limiter.checkAndIncrement(envelope, decision, { rate_limits: [rateConfig] });
 * ```
 */
export class RateLimiter {
  private counters = new Map<string, Counter>();

  /**
   * Check rate limit and increment counter if under limit.
   *
   * This method:
   * 1. Skips non-ALLOW decisions (only rate limit allowed actions)
   * 2. Extracts rate limit config from policy metadata
   * 3. Builds scope key from envelope
   * 4. Cleans up old events (sliding window)
   * 5. Checks if count >= limit
   * 6. If at limit: returns RATE_LIMIT decision
   * 7. If under limit: adds event, returns null
   *
   * @param envelope - Execution envelope
   * @param decision - Policy decision
   * @param rateConfig - Rate limit configuration from policy metadata
   * @returns Modified decision if rate limited, null if under limit
   */
  checkAndIncrement(
    envelope: Envelope,
    decision: Decision,
    rateConfig?: { rate_limits?: RateLimitConfig[] }
  ): Decision | null {
    // Only rate limit ALLOW decisions
    if (decision.decision !== 'ALLOW') {
      return null;
    }

    // Extract rate limit config
    const config = rateConfig?.rate_limits?.[0];
    if (!config) {
      return null; // No rate limiting configured
    }

    const { scope, limit, window_seconds } = config;
    const scopeKey = this._buildScopeKey(envelope, scope);

    // Get or create counter
    let counter = this.counters.get(scopeKey);
    if (!counter) {
      counter = {
        events: [],
        limit,
        windowSeconds: window_seconds,
      };
      this.counters.set(scopeKey, counter);
    }

    // Sliding window cleanup: remove events older than window
    const now = new Date();
    const cutoff = new Date(now.getTime() - counter.windowSeconds * 1000);
    counter.events = counter.events.filter((eventTime) => eventTime > cutoff);

    // Check limit
    const currentCount = counter.events.length;
    if (currentCount >= counter.limit) {
      // Rate limit exceeded
      const resetAt = new Date(
        counter.events[0].getTime() + counter.windowSeconds * 1000
      );

      const rateLimitMetadata: RateLimitMetadata = {
        scope,
        window: `${counter.windowSeconds}s`,
        limit: counter.limit,
        current: currentCount,
        reset_at: resetAt.toISOString(),
      };

      // Return modified decision with RATE_LIMIT type
      return {
        ...decision,
        decision: 'RATE_LIMIT',
        allowed: false,
        reason_codes: ['RATE_LIMIT_EXCEEDED'],
        rate_limit: rateLimitMetadata,
      } as Decision;
    }

    // Under limit - add event and allow
    counter.events.push(now);
    return null;
  }

  /**
   * Build scope key from envelope and scope type.
   *
   * Scope types:
   * - "org": org_id
   * - "user": org_id:user_id
   * - "tool": org_id:tool_name
   * - "user:tool": org_id:user_id:tool_name
   *
   * @param envelope - Execution envelope
   * @param scope - Scope type
   * @returns Scope key for counter Map
   * @private
   */
  private _buildScopeKey(envelope: Envelope, scope: string): string {
    const orgId = envelope.org_id;

    switch (scope) {
      case 'org':
        return orgId;

      case 'user': {
        const userId = envelope.user_id ?? 'anonymous';
        return `${orgId}:${userId}`;
      }

      case 'tool':
      case 'org:tool': {
        return `${orgId}:${envelope.action}`;
      }

      case 'user:tool': {
        const userId = envelope.user_id ?? 'anonymous';
        return `${orgId}:${userId}:${envelope.action}`;
      }

      default:
        // Default to org scope for unknown scope types
        return orgId;
    }
  }

  /**
   * Get current counter stats for a scope key.
   *
   * Useful for debugging or monitoring.
   *
   * @param scopeKey - Scope key to query
   * @returns Counter object or undefined if not found
   */
  getCounterStats(scopeKey: string): Counter | undefined {
    return this.counters.get(scopeKey);
  }

  /**
   * Reset all counters.
   *
   * Useful for testing or clearing state.
   */
  resetAll(): void {
    this.counters.clear();
  }

  /**
   * Reset counter for a specific scope key.
   *
   * @param scopeKey - Scope key to reset
   */
  reset(scopeKey: string): void {
    this.counters.delete(scopeKey);
  }

  /**
   * Get count of active scopes being tracked.
   *
   * @returns Number of scope keys with counters
   */
  getActiveScopeCount(): number {
    return this.counters.size;
  }
}
