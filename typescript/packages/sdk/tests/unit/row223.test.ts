/**
 * Row 223 (HTL-24): the SDK builds a schema 2.0 envelope.
 *
 * Ruled 2026-11-07: "`$id` v2, `schema_version` `v2.0` as both SDKs' default". The envelope `evaluate()` records in
 * local mode is read against envelope_schema.json by the schema's own keywords (`required`, `properties`,
 * `additionalProperties`, a property's `pattern` and `enum`), and its version is the core's one constant. Design: the
 * HTL-24 test design, row 223, behavior 4. Mirrors python/hiitl/sdk/tests/test_row223.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ENVELOPE_SCHEMA_VERSION, type Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';

const ROOT = path.join(__dirname, '../../../../..');
const SCHEMA = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs/specs/envelope_schema.json'), 'utf8'));
const ORG = 'org_test000000000000000';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

/** Where the envelope departs from the schema file, read at the file. */
function departures(envelope: Row): string[] {
  const taken: Record<string, Row> = SCHEMA.properties;
  const found = (SCHEMA.required as string[]).filter((name) => !(name in envelope)).map((name) => `${name} is required`);
  if (SCHEMA.additionalProperties === false) {
    found.push(...Object.keys(envelope).filter((name) => !(name in taken)).map((name) => `${name} is not a property`));
  }
  for (const [name, value] of Object.entries(envelope)) {
    const stated = taken[name] ?? {};
    if ('pattern' in stated && !(typeof value === 'string' && new RegExp(stated.pattern).test(value))) {
      found.push(`${name} ${JSON.stringify(value)} does not match ${stated.pattern}`);
    }
    if ('enum' in stated && !stated.enum.includes(value)) {
      found.push(`${name} ${JSON.stringify(value)} is not one of ${JSON.stringify(stated.enum)}`);
    }
  }
  return found;
}

let dir: string;
let ambient: Record<string, string | undefined>;
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row223-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('row 223: the SDK builds a schema 2.0 envelope', () => {
  it('the envelope evaluate() records is a schema 2.0 envelope', () => {
    const h = new HIITL({ environment: 'dev', agent_id: 'invoice-agent', org_id: ORG, audit_db_path: path.join(dir, 'audit.db') });
    let records: Row[];
    let d: Decision;
    try {
      d = h.evaluate({ action: 'send_invoice', parameters: { invoice_id: 'inv_2231', amount: 640 } }) as Decision;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      records = (h as any).auditLogger.getUnsynced(10);
    } finally {
      h.close();
    }
    expect(records.length).toBe(1);
    const envelope = records[0].envelope;
    expect(envelope.action_id).toBe(d.action_id);
    expect(envelope.schema_version).toBe(ENVELOPE_SCHEMA_VERSION);
    expect(departures(envelope)).toEqual([]);
  });
});
