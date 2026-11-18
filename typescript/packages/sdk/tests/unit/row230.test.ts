/**
 * Row 230 (HTL-29): the SDK store names the record's action `action`, its source's name.
 *
 * Ruled 2026-11-09: "the record's projection of the action takes its source's name, `action`, in the next version of
 * the record format ... the hosted `AuditEvent` column, both SDK stores' columns and the audit query's filter rename
 * with it, by migration, never in place". event_format.md 2.0, "From 1.x": each SDK store, when it opens, renames each
 * column of its own whose name the envelope schema renamed, so a store written before 2.0 keeps each record it holds,
 * with its value, its hash and its `synced` mark. Design: the HTL-29 test design, row 230, behaviors 6-7. Mirrors
 * python/hiitl/sdk/tests/test_row230.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ENVELOPE_RENAMED, ENVELOPE_SCHEMA_VERSION, auditContentHash } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';

const ORG = 'org_r230action00000000';
const ENV = 'dev';
const DECISION: Decision = {
  action_id: 'act_00000000000000000000', decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { ingest_ms: 0, evaluation_ms: 0, total_ms: 0 },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

let dir: string;
const opened: Array<{ close(): void }> = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row230-'));
});

afterEach(() => {
  for (const o of opened.splice(0)) o.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function store(file: string): AuditLogger {
  const log = new AuditLogger(file);
  opened.push(log);
  return log;
}

const actionId = (i: number) => `act_r230${String(i).padStart(20, '0')}`;

/** n records in the store, oldest first; their event_ids. */
function written(log: AuditLogger, n: number, from = 0): string[] {
  return Array.from({ length: n }, (_, k) => {
    const i = from + k;
    const envelope: Envelope = {
      schema_version: ENVELOPE_SCHEMA_VERSION, org_id: ORG, environment: ENV, agent_id: 'r230-agent',
      action_id: actionId(i), idempotency_key: `k${i}`, action: 'send_email', operation: 'execute', target: {},
      parameters: { to: `ops+${i}@example.com` }, timestamp: '2026-11-09T10:00:00Z', signature: '0'.repeat(64),
    };
    return log.write(envelope, DECISION);
  });
}

function columns(file: string): string[] {
  const db = new Database(file, { readonly: true });
  try {
    return (db.prepare('PRAGMA table_info(audit_log)').all() as Row[]).map((c) => c.name);
  } finally {
    db.close();
  }
}

/** Each record as the store holds it, by event_id: the columns, read directly. */
function rows(file: string): Record<string, Row> {
  const db = new Database(file, { readonly: true });
  try {
    return Object.fromEntries((db.prepare('SELECT * FROM audit_log').all() as Row[]).map((r) => [r.event_id, r]));
  } finally {
    db.close();
  }
}

const renamed = (row: Row): Row => Object.fromEntries(Object.entries(row).map(([k, v]) => [ENVELOPE_RENAMED[k] ?? k, v]));

describe('row 230: the store names the action as the envelope does', () => {
  it('test_a_new_store_names_the_action_as_the_envelope_does', () => {
    // Behavior 6: the table has `action` and no column the envelope schema renamed; a record as written, as its
    // lifecycle reads it and as the upload reads it, carries `action`, its envelope's, and a result record too
    const file = path.join(dir, 'audit.db');
    const log = store(file);
    written(log, 1);
    expect(columns(file)).toContain('action');
    expect(columns(file).filter((c) => c in ENVELOPE_RENAMED)).toEqual([]);

    const [decided] = log.lifecycle(ORG, ENV, actionId(0)) as Row[];
    expect([decided.action, decided.envelope.action]).toEqual(['send_email', 'send_email']);
    expect(decided).not.toHaveProperty('tool_name');
    const result = log.writeResult(decided, { status: 'succeeded' });
    expect(result.action).toBe('send_email');   // the result record names it as its decision
    expect(result).not.toHaveProperty('tool_name');

    const sent = log.getUnsynced();
    expect(sent.map((r) => r.action)).toEqual(['send_email', 'send_email']);
    for (const r of sent) expect(r).not.toHaveProperty('tool_name');   // the upload carries the envelope's name
  });

  it('test_a_store_written_before_2_0_is_renamed_when_it_opens_keeping_each_record', () => {
    // Behavior 7: a store whose table names the column `tool_name`, holding a synced record and a pending one, opens
    // with `action`: each record keeps its value, its hash and its mark, the pending one uploads carrying `action`,
    // and the store writes on as any 2.0 store does
    const file = path.join(dir, 'audit.db');
    const first = new AuditLogger(file);
    const events = written(first, 2);
    first.markSynced(events.slice(0, 1));
    first.close();
    const db = new Database(file);
    for (const [old, now] of Object.entries(ENVELOPE_RENAMED)) db.exec(`ALTER TABLE audit_log RENAME COLUMN ${now} TO ${old}`);
    db.close();
    const before = rows(file);
    expect(new Set(Object.values(before).map((r) => r.tool_name))).toEqual(new Set(['send_email']));   // a 1.x store

    const log = store(file);
    const after = columns(file);
    expect(after).toContain('action');
    expect(after).not.toContain('tool_name');
    const held = rows(file);
    // each record keeps each value it held, under the column's new name
    expect(held).toEqual(Object.fromEntries(Object.entries(before).map(([e, r]) => [e, renamed(r)])));
    expect(Object.fromEntries(Object.entries(held).map(([e, r]) => [e, r.synced]))).toEqual({ [events[0]]: 1, [events[1]]: 0 });
    for (const [e, r] of Object.entries(held)) {
      expect(r.content_hash).toBe(auditContentHash(e, JSON.parse(r.envelope), JSON.parse(r.decision), {}));
    }

    const pending = log.getUnsynced();
    expect(pending.map((r) => [r.event_id, r.action])).toEqual([[events[1], 'send_email']]);
    expect(pending[0]).not.toHaveProperty('tool_name');

    const [again] = written(log, 1, 2);
    expect(rows(file)[again].action).toBe('send_email');
    store(file);
    expect(columns(file)).toEqual(after);   // a 2.0 store opens as it is
  });
});
