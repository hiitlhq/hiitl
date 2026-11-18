/**
 * Row 146 (HTL-20), the rate-limit members through the SDK: a decision the limiter counted carries the counter state,
 * and an exceeded rule's own remediation reaches the caller.
 *
 * R-0008: "Decisions must include current counter state snapshot". R-0059 and decision_response.md 1.2: remediation
 * on RATE_LIMIT decisions. Design: the HTL-20 test design, row 146. Mirrors sdk/tests/test_row146.py.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';

const RATE_REMEDIATION = {
  type: 'rate_limit', message: 'Refunds are limited to 2 a minute per agent',
  suggestion: 'Queue the refund and retry after reset_at', details: { retry: 'after reset_at' },
};
const ALLOW_REFUNDS = {
  name: 'allow_refunds', description: 'Refunds are allowed', priority: 100,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
};
const LIMIT_REFUNDS = {
  name: 'limit_refunds', description: '2 refunds a minute per agent', priority: 600,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'RATE_LIMIT', reason_code: 'REFUND_RATE',
  rate_limit: { limit: 2, window_seconds: 60, scope: 'agent' }, remediation: RATE_REMEDIATION,
};

const windowRule = (name: string, priority: number, limit: number, windowSeconds: number, scope: string) => ({
  name, description: `${limit} refunds per ${windowSeconds}s per ${scope}`, priority,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'RATE_LIMIT', reason_code: 'REFUND_RATE',
  rate_limit: { limit, window_seconds: windowSeconds, scope },
});

const clients: HIITL[] = [];
const dirs: string[] = [];

function client(rules: object[]): HIITL {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row146-'));
  dirs.push(dir);
  const policyPath = path.join(dir, 'refunds.json');
  fs.writeFileSync(policyPath, JSON.stringify({ version: 'v1.0.0', description: 'The refund_policy set', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'refund_policy', rules }));
  const hiitl = new HIITL({
    environment: 'dev', agent_id: 'payments-agent', org_id: 'org_test000000000000000', policy_path: policyPath,
    audit_db_path: ':memory:', enable_rate_limiting: true, mode: 'RESPECT_POLICY',
  });
  clients.push(hiitl);
  return hiitl;
}

afterEach(() => {
  vi.useRealTimers();
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
});

describe('row 146: the rate-limit members through the SDK', () => {
  it('an allow the limiter counted carries the tightest window', () => {
    const minute = windowRule('agent_minute', 600, 3, 60, 'agent');
    const hiitl = client([windowRule('org_hourly', 700, 10, 3600, 'org'), minute, ALLOW_REFUNDS]);
    const firstCall = new Date('2026-11-09T12:00:00Z');
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(firstCall);
    const d = hiitl.evaluate({ action: 'refund' });
    expect(d.decision).toBe('ALLOW');
    expect(d.rate_limit).toBeDefined();
    const state = d.rate_limit!;
    expect([state.scope, state.window, state.limit, state.current]).toEqual(['agent', '60s', 3, 1]);
    const resetAt = Date.parse(state.reset_at as unknown as string);
    expect(resetAt).toBe(firstCall.getTime() + minute.rate_limit.window_seconds * 1000);

    const tie = client([windowRule('org_minute', 700, 3, 60, 'org'), windowRule('agent_two', 600, 3, 120, 'agent'), ALLOW_REFUNDS]);
    expect(tie.evaluate({ action: 'refund' }).rate_limit?.window).toBe('60s'); // equal headroom: the first listed
  });

  it('no windowed rule no counter state', () => {
    expect(client([ALLOW_REFUNDS]).evaluate({ action: 'refund' }).rate_limit).toBeUndefined();
  });

  it('the exceeded rules remediation reaches the caller with its counter state', () => {
    const hiitl = client([LIMIT_REFUNDS, ALLOW_REFUNDS]);
    hiitl.evaluate({ action: 'refund' });
    hiitl.evaluate({ action: 'refund' });
    const d = hiitl.evaluate({ action: 'refund' });
    expect(d.decision).toBe('RATE_LIMIT');
    expect(d.matched_rules?.map((m) => m.rule_name)).toEqual(['limit_refunds']);
    expect(d.remediation).toBeDefined();
    const rem = d.remediation!;
    expect([rem.type, rem.message, rem.suggestion]).toEqual(['rate_limit', RATE_REMEDIATION.message, RATE_REMEDIATION.suggestion]);
    expect(rem.details).toEqual({ retry: 'after reset_at', ...d.rate_limit });
    expect([d.rate_limit?.limit, d.rate_limit?.current]).toEqual([2, 2]);
  });

  it('the refusal keeps the evaluation record', () => {
    const staged = {
      name: 'staged_hold', description: 'A staged hold on refunds', priority: 500, lifecycle_stage: 'staged',
      conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'BLOCK', reason_code: 'REFUND_HOLD',
    };
    const hiitl = client([LIMIT_REFUNDS, staged, ALLOW_REFUNDS]);
    const allowed = [hiitl.evaluate({ action: 'refund' }), hiitl.evaluate({ action: 'refund' })];
    const refused = hiitl.evaluate({ action: 'refund' });
    expect([...allowed, refused].map((d) => d.decision)).toEqual(['ALLOW', 'ALLOW', 'RATE_LIMIT']);
    expect(refused.staged_observations?.map((o) => o.rule_name)).toEqual(['staged_hold']);
    expect(refused.rate_limit_rules?.map((r) => [r.rule_name, r.reason_code])).toEqual([['limit_refunds', 'REFUND_RATE']]);
    expect(refused.rate_limit_rules).toEqual(allowed[1].rate_limit_rules);
  });
});
