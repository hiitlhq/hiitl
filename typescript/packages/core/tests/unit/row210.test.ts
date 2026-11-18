/**
 * Row 210 (HTL-23): `trace_id` takes W3C Trace Context's form.
 *
 * Ruled 2026-11-06: "`trace_id` takes the pattern `^[0-9a-f]{32}$` in place of its `maxLength: 128` … It is a
 * breaking change and enters through [the schema-versioning rule's] own door, 'migration paths before breaking
 * changes': the schema version bumps and the migration path is written at the bump." The pattern and its example are
 * read from
 * envelope_schema.json; each other form is the example changed one way. Design: the HTL-23 test design,
 * row 210, behavior 1. Mirrors core/tests/test_row210.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { EnvelopeSchema, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const SPECS = join(__dirname, '../../../../../docs/specs');
const TRACE_ID = JSON.parse(readFileSync(join(SPECS, 'envelope_schema.json'), 'utf8')).properties.trace_id;
const PATTERN = new RegExp(TRACE_ID.pattern);
const EXAMPLE: string = TRACE_ID.examples[0];
const OTHERS: Record<string, string> = {
  uppercase: EXAMPLE.toUpperCase(),
  'one short': EXAMPLE.slice(0, -1),
  'one long': EXAMPLE + EXAMPLE.slice(-1),
  "a caller's own id": 'req-r210-0001',
};

const envelope = (fields: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_test123456789012', environment: 'dev', agent_id: 'agent-210',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row210', action: 'send_invoice',
  timestamp: '2026-11-06T12:00:00Z', signature: 'a'.repeat(64), ...fields,
});

describe('row 210: trace_id takes W3C Trace Context\'s form', () => {
  it('the schema declares the form', () => {
    expect(PATTERN.test(EXAMPLE)).toBe(true);
    expect(Object.entries(OTHERS).filter(([, v]) => PATTERN.test(v)).map(([k]) => k)).toEqual([]);
    expect(TRACE_ID.maxLength).toBeUndefined();
  });

  it('test_the_form_is_taken', () => {
    expect(EnvelopeSchema.parse(envelope({ trace_id: EXAMPLE })).trace_id).toBe(EXAMPLE);
  });

  it('test_no_trace_id_is_taken', () => {
    expect(EnvelopeSchema.parse(envelope()).trace_id).toBeUndefined();
  });

  it.each(Object.entries(OTHERS))('test_another_form_is_refused_naming_the_field[%s]', (_name, value) => {
    const result = EnvelopeSchema.safeParse(envelope({ trace_id: value }));
    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((i) => i.path.join('.'))).toEqual(['trace_id']);
  });
});
