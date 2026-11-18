/**
 * Row 191 (HTL-23, Stop A): what a record's hash covers, in the SDK's store.
 *
 * Ruled 2026-11-06: "each content member a record carries beyond its envelope and decision joins the hash as a further
 * term in a fixed order ...; a record carrying neither hashes exactly as today". By the security architecture §1.4 and
 * Tier 1, "Enables individual record tamper detection". The store reads the hash's terms from the record, never from
 * a list of what it should carry. Design: the HTL-23 test design, row 191, behaviors 3 and 5. Mirrors
 * python/hiitl/sdk/tests/test_row191.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { AUDIT_FURTHER, auditContentHash, type Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';

const ORG = 'org_test000000000000000';
const SET = {
  version: 'v1.0.0', name: 'refunds', description: "The refund agent's refunds",
  scope: { org_id: ORG, environment: 'dev' },
  rules: [{
    name: 'allow_refunds', priority: 100, description: 'Refunds are allowed',
    conditions: { field: 'action', operator: 'equals', value: 'refund' },
    decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
  }],
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
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row191-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  for (const h of clients.splice(0)) h.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function client(): HIITL {
  const file = path.join(dir, 'refunds.json');
  fs.writeFileSync(file, JSON.stringify(SET));
  const h = new HIITL({
    environment: 'dev', agent_id: 'refund-agent', org_id: ORG, policy_path: file,
    audit_db_path: path.join(dir, 'audit.db'), mode: 'RESPECT_POLICY',
  });
  clients.push(h);
  return h;
}

describe('row 191: what a record hash covers, in the store', () => {
  it('a stored result altered no longer verifies', async () => {
    const h = client();
    const d = h.evaluate({ action: 'refund' }) as Decision;
    const result = await h.recordResult(d.action_id, 'succeeded', { duration_ms: 12 });
    const log = (h as any).auditLogger; // eslint-disable-line @typescript-eslint/no-explicit-any
    const decided = (log.lifecycle(ORG, 'dev', d.action_id) as Row[]).find((r) => !('execution_result' in r))!;
    expect([log.verifyIntegrity(result.event_id), log.verifyIntegrity(decided.event_id)]).toEqual([true, true]);

    log.db.prepare('UPDATE audit_log SET execution_result = ? WHERE event_id = ?')
      .run(JSON.stringify({ status: 'failed', duration_ms: 12 }), result.event_id);

    expect(log.verifyIntegrity(result.event_id), 'an altered result no longer verifies').toBe(false);
    expect(log.verifyIntegrity(decided.event_id)).toBe(true);
  });

  it('the upload carries the result and its hash', async () => {
    const h = client();
    const d = h.evaluate({ action: 'refund' }) as Decision;
    await h.recordResult(d.action_id, 'succeeded', { duration_ms: 12 });

    const unsynced = (h as any).auditLogger.getUnsynced(10) as Row[]; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(unsynced.map((r) => r.execution_result)).toEqual([undefined, { status: 'succeeded', duration_ms: 12 }]);
    expect(unsynced.map((r) => r.event_type)).toEqual(['action.evaluated', 'action.executed']);
    expect(AUDIT_FURTHER.filter((m) => m in unsynced[0]), 'a member is carried or absent').toEqual([]);
    for (const r of unsynced) {
      const further = Object.fromEntries(AUDIT_FURTHER.filter((m) => m in r).map((m) => [m, r[m]]));
      expect(auditContentHash(r.event_id, r.envelope, r.decision, further)).toBe(r.content_hash);
    }
    const [decision, result] = unsynced;
    expect([result.envelope, result.decision], "the result record carries the decision record's as stored")
      .toEqual([decision.envelope, decision.decision]);
    expect(result.event_id).not.toBe(decision.event_id);
  });
});
