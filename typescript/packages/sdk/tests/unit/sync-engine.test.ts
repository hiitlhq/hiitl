/**
 * Unit tests for SyncEngine (Block 5e).
 *
 * Parity target: `python/hiitl/sdk/tests/test_sync_engine.py`.
 *
 * Strategy: build a real SyncEngine with stubbed SyncClient, in-memory
 * stub AuditDrainSink, and a temp-dir-backed SyncCache. We don't run
 * the background ticker in these tests — instead we call the private
 * tick / channel methods directly (via `as any`) so the test stays
 * deterministic. Background-tick wiring is covered by an explicit
 * "ticker actually fires after start()" test using fake timers.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { canonicalHash } from '@hiitl/core';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';

import {
  SyncEngine,
  type AuditDrainSink,
  type TelemetryCollectorSink,
} from '../../src/sync-engine.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncClient } from '../../src/sync-client.js';
import type { Logger } from '../../src/logger.js';

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
};

const ORG = 'org_eng_test123456';
const ENV = 'dev';
// A served policy carries its content's hash: one without is refused (sync_engine.md §2.2; HTL-29 row 137)
const P1 = { name: 'p1', content: { foo: 'bar' }, content_hash: canonicalHash({ foo: 'bar' }) };

/**
 * Minimal in-memory drain stub. Records what the engine asks for / marks.
 * Useful for asserting batching + error-id filtering without a real DB.
 */
function makeAudit(rows: Array<Record<string, unknown>>): AuditDrainSink & {
  marked: string[];
} {
  const marked: string[] = [];
  return {
    marked,
    getUnsynced(limit: number) {
      const slice = rows.slice(0, limit);
      // simulate FIFO drain
      rows.splice(0, slice.length);
      return slice;
    },
    markSynced(eventIds: string[]) {
      marked.push(...eventIds);
      return eventIds.length;
    },
  };
}

/**
 * Build a SyncClient backed by a programmable fetch queue. Each test
 * pushes responses in the order they expect the engine to make calls.
 */
function makeClient(queue: Array<Response | Error>): SyncClient {
  const fetchImpl: typeof fetch = async () => {
    const next = queue.shift();
    if (!next) throw new Error('Test bug: unexpected fetch');
    if (next instanceof Error) throw next;
    return next;
  };
  return new SyncClient({
    server_url: 'https://api.test',
    api_key: 'k_test',
    org_id: ORG,
    environment: ENV,
    max_retries: 0, // disable retry to keep tests fast
    timeout: 5,
    logger: silent,
    fetchImpl,
  });
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('SyncEngine', () => {
  let cacheDir: string;
  let cache: SyncCache;

  beforeEach(() => {
    cacheDir = mkdtempSync(path.join(tmpdir(), 'hiitl-engine-test-'));
    cache = new SyncCache({
      cache_dir: cacheDir,
      org_id: ORG,
      environment: ENV,
      logger: silent,
    });
  });

  afterEach(() => {
    rmSync(cacheDir, { recursive: true, force: true });
  });

  // ─── audit drain ──────────────────────────────────────────────────────

  it('_syncAudit uploads batches and marks accepted IDs', async () => {
    const audit = makeAudit([
      { event_id: 'evt_1', envelope: {}, decision: {} },
      { event_id: 'evt_2', envelope: {}, decision: {} },
    ]);
    const client = makeClient([
      json(200, { accepted: 2, duplicates: 0, errors: [] }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test', audit_batch_size: 100 },
      sync_cache: cache,
      audit_logger: audit,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });

    await (engine as unknown as { _syncAudit: () => Promise<void> })._syncAudit();
    expect(audit.marked).toEqual(['evt_1', 'evt_2']);
  });

  it('_syncAudit does NOT mark records that the server rejected', async () => {
    const audit = makeAudit([
      { event_id: 'evt_ok', envelope: {}, decision: {} },
      { event_id: 'evt_bad', envelope: {}, decision: {} },
    ]);
    const client = makeClient([
      json(200, {
        accepted: 1,
        duplicates: 0,
        errors: [{ event_id: 'evt_bad', code: 'BAD', message: 'no' }],
      }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: audit,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    await (engine as unknown as { _syncAudit: () => Promise<void> })._syncAudit();
    expect(audit.marked).toEqual(['evt_ok']);
    // After errors, the drain loop stops — even if more rows are waiting.
  });

  it('_syncAudit drains multiple full batches in one call', async () => {
    const rows: Array<Record<string, unknown>> = [];
    for (let i = 0; i < 25; i++) {
      rows.push({ event_id: `evt_${i}`, envelope: {}, decision: {} });
    }
    const audit = makeAudit(rows);
    const client = makeClient([
      json(200, { accepted: 10, duplicates: 0, errors: [] }),
      json(200, { accepted: 10, duplicates: 0, errors: [] }),
      json(200, { accepted: 5, duplicates: 0, errors: [] }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test', audit_batch_size: 10 },
      sync_cache: cache,
      audit_logger: audit,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    await (engine as unknown as { _syncAudit: () => Promise<void> })._syncAudit();
    expect(audit.marked).toHaveLength(25);
  });

  // ─── policy download + integrity ──────────────────────────────────────

  it('_syncPolicies updates the cache on 200 and returns true', async () => {
    const client = makeClient([
      json(200, {
        policies: [P1],
        version: 'v1',
        etag: 'eA',
        redaction_policy: { manual_redact_fields: [] },
      }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    const updated = await (
      engine as unknown as { _syncPolicies: () => Promise<boolean> }
    )._syncPolicies();
    expect(updated).toBe(true);
    expect(cache.getPolicies()).toEqual({
      policies: [P1],
      version: 'v1',
      redaction_policy: { manual_redact_fields: [] },
    });
    expect(cache.getPoliciesEtag()).toBe('eA');
  });

  it('_syncPolicies returns false on 304 and leaves cache unchanged', async () => {
    // Seed cache so we can verify it's untouched.
    await cache.updatePolicies({ policies: [{ name: 'seed' }], version: 'v0' }, 'eOld');
    const client = makeClient([new Response(null, { status: 304 })]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    const updated = await (
      engine as unknown as { _syncPolicies: () => Promise<boolean> }
    )._syncPolicies();
    expect(updated).toBe(false);
    expect(cache.getPolicies()).toEqual({ policies: [{ name: 'seed' }], version: 'v0' });
    expect(cache.getPoliciesEtag()).toBe('eOld');
  });

  it('_syncPolicies raises POLICY_INTEGRITY_VIOLATION on hash mismatch', async () => {
    const client = makeClient([
      json(200, {
        policies: [
          {
            name: 'tampered',
            content: { foo: 'bar' },
            content_hash: 'deadbeef'.repeat(8), // 64 hex chars, definitely wrong
          },
        ],
        version: 'v1',
        etag: 'e1',
      }),
    ]);
    const log: Logger & { errors: string[] } = {
      errors: [],
      debug: () => {},
      info: () => {},
      warn: () => {},
      error: (m) => log.errors.push(m),
    };
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: log,
      sync_client: client,
    });
    await expect(
      (engine as unknown as { _syncPolicies: () => Promise<boolean> })._syncPolicies()
    ).rejects.toMatchObject({ name: 'SyncError', channel: 'policy' });
    expect(log.errors).toEqual([
      `POLICY_INTEGRITY_VIOLATION: policy 'tampered' content hash mismatch ` +
      `(expected=${'deadbeef'.repeat(8)}, got=${canonicalHash({ foo: 'bar' })}). Rejecting download.`,
    ]);
  });

  it('_syncPolicies accepts policies whose content_hash matches', async () => {
    // The server's digest of the conformance case (sync_engine.md §2.2), the Python writer's same bytes
    const c = JSON.parse(
      readFileSync(path.join(__dirname, '../../../../../tests/conformance/policy_hash/case_001_fixed_policy.json'), 'utf8'),
    );

    const client = makeClient([
      json(200, {
        policies: [{ name: 'good', content: c.content, content_hash: c.expected.content_hash }],
        version: 'v1',
        etag: 'e1',
        redaction_policy: { manual_redact_fields: [] },
      }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    const updated = await (
      engine as unknown as { _syncPolicies: () => Promise<boolean> }
    )._syncPolicies();
    expect(updated).toBe(true);
  });

  // ─── routes + kill switches (smoke) ───────────────────────────────────

  it('_syncRoutes / _syncKillSwitches update the cache', async () => {
    const client = makeClient([
      json(200, { routes: [{ name: 'r1' }], etag: 'eR' }),
      json(200, { kill_switches: [{ name: 'k1' }], server_time: '2026-05-14T00:00:00Z' }),
    ]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });

    await (engine as unknown as { _syncRoutes: () => Promise<boolean> })._syncRoutes();
    expect(cache.getRoutes()).toEqual([{ name: 'r1' }]);

    await (engine as unknown as { _syncKillSwitches: () => Promise<void> })._syncKillSwitches();
    expect(cache.getKillSwitches()).toEqual([{ name: 'k1' }]);
  });

  // ─── circuit breaker protection ───────────────────────────────────────

  it('opens the kill_switches circuit breaker after threshold failures', async () => {
    const client = makeClient([
      json(500, {}),
      json(500, {}),
      json(500, {}),
      json(500, {}),
      json(500, {}),
    ]);
    const engine = new SyncEngine({
      sync_config: {
        server_url: 'https://api.test',
        circuit_breaker_threshold: 5,
      },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    // 5 consecutive failures should trip the breaker.
    const safe = (engine as unknown as {
      _safeSync: (channel: string, fn: () => Promise<unknown>) => Promise<void>;
    })._safeSync.bind(engine);
    const drain = (engine as unknown as {
      _syncKillSwitches: () => Promise<void>;
    })._syncKillSwitches.bind(engine);
    for (let i = 0; i < 5; i++) {
      await safe('kill_switches', drain);
    }
    const status = engine.status() as {
      circuit_breakers: Record<string, { state: string }>;
    };
    expect(status.circuit_breakers.kill_switches.state).toBe('open');
  });

  // ─── telemetry heartbeat ──────────────────────────────────────────────

  it('telemetry sync skips upload when there are no pending records', async () => {
    const collector: TelemetryCollectorSink = {
      flush: () => {},
      getPending: () => [],
      markSent: () => {},
      status: () => ({}),
    };
    // No fetch should fire — empty queue would throw if it did.
    const client = makeClient([]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      telemetry_collector: collector,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    await (engine as unknown as { _syncTelemetry: () => Promise<void> })._syncTelemetry();
    // No exception — passes.
  });

  it('telemetry sync uploads pending records and marks them sent', async () => {
    let markSentArg = -1;
    const pending: Array<Record<string, unknown>> = [{ kind: 'a' }, { kind: 'b' }];
    const collector: TelemetryCollectorSink = {
      flush: () => {},
      getPending: () => pending,
      markSent: (count: number) => {
        markSentArg = count;
      },
      status: () => ({}),
    };
    const client = makeClient([json(200, { accepted: 2 })]);
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      telemetry_collector: collector,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: client,
    });
    await (engine as unknown as { _syncTelemetry: () => Promise<void> })._syncTelemetry();
    expect(markSentArg).toBe(2);
  });

  // ─── lifecycle ────────────────────────────────────────────────────────

  it('start() spawns the ticker; stop() drains and flushes a final audit batch', async () => {
    // The engine's tick uses `performance.now()` to drive channel
    // scheduling — opt into faking it alongside setInterval/Date so the
    // tick fires under controlled time. Same setup as the
    // circuit-breaker tests.
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
    try {
      const audit = makeAudit([
        { event_id: 'evt_final', envelope: {}, decision: {} },
      ]);
      const client = makeClient([
        // Initial tick fires all 4 channels — order matches engine's iteration.
        json(200, { accepted: 1, duplicates: 0, errors: [] }), // audit
        json(200, { policies: [], version: 'v1', etag: 'e', redaction_policy: { manual_redact_fields: [] } }), // policy
        json(200, { routes: [], etag: 'e' }), // routes
        json(200, { kill_switches: [], server_time: 't' }), // kill switches
        // Final-audit-flush in stop(): drain returns empty, no fetch happens.
      ]);
      // First-tick semantics: every channel's lastFired is 0 at
      // construction, so a tick at any monotonic time will fire each
      // channel (now - 0 >= interval). Defaults are large (30s audit,
      // 300s policy) which would require advancing the clock by 30s+
      // to see anything fire — wasteful. We compress all intervals to
      // 0 so every channel fires on every tick within the test budget.
      const engine = new SyncEngine({
        sync_config: {
          server_url: 'https://api.test',
          audit_sync_interval: 0,
          policy_sync_interval: 0,
          route_sync_interval: 0,
          kill_switch_poll_interval: 0,
        },
        sync_cache: cache,
        audit_logger: audit,
        api_key: 'k',
        org_id: ORG,
        environment: ENV,
        logger: silent,
        sync_client: client,
      });
      engine.start();
      // First tick fires after 1s; advance well past so the chained
      // tickInFlight promise resolves.
      await vi.advanceTimersByTimeAsync(1100);
      // Allow chained promise + audit drain to complete.
      await (engine as unknown as { tickInFlight: Promise<void> }).tickInFlight;
      // Audit drained the seeded row.
      expect(audit.marked).toEqual(['evt_final']);

      vi.useRealTimers(); // stop() awaits real promises during drain
      await engine.stop();
    } finally {
      vi.useRealTimers();
    }
  });

  // ─── status snapshot ──────────────────────────────────────────────────

  it('status() includes all four breakers + telemetry when collector is present', () => {
    const collector: TelemetryCollectorSink = {
      flush: () => {},
      getPending: () => [],
      markSent: () => {},
      status: () => ({ window_count: 0 }),
    };
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' },
      sync_cache: cache,
      audit_logger: makeAudit([]),
      telemetry_collector: collector,
      api_key: 'k',
      org_id: ORG,
      environment: ENV,
      logger: silent,
      sync_client: makeClient([]),
    });
    const s = engine.status() as {
      circuit_breakers: Record<string, unknown>;
      telemetry?: Record<string, unknown>;
    };
    expect(Object.keys(s.circuit_breakers).sort()).toEqual([
      'audit',
      'kill_switches',
      'policy',
      'routes',
      'telemetry',
    ]);
    expect(s.telemetry).toEqual({ window_count: 0 });
    // Backpressure counter exposed (TICKET-107 fix).
    expect(s.tick_skip_count).toBe(0);
  });

  // ─── Sprint TICKET-107: concurrency fixes ─────────────────────────────

  describe('tick backpressure (TICKET-107 fix #2)', () => {
    /**
     * Reproduces the unbounded-chain growth bug. Before the fix, every
     * setInterval fire chained `_runOnce` onto `tickInFlight` via
     * `.then(...)`. A hung sync queued every subsequent interval fire
     * indefinitely. The fix: a `tickPending` flag that DROPS new ticks
     * when a previous one is still running, and increments a counter
     * exposed via `status().tick_skip_count`.
     *
     * Test mechanic: rig the sync client to never resolve its first
     * call. Drive the setInterval 5 times via fake timers. The first
     * tick stays pending; each of the 5 fires must be dropped, not queued.
     */
    it('drops ticks (incrementing tick_skip_count) when a previous tick is still in flight', async () => {
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
      try {
        // A fetch impl that returns a promise that never resolves —
        // simulates a hung network call.
        let resolveFirst: ((response: Response) => void) | null = null;
        const hangingFetch: typeof fetch = async () =>
          new Promise<Response>((resolve) => {
            resolveFirst = resolve;
          });
        const hangingClient = new SyncClient({
          server_url: 'https://api.test',
          api_key: 'k',
          org_id: ORG,
          environment: ENV,
          max_retries: 0,
          timeout: 60, // long — we want the hang, not a timeout
          logger: silent,
          fetchImpl: hangingFetch,
        });

        const log: Logger & { warns: string[] } = {
          warns: [],
          debug: () => {},
          info: () => {},
          warn: (m) => log.warns.push(m),
          error: () => {},
        };
        const engine = new SyncEngine({
          sync_config: {
            server_url: 'https://api.test',
            audit_sync_interval: 0, // fire on every tick
            policy_sync_interval: 9999, // suppress other channels
            route_sync_interval: 9999,
            kill_switch_poll_interval: 9999,
          },
          sync_cache: cache,
          audit_logger: makeAudit([
            { event_id: 'evt_hang', envelope: {}, decision: {} },
          ]),
          api_key: 'k',
          org_id: ORG,
          environment: ENV,
          logger: log,
          sync_client: hangingClient,
        });
        const intervals = vi.spyOn(globalThis, 'setInterval');
        engine.start();
        expect(intervals).toHaveBeenCalledTimes(1);
        const period = intervals.mock.calls[0][1] as number; // the engine's own tick
        intervals.mockRestore();
        // 1st tick fires immediately on start() and hangs on the fetch.
        // Now advance through FIRES of the engine's interval. All must be dropped.
        const FIRES = 5;
        await vi.advanceTimersByTimeAsync(FIRES * period);

        const status = engine.status() as { tick_skip_count: number };
        // Every interval fire while the first tick hangs is dropped, none queued.
        expect(status.tick_skip_count).toBe(FIRES);
        expect(log.warns).toEqual(Array.from({ length: FIRES }, (_, i) =>
          `Sync tick skipped — previous tick still in flight (total skipped: ${i + 1}). ` +
          'If this persists, sync is falling behind.'));

        // Unhang the fetch so cleanup can complete.
        if (resolveFirst) {
          resolveFirst!(
            new Response(JSON.stringify({ accepted: 1, duplicates: 0, errors: [] }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            })
          );
        }
        vi.useRealTimers();
        await engine.stop();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('stop() race (TICKET-107 fix #1)', () => {
    /**
     * Reproduces the stop()-vs-in-flight-tick race. Before the fix,
     * `stop()` would `await Promise.race([tickInFlight, timeout])` and
     * then unconditionally call `_syncAudit()` — even if the timeout
     * won the race, leaving the previous tick's `_syncAudit()` still
     * running. Two concurrent drains both call `getUnsynced(N)` (no
     * lock) → may upload the same records twice.
     *
     * The fix: track whether the tick actually completed via a
     * post-resolution flag. If the timeout wins, skip the final
     * flush and log a warning.
     *
     * Test mechanic: rig the audit drain to hang during the first
     * tick, then call stop() with a short flushTimeoutMs. The fix
     * means we get exactly ONE drain attempt (the in-flight one);
     * pre-fix would have been TWO.
     */
    it('skips the final audit flush when the in-flight tick has not completed', async () => {
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
      try {
        let drainCallCount = 0;
        const audit: AuditDrainSink = {
          getUnsynced(limit: number) {
            drainCallCount += 1;
            // Return one record on first call so the engine tries to upload.
            // Return nothing on subsequent calls (post-mark).
            if (drainCallCount === 1) {
              return [{ event_id: 'evt_x', envelope: {}, decision: {} }];
            }
            return [];
          },
          markSynced() {
            return 0;
          },
        };
        // Sync client whose POST hangs.
        const hangingFetch: typeof fetch = async () =>
          new Promise<Response>(() => {
            // never resolves
          });
        const hangingClient = new SyncClient({
          server_url: 'https://api.test',
          api_key: 'k',
          org_id: ORG,
          environment: ENV,
          max_retries: 0,
          timeout: 60,
          logger: silent,
          fetchImpl: hangingFetch,
        });

        const log: Logger & { warns: string[] } = {
          warns: [],
          debug: () => {},
          info: () => {},
          warn: (m) => log.warns.push(m),
          error: () => {},
        };
        const engine = new SyncEngine({
          sync_config: {
            server_url: 'https://api.test',
            audit_sync_interval: 0,
          },
          sync_cache: cache,
          audit_logger: audit,
          api_key: 'k',
          org_id: ORG,
          environment: ENV,
          logger: log,
          sync_client: hangingClient,
        });

        engine.start();
        // Let the first tick reach the hanging fetch.
        await vi.advanceTimersByTimeAsync(50);
        expect(drainCallCount).toBe(1); // first drain by the tick

        // Now stop() with a very short flushTimeoutMs. The tick is
        // still hanging on the fetch; stop() must NOT call _syncAudit
        // again.
        vi.useRealTimers();
        const flushTimeoutMs = 50;
        const stopPromise = engine.stop(flushTimeoutMs);
        await stopPromise;

        // Critical assertion: exactly ONE drain. Pre-fix this would
        // have been TWO (the hung tick + stop's final flush).
        expect(drainCallCount).toBe(1);
        // And the operator gets a clear warning.
        expect(log.warns).toEqual([
          `In-flight tick did not complete within ${flushTimeoutMs}ms. ` +
          'Skipping final flush to avoid concurrent _syncAudit calls. ' +
          'Any unsynced records will retry on the next start().',
        ]);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
