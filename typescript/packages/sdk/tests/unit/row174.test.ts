/**
 * Row 174 (HTL-22): an unreachable hosted service is the outage decision, behind the circuit breaker.
 *
 * decision_response.md, Error Handling: "`CONTROL_PLANE_UNAVAILABLE` - ECP is unreachable", its causes and its
 * "An outage" bullet; Example 9's `metadata {fail_mode, circuit_breaker_state}` and its caller action, "Circuit
 * breaker is open - subsequent calls will fail fast". R-0002: "Configurable fail mode: FAIL_CLOSED (default) or
 * FAIL_OPEN", "circuit breaker". The outage's record and the fail mode turned with Stop B (HTL-23 row 192, ruled
 * 2026-11-06). Design: the HTL-22 test design, row 174; the HTL-23 test design, row 192, behaviors 1 and
 * 2. Mirrors python/hiitl/sdk/tests/test_row174.py.
 */

import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ERROR_MESSAGES, FAIL_OPEN_MESSAGES, envelopeHash, envelopeSignature } from '@hiitl/core';
import { ENVELOPE_SCHEMA_VERSION } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { CircuitState } from '../../src/circuit-breaker.js';
import { createHostedConfig } from '../../src/config.js';
import { HostedClient } from '../../src/http-client.js';
import { HIITL } from '../../src/client.js';
import { ServerError } from '../../src/exceptions.js';

const SPEC = readFileSync(join(__dirname, '../../../../../docs/specs/decision_response.md'), 'utf8');

const ORG_ID = 'org_r174outage000000000';
const SERVER = 'https://ecp.r174.example.com';
const API_KEY = 'sk_test_r174outage0000';
const SECRET = 'r174-signing-secret-0123456789abcdef';

/** What a proxy in front of the service answers when the service behind it does not. */
const GATEWAY_PAGE = '<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center></body></html>';

/**
 * The service's answer to the push of a held record (sync_engine.md §2.1). Row 192 (Stop B (i)): before its next call is
 * sent, the client pushes the outage's record; these cells read the call behind it.
 */
const PUSHED = { accepted: 1, duplicates: 0, errors: [] };

const BLOCK_DECISION = {
  action_id: 'act_r174outage000000000000', decision: 'BLOCK', allowed: false,
  reason_codes: ['AMOUNT_OVER_LIMIT'], policy_version: 'v1.0.0', timing: { total_ms: 1.0 },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

/** An outage is recorded at `audit_db_path` (row 192): each cell's store is its own. */
let dir: string;
const store = (): string => join(dir, 'audit.db');

function client(overrides: Record<string, unknown> = {}): HostedClient {
  return new HostedClient(createHostedConfig({
    environment: 'dev', agent_id: 'r174-agent', org_id: ORG_ID, api_key: API_KEY, server_url: SERVER,
    audit_db_path: store(), ...overrides,
  }));
}

/** A signed envelope as HIITL builds it (the HostedClient's input). */
function envelope(): Envelope {
  const env: Record<string, unknown> = {
    schema_version: ENVELOPE_SCHEMA_VERSION, org_id: ORG_ID, environment: 'dev', agent_id: 'r174-agent',
    action_id: 'act_r174outage000000000000', idempotency_key: 'idem_r174', action: 'send_email',
    operation: 'execute', timestamp: '2026-11-05T12:00:00.000Z', target: {}, parameters: {},
    signature_version: 'hmac-sha256-v1',
  };
  env.signature = envelopeSignature(SECRET, env);
  return env as unknown as Envelope;
}

function hiitl(overrides: Record<string, unknown> = {}): HIITL {
  return new HIITL({
    environment: 'dev', agent_id: 'r174-agent', org_id: ORG_ID, api_key: API_KEY, server_url: SERVER,
    evaluation: 'remote', signature_key: SECRET, audit_db_path: store(), ...overrides,
  });
}

/** The records the store at `audit_db_path` holds for an action, in its own form. */
function recorded(actionId: string): Row[] {
  const log = new AuditLogger(store());
  try {
    return log.lifecycle(ORG_ID, 'dev', actionId) as Row[];
  } finally {
    log.close();
  }
}

function answer(body: Record<string, unknown>, status: number): Response {
  return { status, ok: status < 300, json: () => Promise.resolve(body), headers: new Headers() } as Response;
}

/** The causes Error Handling's CONTROL_PLANE_UNAVAILABLE line names, the decision itself left out. */
function causes(): Set<string> {
  const line = SPEC.match(/^- `CONTROL_PLANE_UNAVAILABLE` - .*$/m)![0];
  return new Set([...line.matchAll(/`([A-Z_]+)`/g)].map((m) => m[1]).filter((c) => c !== 'CONTROL_PLANE_UNAVAILABLE'));
}

function schemaMetadata(): any {
  return JSON.parse(SPEC.split('### JSON Schema')[1].split('```json')[1].split('```')[0]).properties.metadata;
}

/**
 * What evaluate answered, which for an outage is a decision, never an exception. The retries' backoff is timers,
 * run here: the cells read what the client answered, not how long it waited.
 */
async function decided(p: Promise<Decision> | Decision): Promise<Decision> {
  const answered = Promise.resolve(p).catch((e: unknown) => e);
  await vi.runAllTimersAsync();
  const d = await answered;
  expect(d, 'an outage is a decision, never an exception').not.toBeInstanceOf(Error);
  return d as Decision;
}

describe('row 174: the outage decision', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    vi.useFakeTimers();
    dir = mkdtempSync(join(tmpdir(), 'row174-'));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    rmSync(dir, { recursive: true, force: true });
  });

  it('an unreachable service is the outage decision', async () => {
    fetchSpy.mockRejectedValue(new TypeError('fetch failed: connect ECONNREFUSED r174-host'));
    const env = envelope();
    const d = await decided(client({ max_retries: 0 }).evaluate(env));

    expect([d.decision, d.allowed, d.reason_codes, d.error?.code]).toEqual([
      'CONTROL_PLANE_UNAVAILABLE', false, ['CONTROL_PLANE_UNREACHABLE'], 'CONTROL_PLANE_UNAVAILABLE',
    ]);
    expect(d.error?.message).toBe(ERROR_MESSAGES.CONTROL_PLANE_UNREACHABLE);
    expect(d.error?.message, 'the cause is logged, not shown').not.toContain('r174-host');
    expect(d.error?.message).not.toContain(SERVER);
    expect(d.metadata).toEqual({ fail_mode: 'FAIL_CLOSED', circuit_breaker_state: 'closed' });
    expect(d.envelope_hash).toBe(envelopeHash(env as unknown as Record<string, unknown>));
  });

  it('a timeout on every attempt is control plane timeout', async () => {
    const retries = 2;
    fetchSpy.mockRejectedValue(Object.assign(new Error('This operation was aborted'), { name: 'AbortError' }));
    const d = await decided(client({ max_retries: retries }).evaluate(envelope()));

    expect(fetchSpy, 'every attempt the client is configured for').toHaveBeenCalledTimes(retries + 1);
    expect([d.decision, d.allowed, d.reason_codes]).toEqual(['CONTROL_PLANE_UNAVAILABLE', false, ['CONTROL_PLANE_TIMEOUT']]);
    expect(d.error?.message).toBe(ERROR_MESSAGES.CONTROL_PLANE_TIMEOUT);
  });

  it('a transient status the service did not answer is an outage', async () => {
    const c = client({ max_retries: 0 });
    fetchSpy.mockResolvedValueOnce(new Response(GATEWAY_PAGE, { status: 502, headers: { 'Content-Type': 'text/html' } }));
    const outage = await decided(c.evaluate(envelope()));
    expect([outage.decision, outage.reason_codes]).toEqual(['CONTROL_PLANE_UNAVAILABLE', ['CONTROL_PLANE_UNREACHABLE']]);

    fetchSpy.mockResolvedValueOnce(answer(PUSHED, 200)); // the outage's record, pushed before the next call (row 192)
    fetchSpy.mockResolvedValueOnce(answer({ detail: { error: 'UNAVAILABLE', message: 'Try again.' } }, 503));
    const served = await c.evaluate(envelope()).catch((e: unknown) => e); // no retry, so no timer to run
    expect(served).toBeInstanceOf(ServerError);
    expect([(served as ServerError).status_code, (served as ServerError).error_code],
      'the service s error format is the service s answer (row 145)').toEqual([503, 'UNAVAILABLE']);

    fetchSpy.mockResolvedValueOnce(answer(BLOCK_DECISION, 503));
    const answered = await decided(c.evaluate(envelope()));
    expect([answered.decision, answered.reason_codes], 'a decision is the service s answer, on any status')
      .toEqual(['BLOCK', ['AMOUNT_OVER_LIMIT']]);

    fetchSpy.mockResolvedValueOnce(answer({ detail: 'Internal server error' }, 500));
    const err = await c.evaluate(envelope()).catch((e: unknown) => e); // no retry, so no timer to run
    expect(err).toBeInstanceOf(ServerError);
    expect((err as ServerError).status_code, 'a status the client does not retry on is the service s answer').toBe(500);

    fetchSpy.mockResolvedValueOnce(new Response(GATEWAY_PAGE, { status: 429, headers: { 'Content-Type': 'text/html' } }));
    const limited = await decided(c.evaluate(envelope()));
    expect([limited.decision, limited.reason_codes],
      '429 is in the transient set: one the service did not answer is the outage (row 199)')
      .toEqual(['CONTROL_PLANE_UNAVAILABLE', ['CONTROL_PLANE_UNREACHABLE']]);
  });

  it('the breaker opens and the next call fails fast', async () => {
    const c = client({ max_retries: 0 });
    const threshold: number = (c as any).breaker.failure_threshold;
    fetchSpy.mockRejectedValue(new TypeError('fetch failed'));
    const states: string[] = [];
    for (let i = 0; i < threshold; i++) states.push((await decided(c.evaluate(envelope()))).metadata!.circuit_breaker_state);
    expect(states).toEqual([...Array(threshold - 1).fill('closed'), 'open']);

    const sent = fetchSpy.mock.calls.length;
    const held: Decision = await decided(c.evaluate(envelope()));
    expect(fetchSpy.mock.calls.length, 'an open breaker sends no request').toBe(sent);
    expect([held.decision, held.allowed, held.reason_codes]).toEqual(['CONTROL_PLANE_UNAVAILABLE', false, ['CIRCUIT_BREAKER_OPEN']]);
    expect(held.error?.message).toBe(ERROR_MESSAGES.CIRCUIT_BREAKER_OPEN);
    expect(held.metadata?.circuit_breaker_state).toBe('open');
  });

  it('after the reset interval a probe is sent and an answer closes it', async () => {
    const c = client({ max_retries: 0 });
    const breaker = (c as any).breaker;
    for (let i = 0; i < breaker.failure_threshold; i++) breaker.recordFailure();
    expect((await decided(c.evaluate(envelope()))).reason_codes).toEqual(['CIRCUIT_BREAKER_OPEN']);

    breaker._lastFailureTime -= breaker.reset_timeout; // the reset interval has passed
    fetchSpy.mockResolvedValueOnce(answer(PUSHED, 200)); // the held-back call's record, pushed first (row 192)
    fetchSpy.mockResolvedValueOnce(answer(BLOCK_DECISION, 200));
    const probe = await decided(c.evaluate(envelope()));
    const evaluated = fetchSpy.mock.calls.filter(([url]) => new URL(url as string).pathname === '/v1/evaluate');
    expect(evaluated.length, 'one call probes the service').toBe(1);
    expect(probe.decision).toBe('BLOCK');
    expect(breaker.state).toBe(CircuitState.CLOSED);
  });

  it('the causes are the spec s', () => {
    const listed = causes();
    expect([...listed].sort()).toEqual(['CIRCUIT_BREAKER_OPEN', 'CONTROL_PLANE_TIMEOUT', 'CONTROL_PLANE_UNREACHABLE']);
    for (const cause of listed) expect(cause in ERROR_MESSAGES, `${cause} has its authored message`).toBe(true);
    expect([...schemaMetadata().properties.circuit_breaker_state.enum].sort(), 'the breaker s states are the schema s')
      .toEqual(Object.values(CircuitState).sort());
  });

  it('evaluate returns the outage decision', async () => {
    fetchSpy.mockRejectedValue(new TypeError('fetch failed'));
    const h = hiitl();
    const d = await decided(h.evaluate({ action: 'send_email', parameters: { to: 'ops@example.com' } }));
    h.close();
    expect([d.decision, d.allowed]).toEqual(['CONTROL_PLANE_UNAVAILABLE', false]);
    expect(d.metadata?.fail_mode).toBe('FAIL_CLOSED');
  });

  // Stop B (i), ruled 2026-11-06 (HTL-23 row 192, behavior 1): the outage decision is recorded in the hosted
  // client's local store, the envelope it built and the decision, read in the record's own form
  it('an outage the hosted client meets is recorded', async () => {
    fetchSpy.mockRejectedValue(new TypeError('fetch failed'));
    const h = hiitl({ max_retries: 0 });
    const d = await decided(h.evaluate({ action: 'send_email' }));
    h.close();
    const records = recorded(d.action_id);
    expect(records.map((r) => r.decision_type)).toEqual(['CONTROL_PLANE_UNAVAILABLE']);
    expect(records[0].decision.metadata).toEqual({ fail_mode: 'FAIL_CLOSED', circuit_breaker_state: 'closed' });
    expect(records[0].envelope.action).toBe('send_email');
  });

  // Stop B (ii), ruled 2026-11-06 (HTL-23 row 192, behavior 2): under FAIL_OPEN the outage decision is `allowed`
  // true, `error.code` the decision and `error.message` the warning; it is logged at warning and recorded
  it('fail open is a mode the client takes', async () => {
    fetchSpy.mockRejectedValue(new TypeError('fetch failed'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const d = await decided(client({ max_retries: 0, fail_mode: 'FAIL_OPEN' }).evaluate(envelope()));
    expect([d.decision, d.allowed, d.reason_codes]).toEqual(['CONTROL_PLANE_UNAVAILABLE', true, ['CONTROL_PLANE_UNREACHABLE']]);
    expect([d.error?.code, d.error?.message]).toEqual([
      'CONTROL_PLANE_UNAVAILABLE', FAIL_OPEN_MESSAGES.CONTROL_PLANE_UNREACHABLE]);
    expect(d.metadata?.fail_mode).toBe('FAIL_OPEN');
    expect(warn.mock.calls.filter((c) => String(c[0]).includes('fail-open')).length, 'logged at warning').toBe(1);
    const [record] = recorded(d.action_id);
    expect([record.decision.allowed, record.decision.error]).toEqual([
      true, { code: 'CONTROL_PLANE_UNAVAILABLE', message: FAIL_OPEN_MESSAGES.CONTROL_PLANE_UNREACHABLE }]);
  });
});
