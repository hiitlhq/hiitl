/**
 * Row 175 (HTL-22): `trace_id` from the active OpenTelemetry span; `correlation_id` an `evaluate()` option.
 *
 * Trevor's ruling on HTL-20: "`trace_id` from the active OpenTelemetry span when its API can be imported (never a
 * dependency); `correlation_id` an `evaluate()` option. By 'OpenTelemetry compatibility'", event_format.md's "designed
 * with **OpenTelemetry compatibility** in mind"; envelope_schema.json names both "Auto-propagated from execution
 * context". Design: the HTL-22 test design, row 175, behaviors 1-3. Mirrors python/hiitl/sdk/tests/test_row175.py.
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import Module, { createRequire } from 'node:module';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HIITL } from '../../src/client.js';

const TRACE_ID = '0af7651916cd43dd8448eb211c80319c'; // W3C Trace Context's example trace id
const SPAN_ID = 'b7ad6b7169203331';
const CORRELATION_ID = 'req_row175_checkout_42';

// The OpenTelemetry API where it is installed; the span cells skip, naming it, where it is not
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let api: any;
try {
  api = createRequire(import.meta.url)('@opentelemetry/api');
} catch {
  api = undefined;
}

/** The context manager an application's OpenTelemetry setup registers, on AsyncLocalStorage. */
function contextManager() {
  const storage = new AsyncLocalStorage<unknown>();
  return {
    active: () => storage.getStore() ?? api.ROOT_CONTEXT,
    with: (context: unknown, fn: (...args: unknown[]) => unknown, thisArg?: unknown, ...args: unknown[]) =>
      storage.run(context, () => fn.call(thisArg, ...args)),
    bind: (_context: unknown, target: unknown) => target,
    enable() { return this; },
    disable() { storage.disable(); return this; },
  };
}

/** `fn` run with the W3C example span active. */
function inSpan<T>(fn: () => T): T {
  const span = api.trace.wrapSpanContext({ traceId: TRACE_ID, spanId: SPAN_ID, traceFlags: api.TraceFlags.SAMPLED });
  return api.context.with(api.trace.setSpan(api.context.active(), span), fn);
}

/** The envelope the local audit record holds for one evaluate() call. */
function recorded(client: HIITL, extra: Record<string, unknown> = {}): Record<string, unknown> {
  const decision = client.evaluate({ action: 'send_receipt', parameters: { order: 'ord_42' }, ...extra }) as {
    action_id: string;
  };
  const [record] = client.queryAudit({ action_id: decision.action_id }) as { envelope: string }[];
  return JSON.parse(record.envelope);
}

let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // each cell sets the variables it reads; none comes from the shell that runs the suite
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  if (api) api.context.setGlobalContextManager(contextManager());
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  if (api) api.context.disable();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('row 175: trace_id from the active span, correlation_id an evaluate() option', () => {
  it.skipIf(!api)('inside a span the envelope carries its trace id, given @opentelemetry/api', () => {
    const client = new HIITL({ audit_db_path: ':memory:' });
    try {
      const inside = inSpan(() => recorded(client));
      const outside = recorded(client);
      const noOp = api.trace.getTracer('row175').startActiveSpan('no-sdk', (span: { end(): void }) => {
        try {
          return recorded(client);
        } finally {
          span.end();
        }
      });

      expect(inside.trace_id).toBe(TRACE_ID);
      expect(outside).not.toHaveProperty('trace_id');
      expect(noOp).not.toHaveProperty('trace_id');
    } finally {
      client.close();
    }
  });

  it('without the API nothing is set and nothing breaks', async () => {
    // the SDK's import of the API refused; where the test has the API, the call runs inside an active span
    const load = (Module as unknown as { _load: (request: string, ...rest: unknown[]) => unknown })._load;
    vi.spyOn(Module as unknown as { _load: typeof load }, '_load').mockImplementation(function (
      this: unknown, request: string, ...rest: unknown[]
    ) {
      if (request === '@opentelemetry/api') throw new Error(`Cannot find module '${request}'`);
      return load.call(this, request, ...rest);
    });
    vi.resetModules();
    const { HIITL: Refused } = await import('../../src/client.js');
    const client = new Refused({ audit_db_path: ':memory:' });
    let envelope: Record<string, unknown> | undefined;
    let failure: unknown;
    try {
      envelope = api ? inSpan(() => recorded(client)) : recorded(client);
    } catch (e) {
      failure = e; // nothing breaks
    } finally {
      client.close();
      vi.resetModules();
    }

    expect(failure).toBeUndefined();
    expect(envelope!.action).toBe('send_receipt');
    expect(envelope).not.toHaveProperty('trace_id');
  });

  it('a given correlation_id reaches the record', async () => {
    const client = new HIITL({ audit_db_path: ':memory:' });
    try {
      expect(recorded(client, { correlation_id: CORRELATION_ID }).correlation_id).toBe(CORRELATION_ID);
    } finally {
      client.close();
    }

    // hosted: the request body is the envelope the service records
    const fetchSpy = vi.fn().mockResolvedValue({
      status: 200, ok: true, statusText: 'OK', headers: new Headers(),
      json: () => Promise.resolve({ decision: 'ALLOW', allowed: true, reason_codes: ['default_allow'],
        policy_version: '1.0.0', timing: { total_ms: 1 } }),
    } as Response);
    vi.stubGlobal('fetch', fetchSpy);
    const hosted = new HIITL({
      api_key: 'sk_test_row175', server_url: 'https://ecp.example.com', evaluation: 'remote',
      signature_key: 'test-signing-secret-0123456789abcdef', max_retries: 0, audit_db_path: ':memory:',
    });
    try {
      await hosted.evaluate({ action: 'send_receipt', parameters: { order: 'ord_42' }, correlation_id: CORRELATION_ID });
    } finally {
      hosted.close();
    }

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).correlation_id).toBe(CORRELATION_ID);
  });
});
