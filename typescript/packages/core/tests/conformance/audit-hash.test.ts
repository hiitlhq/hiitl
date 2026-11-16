/**
 * The audit content hash — one canonical serialisation in both languages (docs/specs/sync_engine.md §2.1; Trevor,
 * 2026-10-10): a fixed record hashes to the same digest here and in Python (tests/conformance/audit_hash/).
 *
 * Each content member a record carries beyond its envelope and decision joins the hash as a further term, in a fixed
 * order (Stop A, ruled 2026-11-06; event_format.md 1.5; `review` at 1.6, row 217): a case carries the members its
 * record carries, and a case carrying none hashes exactly as before. The terms and their order are read from
 * event_format.md's `content_hash` row.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AUDIT_FURTHER, auditContentHash, canonicalJson } from '../../src/canonical.js';
import { requiredMatch } from '../../../../test-support/declarations.js';

const ROOT = join(__dirname, '../../../../..');
const DIR = join(ROOT, 'tests/conformance/audit_hash');
const CASES = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();
const SPEC = readFileSync(join(ROOT, 'docs/specs/event_format.md'), 'utf8');
const ROW = requiredMatch(SPEC,
  /^\| `content_hash` \|[^\n]+then `:\{C\(\w+\)\}`[^\n]+$/m,
  'event_format.md content_hash row and further terms')[0];
// the spec's further terms, in its order
const FURTHER = [...ROW.matchAll(/then `:\{C\((\w+)\)\}`/g)].map((m) => m[1]);

describe('audit content hash conformance', () => {
  for (const f of CASES) {
    it(`${f}: a fixed record hashes to the conformance digest`, () => {
      const c = JSON.parse(readFileSync(join(DIR, f), 'utf8'));
      expect(canonicalJson(c.envelope)).toBe(c.expected.canonical_envelope);
      expect(canonicalJson(c.decision)).toBe(c.expected.canonical_decision);
      for (const m of FURTHER) {
        if (m in c) expect(canonicalJson(c[m])).toBe(c.expected[`canonical_${m}`]);
      }
      const further = Object.fromEntries(FURTHER.filter((m) => m in c).map((m) => [m, c[m]]));
      expect(auditContentHash(c.event_id, c.envelope, c.decision, further)).toBe(c.expected.content_hash);
    });
  }
  it('carries exactly the record shapes declared by event_format.md Conformance Testing', () => {
    const terms = requiredMatch(SPEC,
      /## Conformance Testing[\s\S]*?a record carrying no further term[\s\S]*?one carrying\s+`(\w+)`, one carrying `(\w+)`, one carrying both, and a held result carrying all three/,
      'event_format.md conformance record shapes');
    const [first, second] = terms.slice(1);
    const declared = [[], [first], [second], [first, second], FURTHER];
    const carried = CASES.map((f) => {
      const c = JSON.parse(readFileSync(join(DIR, f), 'utf8'));
      return FURTHER.filter((m) => m in c);
    });
    expect(carried.map((c) => c.join(',')).sort()).toEqual(declared.map((c) => c.join(',')).sort());
  });
  it("the core's further terms are the spec's, member for member, in order", () => {
    expect([...AUDIT_FURTHER]).toEqual(FURTHER);
  });
});
