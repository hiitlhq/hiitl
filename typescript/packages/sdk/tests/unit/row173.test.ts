/**
 * Row 173 (HTL-22): `HIITL_TIMEOUT` in seconds, in both SDKs.
 *
 * Trevor's ruling on HTL-20: "`HIITL_TIMEOUT` in seconds in both SDKs, by Principle 10 and sync_engine §9"; §9 states
 * its intervals and timeouts in seconds. Design: the HTL-22 test design, row 173, behaviors 1-3. The Python side is
 * python/hiitl/sdk/tests/test_row173.py, with the same value.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';

const SECONDS = '2.5'; // the value test_row173.py sets
const page = readFileSync(path.join(__dirname, '../../../../../docs-site/sdk/typescript-configuration.mdx'), 'utf8');
const [, PAGE_DEFAULT] = /<ParamField path="timeout" type="\w+" default="([^"]+)">/.exec(page)!;

let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // each cell sets the variables it reads; none comes from the shell that runs the suite
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** A hosted client, or what its construction threw. */
function hosted(extra: Record<string, unknown> = {}): { client?: HIITL; refused?: unknown } {
  try {
    return {
      client: new HIITL({
        api_key: 'sk_test_row173', server_url: 'https://ecp.example.com', evaluation: 'remote',
        signature_key: 'test-signing-secret-0123456789abcdef', max_retries: 0, audit_db_path: ':memory:', ...extra,
      }),
    };
  } catch (refused) {
    return { refused };
  }
}

describe('row 173: HIITL_TIMEOUT in seconds, in both SDKs', () => {
  it('HIITL_TIMEOUT=2.5 leaves the request pending at 2499 ms and aborts it at 2500 ms', async () => {
    process.env.HIITL_TIMEOUT = SECONDS;
    const { client, refused } = hosted();
    expect(refused).toBeUndefined();

    vi.useFakeTimers();
    // a server that never answers: the request ends only when the client aborts it
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal!.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    })));
    let outcome: unknown = 'pending';
    const done = client!.evaluate({ action: 'send_email' }).then((d) => { outcome = d; }, (e) => { outcome = e; });

    await vi.advanceTimersByTimeAsync(Number(SECONDS) * 1000 - 1);
    expect(outcome).toBe('pending');
    await vi.advanceTimersByTimeAsync(1);
    await done;
    // the abort is the timeout: row 174's outage decision, never a throw
    const d = outcome as { decision: string; reason_codes: string[] };
    expect([d.decision, d.reason_codes]).toEqual(['CONTROL_PLANE_UNAVAILABLE', ['CONTROL_PLANE_TIMEOUT']]);
    client!.close();
  });

  it("with no setting, the timeout is the configuration page's default", () => {
    const { client, refused } = hosted();
    expect(refused).toBeUndefined();
    expect(client!.hostedConfig!.timeout).toBe(Number(PAGE_DEFAULT));
    client!.close();
  });

  it('a value set in milliseconds is refused, saying the unit', () => {
    const { refused } = hosted({ timeout: 5000 });
    expect(refused).toBeInstanceOf(ConfigurationError);
    expect((refused as Error).message).toMatch(/seconds/);
  });
});
