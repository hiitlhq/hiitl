/**
 * Monotonic clock helper, shared across sync engine modules.
 *
 * `performance.now()` returns milliseconds since the process started
 * (Node ≥18) and is jump-immune — the Node equivalent of Python's
 * `time.monotonic()`. We expose it in seconds because Python's sync
 * engine code uses seconds throughout, and keeping the same unit
 * makes the port byte-comparable when reading log lines side by side.
 *
 * Centralizing this single function in its own module:
 *   - Avoids three duplicate definitions across circuit-breaker.ts,
 *     sync-cache.ts, and sync-engine.ts.
 *   - Gives a single seam for tests that want to mock the clock
 *     without touching `performance.now` directly.
 */

export function monotonicSeconds(): number {
  return performance.now() / 1000;
}
