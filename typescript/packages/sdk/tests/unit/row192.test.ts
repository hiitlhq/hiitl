/**
 * Row 192 (HTL-23, Stop B): the hosted client's outage record, held and pushed, and its fail mode.
 *
 * Ruled 2026-11-06, (i): "the pure-hosted client keeps a local audit buffer for the records the service could not
 * take, pushed when it answers, as hybrid buffers", by Principle 6 and R-0002's "structured CONTROL_PLANE_UNAVAILABLE
 * audit event"; (ii): "a `fail_mode` setting on the hosted client, `FAIL_CLOSED` by default, `FAIL_OPEN` opt-in", by
 * R-0002 and the error-handling rule "Fail-open is opt-in and must be explicitly configured". The contract is
 * decision_response.md "Where the error is answered". Design: the HTL-23 test design, row 192, behaviors 3-9. Mirrors
 * python/hiitl/sdk/tests/test_row192.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { MARKER } from '@hiitl/core';
import type { Decision } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';

const ORG_ID = 'org_r192buffer0000000000';
const SERVER = 'https://ecp.r192.example.com';
const API_KEY = 'sk_test_r192buffer0000';
const SECRET = 'r192-signing-secret-0123456789abcdef';
const EVALUATE = '/v1/evaluate';
const PUSH = '/v1/sync/audit';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
type Answer = (body: Row) => Response;

/** What the service answers, in order, per path; a path with no answer left is not expected. */
let answers: Array<[string, Answer]>;
/** What the client sent, in order. */
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
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row192-'));
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
    environment: 'dev', agent_id: 'r192-agent', org_id: ORG_ID, api_key: API_KEY, server_url: SERVER,
    evaluation: 'remote', signature_key: SECRET, audit_db_path: store, max_retries: 0, ...overrides,
  });
  clients.push(h);
  return h;
}

const json = (body: Row): Response =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const down: Answer = () => {
  throw new TypeError('fetch failed');
};

/** The service's answer to an evaluate: a decision on the action sent. */
const decides: Answer = (body) => json({
  action_id: body.action_id, decision: 'ALLOW', allowed: true, reason_codes: ['ALLOWED'],
  policy_version: 'v1.0.0', timing: { total_ms: 1.0 },
});

/** The service's answer to a push: every record accepted (sync_engine.md §2.1's response). */
const takes: Answer = (body) => json({ accepted: body.records.length, duplicates: 0, errors: [] });

const on = (at: string, answer: Answer): void => {
  answers.push([at, answer]);
};

/** The action_ids the client's n-th push carried, in its order. */
const pushed = (n = 0): string[] => sent.filter((s) => s.path === PUSH)[n].body.records.map((r: Row) => r.action_id);

function read<T>(store: string, f: (log: AuditLogger) => T): T {
  const log = new AuditLogger(store);
  try {
    return f(log);
  } finally {
    log.close();
  }
}

/** The action_ids the store holds unpushed, oldest first. */
const held = (store: string): string[] => read(store, (log) => log.getUnsynced().map((r) => r.action_id as string));

describe('row 192: the hosted client holds what the service could not take', () => {
  it('test_fail_closed_is_the_default_and_the_setting_is_checked', async () => {
    on(EVALUATE, down);
    let d = (await hiitl(path.join(dir, 'closed.db')).evaluate({ action: 'send_email' })) as Decision;
    expect([d.allowed, d.metadata?.fail_mode]).toEqual([false, 'FAIL_CLOSED']);

    process.env.HIITL_FAIL_MODE = 'FAIL_OPEN';
    on(EVALUATE, down);
    d = (await hiitl(path.join(dir, 'open.db')).evaluate({ action: 'send_email' })) as Decision;
    expect([d.allowed, d.metadata?.fail_mode], 'the setting is read from its variable').toEqual([true, 'FAIL_OPEN']);

    const given = (() => {
      try {
        hiitl(path.join(dir, 'x.db'), { fail_mode: 'FAIL_SOMETIMES' });
      } catch (e) {
        return e;
      }
    })();
    process.env.HIITL_FAIL_MODE = 'OPEN';
    const fromVariable = (() => {
      try {
        hiitl(path.join(dir, 'x.db'));
      } catch (e) {
        return e;
      }
    })();
    for (const raised of [given, fromVariable]) {
      expect(raised).toBeInstanceOf(ConfigurationError);
      expect(String((raised as Error).message)).toMatch(/FAIL_CLOSED/);
      expect(String((raised as Error).message)).toMatch(/FAIL_OPEN/);
    }
  });

  it('test_held_records_are_pushed_oldest_first_before_the_next_send', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, down);
    on(PUSH, down);
    on(PUSH, takes);
    on(EVALUATE, decides);
    const h = hiitl(store);
    const first = (await h.evaluate({ action: 'send_email' })) as Decision;
    const second = (await h.evaluate({ action: 'send_email' })) as Decision;
    expect(held(store)).toEqual([first.action_id, second.action_id]);

    const third = (await h.evaluate({ action: 'send_email' })) as Decision;
    expect(third.decision).toBe('ALLOW');
    expect(sent.map((s) => s.path)).toEqual([EVALUATE, PUSH, PUSH, EVALUATE]);
    expect(pushed(1), 'oldest first').toEqual([first.action_id, second.action_id]);
    expect(held(store), 'a pushed record is marked synced').toEqual([]);
  });

  it('test_an_unanswered_push_sends_nothing_further', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, down);
    on(PUSH, () => {
      throw Object.assign(new Error('This operation was aborted'), { name: 'AbortError' });
    });
    const h = hiitl(store);
    const first = (await h.evaluate({ action: 'send_email' })) as Decision;
    const second = (await h.evaluate({ action: 'send_email' })) as Decision;
    expect(sent.map((s) => s.path), 'no evaluate is sent behind an unanswered push').toEqual([EVALUATE, PUSH]);
    expect([second.decision, second.allowed, second.reason_codes]).toEqual([
      'CONTROL_PLANE_UNAVAILABLE', false, ['CONTROL_PLANE_TIMEOUT']]);
    expect(held(store), 'the call is recorded, and nothing held is dropped').toEqual([first.action_id, second.action_id]);
  });

  it('test_a_refused_record_stays_held', async () => {
    const store = path.join(dir, 'audit.db');
    const refuses: Answer = (body) => json({
      accepted: 0, duplicates: 0,
      errors: body.records.map((r: Row) => ({
        event_id: r.event_id, code: 'INSERT_FAILED', message: 'The audit record was not stored',
      })),
    });
    on(EVALUATE, down);
    on(PUSH, refuses);
    on(EVALUATE, decides);
    on(EVALUATE, decides);
    let h = hiitl(store);
    const first = (await h.evaluate({ action: 'send_email' })) as Decision;
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await h.evaluate({ action: 'send_email' });
    await h.evaluate({ action: 'send_email' });
    expect(sent.map((s) => s.path), 'a refused record is not re-sent before every call')
      .toEqual([EVALUATE, PUSH, EVALUATE, EVALUATE]);
    expect(held(store), 'a refused record is never dropped').toEqual([first.action_id]);
    expect(warn.mock.calls.filter((c) => String(c[0]).includes('INSERT_FAILED')).length).toBe(1);

    on(PUSH, takes);
    on(EVALUATE, decides);
    h = hiitl(store);
    await h.evaluate({ action: 'send_email' });
    expect(sent.slice(4).map((s) => s.path), 'constructed again, the client pushes it').toEqual([PUSH, EVALUATE]);
    expect(held(store)).toEqual([]);
  });

  it('test_held_records_survive_a_restart', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, down);
    const first = hiitl(store);
    const kept = (await first.evaluate({ action: 'send_email' })) as Decision;
    first.close();

    on(PUSH, takes);
    on(EVALUATE, decides);
    await hiitl(store).evaluate({ action: 'send_email' });
    expect(sent.map((s) => s.path)).toEqual([EVALUATE, PUSH, EVALUATE]);
    expect(pushed()).toEqual([kept.action_id]);
    expect(held(store)).toEqual([]);
  });

  it('test_a_store_that_cannot_write_blocks_in_either_mode', async () => {
    fs.writeFileSync(path.join(dir, 'file'), "a file where the store's directory would be");
    const store = path.join(dir, 'file', 'audit.db');
    for (const mode of ['FAIL_CLOSED', 'FAIL_OPEN']) {
      on(EVALUATE, down);
      const d = (await hiitl(store, { fail_mode: mode }).evaluate({ action: 'send_email' })) as Decision;
      expect([d.decision, d.allowed, d.reason_codes, d.error?.code], mode).toEqual([
        'BLOCK', false, ['AUDIT_WRITE_FAILED'], 'AUDIT_WRITE_FAILED']);
    }
  });

  it('test_the_hosted_record_takes_the_sdks_declaration', async () => {
    const store = path.join(dir, 'audit.db');
    on(EVALUATE, down);
    const d = (await hiitl(store, { redact_fields: ['parameters.to', 'parameters.cc'] }).evaluate({
      action: 'send_email', parameters: { to: 'ops@example.com', subject: 'Q3' },
    })) as Decision;
    read(store, (log) => {
      const [record, ...more] = log.lifecycle(ORG_ID, 'dev', d.action_id) as Row[];
      expect(more).toEqual([]);
      expect(record.envelope.parameters).toEqual({ to: MARKER, subject: 'Q3' });
      expect(record.redaction).toEqual({ absent: ['parameters.cc'] });
      expect(log.verifyIntegrity(record.event_id)).toBe(true);
    });
  });
});
