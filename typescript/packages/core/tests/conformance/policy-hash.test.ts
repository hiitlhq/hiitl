/**
 * The policy content hash — the audit hash's canonical serialisation, read by every policy and route writer and
 * checker (docs/specs/sync_engine.md §2.2; Trevor, 2026-11-04): a fixed policy set hashes to the same digest here and
 * in Python (tests/conformance/policy_hash/).
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canonicalHash, canonicalJson } from '../../src/canonical.js';

const DIR = join(__dirname, '../../../../../tests/conformance/policy_hash');
const CASES = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe('policy content hash conformance', () => {
  it('carries the non-ASCII and integral-float witnesses named by sync_engine.md §2.2', () => {
    const witnesses = CASES.flatMap((f) => {
      const raw = readFileSync(join(DIR, f), 'utf8');
      return [
        ...(/[\u0080-\uFFFF]/.test(JSON.stringify(JSON.parse(raw).content)) ? ['non-ASCII string'] : []),
        ...(/:\s*-?\d+\.0(?:\s*[,}\]])/.test(raw) ? ['integral float'] : []),
      ];
    });
    expect([...new Set(witnesses)].sort()).toEqual(['integral float', 'non-ASCII string']);
  });
  for (const f of CASES) {
    it(`${f}: a fixed policy hashes to the conformance digest`, () => {
      const c = JSON.parse(readFileSync(join(DIR, f), 'utf8'));
      expect(canonicalJson(c.content)).toBe(c.expected.canonical);
      expect(canonicalHash(c.content)).toBe(c.expected.content_hash);
    });
  }
});
