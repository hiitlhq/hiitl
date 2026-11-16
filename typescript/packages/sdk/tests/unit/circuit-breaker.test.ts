/**
 * Unit tests for the per-channel CircuitBreaker (Block 5c).
 *
 * Parity target: `python/hiitl/sdk/tests/test_circuit_breaker.py` —
 * same state transitions, same threshold semantics, same reset timing.
 *
 * We use fake timers (vitest's `vi.useFakeTimers`) to drive the
 * monotonic clock deterministically. The breaker reads
 * `performance.now()` which vitest patches alongside `Date.now()` —
 * this lets us simulate "60 seconds elapsed" without actually waiting.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  CircuitBreaker,
  CircuitState,
} from '../../src/circuit-breaker.js';
import type { Logger } from '../../src/logger.js';

// Silent logger so tests don't spam stdout. We also assert on it where
// useful (transition log messages).
function makeSilentLogger(): Logger & { calls: Array<[string, string]> } {
  const calls: Array<[string, string]> = [];
  return {
    calls,
    debug: (msg) => calls.push(['debug', msg]),
    info: (msg) => calls.push(['info', msg]),
    warn: (msg) => calls.push(['warn', msg]),
    error: (msg) => calls.push(['error', msg]),
  };
}

describe('CircuitBreaker', () => {
  beforeEach(() => {
    // The breaker uses `performance.now()` as its monotonic clock —
    // by default vitest's fake timers patch setTimeout/setInterval/
    // Date.now but NOT performance.now. We opt into faking performance
    // explicitly via `toFake` so `vi.advanceTimersByTime` advances the
    // breaker's clock too.
    vi.useFakeTimers({
      toFake: [
        'setTimeout',
        'clearTimeout',
        'setInterval',
        'clearInterval',
        'Date',
        'performance',
      ],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts in CLOSED state', () => {
    const cb = new CircuitBreaker('audit');
    expect(cb.state).toBe(CircuitState.CLOSED);
    expect(cb.allowRequest()).toBe(true);
  });

  it('opens after threshold consecutive failures', () => {
    const log = makeSilentLogger();
    const cb = new CircuitBreaker('audit', 3, 60, log);

    cb.recordFailure();
    cb.recordFailure();
    expect(cb.state).toBe(CircuitState.CLOSED);

    cb.recordFailure(); // 3rd → trips
    expect(cb.state).toBe(CircuitState.OPEN);
    expect(cb.allowRequest()).toBe(false);
    // Logged the OPEN transition at error level.
    expect(log.calls).toEqual([['error',
      `Circuit breaker [${cb.name}] → OPEN after ${cb.failure_threshold} consecutive failures. ` +
      `Calls paused for ${cb.reset_timeout}s.`]]);
  });

  it('a single success resets the failure count without re-opening', () => {
    const cb = new CircuitBreaker('policy', 5, 60);
    cb.recordFailure();
    cb.recordFailure();
    cb.recordSuccess(); // resets counter
    cb.recordFailure();
    cb.recordFailure();
    cb.recordFailure();
    cb.recordFailure();
    // 4 consecutive failures after the reset — still under threshold of 5
    expect(cb.state).toBe(CircuitState.CLOSED);
  });

  it('transitions OPEN → HALF_OPEN after reset_timeout', () => {
    const log = makeSilentLogger();
    const cb = new CircuitBreaker('routes', 2, 30, log);

    cb.recordFailure();
    cb.recordFailure();
    expect(cb.state).toBe(CircuitState.OPEN);

    // Advance slightly less than the timeout — still OPEN.
    vi.advanceTimersByTime(29_000);
    expect(cb.state).toBe(CircuitState.OPEN);
    expect(cb.allowRequest()).toBe(false);

    // Cross the threshold — read of `.state` triggers the transition.
    vi.advanceTimersByTime(2_000);
    expect(cb.state).toBe(CircuitState.HALF_OPEN);
    expect(cb.allowRequest()).toBe(true); // allow one probe
    expect(log.calls).toEqual([
      ['error', `Circuit breaker [${cb.name}] → OPEN after ${cb.failure_threshold} consecutive failures. ` +
        `Calls paused for ${cb.reset_timeout}s.`],
      ['info', `Circuit breaker [${cb.name}] → HALF_OPEN (probing after ${cb.reset_timeout}s)`],
    ]);
  });

  it('a failed probe sends HALF_OPEN → OPEN immediately (does not require threshold)', () => {
    const log = makeSilentLogger();
    const cb = new CircuitBreaker('kill_switches', 5, 30, log);
    cb.recordFailure();
    cb.recordFailure();
    cb.recordFailure();
    cb.recordFailure();
    cb.recordFailure(); // trips
    expect(cb.state).toBe(CircuitState.OPEN);

    vi.advanceTimersByTime(30_000);
    expect(cb.state).toBe(CircuitState.HALF_OPEN);

    cb.recordFailure(); // probe fails
    expect(cb.state).toBe(CircuitState.OPEN);
    expect(log.calls).toEqual([
      ['error', `Circuit breaker [${cb.name}] → OPEN after ${cb.failure_threshold} consecutive failures. ` +
        `Calls paused for ${cb.reset_timeout}s.`],
      ['info', `Circuit breaker [${cb.name}] → HALF_OPEN (probing after ${cb.reset_timeout}s)`],
      ['warn', `Circuit breaker [${cb.name}] → OPEN (probe failed, will retry in ${cb.reset_timeout}s)`],
    ]);
  });

  it('a successful probe sends HALF_OPEN → CLOSED and resets failure count', () => {
    const log = makeSilentLogger();
    const cb = new CircuitBreaker('audit', 2, 10, log);
    cb.recordFailure();
    cb.recordFailure();
    expect(cb.state).toBe(CircuitState.OPEN);

    vi.advanceTimersByTime(10_000);
    expect(cb.state).toBe(CircuitState.HALF_OPEN);

    cb.recordSuccess();
    expect(cb.state).toBe(CircuitState.CLOSED);
    expect(cb.status().failure_count).toBe(0);
    expect(log.calls).toEqual([
      ['error', `Circuit breaker [${cb.name}] → OPEN after ${cb.failure_threshold} consecutive failures. ` +
        `Calls paused for ${cb.reset_timeout}s.`],
      ['info', `Circuit breaker [${cb.name}] → HALF_OPEN (probing after ${cb.reset_timeout}s)`],
      ['info', `Circuit breaker [${cb.name}] → CLOSED (recovered from ${CircuitState.HALF_OPEN})`],
    ]);
  });

  it('reset() forces back to CLOSED regardless of prior state', () => {
    const cb = new CircuitBreaker('telemetry', 1, 60);
    cb.recordFailure();
    expect(cb.state).toBe(CircuitState.OPEN);
    cb.reset();
    expect(cb.state).toBe(CircuitState.CLOSED);
    expect(cb.status().failure_count).toBe(0);
  });

  it('status() exposes all introspection fields', () => {
    const cb = new CircuitBreaker('policy', 7, 45);
    cb.recordFailure();
    cb.recordFailure();
    const s = cb.status();
    expect(s).toEqual({
      channel: 'policy',
      state: CircuitState.CLOSED,
      failure_count: 2,
      failure_threshold: 7,
      reset_timeout: 45,
    });
  });
});
