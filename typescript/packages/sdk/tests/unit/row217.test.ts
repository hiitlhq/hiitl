/**
 * Row 217 (HTL-24): a result for a held action, in the SDK's store.
 *
 * Ruled 2026-11-07: "the local store writes the result, naming the review it cannot read … in local mode the record
 * stands as named … One rule in the store and one read at ingest; no per-mode branching." By the ontology §4
 * commitment 3 and Principle 4. The store holds no review case: it passes the decision's unread review to the one
 * rule and writes it as the record's `review`, a further term of its hash (event_format.md 1.6). Design: the HTL-24
 * test design, row 217, behavior 4. Mirrors python/hiitl/sdk/tests/test_row217.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { AUDIT_FURTHER, auditContentHash, type Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { LifecycleError } from '../../src/exceptions.js';

const ORG = 'org_test000000000000000';
const payout = (over: number) => [
  { field: 'action', operator: 'equals', value: 'payout' },
  { field: 'parameters.amount', operator: 'greater_than', value: over },
];
const SET = {
  version: 'v1.0.0', name: 'payouts', description: "The payout agent's payouts",
  scope: { org_id: ORG, environment: 'dev' },
  rules: [
    { name: 'block_large_payouts', priority: 200, description: 'Payouts over 10,000 are refused',
      conditions: { all_of: payout(10000) }, decision: 'BLOCK', reason_code: 'PAYOUT_OVER_LIMIT' },
    { name: 'review_payouts', priority: 100, description: 'Payouts over 1,000 are reviewed',
      conditions: { all_of: payout(1000) }, decision: 'REQUIRE_APPROVAL', reason_code: 'PAYOUT_REVIEW',
      route: 'finance-review' },
    { name: 'allow_payouts', priority: 10, description: 'Other payouts are allowed',
      conditions: { field: 'action', operator: 'equals', value: 'payout' }, decision: 'ALLOW',
      reason_code: 'PAYOUT_ALLOWED' },
  ],
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

let dir: string;
let ambient: Record<string, string | undefined>;
const clients: HIITL[] = [];
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row217-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  for (const h of clients.splice(0)) h.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function client(where = dir): HIITL {
  const file = path.join(where, 'payouts.json');
  fs.writeFileSync(file, JSON.stringify(SET));
  const h = new HIITL({
    environment: 'dev', agent_id: 'payout-agent', org_id: ORG, policy_path: file,
    audit_db_path: path.join(where, 'audit.db'), mode: 'RESPECT_POLICY',
  });
  clients.push(h);
  return h;
}

function held(h: HIITL): Decision {
  const d = h.evaluate({ action: 'payout', parameters: { amount: 4800 } }) as Decision;
  expect([d.decision, Boolean(d.resume_token)]).toEqual(['REQUIRE_APPROVAL', true]);
  return d;
}

const further = (r: Row) => Object.fromEntries(AUDIT_FURTHER.filter((m) => m in r).map((m) => [m, r[m]]));
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const log = (h: HIITL) => (h as any).auditLogger;

describe('row 217: a result for a held action, in the store', () => {
  it('a held result is written naming its unread review', async () => {
    const h = client();
    const d = held(h);
    const written = h.recordResult(d.action_id, 'succeeded', { duration_ms: 412 });
    // the store holds no case, so a held result refused is read as if the action had not executed (gap row 217)
    await expect(written, 'the held result is written, not refused').resolves.toBeDefined();
    const record = (await written) as Row;
    expect(record.review).toEqual({ unread: d.resume_token });
    expect(record.execution_result).toEqual({ status: 'succeeded', duration_ms: 412 });
    expect(Object.keys(further(record))).toEqual(expect.arrayContaining(['execution_result', 'review']));
    expect(auditContentHash(record.event_id, record.envelope, record.decision, further(record)), 'the hash covers the review')
      .toBe(record.content_hash);
    const again = (await h.recordResult(d.action_id, 'succeeded', { duration_ms: 412 })) as Row;
    expect(again.event_id, 'the same result again returns the record that holds it').toBe(record.event_id);
  });

  it('a stored review altered no longer verifies', async () => {
    const h = client();
    const d = held(h);
    const record = (await h.recordResult(d.action_id, 'succeeded')) as Row;
    expect(log(h).verifyIntegrity(record.event_id)).toBe(true);
    log(h).db.prepare('UPDATE audit_log SET review = ? WHERE event_id = ?')
      .run(JSON.stringify({ status: 'approved', timeout_action: 'fail_closed' }), record.event_id);
    expect(log(h).verifyIntegrity(record.event_id), 'a review rewritten as read no longer verifies').toBe(false);
  });

  it('the upload carries the review', async () => {
    const h = client();
    const d = held(h);
    await h.recordResult(d.action_id, 'failed', { error: 'the bank refused the transfer' });
    const [decision, result] = log(h).getUnsynced(10) as Row[];
    expect(['review' in decision, result.review]).toEqual([false, { unread: d.resume_token }]);
    expect([decision.event_type, result.event_type]).toEqual(['action.evaluated', 'action.failed']);
    expect(auditContentHash(result.event_id, result.envelope, result.decision, further(result))).toBe(result.content_hash);
  });

  it('an allowed result names no review', async () => {
    const h = client();
    const d = h.evaluate({ action: 'payout', parameters: { amount: 120 } }) as Decision;
    expect(d.allowed).toBe(true);
    expect('review' in ((await h.recordResult(d.action_id, 'succeeded')) as Row)).toBe(false);
  });

  it('a blocked result is refused and nothing is written', async () => {
    const h = client();
    const d = h.evaluate({ action: 'payout', parameters: { amount: 25000 } }) as Decision;
    expect(d.decision).toBe('BLOCK');
    const refused = await h.recordResult(d.action_id, 'succeeded').catch((e) => e);
    expect(refused).toBeInstanceOf(LifecycleError);
    expect((refused as LifecycleError).reason).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(log(h).lifecycle(ORG, 'dev', d.action_id)).toHaveLength(1);
  });

  it("the store's further columns are the core's terms", () => {
    const columns = (file: string) => {
      const db = new Database(file, { readonly: true });
      const names = (db.prepare('PRAGMA table_info(audit_log)').all() as Row[]).map((c) => c.name);
      db.close();
      return names;
    };
    client().close();
    expect(columns(path.join(dir, 'audit.db'))).toEqual(expect.arrayContaining([...AUDIT_FURTHER]));

    const old = path.join(dir, 'old');
    fs.mkdirSync(old);
    const db = new Database(path.join(old, 'audit.db'));
    db.exec('CREATE TABLE audit_log (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, org_id TEXT NOT NULL, ' +
      'environment TEXT NOT NULL, action_id TEXT NOT NULL, envelope TEXT NOT NULL, decision TEXT NOT NULL, ' +
      'policy_version TEXT NOT NULL, decision_type TEXT NOT NULL, tool_name TEXT, agent_id TEXT, ' +
      'content_hash TEXT NOT NULL)');
    db.close();
    client(old).close();
    expect(columns(path.join(old, 'audit.db'))).toEqual(expect.arrayContaining([...AUDIT_FURTHER]));
  });
});
