/**
 * One organisation id form (HTL-19 row 144): the envelope schema states it and `ORG_ID_PATTERN` reads it, so the SDK
 * takes every id the service mints (sync_engine.md §8).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ORG_ID_PATTERN } from '../../src/types.js';

const SCHEMA = join(__dirname, '../../../../../docs/specs/envelope_schema.json');

describe('ORG_ID_PATTERN', () => {
  it("is the envelope schema's org_id pattern", () => {
    const schema = JSON.parse(readFileSync(SCHEMA, 'utf8'));
    expect(ORG_ID_PATTERN.source).toBe(schema.properties.org_id.pattern);
  });
  it("takes the service's mint and refuses one character short", () => {
    expect(ORG_ID_PATTERN.test('org_0123456789abcdef')).toBe(true);
    expect(ORG_ID_PATTERN.test('org_0123456789abcde')).toBe(false);
  });
});
