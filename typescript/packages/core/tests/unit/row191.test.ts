/**
 * Row 191 (HTL-23, Stop A): what a record's hash covers.
 *
 * Ruled 2026-11-06: "each content member a record carries beyond its envelope and decision joins the hash as a further
 * term in a fixed order (`…:{C(execution_result)}` on a result, `…:{C(redaction)}` where a path is named); a record
 * carrying neither hashes exactly as today ...; one function per language". By the security architecture §1.4, "Every
 * audit record includes a SHA-256 hash of its own content, computed at write time", and Tier 1, "Enables individual
 * record tamper detection". Design: the HTL-23 test design, row 191, behavior 3. Mirrors
 * python/hiitl/core/tests/test_row191.py.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { _auditContentHash as auditContentHash, _canonicalJson as canonicalJson } from '../../src/canonical.js';

const CASES = join(__dirname, '../../../../../tests/conformance/audit_hash');

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Case = Record<string, any>;

const read = (name: string): Case => JSON.parse(readFileSync(join(CASES, `${name}.json`), 'utf8'));

const hash = (c: Case, further?: { execution_result?: unknown; redaction?: unknown }): string =>
  auditContentHash(c.event_id, c.envelope, c.decision, further);

const sha256 = (s: string): string => createHash('sha256').update(s, 'utf8').digest('hex');

describe('row 191: what a record hash covers', () => {
  it('an altered result fails its hash', () => {
    const c = read('case_002_result_record');
    const stored = c.expected.content_hash;
    const result = c.execution_result;
    expect(hash(c, { execution_result: result })).toBe(stored);

    const altered: Record<string, unknown> = {
      status: { ...result, status: 'succeeded' },
      error: { ...result, error: 'card declined' },
      duration_ms: { ...result, duration_ms: 1 },
      'a member added': { ...result, response_id: 'ch_1' },
    };
    for (const [what, r] of Object.entries(altered)) {
      expect(hash(c, { execution_result: r }), what).not.toBe(stored);
    }
    expect(hash(c), 'a result record read without its result does not verify').not.toBe(stored);
  });

  it('an altered absent path fails its hash', () => {
    const c = read('case_003_absent_path');
    const stored = c.expected.content_hash;
    const absent: string[] = c.redaction.absent;
    expect(hash(c, { redaction: c.redaction })).toBe(stored);
    expect(hash(c, { redaction: { absent: absent.slice(0, 1) } })).not.toBe(stored);
    expect(hash(c, { redaction: { absent: [...absent].reverse() } })).not.toBe(stored);
    expect(hash(c)).not.toBe(stored);
  });

  it('a term is joined on presence, never on value', () => {
    const c = read('case_001_fixed_record');
    const base = `${c.event_id}:${canonicalJson(c.envelope)}:${canonicalJson(c.decision)}`;
    expect(hash(c)).toBe(c.expected.content_hash);
    expect(hash(c)).toBe(sha256(base));
    expect(hash(c, { execution_result: undefined, redaction: undefined })).toBe(sha256(base));
    expect(hash(c, { execution_result: null })).toBe(sha256(`${base}:null`));
    expect(hash(c, { redaction: null }), 'one form for a further term').toBe(hash(c, { execution_result: null }));
  });

  it('a term the record does not name is refused', () => {
    // The further terms are the record's own member names: another spelling would hash without its term, unseen
    const c = read('case_002_result_record');
    expect(() => hash(c, { executionResult: c.execution_result } as never))
      .toThrow(/executionResult; a record's further terms are execution_result, redaction/);
  });
});
