/**
 * Row 140 (HTL-29): hiitl sends only over TLS, and only the credential it can read.
 *
 * Security, "TLS everywhere. No exceptions."; sync_engine.md section 8, loopback included; routes.md Validation Rules,
 * "`endpoint` is an `https` URL" and "The party that sends reads the `auth`". Design: the HTL-29 test design,
 * row 140, behaviors 1-4, and row 236, behavior 1. Mirrors python/hiitl/core/tests/test_row140.py: both read the URL
 * table in tests/conformance/transport/.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { RouteSchema } from '../../src/route-types.js';
import { RouteUnanswered, authHeaders, authRefusal, type RouteConfig } from '../../src/routing.js';
import { httpsRefusal } from '../../src/transport.js';

// One verdict per written value in both cores, from the one table both read (routes.md, read by its written form)
const TABLE = join(__dirname, '../../../../../tests/conformance/transport/case_001_written_urls.json');
const URLS = JSON.parse(readFileSync(TABLE, 'utf8')).urls as Array<[unknown, boolean]>;

describe('row 140: one check decides where hiitl sends', () => {
  it.each(URLS)('%j is sent to: %s', (url, sent) => {
    const refusal = httpsRefusal(url, 'server_url');
    if (sent) expect(refusal).toBeNull();
    else {
      expect(refusal).not.toBeNull();   // refused, then named
      expect(refusal).toMatch(new RegExp(`^server_url is ${JSON.stringify(url).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\.`));
      expect(refusal).toContain('https://<host>');
    }
  });

  it('a port of more digits than a number is read from is refused', () => {
    const url = `https://api.hiitl.com:${'1'.repeat(5000)}`;
    expect(httpsRefusal(url, 'server_url')?.startsWith(`server_url is ${JSON.stringify(url)}.`)).toBe(true);
  });

  it('a port is read by its value, however many zeros lead it', () => {
    // By its written form: the zeros that lead a port are not digits of its number, in both cores (HTL-29 review, 7)
    expect(httpsRefusal(`https://api.hiitl.com:${'0'.repeat(5000)}443`, 'server_url')).toBeNull();
  });
});

function route(endpoint = 'https://checks.example/v1', opts: { auth?: Record<string, unknown>; direction?: string } = {}) {
  const direction = opts.direction ?? 'bidirectional';
  const r: Record<string, unknown> = { name: 'content-check', version: 'v1.0.0', direction, timing: 'sync' };
  if (direction === 'inbound') r.inbound = { permissions: { can_signal: true } };
  else Object.assign(r, { endpoint, response_schema: { decision_options: ['approve', 'deny'] },
    sla: { timeout: '5s', timeout_action: 'fail_closed' } });
  if (opts.auth) r.auth = opts.auth;
  return r;
}

describe("row 140: a route's endpoint is https, loopback included", () => {
  it.each(['http://checks.example/v1', 'http://127.0.0.1:9000/v1', 'http://localhost/v1'])('%s', (endpoint) => {
    const parsed = RouteSchema.safeParse(route(endpoint));
    expect(parsed.success).toBe(false);
    expect(parsed.error!.issues.map((i) => i.message).join('\n')).toContain(`route 'content-check' endpoint is "${endpoint}"`);
    expect(RouteSchema.safeParse(route(endpoint.replace('http://', 'https://'))).success).toBe(true);
  });
});

const BEARER = { type: 'bearer_token', secret_ref: 'env:CHECKS_TOKEN' };

describe('row 140: the auth the SDK cannot send is named', () => {
  it.each([
    [{ type: 'hmac_sha256', secret_ref: 'env:CHECKS_TOKEN' }, { CHECKS_TOKEN: 's' }, '"hmac_sha256"'],
    [{ type: 'mtls', secret_ref: 'env:CHECKS_TOKEN' }, { CHECKS_TOKEN: 's' }, '"mtls"'],
    [{ type: 'oauth2', secret_ref: 'env:CHECKS_TOKEN' }, { CHECKS_TOKEN: 's' }, '"oauth2"'],
    [{ type: 'bearer_token', secret_ref: 'vault:secret/checks' }, {}, '"vault:secret/checks"'],
    [{ type: 'api_key', secret_ref: 'CHECKS_TOKEN' }, { CHECKS_TOKEN: 's' }, '"CHECKS_TOKEN"'],
    [{ type: 'api_key', secret_ref: 'env:' }, { '': 's' }, '"env:"'],
    [BEARER, {}, 'CHECKS_TOKEN, which is unset or empty'],
    [BEARER, { CHECKS_TOKEN: '' }, 'CHECKS_TOKEN, which is unset or empty'],
  ])('%j with %j', (auth, environ, names) => {
    const r = route(undefined, { auth }) as RouteConfig;
    const reason = authRefusal(r, environ);
    expect(reason).not.toBeNull();
    expect(reason).toMatch(/^route 'content-check' /);
    expect(reason).toContain(names);
    let thrown: unknown;
    try { authHeaders(r, environ); } catch (e) { thrown = e; }
    expect(thrown).toBeInstanceOf(RouteUnanswered);   // the ask is not sent without its credential, and says why
    expect((thrown as Error).message).toBe(reason);
  });

  it('an auth it can send, or none, or an inbound one is not refused', () => {
    expect(authRefusal(route(undefined, { auth: BEARER }) as RouteConfig, { CHECKS_TOKEN: 's' })).toBeNull();
    expect(authRefusal(route() as RouteConfig, {})).toBeNull();
    const inbound = route(undefined, { direction: 'inbound', auth: { type: 'hmac_sha256', secret_ref: 'vault:x' } });
    expect(authRefusal(inbound as RouteConfig, {})).toBeNull();   // what its sender presents
    expect(authRefusal(RouteSchema.parse(inbound) as RouteConfig, {})).toBeNull();
  });
});

describe('row 140: the header carries the secret and defaults to Authorization', () => {
  it.each([
    [{ type: 'bearer_token', secret_ref: 'env:CHECKS_TOKEN' }, { Authorization: 'Bearer s3' }],
    [{ type: 'api_key', secret_ref: 'env:CHECKS_TOKEN' }, { Authorization: 's3' }],
    [{ type: 'api_key', secret_ref: 'env:CHECKS_TOKEN', header: 'X-Api-Key' }, { 'X-Api-Key': 's3' }],
    [{ type: 'bearer_token', secret_ref: 'env:CHECKS_TOKEN', header: 'X-Token' }, { 'X-Token': 'Bearer s3' }],
  ])('%j', (auth, headers) => {
    const environ = { CHECKS_TOKEN: 's3' };
    expect(authHeaders(route(undefined, { auth }) as RouteConfig, environ)).toEqual(headers);
    expect(authHeaders(RouteSchema.parse(route(undefined, { auth })) as RouteConfig, environ)).toEqual(headers);
    expect(authHeaders(route() as RouteConfig, environ)).toEqual({});
  });
});
