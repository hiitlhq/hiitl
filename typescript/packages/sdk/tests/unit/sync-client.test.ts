/**
 * Unit tests for SyncClient (Block 5c).
 *
 * Parity target: `python/hiitl/sdk/tests/test_sync_client.py`.
 *
 * Strategy: inject a fake `fetch` implementation via the SyncClient
 * constructor's `fetchImpl` option. Each test programs the fake to
 * return specific responses (200, 304, 429, network error) and asserts
 * the client's behavior — including retry counts, header propagation,
 * gzip compression, and 304-handling.
 *
 * We use vitest's fake timers so retry backoff doesn't actually sleep.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { gunzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaredTable, requiredMatch } from '../../../../test-support/declarations.js';

import pkg from '../../package.json';

import { SyncClient, backoffWithJitter } from '../../src/sync-client.js';
import { SyncError } from '../../src/exceptions.js';
import type { Logger } from '../../src/logger.js';

const silentLogger: Logger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
};

/**
 * Build a SyncClient that records every fetch call and returns
 * responses from a programmable queue. Each queued entry is either
 * a Response or a thrown error (timeout / TypeError simulation).
 */
function makeClient(queue: Array<Response | Error>): {
  client: SyncClient;
  calls: Array<{ url: string; method: string; headers: Headers; body?: BodyInit | null }>;
} {
  const calls: Array<{ url: string; method: string; headers: Headers; body?: BodyInit | null }> = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : (input as Request).url;
    const headers = new Headers(init?.headers);
    calls.push({
      url,
      method: init?.method ?? 'GET',
      headers,
      body: init?.body ?? null,
    });
    const next = queue.shift();
    if (!next) {
      throw new Error('Test bug: fetch called more times than the queue allows');
    }
    if (next instanceof Error) throw next;
    return next;
  };

  const client = new SyncClient({
    server_url: 'https://api.test',
    api_key: 'k_test',
    org_id: 'org_test',
    environment: 'dev',
    timeout: 1, // 1s — short, but fake timers mean it doesn't matter
    max_retries: 2,
    logger: silentLogger,
    fetchImpl,
  });

  return { client, calls };
}

/** Construct a `Response` with a JSON body. */
function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('SyncClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ─── headers ────────────────────────────────────────────────────────────

  it('sends the required auth + tenant headers on every request', async () => {
    const { client, calls } = makeClient([
      jsonResponse(200, { kill_switches: [], server_time: '2026-05-14T00:00:00Z' }),
    ]);
    await client.pollKillSwitches();
    const headers = calls[0].headers;
    expect(headers.get('Authorization')).toBe('Bearer k_test');
    expect(headers.get('X-HIITL-Org-Id')).toBe('org_test');
    expect(headers.get('X-HIITL-Environment')).toBe('dev');
    expect(headers.get('X-HIITL-SDK-Version')).toBe(pkg.version);
    expect(headers.get('X-HIITL-SDK-Language')).toBe('typescript');
    expect(headers.get('Accept-Encoding')).toBe('gzip');
  });

  // ─── audit upload ───────────────────────────────────────────────────────

  it('uploadAudit returns the parsed accepted/duplicates/errors counts', async () => {
    const { client } = makeClient([
      jsonResponse(200, { accepted: 5, duplicates: 1, errors: [] }),
    ]);
    const result = await client.uploadAudit([{ event_id: 'evt_1' }], 1);
    expect(result).toEqual({ accepted: 5, duplicates: 1, errors: [] });
  });

  it('uploadAudit compresses payloads larger than 1 KB with gzip', async () => {
    // Build a records array whose serialized JSON exceeds 1 KB.
    const big = Array.from({ length: 50 }, (_, i) => ({
      event_id: `evt_${i}_${'x'.repeat(40)}`,
    }));
    const { client, calls } = makeClient([
      jsonResponse(200, { accepted: 50, duplicates: 0, errors: [] }),
    ]);
    await client.uploadAudit(big, 1);

    expect(calls[0].headers.get('Content-Encoding')).toBe('gzip');
    expect(calls[0].body).toBeInstanceOf(Buffer);
    const compressed = calls[0].body as Buffer;
    const roundtrip = JSON.parse(gunzipSync(compressed).toString('utf-8'));
    expect(roundtrip.records).toHaveLength(50);
    expect(roundtrip.sync_sequence).toBe(1);
  });

  it('uploadAudit raises SyncError("audit") on non-200', async () => {
    const { client } = makeClient([
      jsonResponse(500, { detail: { message: 'something broke' } }),
    ]);
    await expect(client.uploadAudit([{}], 1)).rejects.toMatchObject({
      name: 'SyncError',
      channel: 'audit',
    });
  });

  // ─── policy download with ETag ─────────────────────────────────────────

  it('downloadPolicies sends If-None-Match when etag is provided', async () => {
    const { client, calls } = makeClient([
      jsonResponse(200, { policies: [], version: 'v1', etag: 'abc' }),
    ]);
    await client.downloadPolicies('abc');
    expect(calls[0].headers.get('If-None-Match')).toBe('"abc"');
  });

  it('downloadPolicies returns null on 304 Not Modified', async () => {
    const { client } = makeClient([new Response(null, { status: 304 })]);
    const result = await client.downloadPolicies('abc');
    expect(result).toBeNull();
  });

  it('downloadPolicies parses success response shape', async () => {
    const { client } = makeClient([
      jsonResponse(200, {
        policies: [{ name: 'p1' }],
        version: 'v2',
        etag: 'def',
      }),
    ]);
    const result = await client.downloadPolicies(null);
    expect(result).toEqual({ policies: [{ name: 'p1' }], version: 'v2', etag: 'def' });
  });

  // ─── route download mirror ──────────────────────────────────────────────

  it('downloadRoutes returns null on 304 and parses shape on 200', async () => {
    const r1 = makeClient([new Response(null, { status: 304 })]);
    expect(await r1.client.downloadRoutes('etag1')).toBeNull();

    const r2 = makeClient([jsonResponse(200, { routes: [{ name: 'r1' }], etag: 'e2' })]);
    expect(await r2.client.downloadRoutes(undefined)).toEqual({
      routes: [{ name: 'r1' }],
      etag: 'e2',
    });
  });

  // ─── retry semantics ────────────────────────────────────────────────────

  it('retries 429/503 responses and succeeds on the retry', async () => {
    const { client, calls } = makeClient([
      jsonResponse(503, { detail: 'unavailable' }),
      jsonResponse(200, { kill_switches: [], server_time: 't' }),
    ]);
    const promise = client.pollKillSwitches();
    // Advance through the backoff delay so the retry fires.
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(result.server_time).toBe('t');
    expect(calls).toHaveLength(2);
  });

  it('returns the final response after exhausting retries on retryable status', async () => {
    // max_retries=2 → 1 initial attempt + 2 retries = 3 total. After all
    // three return 503, the loop returns the last response unchanged; the
    // caller's status check then raises SyncError.
    //
    // We attach the rejection assertion BEFORE advancing timers — if the
    // rejection fires during timer advancement and no .catch is attached
    // yet, Node logs an unhandled-rejection warning. `expect(...).rejects`
    // attaches a handler synchronously, so attaching first is safe.
    const { client, calls } = makeClient([
      jsonResponse(503, {}),
      jsonResponse(503, {}),
      jsonResponse(503, {}),
    ]);
    const pendingAssertion = expect(client.pollKillSwitches()).rejects.toMatchObject({
      name: 'SyncError',
      channel: 'kill_switches',
    });
    await vi.runAllTimersAsync();
    await pendingAssertion;
    expect(calls).toHaveLength(3);
  });

  it('does NOT retry non-retryable status codes (e.g. 401)', async () => {
    const { client, calls } = makeClient([jsonResponse(401, { detail: 'unauthorized' })]);
    await expect(client.pollKillSwitches()).rejects.toMatchObject({
      name: 'SyncError',
    });
    expect(calls).toHaveLength(1);
  });

  it('retries on AbortError (request timeout) and surfaces SyncError("transport") when exhausted', async () => {
    const abortError = new DOMException('aborted', 'AbortError');
    const { client, calls } = makeClient([abortError, abortError, abortError]);
    const pendingAssertion = expect(client.pollKillSwitches()).rejects.toMatchObject({
      name: 'SyncError',
      channel: 'transport',
    });
    await vi.runAllTimersAsync();
    await pendingAssertion;
    expect(calls).toHaveLength(3);
  });

  // ─── backoff distribution ───────────────────────────────────────────────

  it('backoffWithJitter applies the declared formula to each controlled draw', () => {
    const spec = readFileSync(join(__dirname, '../../../../../docs/specs/sync_engine.md'), 'utf8');
    const rows = declaredTable(spec, '### Retry Strategy');
    const formula = requiredMatch(spec, /^Jitter formula: `delay \* \(([\d.]+) \+ random\(\) \* ([\d.]+)\)`$/m,
      'sync_engine.md jitter formula');
    const [offset, scale] = formula.slice(1).map(Number);
    const fixed = rows.filter(([attempt]) => !attempt.includes('+'));
    const cap = Number.parseFloat(rows.find(([, delay]) => delay.includes('(max)'))![1]);
    const start = Number.parseFloat(fixed[0][1]);
    const factor = Number.parseFloat(fixed[1][1]) / start;
    const cappedAttempt = Math.ceil(Math.log(cap / start) / Math.log(factor));
    const cases = [...fixed.map(([attempt, base]) => [Number(attempt) - 1, Number.parseFloat(base)]),
      [cappedAttempt, cap], [cappedAttempt + 1, cap]];
    const random = vi.spyOn(Math, 'random');
    try {
      for (const [attempt, base] of cases) {
        for (const draw of [0, 0.25, 0.75, 1 - Number.EPSILON]) {
          random.mockReturnValue(draw);
          expect(backoffWithJitter(attempt)).toBe(base * (offset + draw * scale));
        }
      }
    } finally {
      random.mockRestore();
    }
  });
});
