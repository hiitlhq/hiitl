/**
 * Row 135 (HTL-29 review, condition 4), in the SDK's audit store: a result is answered from what its write stored.
 *
 * The spec: event_format.md "The Lifecycle", "One step": a result is answered from the record as its write stored it,
 * read in the write's own transaction. Security architecture §1.1, "a change is answered from what it wrote". Design:
 * the HTL-29 test design, row 135, behavior 14. Mirrors python/hiitl/sdk/tests/test_row135.py.
 *
 * In this SDK the read of an action's records and its result's write are one step within a process with no hold:
 * `recordResult` reads and writes with no await between them. What is left is the write's own read, which is the
 * write: a read that fails inside it leaves no result recorded, and the caller is told.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import { AuditLogger } from '../../src/audit.js';

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

const clients: HIITL[] = [];
const dirs: string[] = [];

function client(): HIITL {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row135-'));
  dirs.push(dir);
  const file = path.join(dir, 'refunds.json');
  fs.writeFileSync(file, JSON.stringify(SET));
  const h = new HIITL({
    environment: 'dev', agent_id: 'refund-agent', org_id: ORG, policy_path: file,
    audit_db_path: path.join(dir, 'audit.db'), mode: 'RESPECT_POLICY',
  });
  clients.push(h);
  return h;
}

function results(h: HIITL, actionId: string): Array<Record<string, unknown>> {
  return (h as any).auditLogger.lifecycle(ORG, 'dev', actionId).filter((r: Record<string, unknown>) => r.execution_result);
}

afterEach(() => {
  vi.restoreAllMocks();
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
});

describe('row 135: a result is answered from what its write stored', () => {
  it('a read that fails inside the write leaves no result, and the caller is told', async () => {
    const h = client();
    const actionId = (await h.evaluate({ action: 'refund', parameters: { amount: 10 } })).action_id;
    const insert = (AuditLogger.prototype as any).insert;
    const read = AuditLogger.prototype.lifecycle;
    let written = false;
    vi.spyOn(AuditLogger.prototype as any, 'insert').mockImplementation(function (this: AuditLogger, ...args: unknown[]) {
      const stored = insert.apply(this, args);
      written = true;
      return stored;
    });
    vi.spyOn(AuditLogger.prototype, 'lifecycle').mockImplementation(function (this: AuditLogger, ...args) {
      if (written) throw new Error('the store could not be read after the write');
      return read.apply(this, args);
    });

    await expect(h.recordResult(actionId, 'succeeded', { duration_ms: 12 })).rejects.toThrow(/could not be read/);
    vi.restoreAllMocks();
    expect(results(h, actionId)).toEqual([]);
  });

  it('a result written is the result answered', async () => {
    const h = client();
    const actionId = (await h.evaluate({ action: 'refund', parameters: { amount: 10 } })).action_id;
    const answer = await h.recordResult(actionId, 'succeeded', { duration_ms: 12 });
    const [stored] = results(h, actionId);
    expect([answer.event_id, answer.content_hash, answer.execution_result])
      .toEqual([stored.event_id, stored.content_hash, stored.execution_result]);
  });
});
