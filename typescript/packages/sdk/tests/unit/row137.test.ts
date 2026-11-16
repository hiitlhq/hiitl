/**
 * Row 137 (HTL-29): a mark is beside the record, and an absent hash is refused as a wrong one is.
 *
 * The row 224 ruling: "a mark beside the record is what the append-only rule already allows; the record's content
 * never changes" (event_format.md "Append-Only Requirement"). sync_engine.md §2.2: a policy whose `content_hash` is
 * absent, empty, or not the hash of its `content` is refused alike; §4 "Integrity": a cache file whose sidecar is
 * absent, unreadable, or names another hash is discarded, and a sidecar the SDK could not write fails the write.
 * Design: the HTL-29 test design, row 137, behaviors 5-8. Mirrors python/hiitl/sdk/tests/test_row137.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ENVELOPE_SCHEMA_VERSION, canonicalHash } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';

import { AuditLogger } from '../../src/audit.js';
import { SyncError } from '../../src/exceptions.js';
import type { Logger } from '../../src/logger.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const ORG = 'org_test0123456789ab';
const ENV = 'dev';
const DECISION: Decision = {
  action_id: 'act_00000000000000000000', decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { ingest_ms: 0, evaluation_ms: 0, total_ms: 0 },
};
const POLICY = { policy_id: 'pol_r137', name: 'payments', version: 'v1.0.0', content: { rules: [] } };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

function capturing(): Logger & { errors: string[] } {
  const errors: string[] = [];
  return { errors, debug: () => {}, info: () => {}, warn: () => {}, error: (m: string) => errors.push(m) };
}

let dir: string;
const opened: Array<{ close(): void }> = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row137-'));
});

afterEach(() => {
  for (const o of opened.splice(0)) o.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('row 137: a mark is beside the record (behavior 5)', () => {
  const rows = (file: string): Record<string, Row> => {
    const db = new Database(file, { readonly: true });
    const all = db.prepare('SELECT * FROM audit_log').all() as Row[];
    db.close();
    return Object.fromEntries(all.map((r) => [r.event_id, r]));
  };

  it('test_each_mark_changes_its_own_column_and_nothing_of_the_record', () => {
    const file = path.join(dir, 'audit.db');
    const store = new AuditLogger(file);
    opened.push(store);
    const [synced, refused] = [0, 1].map((i) => {
      const envelope: Envelope = {
        schema_version: ENVELOPE_SCHEMA_VERSION, org_id: ORG, environment: ENV, agent_id: 'r137-agent',
        action_id: `act_r137${String(i).padStart(20, '0')}`, idempotency_key: `k${i}`, action: 'send_email',
        operation: 'execute', target: {}, parameters: { to: `ops+${i}@example.com` },
        timestamp: '2026-11-09T10:00:00Z', signature: '0'.repeat(64),
      };
      return store.write(envelope, DECISION);
    });
    const before = rows(file);

    expect(store.markSynced([synced])).toBe(1);
    expect(store.markRefused({ [refused]: 'AUDIT_CONTENT_HASH_MISMATCH' })).toBe(1);

    const after = rows(file);
    expect(after[synced]).toEqual({ ...before[synced], synced: 1 });
    expect(after[refused]).toEqual({ ...before[refused], refused: 'AUDIT_CONTENT_HASH_MISMATCH' });
    expect(store.verifyIntegrity(synced) && store.verifyIntegrity(refused)).toBe(true);
  });
});

describe('row 137: a downloaded policy with no hash is refused as a wrong one is (behavior 6)', () => {
  function engineServing(log: Logger) {
    const served: { policy: Record<string, unknown>; version: string } = { policy: {}, version: '' };
    const client = new SyncClient({
      server_url: 'https://api.test', api_key: 'k', org_id: ORG, environment: ENV, max_retries: 0, timeout: 5,
      logger: log,
      fetchImpl: async () => new Response(JSON.stringify({
        policies: [served.policy], version: served.version, etag: `e-${served.version}`,
        redaction_policy: { manual_redact_fields: [] },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    });
    const cache = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: log });
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test' }, sync_cache: cache,
      audit_logger: { getUnsynced: () => [], markSynced: () => 0 }, api_key: 'k', org_id: ORG, environment: ENV,
      logger: log, sync_client: client,
    });
    const serve = (policy: Record<string, unknown>, version: string) => Object.assign(served, { policy, version });
    return { cache, serve, sync: () => (engine as unknown as { _syncPolicies: () => Promise<boolean> })._syncPolicies() };
  }

  for (const [sent, cause] of [
    ['absent', 'no content_hash'],
    ['', 'no content_hash'],
    ['0'.repeat(64), 'content hash mismatch'],
  ] as const) {
    it(`test_a_downloaded_policy_with_no_hash_is_refused_as_a_wrong_one_is[${sent || 'empty'}]`, async () => {
      const log = capturing();
      const { cache, serve, sync } = engineServing(log);
      serve({ ...POLICY, content_hash: canonicalHash(POLICY.content) }, 'v1');
      expect(await sync()).toBe(true);
      const held = cache.getPolicies();
      expect((held?.policies as Row[]).map((p) => p.policy_id)).toEqual(['pol_r137']);

      const changed = { ...POLICY, content: { rules: [{ name: 'allow-all', decision: 'ALLOW' }] } };
      serve(sent === 'absent' ? changed : { ...changed, content_hash: sent }, 'v2');
      const refused = await sync().then(() => null, (e: unknown) => e);

      expect(refused).toBeInstanceOf(SyncError);
      expect((refused as SyncError).channel).toBe('policy');
      expect((refused as SyncError).message).toContain(cause);
      expect(cache.getPolicies()).toEqual(held);
      expect(log.errors.some((m) => m.includes('POLICY_INTEGRITY_VIOLATION') && m.includes(cause))).toBe(true);
    });
  }
});

describe('row 137: the cache file and its sidecar (behaviors 7 and 8)', () => {
  const cacheIn = (log: Logger) => new SyncCache({ cache_dir: dir, org_id: ORG, environment: ENV, logger: log });
  const sidecar = () => path.join(dir, ORG, ENV, 'policies.json.sha256');
  const warm = async (log: Logger) => {
    const cache = cacheIn(log);
    await cache.loadFromDisk();
    return cache;
  };

  for (const kind of ['absent', 'unreadable', 'another hash'] as const) {
    it(`test_a_cache_file_without_its_readable_hash_is_discarded[${kind}]`, async () => {
      await cacheIn(capturing()).updatePolicies({ version: 'v1' });
      expect((await warm(capturing())).getPolicies()).toEqual({ version: 'v1' });

      fs.unlinkSync(sidecar());
      if (kind === 'unreadable') fs.mkdirSync(sidecar());
      if (kind === 'another hash') fs.writeFileSync(sidecar(), '0'.repeat(64));
      const log = capturing();
      const cache = await warm(log);

      expect(cache.getPolicies()).toBeNull();
      expect(log.errors.some((m) => m.includes('CACHE_INTEGRITY_VIOLATION'))).toBe(true);
    });
  }

  it('test_a_sidecar_the_sdk_cannot_write_fails_the_write', async () => {
    await cacheIn(capturing()).updatePolicies({ version: 'v1' });
    fs.unlinkSync(sidecar());
    fs.mkdirSync(sidecar()); // the sidecar's place is taken, so it cannot be written

    const cache = cacheIn(capturing());
    await cache.updatePolicies({ version: 'v2' });

    expect(cache.getPolicies()).toEqual({ version: 'v2' });
    expect(cache.status().disk_synced).toBe(false);
    expect((await warm(capturing())).getPolicies()).toBeNull();
  });
});
