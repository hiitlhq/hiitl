import { assertNumericDomain } from '@hiitl/core';
import {admitSync,syncChannel,admitConfiguration} from './admission.js';
import {z} from 'zod';
import {syncNumberSchema} from './sync-numbers.js';
/**
 * Disk + memory cache for sync engine (Block 5d).
 *
 * Direct port of `python/hiitl/sdk/sync_cache.py`. Provides fast in-
 * memory reads for the evaluator hot path while persisting data to
 * disk for warm-start across SDK restarts.
 *
 * Key properties (mirrored from Python):
 *  - In-memory copies serve evaluator reads with zero disk I/O. The
 *    evaluator reads references — Node's single-threaded event loop
 *    means we never need a lock around reads or writes.
 *  - Atomic disk writes: write to a `.tmp` then `fs.promises.rename`
 *    (POSIX atomic on the same filesystem). Same guarantee as Python's
 *    `os.rename` + `tempfile.mkstemp` pattern.
 *  - TTL tracking: each channel has independent freshness checks.
 *    Wall-clock-to-monotonic conversion via `performance.now() -
 *    (Date.now() - mtimeMs)`. Matches Python's `_file_mtime` exactly.
 *  - Integrity: SHA-256 hash sidecar per JSON file, written with it. A
 *    file whose sidecar is absent, unreadable or names another hash is
 *    discarded (logs CACHE_INTEGRITY_VIOLATION; sync_engine.md §4).
 *  - Max-stale: CACHE_STALE warning emitted once per channel when
 *    cached data exceeds the stale-age threshold.
 *
 * Cache structure on disk:
 *     {cache_dir}/{org_id}/{environment}/
 *         policies.json        # Full policy data
 *         policies.json.sha256 # Content hash
 *         policies.etag        # ETag for conditional requests
 *         routes.json
 *         routes.json.sha256
 *         routes.etag
 *         kill_switches.json
 *         kill_switches.json.sha256
 */

import { createHash, randomUUID } from 'node:crypto';
import { existsSync, statSync } from 'node:fs';
import {
  mkdir,
  readdir,
  readFile,
  rename,
  stat,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';

import { liveKillSwitches, ORG_FIELDS, PolicySetSchema, type PolicySet } from '@hiitl/core';
import type { Logger } from './logger.js';
import { consoleLogger } from './logger.js';
import { monotonicSeconds } from './time.js';

/**
 * The version a policy pull's cached data holds for evaluation: its first active policy the model reads, a refused
 * one skipped naming why (R-0872), or undefined when it holds none. The cache reads it once, where the pull is received
 * or the disk cache loaded, and holds it: evaluate() reads the held reading, and the kill-switch tick compares the
 * version it names with it (sync_engine.md 2.4 and Numeric domain; HTL-29 row 131; HTL-43 gap 295): one reading of the
 * cached version. Mirrors sync_cache.py `cached_policy_set`.
 */
export function cachedPolicySet(cached: unknown): PolicySet | undefined {
  if (!cached || typeof cached !== 'object') return undefined;
  const policies = (cached as { policies?: Array<Record<string, unknown>> }).policies;
  if (!Array.isArray(policies)) return undefined;
  for (const p of policies) {
    const content = p.content;
    if (p.active === false || !content || typeof content !== 'object') continue;
    const parsed = PolicySetSchema.safeParse(content);
    if (parsed.success) return content as PolicySet;
    const issues = parsed.error.issues.map((i) => `${i.path.join('.') || '(policy set)'}: ${i.message}`);
    console.warn(`Failed to parse cached policy '${p.name ?? '?'}': ${issues.join('; ')}. Trying next source.`);
  }
  return undefined;
}

/** A version and its live switches, as the kill-switch tick's comparison names them. */
export type VersionSide = [unknown, string[]];

/**
 * The version the tick names and the cached version evaluate reads, each as [version, its live switches], when the
 * two differ; null when they agree. "A version string names one policy content per organisation and environment"
 * (policy_format.md "A version identifies what evaluates"), so the two are compared by it, never by the switches'
 * names: the tick is the change signal and the version decides (sync_engine.md 2.4; HTL-29 row 131, condition 2).
 * The engine pulls on a difference, and the cache holds the tick's part while it stands (row 240). A tick naming no
 * version differs from a cached one: an unread version is never the same one. Mirrors sync_cache.py
 * `version_difference`.
 */
export function versionDifference(
  tick: Record<string, unknown> | null,
  cached: PolicySet | null
): [VersionSide, VersionSide] | null {
  const held = tick?.policy_set;
  const named = held && typeof held === 'object' && !Array.isArray(held)
    ? ((held as Record<string, unknown>).version ?? null) : null;
  const version = cached ? cached.version : null;
  if (named === version) return null;
  const listed = tick?.kill_switches;
  const switches = (Array.isArray(listed) ? (listed as Array<Record<string, unknown>>) : [])
    .map((s) => String(s.rule_name))
    .sort();
  return [[named, switches], [version, cached ? liveKillSwitches(cached) : []]];
}

// ─── status types (mirror Python dicts) ───────────────────────────────────

export interface ChannelCacheStatus {
  cached: boolean;
  age_seconds: number;
  etag?: string | null;
}

export interface SyncCacheStatus {
  cache_dir: string;
  disk_synced: boolean;
  policies: ChannelCacheStatus;
  routes: ChannelCacheStatus;
  kill_switches: Omit<ChannelCacheStatus, 'etag'>;
}

// ─── construction options ─────────────────────────────────────────────────

const SyncCacheNumbers=z.object({max_stale_age:z.number().optional()});
export interface SyncCacheOptions extends z.infer<typeof SyncCacheNumbers> {
  /** Base cache directory. Default `~/.hiitl/cache/`. */
  cache_dir?: string;
  /** Organization ID for cache scoping. Required. */
  org_id: string;
  /** Environment for cache scoping (dev/stage/prod). Required. */
  environment: string;
  /** Seconds before logging CACHE_STALE warning. Default 24h. */
  /** Optional logger override. */
  logger?: Logger;
}

/**
 * Disk-backed memory cache for synced data.
 *
 * Construction is synchronous and side-effect-free — no disk I/O until
 * the first `loadFromDisk()` or `update*()` call. This keeps the
 * constructor safe to call from arbitrary contexts (e.g. SDK init).
 */
export class SyncCache {
  private readonly baseDir: string;
  private readonly maxStaleAge: number;
  private readonly log: Logger;
  private dirCreated = false;

  // In-memory state — evaluator reads these references directly. Node's
  // single-threaded event loop means a reference swap is atomic with
  // respect to other JS code; no lock needed.
  private _policies: Record<string, unknown> | null = null;
  private _policiesEtag: string | null = null;
  private _policiesUpdatedAt = 0; // seconds since process start (monotonic)
  // The cached version evaluate reads, read through the model where the policies were received or loaded
  // (sync_engine.md Numeric domain; HTL-43 gap 295). Computed, never stored.
  private _policySet: PolicySet | null = null;

  private _routes: Array<Record<string, unknown>> | null = null;
  private _routesEtag: string | null = null;
  private _routesUpdatedAt = 0;

  private _killSwitches: Record<string, unknown> | null = null; // the last tick, as received
  private _killSwitchesUpdatedAt = 0;
  // The tick's part: the set the last tick names, held from a tick naming a version other than the cached one until
  // a pull lands after it (sync_engine.md 2.4; HTL-29 row 240, condition 2). Computed, never stored.
  private _tickPart: PolicySet | null = null;

  private _diskDiverged = false;
  private readonly _staleWarned: Record<string, boolean> = {};

  // TICKET-121: distinguish "loaded from disk on warm start" from
  // "populated by a successful sync this process." A disk-loaded cache
  // may be stale; an in-process synced cache is fresh. Consumers use
  // cacheStatus() to surface this on each Decision.
  private _syncedThisProcess = false;

  constructor(opts: SyncCacheOptions) {
    admitConfiguration(opts,SyncCacheNumbers);
    const root = opts.cache_dir ?? path.join(homedir(), '.hiitl', 'cache');
    this.baseDir = path.join(root, opts.org_id, opts.environment);
    this.maxStaleAge = opts.max_stale_age ?? 86_400;
    this.log = opts.logger ?? consoleLogger;
  }

  // ─── warm start ────────────────────────────────────────────────────────

  /**
   * Load cached data from disk. Cleans up orphaned .tmp files from prior
   * crashes, then attempts to load each channel's JSON. Returns true if
   * any cached data was loaded.
   *
   * Per-file failures (missing file, JSON parse error, hash mismatch) are
   * non-fatal — the channel simply stays uninitialized.
   */
  async loadFromDisk(): Promise<boolean> {
    await this._cleanupOrphans();
    let loadedAny = false;

    const policies = await this._readJson('policies.json');
    if (policies !== null && typeof policies === 'object' && !Array.isArray(policies)) {
      this._policies = policies as Record<string, unknown>;
      this._policySet = cachedPolicySet(policies) ?? null;
      this._policiesUpdatedAt = await this._fileMtime('policies.json');
      this._policiesEtag = await this._readText('policies.etag');
      loadedAny = true;
      this.log.info('Loaded cached policies from disk');
    }

    const routes = await this._readJson('routes.json');
    if (Array.isArray(routes)) {
      this._routes = routes as Array<Record<string, unknown>>;
      this._routesUpdatedAt = await this._fileMtime('routes.json');
      this._routesEtag = await this._readText('routes.etag');
      loadedAny = true;
      this.log.info('Loaded cached routes from disk');
    }

    const tick = await this._readJson('kill_switches.json');
    if (tick !== null && typeof tick === 'object' && !Array.isArray(tick)) {
      // A tick read at start has had no pull after it, so its part stands until the first one lands (row 240)
      this._holdTick(tick as Record<string, unknown>);
      this._killSwitchesUpdatedAt = await this._fileMtime('kill_switches.json');
      loadedAny = true;
      this.log.info('Loaded cached kill switches from disk');
    } else if (tick !== null) {
      this.log.info(
        "The cached kill-switch file holds an earlier SDK's list, which decides nothing: not read. The next tick " +
          'replaces it.'
      );
    }

    if (loadedAny) {
      this.log.info(`Warm start: loaded cache from ${this.baseDir}`);
    } else {
      this.log.info(`Cold start: no cached data at ${this.baseDir}`);
    }
    return loadedAny;
  }

  // ─── policy cache ─────────────────────────────────────────────────────

  /** Get cached policy data (zero-copy reference). */
  getPolicies(): Record<string, unknown> | null {
    const data = this._policies;
    if (data !== null) {
      this._checkStale('policies', this.getPoliciesAgeSeconds());
    }
    return data;
  }

  /**
   * The cached version evaluate reads (zero-copy reference): the set read through the model where the policies were
   * received or loaded, or null when they hold none (sync_engine.md Numeric domain). Mirrors sync_cache.py
   * `get_policy_set`.
   */
  getPolicySet(): PolicySet | null {
    const policySet = this._policySet;
    if (policySet !== null) {
      this._checkStale('policies', this.getPoliciesAgeSeconds());
    }
    return policySet;
  }

  /**
   * The org's declared fields from the last policy pull (event_format.md §Redaction, row 163(a)), which the local store
   * redacts with its own. Empty until a pull carrying them lands.
   */
  getRedactionFields(): string[] {
    const policy = this._policies?.redaction_policy as Record<string, unknown> | undefined;
    const fields = policy?.[ORG_FIELDS];
    return Array.isArray(fields) ? [...(fields as string[])] : [];
  }

  getPoliciesEtag(): string | null {
    return this._policiesEtag;
  }

  getPoliciesAgeSeconds(): number {
    if (this._policiesUpdatedAt === 0) return Infinity;
    return monotonicSeconds() - this._policiesUpdatedAt;
  }

  /**
   * Atomically update policy cache (memory + disk). Memory is always
   * updated even if disk write fails; disk divergence self-heals on
   * the next successful sync cycle.
   */
  async updatePolicies(
    data: Record<string, unknown>,
    etag?: string | null
  ): Promise<void> {
    admitSync('policy',data);
    const diskOk = await this._tryDiskWrite('policies.json', data, etag, 'policies.etag');
    this._policies = data;
    this._policySet = cachedPolicySet(data) ?? null;
    this._policiesEtag = etag ?? null;
    this._policiesUpdatedAt = monotonicSeconds();
    this._diskDiverged = !diskOk;
    // TICKET-121: any successful updatePolicies — initial or background —
    // flips cacheStatus to "synced" from this point forward in the process.
    this._syncedThisProcess = true;
    // A pull that lands ends the tick's part (sync_engine.md 2.4; row 240)
    this._tickPart = null;
    delete this._staleWarned.policies;
    this.log.debug(`Updated policy cache (etag=${etag ?? 'null'}, disk_ok=${diskOk})`);
  }

  /**
   * Return the per-decision cache status (TICKET-121).
   *
   * Returns one of:
   *   - 'synced'    — `updatePolicies()` has been called this process
   *                   (initial or background sync succeeded). Policies
   *                   in memory are fresh from the server.
   *   - 'from_disk' — Policies in memory came from the on-disk cache
   *                   loaded at startup; no successful sync has run
   *                   this process yet. May be stale.
   *   - 'empty'     — No policies in memory. Evaluator falls back to
   *                   OBSERVE_ALL on every action. Either cold start
   *                   with no disk cache, or sync has never succeeded.
   *
   * The HIITL client stamps this on every Decision so callers can
   * detect "I'm running against a stale or empty cache" and adjust
   * their own behavior (e.g. defer high-stakes actions until first sync).
   */
  cacheStatus(): 'synced' | 'from_disk' | 'empty' {
    if (this._syncedThisProcess) return 'synced';
    if (this._policies !== null) return 'from_disk';
    return 'empty';
  }

  // ─── route cache ──────────────────────────────────────────────────────

  getRoutes(): Array<Record<string, unknown>> | null {
    const data = this._routes;
    if (data !== null) {
      this._checkStale('routes', this.getRoutesAgeSeconds());
    }
    return data;
  }

  getRoutesEtag(): string | null {
    return this._routesEtag;
  }

  getRoutesAgeSeconds(): number {
    if (this._routesUpdatedAt === 0) return Infinity;
    return monotonicSeconds() - this._routesUpdatedAt;
  }

  async updateRoutes(
    data: Array<Record<string, unknown>>,
    etag?: string | null
  ): Promise<void> {
    admitSync('routes',data,[],syncNumberSchema('routes',true));
    const diskOk = await this._tryDiskWrite('routes.json', data, etag, 'routes.etag');
    this._routes = data;
    this._routesEtag = etag ?? null;
    this._routesUpdatedAt = monotonicSeconds();
    this._diskDiverged = !diskOk;
    delete this._staleWarned.routes;
    this.log.debug(`Updated route cache (etag=${etag ?? 'null'}, disk_ok=${diskOk})`);
  }

  // ─── kill switch cache ────────────────────────────────────────────────

  /** The last tick's switch list (zero-copy reference). */
  getKillSwitches(): Array<Record<string, unknown>> | null {
    const tick = this._killSwitches;
    if (tick === null) return null;
    this._checkStale('kill_switches', this.getKillSwitchesAgeSeconds());
    const listed = tick.kill_switches;
    return Array.isArray(listed) ? (listed as Array<Record<string, unknown>>) : null;
  }

  /**
   * The set a tick no pull has followed names, as far as its switches go: evaluate reads it first, and a switch it
   * binds stands under its version (sync_engine.md 2.4; HTL-29 row 240). null when the last tick agrees with the
   * cached version, or a pull has landed since it. Mirrors sync_cache.py `tick_part`.
   */
  tickPart(): PolicySet | null {
    return this._tickPart;
  }

  /**
   * A policy pull answered 304: the cached version is the server's as of the pull, so the tick's part ends, as it
   * does when a new version lands (sync_engine.md 2.4).
   */
  policiesLanded(): void {
    this._tickPart = null;
  }

  getKillSwitchesAgeSeconds(): number {
    if (this._killSwitchesUpdatedAt === 0) return Infinity;
    return monotonicSeconds() - this._killSwitchesUpdatedAt;
  }

  /**
   * Update the kill switch cache (memory + disk) with the tick as received: `kill_switches`, `policy_set`,
   * `server_time`. No ETag — kill switches always return full state. The engine runs its channels one at a time, so a
   * pull that lands after this call was read after this tick. Returns the version the tick names and the cached
   * version, each with its live switches, when they differ (the engine pulls), else null.
   */
  async updateKillSwitches(tick: Record<string, unknown>): Promise<[VersionSide, VersionSide] | null> {
    admitSync('kill_switches',tick);
    const diskOk = await this._tryDiskWrite('kill_switches.json', tick);
    const difference = this._holdTick(tick);
    this._killSwitchesUpdatedAt = monotonicSeconds();
    this._diskDiverged = !diskOk;
    delete this._staleWarned.kill_switches;
    const listed = tick.kill_switches;
    this.log.debug(
      `Updated kill switch cache (${Array.isArray(listed) ? listed.length : 0} switches, disk_ok=${diskOk})`
    );
    return difference;
  }

  /** Hold the tick, and its part when the version it names is not the cached one. */
  private _holdTick(tick: Record<string, unknown>): [VersionSide, VersionSide] | null {
    const difference = versionDifference(tick, this._policySet);
    this._killSwitches = tick;
    this._tickPart = difference !== null ? this._tickPartOf(tick) : null;
    return difference;
  }

  /**
   * A tick's `policy_set` read as a set, or null when it carries none or the model refuses it (logged): the set the
   * tick names, as far as its switches go (sync_engine.md 2.4; HTL-29 row 240). Mirrors sync_cache.py `_tick_part`.
   */
  private _tickPartOf(tick: Record<string, unknown>): PolicySet | null {
    const held = tick.policy_set;
    if (held === null || held === undefined) return null;
    const parsed = PolicySetSchema.safeParse(held);
    if (parsed.success) return held as PolicySet;
    const issues = parsed.error.issues.map((i) => `${i.path.join('.') || '(policy set)'}: ${i.message}`);
    this.log.error(
      "The kill-switch tick's policy_set cannot be read, so its switches bind only once the version's pull lands: " +
        issues.join('; ')
    );
    return null;
  }

  // ─── health snapshot ──────────────────────────────────────────────────

  status(): SyncCacheStatus {
    return {
      cache_dir: this.baseDir,
      disk_synced: !this._diskDiverged,
      policies: {
        cached: this._policies !== null,
        age_seconds: round1(this.getPoliciesAgeSeconds()),
        etag: this._policiesEtag,
      },
      routes: {
        cached: this._routes !== null,
        age_seconds: round1(this.getRoutesAgeSeconds()),
        etag: this._routesEtag,
      },
      kill_switches: {
        cached: this._killSwitches !== null,
        age_seconds: round1(this.getKillSwitchesAgeSeconds()),
      },
    };
  }

  // ─── staleness check ──────────────────────────────────────────────────

  /** Log CACHE_STALE once per channel when age exceeds threshold. */
  private _checkStale(channel: string, ageSeconds: number): void {
    if (ageSeconds > this.maxStaleAge && !this._staleWarned[channel]) {
      this.log.warn(
        `CACHE_STALE: Cached ${channel} are ${Math.round(ageSeconds)} seconds old ` +
          `(max stale age: ${Math.round(this.maxStaleAge)} seconds). Sync may be failing. ` +
          `Continuing with stale data.`
      );
      this._staleWarned[channel] = true;
    }
  }

  // ─── disk write helpers ───────────────────────────────────────────────

  private async _tryDiskWrite(
    filename: string,
    data: unknown,
    etag?: string | null,
    etagFilename?: string
  ): Promise<boolean> {
    try {
      await this._writeJson(filename, data);
      if (etag && etagFilename) {
        await this._writeText(etagFilename, etag);
      }
      return true;
    } catch (err) {
      this.log.warn(
        `Failed to persist ${filename} to disk: ${err instanceof Error ? err.message : String(err)}. ` +
          `In-memory cache updated but on-disk cache is stale. ` +
          `Next successful sync will repair disk cache.`
      );
      return false;
    }
  }

  /** Remove orphaned .tmp files older than `maxAgeSeconds` (default 300s). */
  private async _cleanupOrphans(maxAgeSeconds = 300): Promise<number> {
    if (!existsSync(this.baseDir)) return 0;
    let removed = 0;
    const now = Date.now() / 1000;
    try {
      const entries = await readdir(this.baseDir);
      for (const entry of entries) {
        if (!entry.endsWith('.tmp')) continue;
        const fullPath = path.join(this.baseDir, entry);
        try {
          const st = await stat(fullPath);
          if (!st.isFile()) continue;
          const ageSeconds = now - st.mtimeMs / 1000;
          if (ageSeconds > maxAgeSeconds) {
            await unlink(fullPath);
            removed++;
          }
        } catch {
          // Per-file failure — ignore (matches Python's OSError catch).
        }
      }
    } catch {
      // readdir failure — ignore.
    }
    if (removed > 0) {
      this.log.info(`Cleaned up ${removed} orphaned temp files`);
    }
    return removed;
  }

  /** Ensure cache directory exists (idempotent, cached after first call). */
  private async _ensureDir(): Promise<void> {
    if (this.dirCreated) return;
    await mkdir(this.baseDir, { recursive: true });
    this.dirCreated = true;
  }

  /**
   * Atomically write a JSON file plus its SHA-256 sidecar.
   *
   * Algorithm: serialize → write to a `.tmp` file in the same directory →
   * `rename(tmp, target)`. POSIX rename is atomic when source and dest
   * are on the same filesystem (always true here). Then write the
   * `.sha256` sidecar. The sidecar is part of the write: a file without it
   * is discarded on read (sync_engine.md §4 "Integrity"), so a sidecar that
   * cannot be written fails the write.
   */
  private async _writeJson(filename: string, data: unknown): Promise<void> {
    await this._ensureDir();
    const target = path.join(this.baseDir, filename);
    // Match Python's separators=(",", ":") — no spaces, compact JSON.
    const content = compactJson(data);
    const buf = Buffer.from(content, 'utf-8');

    // Use a UUID-suffixed tmp name so multiple in-flight writes can't
    // collide. Python uses tempfile.mkstemp which generates a unique name
    // via the same mechanism (different implementation, same property).
    const tmpName = `${filename}.${randomUUID()}.tmp`;
    const tmpPath = path.join(this.baseDir, tmpName);
    try {
      await writeFile(tmpPath, buf);
      await rename(tmpPath, target);
    } catch (err) {
      // Cleanup the tmp file on failure. Best-effort — if cleanup fails,
      // the orphan sweep on next startup handles it.
      try {
        await unlink(tmpPath);
      } catch {
        // ignored
      }
      throw err;
    }

    // Sidecar hash: a failure throws, as the data file's does.
    const hash = createHash('sha256').update(buf).digest('hex');
    const hashFile = `${target}.sha256`;
    const hashTmpName = `${filename}.sha256.${randomUUID()}.tmp`;
    const hashTmpPath = path.join(this.baseDir, hashTmpName);
    try {
      await writeFile(hashTmpPath, hash, 'utf-8');
      await rename(hashTmpPath, hashFile);
    } catch (err) {
      try {
        await unlink(hashTmpPath);
      } catch {
        // ignored
      }
      throw err;
    }
  }

  private async _writeText(filename: string, content: string): Promise<void> {
    await this._ensureDir();
    const target = path.join(this.baseDir, filename);
    const tmpName = `${filename}.${randomUUID()}.tmp`;
    const tmpPath = path.join(this.baseDir, tmpName);
    try {
      await writeFile(tmpPath, content, 'utf-8');
      await rename(tmpPath, target);
    } catch (err) {
      try {
        await unlink(tmpPath);
      } catch {
        // ignored
      }
      throw err;
    }
  }

  /**
   * Read JSON file with integrity verification. Returns null on missing
   * file, parse failure, OR a hash sidecar that is absent, unreadable or
   * names another hash. The hash check is critical — a mismatched hash
   * means either disk corruption or tampering, and an absent one proves
   * nothing, so the safe action is to discard the cached data
   * (sync_engine.md §4 "Integrity"; HTL-29 row 137).
   */
  private async _readJson(filename: string): Promise<unknown> {
    const filePath = path.join(this.baseDir, filename);
    if (!existsSync(filePath)) return null;

    let raw: Buffer;
    try {
      raw = await readFile(filePath);
    } catch (err) {
      this.log.warn(
        `Failed to read cache file ${filePath}: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw.toString('utf-8'));
    } catch (err) {
      this.log.warn(
        `Failed to parse cache file ${filePath}: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }

    admitSync(syncChannel(filename),parsed,[],syncNumberSchema(syncChannel(filename),true));
    // Verify the hash sidecar.
    const hashPath = `${filePath}.sha256`;
    let expected: string;
    try {
      expected = (await readFile(hashPath, 'utf-8')).trim();
    } catch (err) {
      this.log.error(
        `CACHE_INTEGRITY_VIOLATION: ${filePath} has no readable content hash ` +
          `(${err instanceof Error ? err.message : String(err)}). Discarding cached data.`
      );
      return null;
    }
    const actual = createHash('sha256').update(raw).digest('hex');
    if (actual !== expected) {
      this.log.error(
        `CACHE_INTEGRITY_VIOLATION: ${filePath} content hash mismatch ` +
          `(expected=${expected.slice(0, 16)}..., got=${actual.slice(0, 16)}...). ` +
          `Discarding cached data.`
      );
      return null;
    }

    return parsed;
  }

  private async _readText(filename: string): Promise<string | null> {
    const filePath = path.join(this.baseDir, filename);
    if (!existsSync(filePath)) return null;
    try {
      const content = await readFile(filePath, 'utf-8');
      return content.trim();
    } catch (err) {
      this.log.warn(
        `Failed to read cache file ${filePath}: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }
  }

  /**
   * Get monotonic-compatible timestamp reflecting actual file age.
   *
   * Direct port of Python's `_file_mtime`. We convert wall-clock mtime
   * to a monotonic-clock value by computing the file's age and
   * subtracting from the current monotonic now. This preserves age
   * semantics while keeping all timestamps on the same monotonic clock.
   *
   * Synchronous statSync used here because existence is already known
   * (caller checked) and the operation runs only during cold-start
   * warm-up, not on the hot path.
   */
  private async _fileMtime(filename: string): Promise<number> {
    const filePath = path.join(this.baseDir, filename);
    try {
      const st = statSync(filePath);
      const fileMtimeWallSec = st.mtimeMs / 1000;
      const wallNowSec = Date.now() / 1000;
      const ageSeconds = Math.max(0, wallNowSec - fileMtimeWallSec);
      return monotonicSeconds() - ageSeconds;
    } catch {
      return 0;
    }
  }
}

// ─── module-level helpers ─────────────────────────────────────────────────

/** Round to one decimal place (matches Python's `round(x, 1)`). */
function round1(value: number): number {
  if (!Number.isFinite(value)) return value;
  return Math.round(value * 10) / 10;
}

/**
 * Compact JSON serialization matching Python's `json.dumps(...,
 * separators=(",", ":"))`. JSON.stringify with no `space` argument
 * already produces compact output without spaces.
 */
function compactJson(value: unknown): string {
  return JSON.stringify(value);
}
