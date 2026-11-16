/**
 * Row 145 (HTL-20): an error says what happened and what to do (Principle 11), the same way on every path.
 *
 * - An invalid `operation` throws EnvelopeValidationError naming the valid operations, in local and hosted mode
 *   alike, before anything is sent.
 * - The cold-start message names the mode the client keeps: under RESPECT_POLICY an empty policy set blocks every
 *   call, and the message says so.
 * - The hosted client and the sync client read the service's one error shape (docs-site/api/overview.mdx "Error
 *   format"): `{"detail": {"error", "message", "details"}}`, a 422's list of field problems, or a message string.
 *   A retryable status's last answer is read the same way.
 *
 * python/hiitl/sdk/tests/test_row145.py holds the same cells (Principle 10).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { Operation } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { EnvelopeValidationError, ServerError, SyncError } from '../../src/exceptions.js';
import { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const KEY = 'sk_test_1234567890abcdef';
const SERVER = 'https://ecp.example';

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row145-'));
});

afterEach(() => {
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  rmSync(dir, { recursive: true, force: true });
});

function hosted(): HIITL {
  return new HIITL({
    api_key: KEY, server_url: SERVER, evaluation: 'remote', max_retries: 0, signature_key: 's'.repeat(32),
    audit_db_path: ':memory:', // its own store (row 192)
  });
}

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

async function operationError(client: HIITL): Promise<string> {
  try {
    await client.evaluate({ action: 'refund', operation: 'refund_everything' as Operation });
  } catch (e) {
    expect(e).toBeInstanceOf(EnvelopeValidationError);
    return (e as Error).message;
  }
  throw new Error('no error was thrown');
}

describe('an invalid operation', () => {
  it('names the valid ones in every mode, before anything is sent', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const local = await operationError(new HIITL({ audit_db_path: ':memory:' }));
    const remote = await operationError(hosted());
    expect(local).toBe(remote);
    for (const op of Object.values(Operation)) expect(local).toContain(op);
    expect(local).toContain("'execute'");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('the cold-start message', () => {
  it.each([
    ['OBSERVE_ALL', 'every action is observed and allowed'],
    ['RESPECT_POLICY', 'every action is blocked (NO_MATCHING_RULE)'],
  ] as const)('names the mode the client keeps: %s', async (mode, outcome) => {
    vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(false);
    vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const h = new HIITL({ api_key: KEY, mode, cache_dir: path.join(dir, 'cache'), audit_db_path: ':memory:' });
    await (h as unknown as { _initialSyncPromise: Promise<boolean> })._initialSyncPromise;
    const cold = warn.mock.calls.map((c) => String(c[0])).filter((m) => m.includes('Cold-start sync'));
    expect(cold).toHaveLength(1);
    expect(cold[0]).toContain(`running in ${mode}`);
    expect(cold[0]).toContain(outcome);
    const d = await h.evaluate({ action: 'refund' });
    expect(d.allowed).toBe(mode === 'OBSERVE_ALL');
    h.close();
  });
});

const SHAPES: Array<[string, number, unknown, string, string]> = [
  ['object', 404, { detail: { error: 'POLICY_NOT_FOUND', message: 'No active policy in this environment.' } },
    'POLICY_NOT_FOUND', 'No active policy in this environment.'],
  ['5xx-with-request-id', 500, { detail: { error: 'INTERNAL_ERROR', message: 'Retry.', details: { request_id: 'req_1' } } },
    'INTERNAL_ERROR', 'Retry.'],
  ['422-list', 422, { detail: [{ loc: ['body', 'action'], msg: 'Field required', type: 'missing' }] },
    'VALIDATION_ERROR', 'body.action: Field required'],
  ['string', 403, { detail: 'Insufficient permissions' }, 'UNKNOWN_ERROR', 'Insufficient permissions'],
  ['not-the-shape', 400, { detail: { error: { code: 'NESTED' }, message: 7 } }, 'UNKNOWN_ERROR', 'Server returned HTTP 400'],
  ['retryable-last-answer', 503, { detail: { error: 'UNAVAILABLE', message: 'Try again shortly.' } },
    'UNAVAILABLE', 'Try again shortly.'],
];

describe('the hosted client', () => {
  it.each(SHAPES)('reads each error shape: %s', async (_id, status, body, code, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(status, body)));
    const err = await hosted().evaluate({ action: 'refund' }).catch((e) => e);
    expect(err).toBeInstanceOf(ServerError);
    expect([err.status_code, err.error_code, err.server_message]).toEqual([status, code, message]);
  });
});

describe('the sync client', () => {
  it.each([
    ['object', { detail: { error: 'INSERT_FAILED', message: 'The audit record was not stored.' } },
      'The audit record was not stored.'],
    ['422-list', { detail: [{ loc: ['body', 'records', 0], msg: 'Field required' }] }, 'body.records.0: Field required'],
    ['string', { detail: 'Not authenticated' }, 'Not authenticated'],
    ['no-message', { detail: { error: 'X' } }, '{"error":"X"}'],
  ] as const)('reads the same shapes: %s', async (_id, body, message) => {
    const client = new SyncClient({
      server_url: SERVER, api_key: KEY, org_id: 'org_x0000000000000000', environment: 'dev', max_retries: 0,
      fetchImpl: async () => answer(400, body),
    });
    const err = await client.downloadPolicies().catch((e) => e);
    expect(err).toBeInstanceOf(SyncError);
    expect(err.message).toBe(`Sync error [policy]: Policy download failed with status 400: ${message}`);
  });
});
