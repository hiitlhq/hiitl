/**
 * Row 171 (HTL-22): the envelope names its own signature version (one version marker; no request header names it).
 *
 * Trevor's ruling on HTL-20: "one signature marker kept, by B.foundation.6". The marker kept is the envelope's
 * `signature_version`, by the project rule "Don't remove or rename existing fields", and the header goes. The spec is
 * read at its producer: envelope_schema.json's `signature_version`. Design: the HTL-22 test design, row 171, behavior
 * 1. Mirrors core/tests/test_row171.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { EnvelopeSchema, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const SPEC = JSON.parse(readFileSync(join(__dirname, '../../../../../docs/specs/envelope_schema.json'), 'utf8'))
  .properties.signature_version;

const envelope = {
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_test123456789012', environment: 'dev', agent_id: 'agent-171',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row171', action: 'send_invoice',
  timestamp: '2026-11-05T12:00:00Z', signature: 'a'.repeat(64),
};

describe('row 171: the envelope names its signature version', () => {
  it("an envelope left without one names the schema's default, the schema's one value", () => {
    expect(SPEC.enum).toEqual([SPEC.default]);
    expect(EnvelopeSchema.parse(envelope).signature_version).toBe(SPEC.default);
  });
});
