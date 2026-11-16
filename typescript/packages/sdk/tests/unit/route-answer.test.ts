/**
 * The SDK asks a sync route and evaluates again with its answer (TICKET-046; policy_format.md 2.7; routes.md "A sync
 * route's answer re-enters evaluation"). Mirrors python/hiitl/sdk/tests/test_route_answer.py (E10, E11).
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';

const POLICY = {
  version: 'v1.0.0', description: 'The content_policy set', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'content_policy',
  rules: [
    { name: 'ask_content_check', priority: 500, conditions: { field: 'action', operator: 'equals', value: 'publish_post' },
      decision: 'ROUTE', reason_code: 'CONTENT_CHECK', route: 'content-check', description: 'Posts are checked' },
    { name: 'block_rejected', priority: 800,
      conditions: { field: 'external.content-check.verdict', operator: 'equals', value: 'rejected' },
      decision: 'BLOCK', reason_code: 'CONTENT_REJECTED', description: 'A rejected post does not publish' },
    { name: 'allow_otherwise', priority: 1, conditions: { field: 'action', operator: 'exists', value: true },
      decision: 'ALLOW', reason_code: 'ALLOWED', description: 'Everything else' },
  ],
};
const ROUTE = {
  name: 'content-check', version: 'v1.0.0', description: 'The content check', direction: 'bidirectional', timing: 'sync',
  purpose: ['assessment'], endpoint: 'https://checks.example/v1/content', protocol: 'http',
  auth: { type: 'bearer_token', header: 'Authorization', secret_ref: 'env:HIITL_TEST_CHECKS_TOKEN' },
  context: { fields: [{ field_path: 'parameters.body' }], include_policy_ref: true },
  response_schema: { decision_options: ['approve', 'deny'], required_fields: ['verdict'], optional_fields: ['reason'] },
  sla: { timeout: '5s', timeout_action: 'fail_closed' },
};

describe('the SDK asks a sync route (TICKET-046)', () => {
  let dir: string;
  let seen: Array<{ url: string; init: any }>;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hiitl-route-'));
    fs.writeFileSync(path.join(dir, 'policy.json'), JSON.stringify(POLICY));
    fs.mkdirSync(path.join(dir, 'routes'));
    fs.writeFileSync(path.join(dir, 'routes', 'content-check.json'), JSON.stringify(ROUTE));
    process.env.HIITL_TEST_CHECKS_TOKEN = 't0k';
    seen = [];
  });
  afterEach(() => {
    delete process.env.HIITL_TEST_CHECKS_TOKEN;
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const client = (answer: () => Response) => new HIITL({
    environment: 'dev', agent_id: 'poster', org_id: 'org_test000000000000000', mode: 'RESPECT_POLICY',
    policy_path: path.join(dir, 'policy.json'), routes_path: path.join(dir, 'routes'), audit_db_path: ':memory:',
    route_fetch: (async (url: any, init: any) => { seen.push({ url: String(url), init }); return answer(); }) as typeof fetch,
  });

  it('asks the route, its answer decides, and the decision carries it', async () => {
    const h = client(() => new Response(JSON.stringify({ verdict: 'rejected', reason: 'slur', score: 0.9 }), { status: 200 }));
    const d = await h.evaluate({ action: 'publish_post', parameters: { body: 'a slur' } });
    expect([d.decision, d.reason_codes]).toEqual(['BLOCK', ['CONTENT_REJECTED']]);
    expect(d.enrichment).toEqual({ 'content-check': { verdict: 'rejected', reason: 'slur' } });
    expect(d.routes?.map((r) => [r.route, r.outcome])).toEqual([['content-check', 'answered']]);
    expect(seen.length).toBe(1);
    expect(seen[0].url).toBe('https://checks.example/v1/content');
    expect(seen[0].init.headers.Authorization).toBe('Bearer t0k');
    expect(JSON.parse(seen[0].init.body)).toEqual({ route: 'content-check', rule: 'ask_content_check',
      action: 'publish_post', fields: { 'parameters.body': 'a slur' } });
  });

  it('fails closed when the route does not answer', async () => {
    const h = client(() => new Response('unavailable', { status: 503 }));
    const d = await h.evaluate({ action: 'publish_post', parameters: { body: 'hello' } });
    expect([d.decision, d.allowed, d.route_ref]).toEqual(['ROUTE', false, 'content-check']);
    expect(d.reason_codes).toEqual([POLICY.rules[0].reason_code, 'ROUTE_UNANSWERED']);
    expect(d.routes?.[0].error).toBe('the route answered 503');
  });

  it('a decision that asks no route stays synchronous', () => {
    const h = client(() => new Response('{}'));
    const d = h.evaluate({ action: 'read_feed' });
    expect(d instanceof Promise).toBe(false);
    expect((d as any).decision).toBe('ALLOW');
  });
});
