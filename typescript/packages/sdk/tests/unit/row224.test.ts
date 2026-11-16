/**
 * Row 224 (HTL-27): a record the service refuses for its own content, settled in the SDK's store.
 *
 * Ruled 2026-11-08: "a record the service refuses for its own content stays in the local store as written, marked
 * refused with the service's code, logged at error, and not sent again". By event_format.md "The Lifecycle" ("a refused
 * result is no record and the service's answer is final"), sync_engine.md "Records are never dropped" and the `synced`
 * mark. sync_engine.md §2.1 is the contract: the codes are core's `RECORD_REFUSALS`, and every other refusal is retried.
 * Design: the HTL-27 test design, row 224, behaviors 3-7. Mirrors python/hiitl/sdk/tests/test_row224.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ENVELOPE_SCHEMA_VERSION, RECORD_REFUSALS } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import type { Logger } from '../../src/logger.js';
import { SyncCache } from '../../src/sync-cache.js';
import type { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const ORG = 'org_r224refused00000000';
const ENV = 'dev';
const DECISION: Decision = {
  action_id: 'act_00000000000000000000', decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { ingest_ms: 0, evaluation_ms: 0, total_ms: 0 },
};
const RETRIED = ['TENANT_MISMATCH', 'INSERT_FAILED', 'QUOTA_EXCEEDED']; // the spec's two, and one the SDK does not know

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

let dir: string;
let ambient: Record<string, string | undefined>;
const opened: Array<{ close(): void }> = [];

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row224-'));
});

afterEach(() => {
  for (const o of opened.splice(0)) o.close();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  fs.rmSync(dir, { recursive: true, force: true });
});

function store(file: string): AuditLogger {
  const log = new AuditLogger(file);
  opened.push(log);
  return log;
}

/** n records in the store, oldest first, a millisecond apart; their event_ids. */
function written(log: AuditLogger, n: number): string[] {
  vi.useFakeTimers({ toFake: ['Date'] });
  const ids = Array.from({ length: n }, (_, i) => {
    vi.setSystemTime(Date.UTC(2026, 10, 8, 10, 0, 0, i));
    const envelope: Envelope = {
      schema_version: ENVELOPE_SCHEMA_VERSION, org_id: ORG, environment: ENV, agent_id: 'r224-agent',
      action_id: `act_r224${String(i).padStart(20, '0')}`, idempotency_key: `k${i}`, action: 'send_email',
      operation: 'execute', target: {}, parameters: { to: `ops+${i}@example.com` }, timestamp: '2026-11-08T10:00:00Z',
      signature: '0'.repeat(64),
    };
    return log.write(envelope, DECISION);
  });
  vi.useRealTimers();
  return ids;
}

/** The upload answer: each record named in `refusals` refused with its code, every other one accepted. */
class Service {
  sent: string[][] = [];
  constructor(public refusals: Record<string, string>) {}

  async uploadAudit(records: Row[], _sequence: number) {
    this.sent.push(records.map((r) => r.event_id));
    const errors = records.filter((r) => r.event_id in this.refusals)
      .map((r) => ({ event_id: r.event_id, code: this.refusals[r.event_id], message: 'not stored' }));
    return { accepted: records.length - errors.length, duplicates: 0, errors };
  }

  close(): void {}
}

/** What the engine logged, at warn and error. */
let logged: Array<[string, string]>;
const capture: Logger = {
  debug: () => {}, info: () => {},
  warn: (m) => logged.push(['warn', m]), error: (m) => logged.push(['error', m]),
};

function engine(log: AuditLogger, service: Service, batch = 100): () => Promise<void> {
  logged = [];
  const cache = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: capture });
  const e = new SyncEngine({
    sync_config: { server_url: 'https://api.test', audit_batch_size: batch }, sync_cache: cache, audit_logger: log,
    api_key: 'sk_test_r224refused0000', org_id: ORG, environment: ENV, logger: capture,
    sync_client: service as unknown as SyncClient,
  });
  return () => (e as unknown as { _syncAudit: () => Promise<void> })._syncAudit();
}

/** Each record as the store holds it, by event_id: the columns, read directly. */
function rows(file: string): Record<string, Row> {
  const db = new Database(file, { readonly: true });
  try {
    return Object.fromEntries((db.prepare('SELECT * FROM audit_log').all() as Row[]).map((r) => [r.event_id, r]));
  } finally {
    db.close();
  }
}

const without = (row: Row, key: string): Row => Object.fromEntries(Object.entries(row).filter(([k]) => k !== key));

describe('row 224: a record refused for its own content', () => {
  for (const code of RECORD_REFUSALS) {
    it(`test_a_record_refused_for_its_content_is_kept_marked_and_not_sent_again (${code})`, async () => {
      // Behavior 3: kept as written, marked refused with the code, out of every pending read, logged at error
      const file = path.join(dir, 'audit.db');
      const log = store(file);
      const [refused, accepted] = written(log, 2);
      const before = rows(file)[refused];
      const service = new Service({ [refused]: code });
      const sync = engine(log, service);

      await sync();
      await sync();

      const after = rows(file);
      expect([after[refused].refused, after[refused].synced]).toEqual([code, 0]);
      expect([after[accepted].refused, after[accepted].synced]).toEqual([null, 1]);
      expect(without(after[refused], 'refused'), 'kept as written').toEqual(without(before, 'refused'));
      expect(log.verifyIntegrity(refused)).toBe(true);
      expect(service.sent, 'not sent again').toEqual([[refused, accepted]]);
      expect([log.getUnsynced(), log.unsyncedBacklog(), log.unsyncedActionIds()]).toEqual([[], [0, 0], new Set()]);
      const about = logged.filter(([, m]) => m.includes(refused));
      expect(about.map(([level]) => level)).toEqual(['error']);
      expect(about[0][1], 'naming the event, the code and the message').toContain(code);
      expect(about[0][1]).toContain('not stored');
    });
  }

  for (const code of RETRIED) {
    it(`test_every_other_refusal_is_retried (${code})`, async () => {
      // Behavior 4: the record stays pending, logged at warning, and the drain stops until the next interval
      const file = path.join(dir, 'audit.db');
      const log = store(file);
      const [held, behind] = written(log, 2);
      const service = new Service({ [held]: code });
      const sync = engine(log, service, 1);

      await sync();

      expect(service.sent, 'the drain stops').toEqual([[held]]);
      expect(rows(file)[held].refused).toBeNull();
      expect(log.getUnsynced().map((r) => r.event_id)).toEqual([held, behind]);
      expect(logged.filter(([, m]) => m.includes(held)).map(([level]) => level)).toEqual(['warn']);

      service.refusals = {};
      await sync();
      expect(service.sent.slice(1), 'sent again at the next interval').toEqual([[held], [behind]]);
      expect(log.getUnsynced()).toEqual([]);
    });
  }

  it('test_the_records_behind_a_refused_one_drain', async () => {
    // Behavior 5: a refusal for the record's content does not stop the drain
    const file = path.join(dir, 'audit.db');
    const log = store(file);
    const [refused, ...behind] = written(log, 3);
    const service = new Service({ [refused]: 'CONTENT_HASH_MISMATCH' });

    await engine(log, service, 1)();

    expect(service.sent).toEqual([[refused], [behind[0]], [behind[1]]]);
    expect(behind.map((e) => rows(file)[e].synced)).toEqual([1, 1]);
  });

  it('test_a_store_written_before_the_mark_gains_it', () => {
    // Behavior 7: a store whose table has no `refused` column opens with it, null on every record it holds, and keeps
    // their marks: the record it had synced stays synced, and the other is still to send (Codex's condition 3, C3.1)
    const file = path.join(dir, 'audit.db');
    const first = new AuditLogger(file);
    const events = written(first, 2);
    first.markSynced(events.slice(0, 1));
    first.close();
    const db = new Database(file);
    db.exec('ALTER TABLE audit_log DROP COLUMN refused');
    db.close();

    const log = store(file);
    const columns = new Database(file, { readonly: true });
    const names = (columns.prepare('PRAGMA table_info(audit_log)').all() as Row[]).map((c) => c.name);
    columns.close();
    expect(names, 'the store gains the mark').toContain('refused');
    expect(log.getUnsynced().map((r) => r.event_id)).toEqual(events.slice(1));
    expect(Object.fromEntries(Object.entries(rows(file)).map(([e, r]) => [e, [r.synced, r.refused]])))
      .toEqual({ [events[0]]: [1, null], [events[1]]: [0, null] });
  });
});

// The hosted client settles its push the same way (behavior 6)

const SERVER = 'https://ecp.r224.example.com';
const EVALUATE = '/v1/evaluate';
const PUSH = '/v1/sync/audit';
type Answer = (body: Row) => Response;

const json = (body: Row): Response =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
const down: Answer = () => {
  throw new TypeError('fetch failed');
};
const decides: Answer = (body) => json({
  action_id: body.action_id, decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { total_ms: 1.0 },
});

function hiitl(file: string): HIITL {
  const h = new HIITL({
    environment: ENV, agent_id: 'r224-agent', org_id: ORG, api_key: 'sk_test_r224refused0000', server_url: SERVER,
    evaluation: 'remote', signature_key: 'r224-signing-secret-0123456789abcdef', audit_db_path: file, max_retries: 0,
  });
  opened.push(h);
  return h;
}

describe('row 224: the hosted client', () => {
  it('test_the_hosted_client_settles_its_push_the_same_way', async () => {
    // Two outages hold two records (the second call's push met none); the next push refuses the first for its own
    // content, and the client marks it refused, the second synced, and sends neither again
    const answers: Array<[string, Answer]> = [];
    const sent: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      const at = new URL(url).pathname;
      sent.push(at);
      const i = answers.findIndex(([p]) => p === at);
      if (i < 0) throw new Error(`no answer registered for ${at}`);
      return answers.splice(i, 1)[0][1](JSON.parse(init.body as string) as Row);
    }));
    const refusesTheFirst: Answer = (body) => json({
      accepted: 1, duplicates: 0,
      errors: [{ event_id: body.records[0].event_id, code: 'EVENT_TYPE_MISMATCH', message: 'not its decision\'s' }],
    });
    answers.push([EVALUATE, down], [PUSH, down], [PUSH, refusesTheFirst], [EVALUATE, decides]);
    const file = path.join(dir, 'audit.db');
    const h = hiitl(file);
    const first = (await h.evaluate({ action: 'send_email' })) as Decision;
    const second = (await h.evaluate({ action: 'send_email' })) as Decision;
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await h.evaluate({ action: 'send_email' });
    h.close();

    const byAction = Object.fromEntries(Object.values(rows(file)).map((r) => [r.action_id, r]));
    expect([byAction[first.action_id].refused, byAction[first.action_id].synced]).toEqual(['EVENT_TYPE_MISMATCH', 0]);
    expect([byAction[second.action_id].refused, byAction[second.action_id].synced]).toEqual([null, 1]);
    expect(error.mock.calls.filter((c) => String(c[0]).includes('EVENT_TYPE_MISMATCH')).length).toBe(1);

    answers.push([EVALUATE, decides]);
    await hiitl(file).evaluate({ action: 'send_email' });
    expect(sent.slice(4), 'constructed again, the client sends nothing refused').toEqual([EVALUATE]);
    expect(answers, 'every answer registered was asked for').toEqual([]);
  });
});
