/**
 * Row 223 (HTL-24): envelope schema 2.0.
 *
 * Ruled 2026-11-07: "`$id` v2, `schema_version` `v2.0` as both SDKs' default, and a v1 envelope refused
 * `VALIDATION_ERROR` naming the version and the migration note; no acceptance window, no dual handling". By R-0007
 * ("Backward-compatible field additions only … Migration path documented before breaking changes") and 1.3's
 * `policy_refs` "removed at the next major version". The schema's version is read from envelope_schema.json, and the
 * migration note's heading from the docs page that carries it. Design: the HTL-24 test design, row 223, behaviors
 * 1–3. Mirrors core/tests/test_row223.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ENVELOPE_MIGRATION_NOTE, ENVELOPE_SCHEMA_VERSION, EnvelopeSchema } from '../../src/types.js';

const ROOT = join(__dirname, '../../../../..');
const SCHEMA = JSON.parse(readFileSync(join(ROOT, 'docs/specs/envelope_schema.json'), 'utf8'));
const DOCS = readFileSync(join(ROOT, 'docs-site/concepts/envelope.mdx'), 'utf8');

const major = (version: string): string => /^v([0-9]+)\.[0-9]+$/.exec(version)![1];

const envelope = (fields: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_test123456789012', environment: 'dev', agent_id: 'agent-223',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row223', action: 'send_invoice',
  timestamp: '2026-11-07T12:00:00Z', signature: 'a'.repeat(64), ...fields,
});

describe('row 223: envelope schema 2.0', () => {
  it("the schema's version is the core's", () => {
    const taken = SCHEMA.properties.schema_version;
    const m = major(ENVELOPE_SCHEMA_VERSION);
    expect(/\/v([0-9]+)\.json$/.exec(SCHEMA.$id)![1]).toBe(m);
    expect(new RegExp(taken.pattern).test(ENVELOPE_SCHEMA_VERSION)).toBe(true);
    expect(taken.examples).toEqual([ENVELOPE_SCHEMA_VERSION]);
    expect(new RegExp(taken.pattern).test(`v${Number(m) - 1}.0`)).toBe(false);
  });

  it('a minor version of the major loads', () => {
    for (const version of [ENVELOPE_SCHEMA_VERSION, `v${major(ENVELOPE_SCHEMA_VERSION)}.7`]) {
      expect(EnvelopeSchema.parse(envelope({ schema_version: version })).schema_version).toBe(version);
    }
  });

  it.each([-1, 1])('another major (%i) is refused, naming the version and the note', (delta) => {
    const other = `v${Number(major(ENVELOPE_SCHEMA_VERSION)) + delta}.0`;
    const parsed = EnvelopeSchema.safeParse(envelope({ schema_version: other }));
    expect(parsed.success).toBe(false);
    const issues = parsed.success ? [] : parsed.error.issues;
    expect(issues.map((i) => i.path)).toEqual([['schema_version']]);
    for (const named of [other, ENVELOPE_SCHEMA_VERSION, ENVELOPE_MIGRATION_NOTE]) {
      expect(issues[0].message).toContain(named);
    }
    expect(DOCS).toContain(`\n### ${ENVELOPE_MIGRATION_NOTE}\n`);
  });

  it('policy_refs is a field the schema does not define', () => {
    expect(SCHEMA.properties.policy_refs).toBeUndefined();
    const parsed = EnvelopeSchema.safeParse(envelope({ policy_refs: ['payments'] }));
    expect(parsed.success).toBe(false);
    const issues = parsed.success ? [] : parsed.error.issues;
    expect(issues.map((i) => [i.code, (i as { keys?: string[] }).keys])).toEqual([['unrecognized_keys', ['policy_refs']]]);
  });
});
