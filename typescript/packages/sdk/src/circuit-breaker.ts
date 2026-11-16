/**
 * Per-channel circuit breaker for the sync engine and the hosted client (Block 5c; row 174).
 *
 * Direct port of `python/hiitl/sdk/circuit_breaker.py`. State machine,
 * timing semantics, and log messages are byte-for-byte equivalent
 * with Python except where Node's single-threaded event loop makes
 * the Python `threading.Lock` unnecessary.
 *
 * States:
 *     CLOSED (normal) → requests flow normally
 *     OPEN (tripped)  → requests are blocked after N consecutive failures
 *     HALF_OPEN       → after reset timeout, one probe request is allowed
 *
 * State transitions:
 *     CLOSED  → OPEN       when failure_count >= threshold
 *     OPEN    → HALF_OPEN  when reset_timeout has elapsed
 *     HALF_OPEN → CLOSED   on success
 *     HALF_OPEN → OPEN     on failure
 *
 * Note on the monotonic clock: Python uses `time.monotonic()` which is
 * jump-immune; Node has no exact equivalent. `performance.now()` (DOMHR
 * time) is monotonic on all supported runtimes (Node ≥18) and survives
 * wall-clock jumps. Internal timestamps use `performance.now() / 1000`
 * to stay in the same unit (seconds) as Python.
 */

import type { Logger } from './logger.js';
import { consoleLogger } from './logger.js';
import { monotonicSeconds } from './time.js';

/** Circuit breaker states (string-valued to match Python's `CircuitState` enum). */
export const CircuitState = {
  CLOSED: 'closed',
  OPEN: 'open',
  HALF_OPEN: 'half_open',
} as const;
export type CircuitState = (typeof CircuitState)[keyof typeof CircuitState];

/** Status snapshot returned by `status()` — used by `SyncEngine.status()`. */
export interface CircuitBreakerStatus {
  channel: string;
  state: CircuitState;
  failure_count: number;
  failure_threshold: number;
  reset_timeout: number;
}

/**
 * Per-channel circuit breaker.
 *
 * Each sync channel (audit, policy, routes, kill switches) gets its own
 * CircuitBreaker instance so failures in one channel don't affect others,
 * and the hosted client holds one for its evaluate calls.
 */
export class CircuitBreaker {
  public readonly name: string;
  public readonly failure_threshold: number;
  public readonly reset_timeout: number;

  private _state: CircuitState = CircuitState.CLOSED;
  private _failureCount = 0;
  private _lastFailureTime = 0;
  private readonly _log: Logger;

  /**
   * @param name - Channel name for logging (e.g., "audit", "policy", "hosted")
   * @param failure_threshold - Consecutive failures before opening (default: 5)
   * @param reset_timeout - Seconds in OPEN state before probing (default: 60)
   * @param logger - Optional logger; falls back to console.
   */
  constructor(
    name: string,
    failure_threshold = 5,
    reset_timeout = 60,
    logger?: Logger
  ) {
    this.name = name;
    this.failure_threshold = failure_threshold;
    this.reset_timeout = reset_timeout;
    this._log = logger ?? consoleLogger;
  }

  /**
   * Current circuit state. Reading the state may trigger the
   * OPEN → HALF_OPEN transition if the reset timeout has elapsed —
   * this matches Python's `state` property exactly.
   */
  get state(): CircuitState {
    if (
      this._state === CircuitState.OPEN &&
      monotonicSeconds() - this._lastFailureTime >= this.reset_timeout
    ) {
      this._state = CircuitState.HALF_OPEN;
      this._log.info(
        `Circuit breaker [${this.name}] → HALF_OPEN ` +
          `(probing after ${this.reset_timeout.toFixed(0)}s)`
      );
    }
    return this._state;
  }

  /**
   * Check if a request should be allowed through the circuit.
   * Reading `.state` first triggers the OPEN → HALF_OPEN check.
   */
  allowRequest(): boolean {
    const current = this.state;
    if (current === CircuitState.CLOSED) return true;
    if (current === CircuitState.HALF_OPEN) return true; // allow one probe
    return false; // OPEN — blocked
  }

  /** Record a successful request. Resets failure count and closes circuit. */
  recordSuccess(): void {
    const previous = this._state;
    this._failureCount = 0;
    this._state = CircuitState.CLOSED;
    if (previous !== CircuitState.CLOSED) {
      this._log.info(
        `Circuit breaker [${this.name}] → CLOSED ` +
          `(recovered from ${previous})`
      );
    }
  }

  /** Record a failed request. Opens circuit after threshold failures. */
  recordFailure(): void {
    this._failureCount += 1;
    this._lastFailureTime = monotonicSeconds();

    if (this._state === CircuitState.HALF_OPEN) {
      // Probe failed — back to OPEN
      this._state = CircuitState.OPEN;
      this._log.warn(
        `Circuit breaker [${this.name}] → OPEN ` +
          `(probe failed, will retry in ${this.reset_timeout.toFixed(0)}s)`
      );
    } else if (
      this._state === CircuitState.CLOSED &&
      this._failureCount >= this.failure_threshold
    ) {
      this._state = CircuitState.OPEN;
      this._log.error(
        `Circuit breaker [${this.name}] → OPEN after ` +
          `${this._failureCount} consecutive failures. ` +
          `Calls paused for ${this.reset_timeout.toFixed(0)}s.`
      );
    }
  }

  /** Force-reset to CLOSED. Used during shutdown / restart. */
  reset(): void {
    this._state = CircuitState.CLOSED;
    this._failureCount = 0;
    this._lastFailureTime = 0;
  }

  /** Status snapshot for health reporting (consumed by SyncEngine.status()). */
  status(): CircuitBreakerStatus {
    return {
      channel: this.name,
      state: this._state,
      failure_count: this._failureCount,
      failure_threshold: this.failure_threshold,
      reset_timeout: this.reset_timeout,
    };
  }
}
