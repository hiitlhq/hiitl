/**
 * Row 204 (HTL-23): every member the decision model declares reaches the hosted caller.
 *
 * Ruled 2026-11-06 as the row reads: "the lists are generated from the decision model, the class swept, by R-0872 and
 * item 13". R-0872: "no field is ever silently dropped". The members are read from the core `DecisionSchema`'s shape,
 * never from a list in the cell: a member the schema gains fails the completeness assertion here until its value is
 * written below, and needs no edit to the client. Design: the HTL-23 test design, row 204. Mirrors
 * python/hiitl/sdk/tests/test_row204.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DecisionSchema } from '@hiitl/core';
import { HIITL } from '../../src/client.js';

const ORG_ID = 'org_r204everymember0000';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

const REMEDIATION = {
  message: 'Refunds over 500 need a manager', suggestion: 'Lower the amount to 500 or less',
  type: 'threshold', details: { field: 'parameters.amount', limit: 500 },
};

// A hosted decision carrying a value for each member. `error` and `remediation` never ride together (the schema's
// own refusal), so the error decision carries `error` and the rest of the members as the full one does.
const FULL: Row = {
  action_id: '', decision: 'BLOCK', allowed: false, reason_codes: ['REFUND_CAPPED'],
  policy_version: 'v1.4.0', timing: { ingest_ms: 0.25, evaluation_ms: 0.5, total_ms: 1.25 },
  matched_rules: [{ rule_name: 'cap_refunds', policy_set: 'refunds', priority: 500 }],
  rate_limit: { scope: 'agent', window: '60s', limit: 10, current: 3, reset_at: '2026-11-06T12:00:00Z' },
  resume_token: 'rt_r204resume00000000', route_ref: 'finance-review',
  escalation_context: { queue: 'finance', sla_minutes: 15 },
  envelope_hash: 'a'.repeat(64),
  remediation: REMEDIATION,
  would_be: 'BLOCK', would_be_reason_codes: ['REFUND_CAPPED'],
  staged_observations: [{
    rule_name: 'hold_refunds', policy_set: 'refunds', priority: 400, would_be_decision: 'REQUIRE_APPROVAL',
    would_be_reason_codes: ['REFUND_HELD'], would_be_binding: false,
  }],
  rate_limit_rules: [{
    rule_name: 'meter_refunds', policy_set: 'refunds', priority: 300, reason_code: 'REFUNDS_METERED', limit: 100,
    window_seconds: 3600, scope: 'agent', remediation: REMEDIATION,
  }],
  enrichment: { fraud: { score: 0.12 } },
  routes: [{ rule_name: 'score_refunds', route: 'fraud-score', outcome: 'answered', fields: ['score'] }],
  missing_fields: [{ rule_name: 'cap_by_region', policy_set: 'refunds', field: 'parameters.region' }],
  cache_status: 'synced',
  metadata: { fail_mode: 'FAIL_CLOSED', circuit_breaker_state: 'closed' },
};
const { remediation: _dropped, ...WITHOUT_REMEDIATION } = FULL;
const ERRORED: Row = {
  ...WITHOUT_REMEDIATION,
  error: { code: 'RATE_LIMIT_SERVICE_ERROR', message: 'The rate limit counter could not be read.' },
};

/** The members the refined core object schema declares. */
const members = (): string[] => Object.keys(DecisionSchema.shape);

let dir: string;
let ambient: Record<string, string | undefined>;
const clients: HIITL[] = [];

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row204-'));
});

afterEach(() => {
  for (const h of clients.splice(0)) h.close();
  vi.unstubAllGlobals();
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  fs.rmSync(dir, { recursive: true, force: true });
});

function answering(decision: Row): void {
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
    const sent = JSON.parse(init.body as string) as Row;
    return new Response(JSON.stringify({ ...decision, action_id: sent.action_id }),
      { status: 200, headers: { 'Content-Type': 'application/json' } });
  }));
}

function hiitl(): HIITL {
  const h = new HIITL({
    environment: 'dev', agent_id: 'r204-agent', org_id: ORG_ID, api_key: 'sk_test_r204everymember',
    server_url: 'https://ecp.r204.example.com', evaluation: 'remote',
    signature_key: 'r204-signing-secret-0123456789abcdef', audit_db_path: path.join(dir, 'audit.db'),
    max_retries: 0,
  });
  clients.push(h);
  return h;
}

describe('row 204: every member the decision model declares reaches the hosted caller', () => {
  it("test_the_cells_decisions_carry_every_member", () => {
    expect(new Set([...Object.keys(FULL), ...Object.keys(ERRORED)])).toEqual(new Set(members()));
    for (const decision of [FULL, ERRORED]) {
      const parsed = DecisionSchema.parse(decision) as Row;
      const empty = Object.keys(decision).filter((m) =>
        parsed[m] === undefined || parsed[m] === null ||
        (Array.isArray(parsed[m]) && parsed[m].length === 0));
      expect(empty, 'each member carries a value').toEqual([]);
    }
  });

  for (const [name, decision] of [['remediation', FULL], ['error', ERRORED]] as const) {
    it(`test_each_member_reaches_the_caller[${name}]`, async () => {
      answering(decision);
      const d = (await hiitl().evaluate({ action: 'refund', parameters: { amount: 900 } })) as Row;
      const sent = DecisionSchema.parse({ ...decision, action_id: d.action_id }) as Row;
      const differing = members().filter((m) => JSON.stringify(d[m]) !== JSON.stringify(sent[m]));
      expect(differing, 'each member as the response carried it').toEqual([]);
    });
  }
});
