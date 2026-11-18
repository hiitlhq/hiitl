/**
 * Row 193 (HTL-23) in the SDK: an unexpected failure once the envelope exists is a decision.
 *
 * Ruled 2026-11-06: "once an envelope exists, an unexpected failure on the evaluate path is `BLOCK`, fail-closed, with
 * `error.code` and an authored message, its record written where the store answers; the same for a failed dedup read
 * in both SDKs", by decision_response.md "Never return generic 500 errors without a decision response body" and
 * Principle 7. `error` "= ECP itself failed ... The action was not evaluated" (decision_response.md), so neither is
 * the first decision under its key. Design: the HTL-23 test design, row 193, behavior 6. Mirrors
 * python/hiitl/sdk/tests/test_row193.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ERROR_MESSAGES, type Decision } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import { AuditLogError } from '../../src/exceptions.js';

const ORG = 'org_test000000000000000';
const SENTINEL = '/var/lib/hiitl/r193_the_cause_never_said';
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
const clients: HIITL[] = [];
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row193-'));
});
afterEach(() => {
  vi.restoreAllMocks();
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

/** A hybrid client's sync cache whose read of its held policy fails unexpectedly. */
const cacheUnreadable = (h: HIITL) => {
  (h as Row).syncCache = {
    getPolicySet: () => {
      throw new Error(SENTINEL);
    },
    tickPart: () => null, // no kill-switch tick pending (row 240)
    cacheStatus: () => 'synced',
  };
};

const dedupUnreadable = (h: HIITL) =>
  vi.spyOn((h as Row).auditLogger, 'firstDecisionUnderKey').mockImplementation(() => {
    throw new AuditLogError(`Failed to read the first decision under the key: ${SENTINEL}`);
  });

const storeDown = (h: HIITL) =>
  vi.spyOn((h as Row).auditLogger, 'write').mockImplementation(() => {
    throw new AuditLogError(`Failed to write audit record: ${SENTINEL}`);
  });

const FAULTS: Array<[string, (h: HIITL) => unknown, string]> = [
  ['unexpected', cacheUnreadable, 'EVALUATION_FAILED'],
  ['dedup-read', dedupUnreadable, 'AUDIT_READ_FAILED'],
];

/** The decision evaluate() answers; a failure it throws instead fails the cell on its assertion (the row: a decision,
 * never a throw). */
function answered(h: HIITL, key: string): Decision {
  let d: Decision | undefined;
  expect(() => {
    d = h.evaluate({ action: 'refund', idempotency_key: key }) as Decision;
  }, 'evaluate() answers a decision, never a throw').not.toThrow();
  return d!;
}

const logged = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.map((c) => c.map(String).join(' ')).join('\n');

describe('row 193: an unexpected failure once the envelope exists is a decision', () => {
  it.each(FAULTS)('test_the_failure_is_a_block_decision_recorded (%s)', (_, fault, reason) => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const h = client();
    fault(h);
    const d = answered(h, 'idem_r193_record');
    expect([d.decision, d.allowed, d.reason_codes]).toEqual(['BLOCK', false, [reason]]);
    expect([d.error?.code, d.error?.message]).toEqual([reason, ERROR_MESSAGES[reason]]);
    expect(JSON.stringify(d)).not.toContain(SENTINEL);
    expect(logged(error)).toContain(SENTINEL);
    const log = new AuditLogger(path.join(dir, 'audit.db'));
    try {
      const [record, ...more] = log.lifecycle(ORG, 'dev', d.action_id) as Row[];
      expect(more).toEqual([]);
      expect([record.decision_type, record.decision.error.code]).toEqual(['BLOCK', reason]);
    } finally {
      log.close();
    }
  });

  it.each(FAULTS)('test_with_the_store_down_too_the_answer_stands (%s)', (_, fault, reason) => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const h = client();
    fault(h);
    storeDown(h);
    const d = h.evaluate({ action: 'refund', idempotency_key: 'idem_r193_down' }) as Decision;
    expect([d.decision, d.reason_codes, d.error?.code]).toEqual(['BLOCK', [reason], reason]);
    expect(logged(error)).toContain('could not be written');
  });

  it.each(FAULTS)('test_neither_is_the_first_decision_under_its_key (%s)', (_, fault, reason) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const h = client();
    const faulted = fault(h) as { mockRestore?: () => void } | undefined;
    expect((h.evaluate({ action: 'refund', idempotency_key: 'idem_r193_retry' }) as Decision).reason_codes)
      .toEqual([reason]);
    if (faulted?.mockRestore) faulted.mockRestore();
    else (h as Row).syncCache = undefined;
    const again = h.evaluate({ action: 'refund', idempotency_key: 'idem_r193_retry' }) as Decision;
    expect([again.decision, again.reason_codes]).toEqual(['ALLOW', ['REFUND_ALLOWED']]);
  });
});
