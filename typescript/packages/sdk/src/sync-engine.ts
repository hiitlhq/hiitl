/**
 * Sync engine — background synchronization orchestrator (Block 5e).
 *
 * Direct port of `python/hiitl/sdk/sync_engine.py`. Manages independent
 * sync channels on their own schedules:
 *   - Audit upload         (local → server, 30s default)
 *   - Policy download      (server → local, 5m default)
 *   - Route download       (server → local, 5m default)
 *   - Kill switch polling  (server → local, 30s default)
 *   - Telemetry upload     (optional; ignored if no collector passed)
 *
 * Core invariant: evaluation is NEVER blocked by sync. All sync operations
 * run in the background; the evaluator reads the in-memory cache directly.
 *
 * Threading model translation:
 *   - Python uses a daemon `threading.Thread` driven by a polling loop.
 *   - Node has no threads in the GIL sense — we use a single
 *     `setInterval` keyed at 1s (matching Python's 1s polling tick),
 *     plus per-channel "last fired" timestamps. Channels fire when
 *     `now - last_run >= interval`.
 *   - Shutdown is cooperative via an `AbortController`. The Python
 *     `_stop_event.wait(timeout=1.0)` pattern translates to checking
 *     `signal.aborted` between channel calls.
 *
 * No locking is needed for in-memory state — Node's single-threaded
 * event loop guarantees that JS code never runs concurrently with itself.
 */

import { canonicalHash, ORG_FIELDS, RECORD_REFUSALS, Redaction } from '@hiitl/core';

import { CircuitBreaker } from './circuit-breaker.js';
import { SyncError } from './exceptions.js';
import type { Logger } from './logger.js';
import { consoleLogger } from './logger.js';
import { SyncCache } from './sync-cache.js';
import { SyncClient } from './sync-client.js';
import { monotonicSeconds } from './time.js';

// ─── audit + telemetry contracts (decoupled from concrete impls) ──────────
//
// We define minimal interfaces here rather than importing AuditLogger and
// TelemetryCollector concretely. Two reasons:
// 1. The sync engine only needs three audit methods (getUnsynced /
//    markSynced) and a small telemetry surface. Decoupling lets callers
//    swap implementations (e.g. a Postgres-backed audit store) without
//    changing the engine.
// 2. It makes the unit tests easy — we feed in stubs that implement
//    just these surfaces.

export interface AuditDrainSink {
  /** Read unsynced records (oldest first, capped at `limit`). */
  getUnsynced(limit: number): Array<Record<string, unknown>>;
  /** Mark records as synced. Idempotent. Returns rows affected. */
  markSynced(eventIds: string[]): number;
  /** Mark records refused with the service's code, by event_id (row 224). Returns rows affected. */
  markRefused(refusals: Record<string, string>): number;
  /**
   * The unsynced records: [how many, their size in bytes]. The engine reads BUFFER_FULL from it
   * (sync_engine.md section 7); a sink without it is not checked.
   */
  unsyncedBacklog?(): [number, number];
}

const isRecordRefusal = (code: unknown): boolean => (RECORD_REFUSALS as readonly unknown[]).includes(code);

/**
 * An upload's answer, settled in the local store (sync_engine.md section 2.1; row 224, ruled 2026-11-08). A record no
 * error names is marked synced. A record refused for its own content (core's `RECORD_REFUSALS`) is final: it stays in
 * the store as written, marked refused with the code, logged at error, and is not sent again. Any other error leaves
 * its record unsynced, logged at warning; a code the SDK does not know is retried, never read as final. The sync
 * engine and the hosted client both settle here, each logging to its own `log`. Mirrors audit.py `settle_upload`.
 *
 * @returns Whether the drain goes on: false when any error is retried
 */
export function settleUpload(
  store: Pick<AuditDrainSink, 'markSynced' | 'markRefused'>,
  records: ReadonlyArray<Record<string, unknown>>,
  errors: ReadonlyArray<Record<string, unknown>>,
  log: Logger,
): boolean {
  const retried = new Set(errors.filter((e) => !isRecordRefusal(e.code)).map((e) => e.event_id));
  const sent = records.map((r) => r.event_id as string);
  const refused: Record<string, string> = {};
  for (const e of errors) {
    if (isRecordRefusal(e.code) && sent.includes(e.event_id as string) && !retried.has(e.event_id)) {
      refused[e.event_id as string] = e.code as string;
    }
  }
  const synced = sent.filter((id) => !Object.hasOwn(refused, id) && !retried.has(id));
  if (synced.length > 0) store.markSynced(synced);
  if (Object.keys(refused).length > 0) store.markRefused(refused);
  for (const err of errors) {
    if (isRecordRefusal(err.code)) {
      log.error(
        `Audit record ${err.event_id ?? '?'} refused for its own content: [${err.code}] ${err.message ?? '?'}. ` +
          'It is kept in the local store, marked refused, and not sent again (sync_engine.md section 2.1).'
      );
    } else {
      log.warn(
        `Audit record ${err.event_id ?? '?'} was not stored: [${err.code ?? '?'}] ${err.message ?? '?'}. ` +
          'It stays unsynced and is sent again.'
      );
    }
  }
  return retried.size === 0;
}

export interface TelemetryCollectorSink {
  /** Roll the current window into a pending record. */
  flush(): void;
  /** Read all pending (un-uploaded) records. */
  getPending(): Array<Record<string, unknown>>;
  /** Mark records as sent so they don't re-upload. */
  markSent(count: number): void;
  /** Status snapshot for engine health reporting. */
  status(): Record<string, unknown>;
}

// ─── configuration ────────────────────────────────────────────────────────

export interface SyncConfig {
  /** Backend base URL — e.g. `https://api.hiitl.com`. */
  server_url: string;
  /** Audit upload interval in seconds. Default 30. */
  audit_sync_interval?: number;
  /** Max records per audit upload batch. Default 100. */
  audit_batch_size?: number;
  /** Unsynced audit records at which BUFFER_FULL is emitted. Default 10000. */
  max_buffer_records?: number;
  /** Unsynced audit bytes at which BUFFER_FULL is emitted. Default 52428800 (50 MB). */
  max_buffer_size_bytes?: number;
  /** Policy download interval in seconds. Default 300. */
  policy_sync_interval?: number;
  /** Route download interval in seconds. Default 300. */
  route_sync_interval?: number;
  /** Kill switch poll interval in seconds. Default 30. */
  kill_switch_poll_interval?: number;
  /** Telemetry sync interval (only used when a collector is passed). Default 60. */
  telemetry_sync_interval?: number;
  /** Per-request timeout in seconds. Default 10. */
  sync_timeout?: number;
  /** Max retry attempts for transient failures. Default 3. */
  sync_max_retries?: number;
  /** Circuit-breaker consecutive-failure threshold. Default 5. */
  circuit_breaker_threshold?: number;
  /** Circuit-breaker reset timeout (OPEN → HALF_OPEN). Default 60s. */
  circuit_breaker_reset?: number;
}

export interface SyncEngineOptions {
  sync_config: SyncConfig;
  sync_cache: SyncCache;
  audit_logger: AuditDrainSink;
  api_key: string;
  org_id: string;
  environment: string;
  /** Optional telemetry collector. When omitted, telemetry sync is disabled. */
  telemetry_collector?: TelemetryCollectorSink;
  /** Optional logger. */
  logger?: Logger;
  /** Optional pre-built sync client (used in tests to inject a stub). */
  sync_client?: SyncClient;
}

/** The sync engine's defaults (sync_engine.md §9); the hosted client's push batch is audit_batch_size's. */
export const DEFAULTS = {
  audit_sync_interval: 30,
  audit_batch_size: 100,
  max_buffer_records: 10_000,
  max_buffer_size_bytes: 52_428_800,
  policy_sync_interval: 300,
  route_sync_interval: 300,
  kill_switch_poll_interval: 30,
  telemetry_sync_interval: 60,
  sync_timeout: 10,
  sync_max_retries: 3,
  circuit_breaker_threshold: 5,
  circuit_breaker_reset: 60,
} as const;

// ─── engine ───────────────────────────────────────────────────────────────

export class SyncEngine {
  private readonly config: Required<SyncConfig>;
  private readonly cache: SyncCache;
  private readonly auditLogger: AuditDrainSink;
  private readonly telemetryCollector?: TelemetryCollectorSink;
  private readonly client: SyncClient;
  private readonly breakers: Record<string, CircuitBreaker>;
  private readonly log: Logger;

  private auditSequence = 0;
  /** BUFFER_FULL is logged once per crossing, re-armed below the limit. */
  private bufferFull = false;
  private lastTelemetrySentSec = 0;
  private started = false;
  private tickerHandle: ReturnType<typeof setInterval> | null = null;
  private stopController = new AbortController();
  /** Promise that resolves when the current tick's work finishes. */
  private tickInFlight: Promise<void> = Promise.resolve();
  /**
   * True between the moment a tick is dispatched and the moment it
   * resolves. Used by the setInterval handler to apply BACKPRESSURE —
   * if a tick is still running when the next interval fires, the new
   * tick is dropped instead of being queued onto `tickInFlight`. Without
   * this, a hung sync (slow network, server stall, dropped retry) would
   * queue every subsequent tick indefinitely; on recovery, the SDK
   * would hammer the server with the backlog.
   */
  private tickPending = false;
  /** Count of ticks skipped due to `tickPending` backpressure. Exposed via `status()`. */
  private tickSkipCount = 0;

  // Per-channel "last fired" timestamps in monotonic seconds. 0 means
  // "fire on next tick" — the initial value, so all channels run
  // immediately on the first tick. Matches Python sync_engine.py.
  private lastAudit = 0;
  private lastPolicy = 0;
  private lastRoutes = 0;
  private lastKillSwitches = 0;
  private lastTelemetry = 0;

  constructor(opts: SyncEngineOptions) {
    this.config = mergeWithDefaults(opts.sync_config);
    this.cache = opts.sync_cache;
    this.auditLogger = opts.audit_logger;
    this.telemetryCollector = opts.telemetry_collector;
    this.log = opts.logger ?? consoleLogger;

    this.client =
      opts.sync_client ??
      new SyncClient({
        server_url: this.config.server_url,
        api_key: opts.api_key,
        org_id: opts.org_id,
        environment: opts.environment,
        timeout: this.config.sync_timeout,
        max_retries: this.config.sync_max_retries,
        logger: this.log,
      });

    const cbThreshold = this.config.circuit_breaker_threshold;
    const cbReset = this.config.circuit_breaker_reset;
    this.breakers = {
      audit: new CircuitBreaker('audit', cbThreshold, cbReset, this.log),
      policy: new CircuitBreaker('policy', cbThreshold, cbReset, this.log),
      routes: new CircuitBreaker('routes', cbThreshold, cbReset, this.log),
      kill_switches: new CircuitBreaker(
        'kill_switches',
        cbThreshold,
        cbReset,
        this.log
      ),
    };
    if (this.telemetryCollector) {
      this.breakers.telemetry = new CircuitBreaker(
        'telemetry',
        cbThreshold,
        cbReset,
        this.log
      );
    }
  }

  // ─── lifecycle ────────────────────────────────────────────────────────

  /**
   * Start the background sync ticker. Non-blocking — returns immediately.
   * The first tick fires all pull channels (lastAudit / lastPolicy / etc.
   * are all 0).
   */
  start(): void {
    if (this.started) return;
    this.stopController = new AbortController();
    // Python's _run_loop fires the first iteration BEFORE its first
    // _stop_event.wait(1.0) — meaning sync runs immediately on start,
    // not after a 1-second delay. Mirror that here: kick off the first
    // tick before scheduling the interval. Without this, a caller who
    // does `engine.start(); await engine.stop();` would see zero syncs.
    this._dispatchTick();

    this.tickerHandle = setInterval(() => {
      this._dispatchTick();
    }, 1000);
    // `unref` lets the Node process exit naturally if nothing else is
    // pending. The user has to call `stop()` explicitly to drain — same
    // pattern as a daemon thread.
    if (typeof this.tickerHandle.unref === 'function') {
      this.tickerHandle.unref();
    }
    this.started = true;
    this.log.info(`Sync engine started (server=${this.config.server_url})`);
  }

  /**
   * Dispatch a tick if no previous tick is still running. If a previous
   * tick IS still running, increment the skip counter and log a warning
   * (visibility > noise — operators need to see when sync is falling
   * behind). Block 5e's original implementation chained ticks via
   * `tickInFlight.then(...)`, which queued every interval fire onto a
   * single promise chain. Under sustained slow sync, that produced
   * unbounded backlog growth. This pattern drops new ticks on the
   * floor instead — backpressure at the source.
   */
  private _dispatchTick(): void {
    if (this.tickPending) {
      this.tickSkipCount += 1;
      this.log.warn(
        `Sync tick skipped — previous tick still in flight ` +
          `(total skipped: ${this.tickSkipCount}). ` +
          `If this persists, sync is falling behind.`
      );
      return;
    }
    this.tickPending = true;
    this.tickInFlight = this._runOnce().finally(() => {
      this.tickPending = false;
    });
  }

  /**
   * Stop the sync engine, drain in-flight work, and flush a final audit
   * batch on best-effort basis.
   *
   * @param flushTimeoutMs Max time to wait for in-flight tick + final
   *   flush (default 5000ms). Matches Python's 5s default.
   */
  async stop(flushTimeoutMs = 5_000): Promise<void> {
    if (!this.started) return;
    this.log.info('Stopping sync engine...');
    this.stopController.abort();
    if (this.tickerHandle !== null) {
      clearInterval(this.tickerHandle);
      this.tickerHandle = null;
    }

    // Wait for any in-flight tick to finish, up to the timeout. Track
    // whether the tick actually completed (vs. the timeout winning the
    // race). Block 5 retrospective TICKET-107: if the timeout wins and
    // we then call `_syncAudit()` here, it races with the still-running
    // tick's own `_syncAudit()` — two concurrent drains both call
    // `getUnsynced(N)` (no lock) and may upload the same records twice.
    // Server-side dedup masks user impact but wastes bandwidth.
    let tickCompleted = false;
    this.tickInFlight.then(() => {
      tickCompleted = true;
    }).catch(() => {
      // If the tick rejected, treat it as "completed" — the rejection
      // already happened; there's no concurrent work to race with.
      tickCompleted = true;
    });
    await Promise.race([
      this.tickInFlight.catch(() => undefined),
      new Promise<void>((resolve) => setTimeout(resolve, flushTimeoutMs)),
    ]);

    // Best-effort final flushes — only when the in-flight tick has
    // actually finished. If we timed out, the tick is still going and
    // a concurrent final flush would race against it. Skip with a warn
    // so the operator knows shutdown wasn't fully clean.
    if (tickCompleted) {
      try {
        await this._syncAudit();
      } catch (e) {
        this.log.warn(
          `Final audit flush failed: ${e instanceof Error ? e.message : String(e)}`
        );
      }
      if (this.telemetryCollector) {
        try {
          await this._syncTelemetry();
        } catch (e) {
          this.log.warn(
            `Final telemetry flush failed: ${e instanceof Error ? e.message : String(e)}`
          );
        }
      }
    } else {
      this.log.warn(
        `In-flight tick did not complete within ${flushTimeoutMs}ms. ` +
          'Skipping final flush to avoid concurrent _syncAudit calls. ' +
          'Any unsynced records will retry on the next start().'
      );
    }

    this.started = false;
    this.log.info('Sync engine stopped');
  }

  /**
   * Perform initial sync (blocking, for cold start with no disk cache).
   * Attempts policy download first, then routes + kill switches within
   * the remaining time budget.
   *
   * @returns true if policies were downloaded; false otherwise.
   */
  async initialSync(timeoutSec = 10): Promise<boolean> {
    // Use monotonic seconds for the deadline so a wall-clock jump
    // (NTP correction, daylight-savings, manual time-set) doesn't
    // unexpectedly extend or shrink the budget. Python uses
    // time.monotonic() for the same reason.
    const deadlineSec = monotonicSeconds() + timeoutSec;
    let policiesOk = false;

    if (monotonicSeconds() < deadlineSec) {
      try {
        policiesOk = await this._syncPolicies();
      } catch (e) {
        this.log.warn(
          `Initial policy sync failed: ${e instanceof Error ? e.message : String(e)}`
        );
      }
    }
    if (monotonicSeconds() < deadlineSec) {
      try {
        await this._syncRoutes();
      } catch (e) {
        this.log.warn(
          `Initial route sync failed: ${e instanceof Error ? e.message : String(e)}`
        );
      }
    }
    if (monotonicSeconds() < deadlineSec) {
      try {
        await this._syncKillSwitches();
      } catch (e) {
        this.log.warn(
          `Initial kill switch sync failed: ${e instanceof Error ? e.message : String(e)}`
        );
      }
    }

    if (policiesOk) {
      this.log.info('Initial sync completed: policies downloaded');
    } else {
      this.log.warn(
        `Initial sync: no policies downloaded within ${timeoutSec.toFixed(1)}s timeout. ` +
          'Using local fallback.'
      );
    }
    return policiesOk;
  }

  /** Engine health status — used for /v1/health dashboards. */
  status(): Record<string, unknown> {
    const result: Record<string, unknown> = {
      running: this.started,
      server_url: this.config.server_url,
      cache: this.cache.status(),
      circuit_breakers: Object.fromEntries(
        Object.entries(this.breakers).map(([name, cb]) => [name, cb.status()])
      ),
      audit_sequence: this.auditSequence,
      // Backpressure visibility (Block 5e SR review fix). If this number
      // grows over time, sync is slower than the 1s tick cadence — likely
      // a slow server or a wide hanging request. TICKET-110 wires this
      // into a metrics callback so operators can alert on it.
      tick_skip_count: this.tickSkipCount,
    };
    if (this.telemetryCollector) {
      result.telemetry = this.telemetryCollector.status();
    }
    return result;
  }

  // ─── tick loop ────────────────────────────────────────────────────────

  /**
   * One tick of the sync loop. Each channel fires on its own schedule.
   * Errors are isolated per channel (circuit breaker handles them).
   */
  private async _runOnce(): Promise<void> {
    if (this.stopController.signal.aborted) return;
    const now = monotonicSeconds();

    if (now - this.lastAudit >= this.config.audit_sync_interval) {
      // the backlog is read first, whatever the audit circuit's state
      this._checkAuditBuffer();
      await this._safeSync('audit', () => this._syncAudit());
      this.lastAudit = monotonicSeconds();
    }
    if (now - this.lastPolicy >= this.config.policy_sync_interval) {
      await this._safeSync('policy', () => this._syncPolicies());
      this.lastPolicy = monotonicSeconds();
    }
    if (now - this.lastRoutes >= this.config.route_sync_interval) {
      await this._safeSync('routes', () => this._syncRoutes());
      this.lastRoutes = monotonicSeconds();
    }
    if (now - this.lastKillSwitches >= this.config.kill_switch_poll_interval) {
      await this._safeSync('kill_switches', () => this._syncKillSwitches());
      this.lastKillSwitches = monotonicSeconds();
    }
    if (this.telemetryCollector) {
      if (now - this.lastTelemetry >= this.config.telemetry_sync_interval) {
        await this._safeSync('telemetry', () => this._syncTelemetry());
        this.lastTelemetry = monotonicSeconds();
      }
    }
  }

  /**
   * Emit BUFFER_FULL when the unsynced audit backlog reaches its limit (sync_engine.md section 7):
   * max_buffer_records records or max_buffer_size_bytes bytes, whichever comes first. Logged once
   * per crossing. No record is dropped: the backlog is the local audit store, on disk, and it
   * uploads oldest-first when sync recovers. Mirrors sync_engine.py `_check_audit_buffer`.
   */
  private _checkAuditBuffer(): void {
    if (!this.auditLogger.unsyncedBacklog) return;
    let count: number;
    let size: number;
    try {
      [count, size] = this.auditLogger.unsyncedBacklog();
    } catch (err) {
      this.log.warn(`BUFFER_FULL check could not read the audit backlog: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    const full = count >= this.config.max_buffer_records || size >= this.config.max_buffer_size_bytes;
    if (full && !this.bufferFull) {
      this.log.warn(
        `BUFFER_FULL: ${count} unsynced audit records (${size} bytes) have reached the audit buffer's limit ` +
          `(max_buffer_records=${this.config.max_buffer_records}, max_buffer_size_bytes=${this.config.max_buffer_size_bytes}). ` +
          'No record is dropped: they stay in the local audit store and upload, oldest first, when sync recovers.'
      );
    }
    this.bufferFull = full;
  }

  /** Execute a sync function with circuit-breaker protection. */
  private async _safeSync(channel: string, fn: () => Promise<unknown>): Promise<void> {
    const breaker = this.breakers[channel];
    if (!breaker.allowRequest()) return; // Circuit open

    try {
      await fn();
      breaker.recordSuccess();
    } catch (err) {
      breaker.recordFailure();
      if (err instanceof SyncError) {
        this.log.warn(`Sync [${channel}] failed: ${err.message}`);
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        this.log.error(`Sync [${channel}] unexpected error: ${msg}`);
      }
    }
  }

  // ─── channel implementations ──────────────────────────────────────────

  /**
   * Upload unsynced audit records in batches, each answer settled by `settleUpload`. Drains until either:
   *   - the audit table is empty
   *   - a batch returns a retried error (stops to retry next interval); a refusal for a record's own content does
   *     not stop it (row 224)
   *   - shutdown is requested
   *   - the batch was a partial batch (no more records waiting)
   */
  private async _syncAudit(): Promise<void> {
    while (true) {
      const records = this.auditLogger.getUnsynced(this.config.audit_batch_size);
      if (records.length === 0) break;

      this.auditSequence += 1;
      const result = await this.client.uploadAudit(records, this.auditSequence);
      const goesOn = settleUpload(this.auditLogger, records, result.errors, this.log);

      this.log.debug(
        `Audit sync: accepted=${result.accepted}, duplicates=${result.duplicates}, errors=${result.errors.length}`
      );

      // A retried refusal stops the drain until the next interval; a final one does not (row 224)
      if (!goesOn) break;

      if (records.length < this.config.audit_batch_size) break;
      if (this.stopController.signal.aborted) break;
    }
  }

  /**
   * Download policies. Verifies each policy's content_hash before caching, in the one form every writer and checker
   * reads (sync_engine.md §2.2: SHA-256 over RFC 8785) — Python's POLICY_INTEGRITY_VIOLATION check, the same bytes.
   * Returns true if new policies were downloaded, false on 304.
   */
  private async _syncPolicies(): Promise<boolean> {
    const etag = this.cache.getPoliciesEtag();
    const result = await this.client.downloadPolicies(etag);
    if (result === null) {
      // 304 Not Modified: the cached version is the server's as of this pull (sync_engine.md 2.4)
      this.cache.policiesLanded();
      this.log.debug(`Policy sync: not modified (etag=${etag ?? 'null'})`);
      return false;
    }

    // A policy with no hash is refused as one whose hash differs: an absent hash proves nothing (sync_engine.md
    // §2.2; HTL-29 row 137)
    for (const policy of result.policies) {
      const expectedHash = policy.content_hash;
      const actualHash = canonicalHash((policy.content ?? {}) as unknown);
      if (actualHash !== expectedHash) {
        const cause = expectedHash
          ? `content hash mismatch (expected=${String(expectedHash)}, got=${actualHash})`
          : 'no content_hash';
        this.log.error(`POLICY_INTEGRITY_VIOLATION: policy '${policy.name ?? '?'}' ${cause}. Rejecting download.`);
        throw new SyncError('policy', `Policy integrity violation for '${policy.name ?? '?'}': ${cause}`);
      }
    }

    // The org's redaction policy rides the policy pull, and the local store redacts it with its own declaration
    // (event_format.md §Redaction, row 163(a)). A response without it is refused, never read as "nothing declared":
    // the store would write an org-declared field in clear.
    const declared = result.redaction_policy?.[ORG_FIELDS];
    if (!Array.isArray(declared)) {
      throw new SyncError(
        'policy',
        `The policy response carries no redaction_policy.${ORG_FIELDS} list, so the fields the org redacts are ` +
          'unknown. The cache keeps what it had (event_format.md §Redaction).'
      );
    }
    try {
      Redaction.declared(declared as string[], undefined, ORG_FIELDS);
    } catch (e: any) {
      throw new SyncError('policy', `The policy response's redaction_policy is refused: ${e.message}`);
    }

    await this.cache.updatePolicies(
      { policies: result.policies, version: result.version, redaction_policy: { [ORG_FIELDS]: [...declared] } },
      result.etag
    );
    this.log.info(
      `Policy sync: downloaded ${result.policies.length} policies (version=${result.version})`
    );
    return true;
  }

  /** Download route configs. Returns true if new data, false on 304. */
  private async _syncRoutes(): Promise<boolean> {
    const etag = this.cache.getRoutesEtag();
    const result = await this.client.downloadRoutes(etag);
    if (result === null) {
      this.log.debug(`Route sync: not modified (etag=${etag ?? 'null'})`);
      return false;
    }
    await this.cache.updateRoutes(result.routes, result.etag);
    this.log.info(`Route sync: downloaded ${result.routes.length} routes`);
    return true;
  }

  /**
   * Poll kill switches. Always full-state — no ETag. The tick is the change signal and the version decides: a tick
   * naming a version other than the one evaluate reads pulls the version in this tick, and the list itself decides
   * nothing (sync_engine.md 2.4; HTL-29 row 131, condition 2). Until a pull lands, the version the tick names decides
   * in its switches' scope, and the pull is made at every tick past the policy breaker, each miss logged at error
   * (row 240, ruled 2026-11-09). Mirrors sync_engine.py `_sync_kill_switches`.
   */
  private async _syncKillSwitches(): Promise<void> {
    const result = await this.client.pollKillSwitches();
    const difference = await this.cache.updateKillSwitches({ ...result });
    this.log.debug(
      `Kill switch sync: ${result.kill_switches.length} active switches ` +
        `(server_time=${result.server_time})`
    );

    if (difference === null) return;
    const [[version, named], [cached, held]] = difference;
    const sides =
      `Kill switch tick names version ${String(version)} (switches [${named.join(', ')}]), ` +
      `the cached version ${String(cached)} (switches [${held.join(', ')}])`;
    this.log.info(`${sides}: pulling the version`);
    const breaker = this.breakers.policy;
    try {
      await this._syncPolicies();
    } catch (e) {
      breaker.recordFailure();
      const msg = e instanceof Error ? e.message : String(e);
      this.log.error(
        `${sides}, and its pull failed: ${msg}. Until a pull lands, the tick's version decides in its switches' ` +
          'scope; the pull is made again at the next tick.'
      );
      return;
    }
    breaker.recordSuccess();
  }

  /**
   * Flush current telemetry window and upload pending records. Implements
   * the 10-minute heartbeat behavior — if nothing has been sent for a
   * while and the current window is empty, flush again to produce an
   * empty heartbeat so the server knows the SDK is alive.
   */
  private async _syncTelemetry(): Promise<void> {
    if (!this.telemetryCollector) return;
    const collector = this.telemetryCollector;
    const now = monotonicSeconds();

    collector.flush();

    let pending = collector.getPending();
    if (pending.length === 0 && now - this.lastTelemetrySentSec >= 600) {
      // Force an empty-window heartbeat per Python spec §7.4.
      collector.flush();
      pending = collector.getPending();
    }

    if (pending.length === 0) return;

    const result = await this.client.uploadTelemetry(pending);
    collector.markSent(result.accepted);
    this.lastTelemetrySentSec = monotonicSeconds();
    this.log.debug(`Telemetry sync: uploaded ${result.accepted} records`);
  }
}

// ─── helpers ──────────────────────────────────────────────────────────────

function mergeWithDefaults(c: SyncConfig): Required<SyncConfig> {
  return {
    server_url: c.server_url,
    audit_sync_interval: c.audit_sync_interval ?? DEFAULTS.audit_sync_interval,
    audit_batch_size: c.audit_batch_size ?? DEFAULTS.audit_batch_size,
    max_buffer_records: c.max_buffer_records ?? DEFAULTS.max_buffer_records,
    max_buffer_size_bytes: c.max_buffer_size_bytes ?? DEFAULTS.max_buffer_size_bytes,
    policy_sync_interval: c.policy_sync_interval ?? DEFAULTS.policy_sync_interval,
    route_sync_interval: c.route_sync_interval ?? DEFAULTS.route_sync_interval,
    kill_switch_poll_interval:
      c.kill_switch_poll_interval ?? DEFAULTS.kill_switch_poll_interval,
    telemetry_sync_interval: c.telemetry_sync_interval ?? DEFAULTS.telemetry_sync_interval,
    sync_timeout: c.sync_timeout ?? DEFAULTS.sync_timeout,
    sync_max_retries: c.sync_max_retries ?? DEFAULTS.sync_max_retries,
    circuit_breaker_threshold:
      c.circuit_breaker_threshold ?? DEFAULTS.circuit_breaker_threshold,
    circuit_breaker_reset: c.circuit_breaker_reset ?? DEFAULTS.circuit_breaker_reset,
  };
}
