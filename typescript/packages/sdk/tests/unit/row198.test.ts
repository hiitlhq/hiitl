/**
 * Row 198 (HTL-23): `status()` names the hosted breaker.
 *
 * Ruled 2026-11-06 as the row reads: "no setting until a caller needs one, by 'new things must earn their place', and
 * `status()` reports the hosted breaker's state as it reports the sync breaker's, by 'no silent degradation'". The
 * contract is decision_response.md "Where the error is answered" ("`status()` names its state in both SDKs ...
 * `circuit_breakers.hosted`"). The TypeScript client gains the `status()` Python's has (Principle 10). Design:
 * the HTL-23 test design, row 198. Mirrors python/hiitl/sdk/tests/test_row198.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { Decision } from '@hiitl/core';
import { CircuitBreaker } from '../../src/circuit-breaker.js';
import { HIITL } from '../../src/client.js';
import { HostedModeConfigSchema } from '../../src/config.js';

let dir: string;
let sent: string[];
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row198-'));
  sent = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    sent.push(new URL(url).pathname);
    throw new TypeError('fetch failed');
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  fs.rmSync(dir, { recursive: true, force: true });
});

/** CircuitBreaker's own defaults, read from an instance constructed with none given. */
function defaults(): { failure_threshold: number; reset_timeout: number } {
  const { failure_threshold, reset_timeout } = new CircuitBreaker('defaults');
  return { failure_threshold, reset_timeout };
}

describe('row 198: status() names the hosted breaker', () => {
  it('test_a_hosted_clients_status_names_its_breaker', async () => {
    const h = new HIITL({
      environment: 'dev', agent_id: 'r198-agent', org_id: 'org_r198breaker000000000',
      api_key: 'sk_test_r198breaker0000', server_url: 'https://ecp.r198.example.com', evaluation: 'remote',
      signature_key: 'r198-signing-secret-0123456789abcdef', audit_db_path: path.join(dir, 'audit.db'),
      max_retries: 0,
    });
    try {
      expect(h.status().circuit_breakers?.hosted.state).toBe('closed');

      const threshold = defaults().failure_threshold;
      for (let i = 0; i < threshold; i++) {
        expect(((await h.evaluate({ action: 'send_email' })) as Decision).decision).toBe('CONTROL_PLANE_UNAVAILABLE');
      }
      expect(sent.length, 'each outage is one send').toBe(threshold);

      const breaker = h.status().circuit_breakers?.hosted;
      expect(breaker?.state).toBe('open');
      expect({ failure_threshold: breaker?.failure_threshold, reset_timeout: breaker?.reset_timeout },
        "the breaker runs at the class's defaults").toEqual(defaults());

      const after = (await h.evaluate({ action: 'send_email' })) as Decision;
      expect(after.reason_codes).toEqual(['CIRCUIT_BREAKER_OPEN']);
      expect(sent.length, 'an open breaker sends nothing, not even a push').toBe(threshold);
    } finally {
      h.close();
    }
  });

  it('test_the_hosted_breaker_has_no_setting', () => {
    const options = Object.keys(HostedModeConfigSchema.shape);
    expect(options.filter((o) => o in defaults())).toEqual([]);
  });
});
