/**
 * Row 180 (HTL-22): the unit suite runs with the network refused.
 *
 * Trevor's ruling on HTL-20: "the unit suites run with the network refused, by the mode table's CI/CD row", the table
 * that names Pure Local the mode for "Dev, CI/CD, air-gapped". Design: the HTL-22 test design, row 180, behaviors 1 and
 * 2. The guard is tests/unit/offline.ts; behavior 3, the exit cell, is this suite passing with it on. Mirrors
 * python/hiitl/sdk/tests/test_row180.py.
 */

import http from 'node:http';
import net from 'node:net';
import { describe, expect, it } from 'vitest';

const PAST_THE_MACHINE = '192.0.2.1'; // TEST-NET-1 (RFC 5737): documentation only, routed nowhere
const NAMED = 'api.example.invalid'; // RFC 6761: a name that never resolves
const UNANSWERED_MS = 2000; // where nothing refuses, the request is given up after this and reports no refusal
// the rule the setup's refusal names; the cell leaves the setup unimported, so the suite's wiring alone installs the guard
const RULE = 'the unit suites run with the network refused';

/** The error that ends a request, or undefined if it completes or is given up. */
async function refusal(request: () => Promise<unknown>): Promise<(Error & { code?: string }) | undefined> {
  try {
    await request();
    return undefined;
  } catch (e) {
    const error = ((e as { cause?: unknown }).cause ?? e) as Error & { code?: string };
    return error.name === 'TimeoutError' ? undefined : error;
  }
}

const REQUESTS: Record<string, (host: string) => Promise<unknown>> = {
  fetch: (host) => fetch(`https://${host}/v1/sync`, { signal: AbortSignal.timeout(UNANSWERED_MS) }),
  http: (host) => new Promise((resolve, reject) => {
    const request = http.get({ host, port: 80, path: '/', timeout: UNANSWERED_MS }, resolve);
    request.on('timeout', () => request.destroy(Object.assign(new Error('unanswered'), { name: 'TimeoutError' })));
    request.on('error', reject);
  }),
  net: (host) => new Promise<void>((resolve, reject) => {
    const socket = net.connect({ host, port: 443 });
    socket.setTimeout(UNANSWERED_MS, () => socket.destroy(Object.assign(new Error('unanswered'), { name: 'TimeoutError' })));
    socket.on('connect', () => { socket.destroy(); resolve(); });
    socket.on('error', reject);
  }),
};

describe('row 180: the unit suite runs with the network refused', () => {
  it.each(Object.keys(REQUESTS))('a connect past the loopback by %s is refused, naming the host and the rule', async (by) => {
    for (const host of [PAST_THE_MACHINE, NAMED]) {
      const refused = await refusal(() => REQUESTS[by](host));

      expect(refused?.code, `${by} to ${host}`).toBe('ECONNREFUSED');
      expect(refused?.message).toContain(host);
      expect(refused?.message).toContain(RULE);
    }
  });

  it('the loopback stays open', async () => {
    const server = http.createServer((_request, response) => response.end('answered'));
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const { port } = server.address() as net.AddressInfo;
    let answered: string | undefined;
    try {
      const refused = await refusal(async () => {
        answered = await (await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(UNANSWERED_MS) })).text();
      });
      expect(refused).toBeUndefined();
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
    expect(answered).toBe('answered');
  });
});
