/**
 * Row 200 (HTL-23): the hosted result write during an outage.
 *
 * Ruled 2026-11-06: "The hosted result write does not raise on an outage: with 192 (i) ruled, the result is held in
 * the same local buffer and pushed; a typed error only when the buffer itself cannot be written", by Principle 4 and
 * Principle 6. The contract is event_format.md "The Lifecycle" ("A result the hosted service could not take") and
 * sync_engine.md "The hosted client's buffer". Design: the HTL-23 test design, row 200. Mirrors
 * python/hiitl/sdk/tests/test_row200.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { LIFECYCLE_MESSAGES, type Decision } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import { AuditLogError } from '../../src/exceptions.js';

const ORG_ID = 'org_r200heldresult000000';
const EVALUATE = '/v1/evaluate';
const PUSH = '/v1/sync/audit';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
type Answer = (body: Row) => Response;

let answers: Array<[string, Answer]>;
let sent: Array<{ path: string; body: Row }>;
let dir: string;
let ambient: Record<string, string | undefined>;
const clients: HIITL[] = [];

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row200-'));
  answers = [];
  sent = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    const at = new URL(url).pathname;
    const body = JSON.parse(init.body as string) as Row;
    sent.push({ path: at, body });
    const i = answers.findIndex(([p]) => p === at);
    if (i < 0) throw new Error(`no answer registered for ${at}`);
    return answers.splice(i, 1)[0][1](body);
  }));
});

afterEach(() => {
  for (const h of clients.splice(0)) h.close();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  fs.rmSync(dir, { recursive: true, force: true });
  expect(answers.map(([p]) => p), 'every answer registered was asked for').toEqual([]);
});

function hiitl(store: string, overrides: Record<string, unknown> = {}): HIITL {
  const h = new HIITL({
    environment: 'dev', agent_id: 'r200-agent', org_id: ORG_ID, api_key: 'sk_test_r200heldresult0',
    server_url: 'https://ecp.r200.example.com', evaluation: 'remote',
    signature_key: 'r200-signing-secret-0123456789abcdef', audit_db_path: store, max_retries: 0, ...overrides,
  });
  clients.push(h);
  return h;
}

const json = (body: Row, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const down: Answer = () => {
  throw new TypeError('fetch failed');
};

const decides: Answer = (body) => json({
  action_id: body.action_id, decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { total_ms: 1.0 },
});

const takes: Answer = (body) => json({ accepted: body.records.length, duplicates: 0, errors: [] });

const on = (at: string, answer: Answer): void => {
  answers.push([at, answer]);
};

const resultPath = (actionId: string): string => `/v1/actions/${actionId}/result`;

function heldResults(store: string): Row[] {
  const log = new AuditLogger(store);
  try {
    return log.heldResults();
  } finally {
    log.close();
  }
}

describe('row 200: the hosted result write during an outage', () => {
  it('test_a_result_during_an_outage_is_held', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, decides);
    const h = hiitl(store);
    const d = (await h.evaluate({ action: 'send_email' })) as Decision;
    on(resultPath(d.action_id), down);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const held = await h.recordResult(d.action_id, 'succeeded', { duration_ms: 412 });
    const result = { status: 'succeeded', duration_ms: 412 };
    expect(held).toEqual({ action_id: d.action_id, execution_result: result, held: true });
    expect(warn.mock.calls.filter((c) => String(c[0]).includes(d.action_id)).length).toBe(1);
    expect(heldResults(store)).toEqual([{ action_id: d.action_id, execution_result: result }]);
  });

  it('test_a_held_result_is_pushed_after_the_records', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, down);
    const h = hiitl(store, { fail_mode: 'FAIL_OPEN' });
    const outage = (await h.evaluate({ action: 'send_email' })) as Decision;
    expect(outage.allowed).toBe(true);

    on(PUSH, down);
    const held = await h.recordResult(outage.action_id, 'failed', { error: 'smtp 421' });
    expect((held as Row).held).toBe(true);

    const result = { status: 'failed', error: 'smtp 421' };
    on(PUSH, takes);
    on(resultPath(outage.action_id), () => json({ action_id: outage.action_id, execution_result: result }));
    on(EVALUATE, decides);
    await h.evaluate({ action: 'send_email' });
    expect(sent.map((s) => s.path)).toEqual([EVALUATE, PUSH, PUSH, resultPath(outage.action_id), EVALUATE]);
    expect(sent[3].body).toEqual(result);
    expect(heldResults(store)).toEqual([]);
  });

  it('test_a_held_result_refused_at_the_push_is_removed', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, decides);
    const h = hiitl(store);
    const d = (await h.evaluate({ action: 'send_email' })) as Decision;
    on(resultPath(d.action_id), down);
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await h.recordResult(d.action_id, 'succeeded');

    on(resultPath(d.action_id), () => json({ detail: {
      error: 'RESULT_ALREADY_RECORDED', message: LIFECYCLE_MESSAGES.RESULT_ALREADY_RECORDED } }, 409));
    on(EVALUATE, decides);
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const after = (await h.evaluate({ action: 'send_email' })) as Decision;
    expect(after.decision).toBe('ALLOW');
    expect(sent.slice(-2).map((s) => s.path)).toEqual([resultPath(d.action_id), EVALUATE]);
    expect(heldResults(store), 'a refused result is no record').toEqual([]);
    expect(error.mock.calls.filter((c) =>
      String(c[0]).includes(d.action_id) && String(c[0]).includes('RESULT_ALREADY_RECORDED')).length).toBe(1);
  });

  it('test_a_result_the_store_cannot_hold_raises', async () => {
    fs.writeFileSync(path.join(dir, 'file'), "a file where the store's directory would be");
    on(EVALUATE, decides);
    const h = hiitl(path.join(dir, 'file', 'audit.db'));
    const d = (await h.evaluate({ action: 'send_email' })) as Decision;
    on(resultPath(d.action_id), down);
    await expect(h.recordResult(d.action_id, 'succeeded')).rejects.toBeInstanceOf(AuditLogError);
  });
});
