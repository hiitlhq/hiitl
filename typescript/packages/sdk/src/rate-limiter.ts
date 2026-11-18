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
 * 2. On check: filter out events older than each window
 * 3. Compare every window's count to its limit, before counting any
 * 4. If all are under: add the event to every window, allow
 * 5. If one is at/over: return the RATE_LIMIT decision, counting nothing
 *
 * @example
 * ```typescript
 * import { RateLimiter } from '@hiitl/sdk';
 *
 * const limiter = new RateLimiter();
 * const rateLimited = limiter.checkAndIncrement(envelope, decision);
 * if (rateLimited) {
 *   console.log('Rate limited!', rateLimited.rate_limit.reset_at);
 * }
 * ```
 */

import { counterState, limitExceeded, tightest } from '@hiitl/core';
import type { Envelope, Decision } from '@hiitl/core';

/**
 * Counter for a specific scope (tracks event timestamps).
 */
interface Counter {
  events: Date[]; // Timestamps of events in window
  limit: number; // Max events allowed in window
  windowSeconds: number; // Window duration in seconds
}

// A rule's scope -> the limiter's scope-key form (mirrors hiitl/core/rate_limits.py).
const RULE_SCOPE: Record<'action' | 'agent' | 'user' | 'org' | 'user_action', string> = {
  action: 'tool',
  agent: 'agent_id',
  user: 'user',
  org: 'org',
  user_action: 'user:tool',
};

type ListedRule = NonNullable<Decision['rate_limit_rules']>[number];

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
 * // decision.rate_limit_rules: the windowed RATE_LIMIT rules the evaluator listed
 * const rateLimited = limiter.checkAndIncrement(envelope, decision);
 * ```
 */
export class RateLimiter {
  private counters = new Map<string, Counter>();

  /**
   * Read every windowed RATE_LIMIT rule the decision lists, then count the call in all of them or in none
   * (policy_format.md "Rate-limit rules"; R-0056: counted "on ALLOW decisions only"). Mirrors the Python limiter.
   *
   * Only an ALLOW is counted. The rules come from the evaluator (decision.rate_limit_rules) — one representation, the
   * rule's (T47): a set's metadata.rate_limits is compiled to such rules when the set loads. A window exceeded: the
   * RATE_LIMIT decision for the first such window in listed order, and the call is counted in no window — it did not
   * proceed. None exceeded: the call is counted in every window, the ALLOW's `rate_limit` is set to the window with
   * the least headroom left (R-0008), and null is returned.
   *
   * @param envelope - Execution envelope
   * @param decision - Policy decision
   * @returns The refusal if a window is exceeded, null otherwise
   */
  checkAndIncrement(envelope: Envelope, decision: Decision): Decision | null {
    if (decision.decision !== 'ALLOW' || !decision.rate_limit_rules?.length) {
      return null;
    }
    const now = new Date();
    const read: Array<{ rule: ListedRule; counter: Counter; resetAt: Date }> = [];
    for (const rule of decision.rate_limit_rules) {
      const counter = this._window(envelope, rule, now);
      const resetAt = new Date((counter.events[0] ?? now).getTime() + counter.windowSeconds * 1000);
      if (counter.events.length >= counter.limit) {
        return limitExceeded(decision, rule, counter.events.length, resetAt);
      }
      read.push({ rule, counter, resetAt });
    }
    for (const { counter } of read) {
      counter.events.push(now);
    }
    decision.rate_limit = tightest(read.map(({ rule, counter, resetAt }) => counterState(rule, counter.events.length, resetAt)));
    return null;
  }

  /** A rule's window, counted under `rule:<name>:<scope key>`, its calls older than the window dropped. */
  private _window(envelope: Envelope, rule: ListedRule, now: Date): Counter {
    const scopeKey = `rule:${rule.rule_name}:` + this._buildScopeKey(envelope, RULE_SCOPE[rule.scope]);
    let counter = this.counters.get(scopeKey);
    if (!counter) {
      counter = { events: [], limit: rule.limit, windowSeconds: rule.window_seconds };
      this.counters.set(scopeKey, counter);
    }
    counter.limit = rule.limit;
    counter.windowSeconds = rule.window_seconds;
    const cutoff = new Date(now.getTime() - counter.windowSeconds * 1000);
    counter.events = counter.events.filter((eventTime) => eventTime > cutoff);
    return counter;
  }

  /**
   * Build scope key from envelope and scope type.
   *
   * Scope types:
   * - "org": org_id
   * - "user": org_id:user_id
   * - "tool": org_id:action
   * - "user:tool": org_id:user_id:action
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

      case 'agent_id': {
        return `${orgId}:${envelope.agent_id ?? 'unknown'}`;
      }

      case 'user':
      case 'user_id': {
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
