/**
 * Row 132 (HTL-20): observe never blocks, and a failing limiter never allows.
 *
 * Under OBSERVE_ALL a call past its limit comes back OBSERVE with `would_be: RATE_LIMIT` (ecp_evaluate_spec.md
 * "Observe Mode"). A limiter that throws blocks the call (safe by default), observed under OBSERVE_ALL. The limiter
 * reads every window before it counts any, so a call one window refuses is counted in none (policy_format.md
 * "Evaluation is Side-Effect Free", "on an ALLOW", R-0056). Design: the HTL-20 test design, row 132.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';

const ALLOW_PAYMENTS = {
  name: 'allow_payments', priority: 100, description: 'Payments and refunds are allowed',
  conditions: { field: 'action', operator: 'in', value: ['pay', 'refund'] },
  decision: 'ALLOW', reason_code: 'PAYMENT_ALLOWED',
};
const PAY_RATE = {
  name: 'pay_rate', priority: 600, description: 'At most 2 payments a minute per agent',
  conditions: { field: 'action', operator: 'equals', value: 'pay' },
  decision: 'RATE_LIMIT', reason_code: 'PAY_RATE',
  rate_limit: { limit: 2, window_seconds: 60, scope: 'agent' },
};

const clients: HIITL[] = [];
const dirs: string[] = [];

function client(rules: object[], mode: 'RESPECT_POLICY' | 'OBSERVE_ALL'): HIITL {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row132-'));
  dirs.push(dir);
  const policyPath = path.join(dir, 'payments.json');
  fs.writeFileSync(policyPath, JSON.stringify({ version: 'v1.0.0', description: 'The payments set', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'payments', rules }));
  const hiitl = new HIITL({
    environment: 'dev', agent_id: 'payments-agent', org_id: 'org_test000000000000000', policy_path: policyPath,
    audit_db_path: ':memory:', enable_rate_limiting: true, mode,
  });
  clients.push(hiitl);
  return hiitl;
}

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
});

describe('row 132: observe never blocks, and a failing limiter never allows', () => {
  it('observe all past the limit is observed not blocked', () => {
    const hiitl = client([PAY_RATE, ALLOW_PAYMENTS], 'OBSERVE_ALL');
    hiitl.evaluate({ action: 'pay' });
    hiitl.evaluate({ action: 'pay' });
    const d = hiitl.evaluate({ action: 'pay' });
    expect([d.decision, d.allowed]).toEqual(['OBSERVE', true]);
    expect([d.would_be, d.would_be_reason_codes]).toEqual(['RATE_LIMIT', ['RATE_LIMIT_EXCEEDED']]);
    expect(d.matched_rules?.map((m) => m.rule_name)).toEqual(['pay_rate']);
    expect([d.rate_limit?.scope, d.rate_limit?.window, d.rate_limit?.limit, d.rate_limit?.current])
      .toEqual(['agent', '60s', 2, 2]);
  });

  it('each would_be is what enforcing the same calls decides', () => {
    const run = (mode: 'RESPECT_POLICY' | 'OBSERVE_ALL') => {
      const hiitl = client([PAY_RATE, ALLOW_PAYMENTS], mode);
      return Array.from({ length: 5 }, () => hiitl.evaluate({ action: 'pay' }));
    };
    const enforced = run('RESPECT_POLICY');
    const observed = run('OBSERVE_ALL');
    expect(enforced.map((d) => d.decision)).toEqual(['ALLOW', 'ALLOW', 'RATE_LIMIT', 'RATE_LIMIT', 'RATE_LIMIT']);
    expect(enforced.map((d) => d.rate_limit?.current)).toEqual([1, 2, 2, 2, 2]); // a refused call is counted in no window
    expect(observed.every((d) => d.allowed)).toBe(true);
    expect(observed.map((d) => d.would_be ?? d.decision)).toEqual(enforced.map((d) => d.decision));
    expect(observed.map((d) => d.rate_limit?.current)).toEqual(enforced.map((d) => d.rate_limit?.current));
  });

  for (const mode of ['RESPECT_POLICY', 'OBSERVE_ALL'] as const) {
    it(`a failing limiter does not let the call through (${mode})`, () => {
      const hiitl = client([PAY_RATE, ALLOW_PAYMENTS], mode);
      // The in-process form of a limiter whose store cannot be read.
      (hiitl as any).rateLimiter = { checkAndIncrement: () => { throw new Error('counter store unreadable'); } };
      // The message is authored; the cause is logged, never said (HTL-22 row 159).
      const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
      const d = hiitl.evaluate({ action: 'pay' });
      expect(logged.mock.calls.flat().join(' ')).toContain('counter store unreadable');
      logged.mockRestore();
      expect(d.error?.code).toBe('RATE_LIMIT_SERVICE_ERROR');
      expect(d.error?.message).not.toContain('counter store unreadable');
      if (mode === 'RESPECT_POLICY') {
        expect([d.decision, d.allowed, d.reason_codes]).toEqual(['BLOCK', false, ['RATE_LIMIT_SERVICE_ERROR']]);
      } else {
        expect([d.decision, d.allowed]).toEqual(['OBSERVE', true]);
        expect([d.would_be, d.would_be_reason_codes]).toEqual(['BLOCK', ['RATE_LIMIT_SERVICE_ERROR']]);
      }
    });
  }

  it('a call one window refuses is counted in no window', () => {
    // The wider window is listed first: 2 calls a minute across the org, then 1 payment a minute.
    const orgRate = {
      name: 'org_rate', priority: 700, description: 'At most 2 money movements a minute',
      conditions: { field: 'action', operator: 'in', value: ['pay', 'refund'] },
      decision: 'RATE_LIMIT', reason_code: 'ORG_RATE',
      rate_limit: { limit: 2, window_seconds: 60, scope: 'org' },
    };
    const onePay = { ...PAY_RATE, name: 'one_pay', rate_limit: { limit: 1, window_seconds: 60, scope: 'agent' } };
    const hiitl = client([orgRate, onePay, ALLOW_PAYMENTS], 'RESPECT_POLICY');
    const [first, refused, refund, over] = ['pay', 'pay', 'refund', 'refund'].map((action) => hiitl.evaluate({ action }));
    expect(first.decision).toBe('ALLOW');
    expect(refused.decision).toBe('RATE_LIMIT');
    expect(refused.matched_rules?.map((m) => m.rule_name)).toEqual(['one_pay']);
    expect(refund.decision, 'the refused payment was counted in the org window').toBe('ALLOW');
    expect(refund.rate_limit?.current).toBe(2);
    expect(over.decision).toBe('RATE_LIMIT');
    expect(over.matched_rules?.map((m) => m.rule_name)).toEqual(['org_rate']);
  });
});
