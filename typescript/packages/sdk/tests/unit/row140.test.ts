/**
 * Row 140 (HTL-29): the SDK sends only over TLS, and only the credential it can read.
 *
 * routes.md Validation Rules, "`endpoint` is an `https` URL" and "The party that sends reads the `auth`";
 * sync_engine.md section 8, a `server_url` that is not https "is refused when the client is constructed, naming it".
 * Design: the HTL-29 test design, row 140, behaviors 5-9. Mirrors python/hiitl/sdk/tests/test_row140.py.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import { DEFAULT_SERVER_URL, HostedModeConfigSchema, createHostedConfig } from '../../src/config.js';
import { ConfigurationError, RouteLoadError, ServerError, SyncError } from '../../src/exceptions.js';
import { HostedClient } from '../../src/http-client.js';
import { RouteLoader } from '../../src/route-loader.js';
import { SyncClient } from '../../src/sync-client.js';

const ORG = 'org_test000000000000000';
const KEY = 'sk_test_1234567890abcdef';
const POLICY = {
  version: 'v1.0.0', description: 'Refunds are checked before they are paid', name: 'refund_policy',
  scope: { org_id: ORG, environment: 'dev' },
  rules: [
    { name: 'ask_refund_check', priority: 500, conditions: { field: 'action', operator: 'equals', value: 'issue_refund' },
      decision: 'ROUTE', reason_code: 'REFUND_CHECK', route: 'refund-check', description: 'Refunds are checked' },
    { name: 'allow_otherwise', priority: 1, conditions: { field: 'action', operator: 'exists', value: true },
      decision: 'ALLOW', reason_code: 'ALLOWED', description: 'Everything else' },
  ],
};

function route(over: Record<string, unknown> = {}) {
  return {
    name: 'refund-check', version: 'v1.0.0', direction: 'bidirectional', timing: 'sync',
    endpoint: 'https://risk.example/v1/refunds',
    auth: { type: 'bearer_token', secret_ref: 'env:HIITL_TEST_RISK_TOKEN' },
    response_schema: { decision_options: ['approve', 'deny'], required_fields: ['verdict'] },
    sla: { timeout: '5s', timeout_action: 'fail_closed' },
    ...over,
  };
}

const SERVER_VARIABLES = ['HIITL_SERVER_URL', 'HIITL_API_KEY', 'HIITL_EVALUATION', 'HIITL_SIGNATURE_KEY'];
let dir: string;
let saved: Record<string, string | undefined>;
let seen: Array<{ url: string; init: any }>;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hiitl-row140-'));
  fs.writeFileSync(path.join(dir, 'policy.json'), JSON.stringify(POLICY));
  fs.mkdirSync(path.join(dir, 'routes'));
  saved = Object.fromEntries([...SERVER_VARIABLES, 'HIITL_TEST_RISK_TOKEN', 'HIITL_TEST_UNSET_TOKEN']
    .map((name) => [name, process.env[name]]));
  for (const name of [...SERVER_VARIABLES, 'HIITL_TEST_UNSET_TOKEN']) delete process.env[name];
  process.env.HIITL_TEST_RISK_TOKEN = 'r1sk';
  seen = [];
});
afterEach(() => {
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
  fs.rmSync(dir, { recursive: true, force: true });
  vi.restoreAllMocks();
});

function write(r: Record<string, unknown>): string {
  const file = path.join(dir, 'routes', `${r.name}.json`);
  fs.writeFileSync(file, JSON.stringify(r));
  return file;
}

const client = (answer = () => new Response(JSON.stringify({ verdict: 'approve' }), { status: 200 })) => new HIITL({
  environment: 'dev', agent_id: 'refunder', org_id: ORG, mode: 'RESPECT_POLICY',
  policy_path: path.join(dir, 'policy.json'), routes_path: path.join(dir, 'routes'), audit_db_path: ':memory:',
  route_fetch: (async (url: any, init: any) => { seen.push({ url: String(url), init }); return answer(); }) as typeof fetch,
});

const REFUSED: Array<[Record<string, unknown>, string]> = [
  [{ auth: { type: 'hmac_sha256', secret_ref: 'env:HIITL_TEST_RISK_TOKEN' } }, '"hmac_sha256"'],
  [{ auth: { type: 'bearer_token', secret_ref: 'vault:risk/token' } }, '"vault:risk/token"'],
  [{ auth: { type: 'api_key', secret_ref: 'env:HIITL_TEST_UNSET_TOKEN' } }, 'HIITL_TEST_UNSET_TOKEN, which is unset'],
  [{ endpoint: 'http://127.0.0.1:9000/v1/refunds' }, '"http://127.0.0.1:9000/v1/refunds"'],
];

describe('row 140: a route the SDK cannot send is refused at load', () => {
  it.each(REFUSED)('%j', (over, cause) => {
    const file = write(route(over));
    let thrown: unknown;
    try { new RouteLoader(path.join(dir, 'routes')).get('refund-check'); } catch (e) { thrown = e; }
    expect(thrown).toBeInstanceOf(RouteLoadError);
    expect((thrown as Error).message).toContain(file);
    expect((thrown as Error).message).toContain(cause);
  });

  it("an inbound route's auth is not read at load", () => {
    write({ name: 'risk-signals', version: 'v1.0.0', direction: 'inbound', timing: 'async',
      auth: { type: 'hmac_sha256', secret_ref: 'vault:risk/signing' }, inbound: { permissions: { can_signal: true } } });
    expect(new RouteLoader(path.join(dir, 'routes')).get('risk-signals')!.name).toBe('risk-signals');
  });

  it.each(REFUSED)('through evaluate, %j fails closed and sends nothing', async (over, cause) => {
    write(route(over));
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
    const d = await client().evaluate({ action: 'issue_refund', parameters: { amount: 120 } });
    expect([d.decision, d.allowed, d.reason_codes]).toEqual(['POLICY_ERROR', false, ['POLICY_EVALUATION_FAILED']]);
    expect(seen).toEqual([]);   // the route is not asked
    expect(logged.mock.calls.flat().join('\n')).toContain(cause);   // the log names the cause
  });
});

describe('row 140: the ask sends only the credential its route declares', () => {
  it('an auth unsendable at the ask is unanswered, not sent bare', async () => {
    write(route());
    const h = client();
    expect((await h.evaluate({ action: 'issue_refund', parameters: { amount: 120 } })).decision).toBe('ALLOW');
    expect(seen[0].init.headers.Authorization).toBe('Bearer r1sk');
    delete process.env.HIITL_TEST_RISK_TOKEN;
    const d = await h.evaluate({ action: 'issue_refund', parameters: { amount: 120 } });
    expect([d.decision, d.allowed, d.route_ref]).toEqual(['ROUTE', false, 'refund-check']);
    expect(d.reason_codes).toContain('ROUTE_UNANSWERED');
    expect(d.routes?.[0].error).toContain('HIITL_TEST_RISK_TOKEN');
    expect(seen.length).toBe(1);   // nothing is sent without the credential its route declares
  });

  it('api_key defaults to the Authorization header through a real ask', async () => {
    write(route({ auth: { type: 'api_key', secret_ref: 'env:HIITL_TEST_RISK_TOKEN' } }));
    expect((await client().evaluate({ action: 'issue_refund', parameters: { amount: 120 } })).decision).toBe('ALLOW');
    expect(seen.length).toBe(1);
    expect(seen[0].init.headers.Authorization).toBe('r1sk');
    expect(seen[0].init.headers['X-Api-Key']).toBeUndefined();
  });
});

const HTTP = ['http://api.hiitl.example', 'http://127.0.0.1:8000', 'http://localhost:8000'];
const HOSTED = { environment: 'dev', agent_id: 'a', org_id: ORG, api_key: KEY } as const;

function refused(build: () => unknown): string {
  try { build(); } catch (e) { expect(e).toBeInstanceOf(ConfigurationError); return (e as Error).message; }
  return expect.unreachable('not refused');
}

describe('row 140: every server_url that carries the key is https', () => {
  it.each(HTTP)('%s', (url) => {
    const named = `server_url (HIITL_SERVER_URL) is ${JSON.stringify(url)}`;
    const parsed = HostedModeConfigSchema.safeParse({ ...HOSTED, server_url: url });
    expect(parsed.success).toBe(false);
    expect(parsed.error!.issues.map((i) => i.message).join('\n')).toContain(named);
    expect(refused(() => new HIITL({ api_key: KEY, server_url: url, audit_db_path: ':memory:' }))).toContain(named);
    expect(refused(() => new HIITL({ api_key: KEY, server_url: url, evaluation: 'remote', signature_key: 's'.repeat(32),
      audit_db_path: ':memory:' } as any))).toContain(named);
    expect(refused(() => new HIITL({ server_url: url, audit_db_path: ':memory:' }))).toContain(named);   // any mode
    expect(refused(() => new SyncClient({ server_url: url, api_key: KEY, org_id: ORG, environment: 'dev' })))
      .toContain(`server_url is ${JSON.stringify(url)}`);
    expect(refused(() => new HostedClient({ ...createHostedConfig({ ...HOSTED, server_url: 'https://x.example' }),
      server_url: url }))).toContain(`server_url is ${JSON.stringify(url)}`);
    process.env.HIITL_SERVER_URL = url;
    expect(refused(() => new HIITL({ api_key: KEY, audit_db_path: ':memory:' }))).toContain(named);
    expect(refused(() => new HIITL({ audit_db_path: ':memory:' }))).toContain(named);
  });

  it('an https server_url passes and its trailing slash is stripped', () => {
    expect(createHostedConfig({ ...HOSTED, server_url: 'https://127.0.0.1:8443/' }).server_url)
      .toBe('https://127.0.0.1:8443');
    expect(DEFAULT_SERVER_URL.startsWith('https://')).toBe(true);   // the default is https
  });
});

// A redirect names a URL the check did not read, so no sender follows one (sync_engine.md section 8): the sender's
// https URL is served by a local server that answers 307 to a second, plain-http one. The second server must hear
// nothing, and the sender reads the 307 as it reads any answer that is not a success.
async function listen(handler: http.RequestListener): Promise<[http.Server, string]> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return [server, `http://127.0.0.1:${(server.address() as AddressInfo).port}`];
}

async function redirecting(answer: unknown) {
  const heard: string[] = [];
  const [onward, onwardUrl] = await listen((req, res) => {
    heard.push(String(req.url));
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(answer));
  });
  const [first, firstUrl] = await listen((req, res) => {
    res.writeHead(307, { location: `${onwardUrl}${req.url}` }).end();
  });
  const asked: string[] = [];
  const real = globalThis.fetch;
  const served = (async (url: any, init?: RequestInit) => {
    asked.push(String(url));
    return real(String(url).replace(/^https:\/\/[^/]+/, firstUrl), init);
  }) as typeof fetch;
  const close = () => { first.close(); onward.close(); };
  return { heard, asked, served, close };
}

async function outcome(run: () => Promise<unknown>): Promise<[unknown, unknown]> {
  try { return [await run(), undefined]; } catch (e) { return [undefined, e]; }
}

describe('row 140: no sender follows a redirect', () => {
  it('the hosted call reads a 307 as the service answer', async () => {
    const r = await redirecting({ decision: 'ALLOW', allowed: true, reason_codes: [], action_id: 'act_x' });
    vi.stubGlobal('fetch', r.served);
    try {
      const h = new HIITL({ ...HOSTED, server_url: 'https://ecp.example', evaluation: 'remote',
        signature_key: 's'.repeat(32), audit_db_path: ':memory:' } as any);
      const [, thrown] = await outcome(() => h.evaluate({ action: 'issue_refund', parameters: { amount: 120 } }));
      expect(r.heard).toEqual([]);   // the redirect's URL hears nothing
      expect(r.asked).toEqual(['https://ecp.example/v1/evaluate']);
      expect(thrown).toBeInstanceOf(ServerError);
      expect((thrown as ServerError).status_code).toBe(307);
    } finally { vi.unstubAllGlobals(); r.close(); }
  });

  it('the sync client reads a 307 as the service answer', async () => {
    const r = await redirecting({ kill_switches: [], policy_set: null, server_time: '' });
    try {
      const sync = new SyncClient({ server_url: 'https://ecp.example', api_key: KEY, org_id: ORG, environment: 'dev',
        max_retries: 0, fetchImpl: r.served });
      const [, thrown] = await outcome(() => sync.pollKillSwitches());
      expect(r.heard).toEqual([]);
      expect(r.asked).toEqual(['https://ecp.example/v1/sync/kill-switches']);
      expect(thrown).toBeInstanceOf(SyncError);
      expect((thrown as Error).message).toContain('status 307');
    } finally { r.close(); }
  });

  it("the route ask reads a 307 as the route's answer", async () => {
    write(route());
    const r = await redirecting({ verdict: 'approve' });
    try {
      const h = new HIITL({
        environment: 'dev', agent_id: 'refunder', org_id: ORG, mode: 'RESPECT_POLICY',
        policy_path: path.join(dir, 'policy.json'), routes_path: path.join(dir, 'routes'), audit_db_path: ':memory:',
        route_fetch: r.served,
      });
      const d = await h.evaluate({ action: 'issue_refund', parameters: { amount: 120 } });
      expect(r.heard).toEqual([]);
      expect(r.asked).toEqual(['https://risk.example/v1/refunds']);
      expect([d.decision, d.allowed, d.route_ref]).toEqual(['ROUTE', false, 'refund-check']);
      expect(d.reason_codes).toContain('ROUTE_UNANSWERED');
      expect(d.routes?.[0].error).toContain('the route answered 307');
    } finally { r.close(); }
  });
});
