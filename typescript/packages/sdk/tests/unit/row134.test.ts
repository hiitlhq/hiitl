/**
 * Row 134 with row 127 (HTL-20): the TypeScript SDK signs the envelope it records, verifies it before evaluating,
 * and every decision carries envelope_hash. Mirrors python/hiitl/sdk/tests/test_row134.py.
 *
 * the security architecture §1.3: "The SDK signs every envelope … The evaluator verifies before processing".
 * Row 127: one canonical form everywhere. Security Tier 1: "Decision includes SHA-256 of the evaluated envelope".
 */

import { describe, it, expect } from 'vitest';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { envelopeHash, envelopeSignature } from '@hiitl/core';
import type { Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { AuditLogger } from '../../src/audit.js';

const KEY = 'row134-local-signing-key-0123456789abcdef';

function client(signatureKey?: string): { h: HIITL; records: () => Array<Record<string, any>> } {
  const db = join(mkdtempSync(join(tmpdir(), 'hiitl-row134-')), 'a.db');
  const h = new HIITL({
    audit_db_path: db,
    principal_verifier: () => ({ sub: 'ledgerbot-ops', scope: 'refunds:write' }),
    ...(signatureKey ? { signature_key: signatureKey } : {}),
  });
  return { h, records: () => new AuditLogger(db).getUnsynced(10) as Array<Record<string, any>> };
}

describe('row 134: the local SDK signs what it records and verifies before evaluating', () => {
  it('the record alone re-derives its signature (behavior 2)', () => {
    const { h, records } = client(KEY);
    h.evaluate({
      action: 'refund',
      parameters: { amount: 150.5, memo: 'é', items: [{ sku: 'a', note: null }] },
      target: { account_id: 'acct_123' },
      principal_token: 't',
    });
    const [rec] = records();
    expect(rec.envelope.principal.verified_by).toBe('sdk_verifier');
    expect(rec.envelope.signature).toBe(envelopeSignature(KEY, rec.envelope));
    expect(rec.envelope.parameters.items[0]).toEqual({ sku: 'a', note: null });
  });

  it('without a key the signature is zeros', () => {
    const { h, records } = client();
    h.evaluate({ action: 'refund' });
    expect(records()[0].envelope.signature).toBe('0'.repeat(64));
  });

  // The refusal is the decision SIGNATURE_INVALID, recorded (the security architecture §1.3: "action rejected with
  // `SIGNATURE_INVALID`, audit record written"; HTL-22 row 159).
  it('an envelope altered after signing is refused and recorded (behavior 11)', () => {
    const { h, records } = client(KEY);
    const anyH = h as any;
    const build = anyH._buildEnvelope.bind(h);
    anyH._buildEnvelope = (...args: unknown[]) => {
      const envelope = build(...args);
      envelope.parameters.amount = 1_000_000;
      return envelope;
    };
    const d = h.evaluate({ action: 'refund', parameters: { amount: 10 } }) as Decision;
    expect([d.decision, d.allowed, d.reason_codes]).toEqual([
      'SIGNATURE_INVALID', false, ['ENVELOPE_SIGNATURE_VERIFICATION_FAILED'],
    ]);
    expect(d.error?.code).toBe('SIGNATURE_INVALID');
    const [rec, ...rest] = records();
    expect(rest).toEqual([]);
    expect(rec.decision.decision).toBe('SIGNATURE_INVALID');
    expect(rec.envelope.parameters.amount).toBe(1_000_000);
    expect(d.envelope_hash).toBe(envelopeHash(rec.envelope));
  });

  it.each([
    ['signed', KEY],
    ['unsigned', undefined],
  ])('the local decision carries the envelope hash, %s (behavior 12)', (_name, key) => {
    const { h, records } = client(key);
    const decision = h.evaluate({ action: 'refund', parameters: { amount: 10 } }) as Decision;
    const [rec] = records();
    expect(decision.envelope_hash).toBe(envelopeHash(rec.envelope));
    expect(rec.decision.envelope_hash).toBe(decision.envelope_hash);
    expect(JSON.stringify(rec.envelope).match(/"signature"/g)).toHaveLength(1);
  });
});
