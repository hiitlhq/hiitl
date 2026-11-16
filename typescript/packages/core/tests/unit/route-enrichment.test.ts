/**
 * A sync route's answer re-enters evaluation (policy_format.md 2.7; TICKET-046). Mirrors
 * python/hiitl/core/tests/test_route_enrichment.py (E6–E10). Design: TEST_DESIGN_route_enrichment.md.
 */
import { describe, it, expect } from 'vitest';
import { PolicyEvaluator, type Enrichment } from '../../src/evaluator.js';
import * as routing from '../../src/routing.js';
import { ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const env = (extra: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION,
  org_id: 'org_1234567890abcdef', environment: 'prod', agent_id: 'agent_ops_bot',
  action_id: 'act_route0000000000000000000', timestamp: '2026-10-11T10:00:00Z', operation: 'execute',
  parameters: { body: 'hello', channel: 'public' }, idempotency_key: 'idem_route', target: {},
  signature: '0'.repeat(64), action: 'publish_post', ...extra,
});
const rule = (name: string, priority: number, conditions: any, decision: string, reason_code: string, route?: string) =>
  ({ name, priority, conditions, decision, reason_code, description: `Rule: ${name}`, ...(route ? { route } : {}) });
const ASK = rule('ask_content_check', 500, { field: 'action', operator: 'equals', value: 'publish_post' }, 'ROUTE', 'CONTENT_CHECK', 'content-check');
const READ = rule('block_rejected', 800, { field: 'external.content-check.verdict', operator: 'equals', value: 'rejected' }, 'BLOCK', 'CONTENT_REJECTED');
const ALLOW = rule('allow_otherwise', 1, { field: 'action', operator: 'exists', value: true }, 'ALLOW', 'ALLOWED');
const POLICY = { version: 'v1.0.0', description: 'The p set', scope: { org_id: 'org_1234567890abcdef', environment: 'prod' }, name: 'p', rules: [ASK, READ, ALLOW] };

const route = (o: { required?: string[]; optional?: string[]; timeout_action?: string; fields?: string[];
  include_policy_ref?: boolean; auth?: any; direction?: string } = {}) => ({
  name: 'content-check', direction: o.direction ?? 'bidirectional', timing: 'sync', endpoint: 'https://checks.example/c',
  response_schema: { decision_options: ['accept', 'reject'], required_fields: o.required ?? ['verdict'],
    optional_fields: o.optional ?? ['reason'] },
  sla: { timeout: '5s', timeout_action: o.timeout_action ?? 'fail_closed' },
  context: { include_policy_ref: o.include_policy_ref ?? true,
    ...(o.fields ? { fields: o.fields.map((f) => ({ field_path: f })) } : {}) },
  ...(o.auth ? { auth: o.auth } : {}),
});

async function run(answer: unknown, r: any, policy: any = POLICY) {
  const ev = new PolicyEvaluator();
  const envelope = env();
  const asked: Array<[string, any]> = [];
  const d = await routing.evaluateWithRoutes(
    (e: Enrichment | null) => ev.evaluate(envelope, policy, 'RESPECT_POLICY', e),
    (n) => (n === r.name ? r : null),
    async (rt, p) => { asked.push([rt.name, p]); if (answer instanceof Error) throw answer; return answer; },
    envelope);
  return { d, asked };
}

describe('route enrichment (TICKET-046)', () => {
  it('E6: a caller\'s external key is not the enrichment context', () => {
    // The envelope refuses the key, naming it (R-0872, row 147): never read by a rule, never silently dropped.
    expect(() => new PolicyEvaluator().evaluate(env({ external: { 'content-check': { verdict: 'rejected' } } }),
      { version: 'v1.0.0', description: 'E6: a caller\'s external key is not the enrichment context', scope: { org_id: 'org_1234567890abcdef', environment: 'prod' }, name: 'p', rules: [READ, ALLOW] })).toThrow(/unrecognized_keys[\s\S]*"external"/);
  });

  it('E7: the route is asked once and its answer decides', async () => {
    const { d, asked } = await run({ verdict: 'rejected', reason: 'slur' }, route());
    expect(asked.map(([n]) => n)).toEqual(['content-check']);
    expect([d.decision, d.reason_codes]).toEqual(['BLOCK', ['CONTENT_REJECTED']]);
    expect(d.enrichment).toEqual({ 'content-check': { verdict: 'rejected', reason: 'slur' } });
    expect(d.routes).toEqual([{ rule_name: 'ask_content_check', route: 'content-check', outcome: 'answered', fields: ['verdict', 'reason'] }]);
  });

  it('E7: an answer no rule reads does not ask again; a non-sync route asks nothing', async () => {
    let r = await run({ verdict: 'accepted' }, route());
    expect([r.asked.length, r.d.decision]).toEqual([1, 'ALLOW']);
    r = await run({}, route({ direction: 'outbound' }));
    expect([r.asked.length, r.d.decision, r.d.route_ref, r.d.routes]).toEqual([0, 'ROUTE', 'content-check', undefined]);
  });

  it('E8: only declared fields re-enter; a missing required field is no answer', async () => {
    let r = await run({ verdict: 'accepted', internal_score: 0.2 }, route());
    expect(r.d.enrichment).toEqual({ 'content-check': { verdict: 'accepted' } });
    r = await run({ reason: 'n/a' }, route());
    expect([r.d.decision, r.d.allowed]).toEqual(['ROUTE', false]);
    expect(r.d.reason_codes).toContain(routing.UNANSWERED);
    expect(r.d.routes?.[0].outcome).toBe('unanswered');
    expect(r.d.routes?.[0].error).toContain('verdict');
    expect(r.d.enrichment).toBeUndefined();
  });

  it.each(['fail_closed', 'escalate', 'extend'])('E9: an unanswered route fails closed (%s)', async (action) => {
    const { d } = await run(new routing.RouteUnanswered('timed out after 5s'), route({ timeout_action: action }));
    expect([d.decision, d.allowed, d.route_ref]).toEqual(['ROUTE', false, 'content-check']);
    expect(d.reason_codes).toContain(routing.UNANSWERED);
    expect([d.routes?.[0].outcome, d.routes?.[0].error]).toEqual(['unanswered', 'timed out after 5s']);
  });

  it('E9: fail open evaluates again with nothing and other rules still bind', async () => {
    const hold = rule('hold_public_posts', 300, { field: 'parameters.channel', operator: 'equals', value: 'public' },
      'REQUIRE_APPROVAL', 'PUBLIC_POST_HELD');
    const { d, asked } = await run(new routing.RouteUnanswered('503'), route({ timeout_action: 'fail_open' }),
      { version: 'v1.0.0', description: 'E9: fail open evaluates again with nothing and other rules still bind', scope: { org_id: 'org_1234567890abcdef', environment: 'prod' }, name: 'p', rules: [ASK, READ, hold, ALLOW] });
    expect(asked.length).toBe(1);
    expect(d.enrichment).toEqual({ 'content-check': {} });
    expect(d.routes?.[0].outcome).toBe('failed_open');
    expect([d.decision, d.reason_codes]).toEqual(['REQUIRE_APPROVAL', ['PUBLIC_POST_HELD']]);
  });

  it('E10: the payload carries the route\'s context fields or the envelope', async () => {
    let r = await run({ verdict: 'accepted' }, route({ fields: ['parameters.body', 'action'] }));
    expect(r.asked[0][1]).toEqual({ route: 'content-check', rule: 'ask_content_check', action: 'publish_post',
      fields: { 'parameters.body': 'hello', action: 'publish_post' } });
    r = await run({ verdict: 'accepted' }, route({ include_policy_ref: false }));
    expect('rule' in r.asked[0][1]).toBe(false);
    expect(r.asked[0][1].fields.parameters).toEqual({ body: 'hello', channel: 'public' });
  });

  it('E10: auth reads the secret ref; the SLA timeout in seconds', () => {
    expect(routing.authHeaders(route({ auth: { type: 'bearer_token', header: 'Authorization', secret_ref: 'env:CHECKS_TOKEN' } }),
      { CHECKS_TOKEN: 't0k' })).toEqual({ Authorization: 'Bearer t0k' });
    expect(routing.authHeaders(route({ auth: { type: 'api_key', header: 'X-Api-Key', secret_ref: 'env:K' } }), { K: 'k' }))
      .toEqual({ 'X-Api-Key': 'k' });
    expect(routing.authHeaders(route(), {})).toEqual({});
    expect(['30s', '2m', '1h'].map((t) => routing.timeoutSeconds({ sla: { timeout: t } }))).toEqual([30, 120, 3600]);
  });
});
