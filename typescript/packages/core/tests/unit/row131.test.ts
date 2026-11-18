/**
 * Row 131 (HTL-29): a kill switch is live when the evaluator binds it; an outbound route's fields are its source's.
 *
 * policy_format.md "A version identifies what evaluates" and "Uncalibrated bounds"; sync_engine.md 2.4 "kill switches
 * always return the full active set"; routes.md "filters" and "Outbound routes and filters". Design: the HTL-29 test
 * design, row 131, behaviors 1, 12 and 13. Mirrors python/hiitl/core/tests/test_row131.py.
 */

import { describe, expect, it } from 'vitest';
import { liveKillSwitches } from '../../src/evaluator.js';
import { RouteSchema } from '../../src/route-types.js';
import { DecisionTypeSchema, PolicySetSchema, SensitivitySchema } from '../../src/types.js';

const ON_PAY = { field: 'action', operator: 'equals', value: 'pay' };

function rule(name: string, decision = 'KILL_SWITCH', stage = 'active', conditions: unknown = ON_PAY) {
  return { name, description: name, priority: 100, conditions, decision,
    reason_code: name.toUpperCase().replace(/-/g, '_'), lifecycle_stage: stage };
}

function policySet(...rules: unknown[]) {
  return PolicySetSchema.parse({ name: 'payments', version: 'v1.0.0', description: 'payments',
    scope: { org_id: 'org_test000000000000', environment: 'dev' }, rules });
}

describe('row 131: the core reads the live switches', () => {
  it('a switch is live when the evaluator binds it', () => {
    const placeholder = { all_of: [ON_PAY, { field: 'parameters.amount', operator: 'greater_than',
      value: { $uncalibrated: 'the distribution of parameters.amount on pay' } }] };
    const policy = policySet(rule('halt-refunds'), rule('halt-disabled', 'KILL_SWITCH', 'disabled'),
      rule('halt-staged', 'KILL_SWITCH', 'staged'), rule('halt-uncalibrated', 'KILL_SWITCH', 'active', placeholder),
      rule('block-pay', 'BLOCK'), rule('halt-payments'));
    expect(liveKillSwitches(policy)).toEqual(['halt-payments', 'halt-refunds']);   // active, no placeholder, sorted
  });

  it('a set with no switch makes none live', () => {
    expect(liveKillSwitches(policySet(rule('block-pay', 'BLOCK')))).toEqual([]);
  });
});

function outbound(fields: Record<string, unknown> = {}) {
  return { name: 'audit-sink', version: 'v1.0.0', direction: 'outbound', timing: 'async',
    endpoint: 'https://sink.example/v1', ...fields };
}

function messages(route: unknown): string {
  const parsed = RouteSchema.safeParse(route);
  expect(parsed.success).toBe(false);
  return parsed.error!.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('\n');
}

describe("row 131: an outbound route's filter values are their source's", () => {
  it.each([
    ['decisions', 'DENY', DecisionTypeSchema.options],
    ['sensitivity', 'secret', SensitivitySchema.options],
  ] as Array<[string, string, readonly string[]]>)('a %s value outside its source is refused naming the allowed ones',
    (key, value, allowed) => {
      const message = messages(outbound({ filters: { [key]: [value] } }));
      expect(message).toContain(`filters.${key}.0`);
      expect(message).toContain(`'${value}'`);
      for (const v of allowed) expect(message).toContain(`'${v}'`);
    });

  it('a filter naming tools is refused, naming actions', () => {
    const message = messages(outbound({ filters: { tools: ['pay'] } }));
    expect(message).toContain('filters.tools is a key the route format does not define: it was renamed filters.actions, ' +
      'with no alias. Write filters.actions');
    expect(RouteSchema.parse(outbound({ filters: { actions: ['pay'] } })).filters?.actions).toEqual(['pay']);
  });

  it('the values the old lists did not hold are taken', () => {
    const route = RouteSchema.parse(outbound({ filters: { decisions: ['OBSERVE'], sensitivity: ['pii'] } }));
    expect([route.filters?.decisions, route.filters?.sensitivity]).toEqual([['OBSERVE'], ['pii']]);
  });
});

describe('row 131: context on an outbound route', () => {
  it('is refused naming why', () => {
    const message = messages(outbound({ context: { include_policy_ref: true } }));
    expect(message).toContain("outbound routes must not have 'context'");
    expect(message).toContain('sends the record');
  });

  it('is taken on a bidirectional route', () => {
    const route = RouteSchema.parse({ name: 'finance-review', version: 'v1.0.0', direction: 'bidirectional',
      timing: 'sync', endpoint: 'https://review.example/v1', context: { include_policy_ref: true },
      response_schema: { decision_options: ['approve', 'deny'] }, sla: { timeout: '5s', timeout_action: 'fail_closed' } });
    expect(route.context?.include_policy_ref).toBe(true);
  });
});
