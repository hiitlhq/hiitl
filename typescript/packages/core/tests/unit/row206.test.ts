/**
 * Row 206 (HTL-23): each core model refuses a value outside an enum its spec declares.
 *
 * Ruled 2026-11-06 as the row reads: "each core model refuses it, row 147's class". Row 147 (R-1170): "each model
 * refuses what its spec refuses". The row found `signature_version`; the class is every enum envelope_schema.json
 * declares, read from the schema, never listed here (item 13). Design: the HTL-23 test design, row 206.
 * Mirrors core/tests/test_row206.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { EnvelopeSchema, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const SPECS = join(__dirname, '../../../../../docs/specs');
const ENVELOPE_SCHEMA = JSON.parse(readFileSync(join(SPECS, 'envelope_schema.json'), 'utf8'));
const OUTSIDE = 'outside-r206';
const PRINCIPAL = { sub: 'user-r206', verified_by: 'sdk_verifier' };

type Path = Array<string | number>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Node = Record<string, any>;

/** [path, members] of each enum the schema declares; an array's item is its index 0. */
function enums(node: Node, path: Path = []): Array<[Path, string[]]> {
  const found: Array<[Path, string[]]> = Array.isArray(node.enum) ? [[path, node.enum]] : [];
  for (const [name, sub] of Object.entries((node.properties ?? {}) as Node)) found.push(...enums(sub, [...path, name]));
  if (node.items && typeof node.items === 'object' && !Array.isArray(node.items)) {
    found.push(...enums(node.items, [...path, 0]));
  }
  return found;
}

const ENUMS = enums(ENVELOPE_SCHEMA);

const envelope = (fields: Node = {}): Node => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_test123456789012', environment: 'dev', agent_id: 'agent-206',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row206', action: 'send_invoice',
  timestamp: '2026-11-06T12:00:00Z', signature: 'a'.repeat(64), principal: { ...PRINCIPAL }, ...fields,
});

/** An envelope whose value at `path` is `value`. */
function withValue(path: Path, value: unknown): Node {
  const e = envelope();
  let node: Node = e;
  for (let i = 0; i < path.length - 1; i++) {
    const step = path[i];
    node[step] ??= typeof path[i + 1] === 'number' ? [undefined] : {};
    node = node[step];
  }
  node[path[path.length - 1]] = value;
  return e;
}

describe('row 206: each core model refuses a value outside an enum its spec declares', () => {
  it('the schema declares the row\'s enum', () => {
    expect(ENUMS.map(([p]) => p.join('.'))).toContain('signature_version');
  });

  for (const [path, members] of ENUMS) {
    const id = path.join('.');

    it(`test_a_value_outside_the_enum_is_refused_naming_the_field[${id}]`, () => {
      const result = EnvelopeSchema.safeParse(withValue(path, OUTSIDE));
      expect(result.success).toBe(false);
      const found = result.success ? [] : result.error.issues.map((i) => i.path.join('.'));
      expect(found, `the malformed enum is at ${id}`).toEqual([id]);
    });

    it(`test_each_member_of_the_enum_is_taken[${id}]`, () => {
      for (const member of members) {
        const result = EnvelopeSchema.safeParse(withValue(path, member));
        expect(result.success, `${id} = ${member}`).toBe(true);
      }
    });
  }

  it('test_an_envelope_with_no_signature_version_takes_the_default', () => {
    expect(EnvelopeSchema.parse(envelope()).signature_version)
      .toBe(ENVELOPE_SCHEMA.properties.signature_version.default);
  });
});
