/**
 * `requested_scopes` on the TypeScript SDK's evaluate() (TICKET-138; §9.15:
 * a field the SDK's evaluate() has no argument for is hiitl's own
 * requirement). The argument reaches the evaluated envelope, the audit record
 * and its content hash, and the hosted request body. Mirrors the Python cells.
 */

import { describe, it, expect, vi } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { auditContentHash } from '@hiitl/core';
import type { Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { AuditLogger } from '../../src/audit.js';

// at-0009's generated gate, as generate renders it (requested_scopes ⊄ principal.scopes → BLOCK)
const GATE = {
  name: 'p',
  version: 'v1.0.0',
  description: 'The p set',
  scope: { org_id: 'org_mycompany123456789', environment: 'dev' },
  rules: [
    { name: 'gen-at-0009-system', description: 'd', priority: 900, decision: 'BLOCK', reason_code: 'AT_0009_BLOCK',
      conditions: { all_of: [
        { field: 'action', operator: 'exists', value: true },
        { field: 'requested_scopes', operator: 'not_in', value: { $field: 'principal.scopes' } },
      ] } },
    { name: 'allow', description: 'd', priority: 1, decision: 'ALLOW', reason_code: 'OK',
      conditions: { field: 'action', operator: 'exists', value: true } },
  ],
};

function client(): { h: HIITL; db: string } {
  const dir = mkdtempSync(join(tmpdir(), 'hiitl-scopes-'));
  const policyPath = join(dir, 'policy.json');
  writeFileSync(policyPath, JSON.stringify(GATE));
  const db = join(dir, 'a.db');
  const h = new HIITL({
    policy_path: policyPath,
    mode: 'RESPECT_POLICY',
    audit_db_path: db,
    principal_verifier: () => ({ sub: 'user_7', scope: 'refunds:write read' }),
  });
  return { h, db };
}

describe('requested_scopes (TICKET-138)', () => {
  it('reaches the evaluated envelope', () => {
    const { h } = client();
    const ok = h.evaluate({ action: 'refund', principal_token: 't', requested_scopes: ['read'] }) as Decision;
    expect(ok.decision).toBe('ALLOW');
    const blocked = h.evaluate({ action: 'refund', principal_token: 't', requested_scopes: ['read', 'admin'] }) as Decision;
    expect([blocked.decision, blocked.reason_codes]).toEqual(['BLOCK', ['AT_0009_BLOCK']]);
  });

  it('the audit record carries it and its content hash covers it', () => {
    const { h, db } = client();
    h.evaluate({ action: 'refund', principal_token: 't', requested_scopes: ['read'] });
    const [rec] = new AuditLogger(db).getUnsynced(10) as Array<Record<string, any>>;
    expect(rec.envelope.requested_scopes).toEqual(['read']);
    expect(rec.content_hash).toBe(auditContentHash(rec.event_id, rec.envelope, rec.decision));
    const { requested_scopes: _omit, ...without } = rec.envelope;
    expect(rec.content_hash).not.toBe(auditContentHash(rec.event_id, without, rec.decision));
  });

  it('omitted, it is absent', () => {
    const { h, db } = client();
    h.evaluate({ action: 'refund' });
    const [rec] = new AuditLogger(db).getUnsynced(10) as Array<Record<string, any>>;
    expect(rec.envelope.requested_scopes).toBeUndefined();
  });

  it('the hosted path forwards it in the body', async () => {
    let body: Record<string, unknown> | undefined;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: { body: string }) => {
      body = JSON.parse(init.body);
      return new Response(JSON.stringify({ action_id: 'act_x', decision: 'ALLOW', allowed: true,
        reason_codes: ['OK'], policy_version: '1', timing: { total_ms: 1 } }), { status: 200 });
    }));
    try {
      const h = new HIITL({
        api_key: 'test-api-key-12345', server_url: 'https://api.example.invalid', evaluation: 'remote', environment: 'dev', agent_id: 'a',
        org_id: 'org_mycompany123456789', signature_key: 's'.repeat(32), audit_db_path: ':memory:',
      });
      await h.evaluate({ action: 'refund', requested_scopes: ['refunds:write'] });
      expect(body?.requested_scopes).toEqual(['refunds:write']);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
