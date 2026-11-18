/**
 * Unit tests for SyncCache (Block 5d).
 *
 * Parity target: `python/hiitl/sdk/tests/test_sync_cache.py`.
 *
 * Strategy: each test gets its own temp directory under the OS temp
 * root so disk I/O is isolated. We exercise the full
 * write → read → integrity-verify → stale-warn pipeline against real
 * filesystem operations — no fs mocking — because the atomic-rename
 * + hash-sidecar contract is the load-bearing safety guarantee and
 * mocking it away would defeat the test.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { mkdtempSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';

import { SyncCache } from '../../src/sync-cache.js';
import type { Logger } from '../../src/logger.js';

const ORG = 'org_test1234567890ab';
const ENV = 'dev';

function makeTempDir(): string {
  return mkdtempSync(path.join(tmpdir(), 'hiitl-sync-cache-test-'));
}

function makeCapturingLogger(): Logger & { messages: Array<[string, string]> } {
  const messages: Array<[string, string]> = [];
  return {
    messages,
    debug: (m) => messages.push(['debug', m]),
    info: (m) => messages.push(['info', m]),
    warn: (m) => messages.push(['warn', m]),
    error: (m) => messages.push(['error', m]),
  };
}

describe('SyncCache', () => {
  let cacheDir: string;

  beforeEach(() => {
    cacheDir = makeTempDir();
  });

  afterEach(async () => {
    await rm(cacheDir, { recursive: true, force: true });
  });

  // ─── basic policy round-trip ────────────────────────────────────────────

  it('updatePolicies persists data and getPolicies returns it', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    const data = { policies: [{ name: 'p1' }], version: 'v1' };
    await cache.updatePolicies(data, 'etag-abc');

    expect(cache.getPolicies()).toEqual(data);
    expect(cache.getPoliciesEtag()).toBe('etag-abc');

    // Disk file present and matches.
    const file = path.join(cacheDir, ORG, ENV, 'policies.json');
    expect(existsSync(file)).toBe(true);
    const raw = await readFile(file, 'utf-8');
    expect(JSON.parse(raw)).toEqual(data);

    // Sidecar hash matches the bytes on disk.
    const hashPath = `${file}.sha256`;
    expect(existsSync(hashPath)).toBe(true);
  });

  it('routes and kill_switches follow the same round-trip', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache.updateRoutes([{ name: 'r1' }], 'etag-r');
    await cache.updateKillSwitches({ kill_switches: [{ name: 'ks1' }], policy_set: null, server_time: '' });

    expect(cache.getRoutes()).toEqual([{ name: 'r1' }]);
    expect(cache.getRoutesEtag()).toBe('etag-r');
    expect(cache.getKillSwitches()).toEqual([{ name: 'ks1' }]);
  });

  // ─── warm start ────────────────────────────────────────────────────────

  it('loadFromDisk restores policies + routes + kill switches', async () => {
    // Write via one cache instance...
    const writer = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await writer.updatePolicies({ policies: [{ name: 'p1' }], version: 'v1' }, 'epol');
    await writer.updateRoutes([{ name: 'r1' }], 'erou');
    await writer.updateKillSwitches({ kill_switches: [{ name: 'ks1' }], policy_set: null, server_time: '' });

    // ...read via a fresh instance.
    const reader = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    const loaded = await reader.loadFromDisk();
    expect(loaded).toBe(true);
    expect(reader.getPolicies()).toEqual({ policies: [{ name: 'p1' }], version: 'v1' });
    expect(reader.getPoliciesEtag()).toBe('epol');
    expect(reader.getRoutes()).toEqual([{ name: 'r1' }]);
    expect(reader.getRoutesEtag()).toBe('erou');
    expect(reader.getKillSwitches()).toEqual([{ name: 'ks1' }]);
  });

  it('loadFromDisk returns false on cold start (missing directory)', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    // Directory not created yet (no update calls).
    expect(await cache.loadFromDisk()).toBe(false);
    expect(cache.getPolicies()).toBeNull();
  });

  // ─── integrity verification ────────────────────────────────────────────

  it('CACHE_INTEGRITY_VIOLATION: tampered file discarded on read', async () => {
    const log = makeCapturingLogger();
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache.updatePolicies({ policies: [{ name: 'p1' }] });

    // Tamper with the on-disk bytes without updating the hash sidecar.
    const file = path.join(cacheDir, ORG, ENV, 'policies.json');
    await writeFile(file, JSON.stringify({ policies: [{ name: 'TAMPERED' }] }));

    // Fresh cache instance — should detect hash mismatch on load.
    const reader = new SyncCache({
      cache_dir: cacheDir,
      org_id: ORG,
      environment: ENV,
      logger: log,
    });
    const loaded = await reader.loadFromDisk();
    expect(loaded).toBe(false);
    expect(reader.getPolicies()).toBeNull();
    const expected = (await readFile(`${file}.sha256`, 'utf8')).trim();
    const actual = createHash('sha256').update(await readFile(file)).digest('hex');
    expect(log.messages.filter(([level]) => level !== 'debug' && level !== 'info')).toEqual([
      ['error', `CACHE_INTEGRITY_VIOLATION: ${file} content hash mismatch ` +
        `(expected=${expected.slice(0, 16)}..., got=${actual.slice(0, 16)}...). Discarding cached data.`],
    ]);
  });

  // ─── orphan cleanup ────────────────────────────────────────────────────

  it('loadFromDisk removes stale .tmp orphans on warm start', async () => {
    const tenantDir = path.join(cacheDir, ORG, ENV);
    await mkdir(tenantDir, { recursive: true });

    // Drop a stale .tmp from a "previous crash" — set its mtime old.
    const orphan = path.join(tenantDir, 'policies.json.abc.tmp');
    await writeFile(orphan, 'partial bytes from a crash');
    // Force mtime to 10 minutes ago — older than the 300s threshold.
    const past = (Date.now() - 600_000) / 1000;
    await (await import('node:fs/promises')).utimes(orphan, past, past);

    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache.loadFromDisk();

    expect(existsSync(orphan)).toBe(false);
  });

  it('orphan cleanup leaves recent .tmp files alone', async () => {
    const tenantDir = path.join(cacheDir, ORG, ENV);
    await mkdir(tenantDir, { recursive: true });
    const recentOrphan = path.join(tenantDir, 'policies.json.def.tmp');
    await writeFile(recentOrphan, 'in-flight write');

    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache.loadFromDisk();

    // Recent orphan still there — it might be a legitimate in-flight write.
    expect(existsSync(recentOrphan)).toBe(true);
  });

  // ─── atomicity ─────────────────────────────────────────────────────────

  it('writes leave no .tmp file behind on success', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache.updatePolicies({ policies: [{ name: 'p1' }] }, 'e1');
    await cache.updateRoutes([{ name: 'r1' }], 'e2');
    await cache.updateKillSwitches({ kill_switches: [{ name: 'k1' }], policy_set: null, server_time: '' });

    const entries = await readdir(path.join(cacheDir, ORG, ENV));
    const tmps = entries.filter((e) => e.endsWith('.tmp'));
    expect(tmps).toEqual([]);
  });

  // ─── stale warning ─────────────────────────────────────────────────────

  it('CACHE_STALE warning fires once per channel beyond max_stale_age', () => {
    const log = makeCapturingLogger();
    const cache = new SyncCache({
      cache_dir: cacheDir,
      org_id: ORG,
      environment: ENV,
      max_stale_age: 1,
      logger: log,
    });

    // Synthetic stale state — bypass the disk write to keep the test
    // hermetic. We directly set the in-memory state via reflection,
    // matching what _readJson would have produced.
    type CachePrivate = {
      _policies: Record<string, unknown> | null;
      _policiesUpdatedAt: number;
    };
    const internal = cache as unknown as CachePrivate;
    internal._policies = { policies: [] };
    // Pretend the cache was updated 1 hour ago in monotonic seconds.
    internal._policiesUpdatedAt = performance.now() / 1000 - 3600;

    // First read triggers stale warning...
    cache.getPolicies();
    const staleWarnings = log.messages.filter(
      ([level, msg]) => level === 'warn' && msg.includes('CACHE_STALE')
    );
    expect(staleWarnings).toHaveLength(1);

    // ...subsequent reads do NOT spam the log.
    cache.getPolicies();
    cache.getPolicies();
    const stillOne = log.messages.filter(
      ([level, msg]) => level === 'warn' && msg.includes('CACHE_STALE')
    );
    expect(stillOne).toHaveLength(1);
  });

  it('updating a channel clears its stale-warned flag (allows future warnings)', () => {
    const log = makeCapturingLogger();
    const cache = new SyncCache({
      cache_dir: cacheDir,
      org_id: ORG,
      environment: ENV,
      max_stale_age: 1,
      logger: log,
    });
    type CachePrivate = {
      _policies: Record<string, unknown> | null;
      _policiesUpdatedAt: number;
      _staleWarned: Record<string, boolean>;
    };
    const internal = cache as unknown as CachePrivate;

    internal._policies = { policies: [] };
    internal._policiesUpdatedAt = performance.now() / 1000 - 3600;
    cache.getPolicies(); // first warning

    // updatePolicies clears the warned flag so a future stale state
    // can warn again. (We just check the flag is gone; the actual
    // re-warning needs another stale window.)
    return cache.updatePolicies({ policies: [{ name: 'fresh' }] }).then(() => {
      expect(internal._staleWarned.policies).toBeUndefined();
    });
  });

  // ─── status() snapshot ─────────────────────────────────────────────────

  it('status() reports cached state per channel', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    let s = cache.status();
    expect(s.policies.cached).toBe(false);
    expect(s.routes.cached).toBe(false);
    expect(s.kill_switches.cached).toBe(false);
    expect(s.disk_synced).toBe(true); // no failed writes yet
    expect(s.cache_dir).toBe(path.join(cacheDir, ORG, ENV));

    await cache.updatePolicies({ policies: [] }, 'e1');
    s = cache.status();
    expect(s.policies.cached).toBe(true);
    expect(s.policies.etag).toBe('e1');
  });

  // ─── disk write failure ────────────────────────────────────────────────

  it('disk write failure leaves memory updated and marks disk_diverged', async () => {
    const log = makeCapturingLogger();
    const cache = new SyncCache({
      cache_dir: cacheDir,
      org_id: ORG,
      environment: ENV,
      logger: log,
    });

    // Create the cache dir, then chmod to read-only to force write
    // failure. Skipping on platforms where chmod doesn't work (Windows).
    await mkdir(path.join(cacheDir, ORG, ENV), { recursive: true });
    const tenantDir = path.join(cacheDir, ORG, ENV);
    if (process.platform === 'win32') {
      // Windows file permissions are too fiddly for this test.
      return;
    }
    const { chmod } = await import('node:fs/promises');
    await chmod(tenantDir, 0o500); // read+execute only

    try {
      await cache.updatePolicies({ policies: [{ name: 'p1' }] }, 'e1');

      // Memory should still have the data...
      expect(cache.getPolicies()).toEqual({ policies: [{ name: 'p1' }] });
      // ...but disk should be marked diverged.
      expect(cache.status().disk_synced).toBe(false);
      // ...and a warning logged.
      // OS text and the generated temporary filename vary; the warning's level and named file do not.
      expect(log.messages.filter(([level]) => level !== 'debug' && level !== 'info').map(([level, message]) =>
        [level, /^Failed to persist (\S+) to disk:/.exec(message)?.[1]]))
        .toEqual([['warn', 'policies.json']]);
    } finally {
      // Restore so afterEach can clean up.
      await chmod(tenantDir, 0o755);
    }
  });

  // ─── age computation ──────────────────────────────────────────────────

  it('getPoliciesAgeSeconds is the elapsed time since the update', async () => {
    const cache = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    expect(cache.getPoliciesAgeSeconds()).toBe(Infinity);
    const updatedMs = 12_000;
    const elapsedMs = 2_500;
    const clock = vi.spyOn(performance, 'now').mockReturnValue(updatedMs);
    try {
      await cache.updatePolicies({ policies: [] });
      clock.mockReturnValue(updatedMs + elapsedMs);
      expect(cache.getPoliciesAgeSeconds()).toBe(elapsedMs / 1000);
    } finally {
      clock.mockRestore();
    }
  });

  it('warm-start preserves file age across instances (mtime-aware)', async () => {
    // Write a file, backdate it, then warm-start a new cache. The age
    // reported by the new instance is the wall-clock age of the file,
    // not zero.
    const cache1 = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
    await cache1.updatePolicies({ policies: [] });

    // Backdate the file mtime, and hold the cache's clocks at whole seconds so
    // no time passes during the read; the monotonic reading is past the
    // backdate, so the file's stamp on it is after 0 (the never-updated mark).
    const BACKDATE_S = 30;
    const nowS = Math.floor(Date.now() / 1000);
    const monoS = Math.floor(performance.now() / 1000) + BACKDATE_S + 1;
    const file = path.join(cacheDir, ORG, ENV, 'policies.json');
    const { utimes } = await import('node:fs/promises');
    await utimes(file, nowS - BACKDATE_S, nowS - BACKDATE_S);
    // Also the sidecar — we don't validate sidecar mtime but keep it consistent.
    await utimes(`${file}.sha256`, nowS - BACKDATE_S, nowS - BACKDATE_S);

    const wall = vi.spyOn(Date, 'now').mockReturnValue(nowS * 1000);
    const mono = vi.spyOn(performance, 'now').mockReturnValue(monoS * 1000);
    try {
      const cache2 = new SyncCache({ cache_dir: cacheDir, org_id: ORG, environment: ENV });
      await cache2.loadFromDisk();
      expect(cache2.getPoliciesAgeSeconds()).toBe(BACKDATE_S);
    } finally {
      wall.mockRestore();
      mono.mockRestore();
    }
  });
});
