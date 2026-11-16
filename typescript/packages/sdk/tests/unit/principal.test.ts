/**
 * A7 on the TypeScript SDK (envelope_schema.json
 * `principal`): the principal is set only by the configured verifier from a
 * token passed to evaluate(); a token with no verifier, or on the hosted path
 * (not built), is a configuration error; a rejected token leaves no principal,
 * so an identity gate blocks. Mirrors the Python cells.
 */

import { describe, it, expect, vi } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import type { Decision } from '@hiitl/core';

const GATE = {
  name: 'p',
  version: 'v1.0.0',
  description: 'The p set',
  scope: { org_id: 'org_mycompany123456789', environment: 'dev' },
  rules: [
    { name: 'verified_only', description: 'd', priority: 900, decision: 'BLOCK', reason_code: 'UNVERIFIED',
      conditions: { none_of: [{ field: 'principal.sub', operator: 'exists', value: true }] } },
    { name: 'refunds_scope', description: 'd', priority: 800, decision: 'BLOCK', reason_code: 'NO_SCOPE',
      conditions: { none_of: [{ field: 'principal.scopes', operator: 'contains', value: 'refunds:write' }] } },
    { name: 'allow', description: 'd', priority: 1, decision: 'ALLOW', reason_code: 'OK',
      conditions: { field: 'action', operator: 'exists', value: true } },
  ],
};

const verifier = (token: string) => {
  if (token !== 'good') throw new Error('bad signature');
  return { sub: 'user_7', scope: 'refunds:write read', iss: 'https://idp', aud: 'https://api' };
};

function client(withVerifier: boolean): HIITL {
  const dir = mkdtempSync(join(tmpdir(), 'hiitl-principal-'));
  const policyPath = join(dir, 'policy.json');
  writeFileSync(policyPath, JSON.stringify(GATE));
  return new HIITL({
    policy_path: policyPath,
    mode: 'RESPECT_POLICY',
    audit_db_path: join(dir, 'a.db'),
    ...(withVerifier ? { principal_verifier: verifier } : {}),
  });
}

describe('verified principal (A7)', () => {
  it('a verified token sets the principal and passes the gate', () => {
    const d = client(true).evaluate({ action: 'refund', principal_token: 'good' }) as Decision;
    expect(d.decision).toBe('ALLOW');
  });

  it('no token means no principal; the gate blocks', () => {
    const d = client(true).evaluate({ action: 'refund' }) as Decision;
    expect(d.decision).toBe('BLOCK');
    expect(d.reason_codes).toEqual(['UNVERIFIED']);
  });

  it('a rejected token leaves no principal', () => {
    const d = client(true).evaluate({ action: 'refund', principal_token: 'forged' }) as Decision;
    expect(d.reason_codes).toEqual(['UNVERIFIED']);
  });

  it('a token without a verifier is a configuration error', () => {
    expect(() => client(false).evaluate({ action: 'refund', principal_token: 'good' })).toThrow(ConfigurationError);
  });

  it('the hosted path forwards a principal token as its header, never in the body', async () => {
    let seen: { headers: Record<string, string>; body: Record<string, unknown> } | undefined;
    const fetchStub = vi.fn(async (_url: string, init: { headers: Record<string, string>; body: string }) => {
      seen = { headers: init.headers, body: JSON.parse(init.body) };
      return new Response(JSON.stringify({ action_id: 'act_x', decision: 'ALLOW', allowed: true,
        reason_codes: ['OK'], policy_version: '1', timing: { total_ms: 1 } }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchStub);
    try {
      const h = new HIITL({
        api_key: 'test-api-key-12345', server_url: 'https://api.example.invalid', evaluation: 'remote', environment: 'dev', agent_id: 'a',
        org_id: 'org_mycompany123456789', signature_key: 's'.repeat(32), audit_db_path: ':memory:',
      });
      await h.evaluate({ action: 'refund', principal_token: 'tok-123' });
      expect(seen?.headers['X-Hiitl-Principal-Token']).toBe('tok-123');
      expect(Object.keys(seen?.headers ?? {}).map((name) => name.toLowerCase())).not.toContain('x-hiitl-signature-version');
      expect(seen?.body).not.toHaveProperty('principal');
      expect(seen?.body).not.toHaveProperty('principal_token');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
