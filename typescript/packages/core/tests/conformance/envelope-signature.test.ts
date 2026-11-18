/**
 * The envelope's signed form — one canonical serialisation in both languages (the security architecture §1.3;
 * row 127, Trevor, 2026-11-04): a fixed envelope signs and hashes to the same values here and in Python
 * (tests/conformance/envelope_signature/).
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { envelopeHash, envelopeSignature, envelopeSignedForm, envelopeVerifies } from '../../src/canonical.js';

const DIR = join(__dirname, '../../../../../tests/conformance/envelope_signature');
const CASES = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe('envelope signature conformance', () => {
  it('covers the SDK and hosted principal signed forms (security architecture §1.3)', () => {
    const forms = CASES.map((f) => {
      const c = JSON.parse(readFileSync(join(DIR, f), 'utf8'));
      const signed = JSON.parse(c.expected.signed_form);
      return [c.envelope.principal.verified_by, signed.principal ?? null];
    });
    const principals = CASES.map((f) => JSON.parse(readFileSync(join(DIR, f), 'utf8')).envelope.principal);
    expect(forms).toEqual(principals.map((principal) => [principal.verified_by,
      principal.verified_by === 'hosted' ? null : principal]));
    expect([...new Set(principals.map((p) => p.verified_by))].sort()).toEqual(['hosted', 'sdk_verifier']);
  });
  for (const f of CASES) {
    it(`${f}: a fixed envelope signs to the conformance values`, () => {
      const c = JSON.parse(readFileSync(join(DIR, f), 'utf8'));
      expect(envelopeSignedForm(c.envelope)).toBe(c.expected.signed_form);
      expect(envelopeSignature(c.secret, c.envelope)).toBe(c.expected.signature);
      expect(c.envelope.signature).toBe(c.expected.signature);
      expect(envelopeVerifies(c.secret, c.envelope)).toBe(true);
      expect(envelopeHash(c.envelope)).toBe(c.expected.envelope_hash);
    });
  }
});
