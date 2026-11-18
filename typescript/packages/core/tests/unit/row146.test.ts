/**
 * Row 146 (HTL-20), the rate-limit members in core: the counter state, the rule's own remediation, and the
 * remediation details that state a fact of the call, computed from the call.
 *
 * R-0008: "Decisions must include current counter state snapshot". R-0059: remediation lets the developer "refine and
 * proceed with the adjusted tool call". policy_format.md "Remediation on Rules" (the computed-details table) and
 * "Rate-limit rules". Design: the HTL-20 test design, row 146. Mirrors core/tests/test_row146.py.
 */

import { describe, it, expect } from 'vitest';
import { ZodError } from 'zod';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { counterState, limitExceeded, tightest } from '../../src/rate-limits.js';
import { ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';
import type { Envelope, PolicySet, RateLimitRule } from '../../src/types.js';

const STAMP = '2026-02-14T15:30:00.25Z';
const RESET_AT = new Date(Date.parse(STAMP) + 60_000);
const RATE_REMEDIATION = {
  type: 'rate_limit', message: 'Refunds are limited to 2 a minute per agent',
  suggestion: 'Queue the refund and retry after reset_at', details: { retry: 'after reset_at' },
};

const envelope = (action = 'refund', parameters: Record<string, unknown> = {}): Envelope => ({
  schema_version: ENVELOPE_SCHEMA_VERSION,
  org_id: 'org_test123456789012', environment: 'dev', agent_id: 'payments-agent',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row146', action, operation: 'execute',
  target: {}, parameters, timestamp: STAMP, signature: 'a'.repeat(64),
}) as unknown as Envelope;

const policy = (...rules: object[]): PolicySet =>
  ({ name: 'refund_policy', version: 'v1.0.0', description: 'The refund_policy set', scope: { org_id: 'org_test123456789012', environment: 'dev' }, rules }) as unknown as PolicySet;

const evaluate = (env: Envelope, p: PolicySet) => new PolicyEvaluator().evaluate(env, p);

const ALLOW_REFUNDS = {
  name: 'allow_refunds', description: 'Refunds are allowed', priority: 100,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
};
const LIMIT_REFUNDS = {
  name: 'limit_refunds', description: '2 refunds a minute per agent', priority: 600,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'RATE_LIMIT', reason_code: 'REFUND_RATE',
  rate_limit: { limit: 2, window_seconds: 60, scope: 'agent' }, remediation: RATE_REMEDIATION,
};

const windowRule = (name: string, limit: number): RateLimitRule => ({
  rule_name: name, policy_set: 'refund_policy', priority: 600, reason_code: 'RATE', limit, window_seconds: 60, scope: 'agent',
});

describe('row 146: the rate-limit members in core', () => {
  it('tightest is the least headroom first listed on a tie', () => {
    const wide = counterState(windowRule('wide', 10), 3, RESET_AT);
    const narrow = counterState(windowRule('narrow', 5), 3, RESET_AT);
    expect(tightest([wide, narrow])).toBe(narrow);
    const first = counterState(windowRule('first', 5), 3, RESET_AT);
    const second = counterState(windowRule('second', 4), 2, RESET_AT);
    expect(tightest([first, second])).toBe(first);
  });

  it('limit exceeded keeps the decision and names the rule', () => {
    const staged = {
      name: 'staged_block', description: 'A staged hold on refunds', priority: 500, lifecycle_stage: 'staged',
      conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'BLOCK', reason_code: 'REFUND_HOLD',
    };
    const decision = evaluate(envelope(), policy(LIMIT_REFUNDS, staged, ALLOW_REFUNDS));
    expect(decision.decision).toBe('ALLOW');
    expect(decision.staged_observations).toEqual([{
      rule_name: staged.name, policy_set: 'refund_policy', priority: staged.priority,
      would_be_decision: staged.decision, would_be_reason_codes: [staged.reason_code], would_be_binding: true,
    }]);
    const rule = decision.rate_limit_rules![0];
    const refused = limitExceeded(decision, rule, 2, RESET_AT);
    expect([refused.decision, refused.allowed, refused.reason_codes]).toEqual(['RATE_LIMIT', false, ['RATE_LIMIT_EXCEEDED']]);
    expect(refused.matched_rules?.map((m) => m.rule_name)).toEqual(['limit_refunds']);
    expect(refused.staged_observations).toEqual(decision.staged_observations);
    expect(refused.rate_limit_rules).toEqual(decision.rate_limit_rules);
    expect([refused.action_id, refused.policy_version]).toEqual([decision.action_id, decision.policy_version]);
    expect(refused.rate_limit).toEqual(counterState(rule, 2, RESET_AT));
    expect(refused.remediation).toBeDefined();
    const rem = refused.remediation!;
    expect([rem.type, rem.message, rem.suggestion]).toEqual(['rate_limit', RATE_REMEDIATION.message, RATE_REMEDIATION.suggestion]);
    expect(rem.details).toEqual({ retry: 'after reset_at', ...refused.rate_limit });
  });

  it('a windowed rule is listed with its remediation', () => {
    const [listed, ...rest] = evaluate(envelope(), policy(LIMIT_REFUNDS, ALLOW_REFUNDS)).rate_limit_rules ?? [];
    expect(rest).toEqual([]);
    expect([listed.rule_name, listed.reason_code]).toEqual(['limit_refunds', 'REFUND_RATE']);
    expect(listed.remediation).toEqual(RATE_REMEDIATION);
  });

  const blocked = (parameters: Record<string, unknown>, blockedFields: unknown) => {
    const rule = {
      name: 'restrict_fields', description: 'Identity numbers are not exported', priority: 900,
      conditions: { field: 'action', operator: 'equals', value: 'export' }, decision: 'BLOCK', reason_code: 'FIELD_RESTRICTED',
      remediation: {
        type: 'field_restriction', message: 'Identity numbers are not exported', suggestion: 'Drop the blocked fields and retry',
        details: { blocked_fields: blockedFields },
      },
    };
    return evaluate(envelope('export', parameters), policy(rule)).remediation?.details;
  };
  const COMPUTED = { ref: 'parameters.fields', filter: ['dob', 'ssn', 'tax_id'] };

  const computedCases: [string, Record<string, unknown>, unknown, object][] = [
    ['order-and-once', { fields: ['name', 'ssn', 'email', 'dob', 'ssn'] }, COMPUTED,
      { blocked_fields: ['ssn', 'dob'], field_ref: 'parameters.fields' }],
    ['single-value', { fields: 'ssn' }, COMPUTED, { blocked_fields: ['ssn'], field_ref: 'parameters.fields' }],
    ['nothing-at-ref', {}, COMPUTED, { blocked_fields: [], field_ref: 'parameters.fields' }],
    ['list-as-written', { fields: ['ssn'] }, ['ssn', 'dob'], { blocked_fields: ['ssn', 'dob'] }],
  ];
  for (const [id, parameters, written, expected] of computedCases) {
    it(`blocked fields are the calls values in the filter (${id})`, () => {
      expect(blocked(parameters, written)).toEqual(expected);
    });
  }

  const shapeCases: [string, unknown, string][] = [
    ['string', 'ssn', 'a string'],
    ['no-filter', { ref: 'parameters.fields' }, "an object with keys ['ref']"],
    ['empty-ref', { ref: '', filter: ['ssn'] }, "an object with keys ['filter', 'ref']"],
    ['filter-not-a-list', { ref: 'parameters.fields', filter: 'ssn' }, "an object with keys ['filter', 'ref']"],
  ];
  for (const [id, written, shape] of shapeCases) {
    it(`a blocked fields shape outside the two is refused naming it (${id})`, () => {
      let refused: unknown;
      try {
        blocked({}, written);
      } catch (e) {
        refused = e;
      }
      expect(refused).toBeInstanceOf(ZodError);
      const message = (refused as ZodError).message;
      expect(message).toContain(`remediation.details.blocked_fields is ${shape}.`);
      expect(message).toContain('a list of field names');
      expect(message).toContain('{ref, filter}');
    });
  }

  const threshold = (parameters: Record<string, unknown>) => {
    const rule = {
      name: 'refund_ceiling', description: 'Refunds above 10000 are blocked', priority: 900,
      conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'BLOCK', reason_code: 'REFUND_CEILING',
      remediation: {
        type: 'threshold', message: 'Refunds above 10000 are blocked', suggestion: 'Split the refund',
        details: { field: 'parameters.amount', limit: 10000, current_value: 0 },
      },
    };
    return evaluate(envelope('refund', parameters), policy(rule)).remediation?.details;
  };

  it('threshold current value is the calls value', () => {
    expect(threshold({ amount: 12500 })).toEqual({ field: 'parameters.amount', limit: 10000, current_value: 12500 });
    expect(threshold({})).toEqual({ field: 'parameters.amount', limit: 10000 });
  });

  it('temporal current time is the calls timestamp', () => {
    const rule = {
      name: 'refund_hours', description: 'Refunds wait for business hours', priority: 900,
      conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'BLOCK', reason_code: 'OUTSIDE_HOURS',
      remediation: {
        type: 'temporal', message: 'Refunds run in business hours', suggestion: 'Retry at 09:00',
        details: { current_time: "the author's guess" },
      },
    };
    expect(evaluate(envelope(), policy(rule)).remediation?.details).toEqual({ current_time: '2026-02-14T15:30:00.250Z' });
  });
});
