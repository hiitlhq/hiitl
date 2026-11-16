/**
 * Row 150 (HTL-22): what a record is, and `recordResult` up to the write, in the SDK.
 *
 * The Stop 1 ruling (HTL-20): "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle
 * fields (`event_type`; `execution_result` on a result), appended against the decision's `action_id`". Principle 4:
 * BLOCKED is terminal. Infrastructure spec 2: "idempotent state transitions". Derived state is computed, never stored:
 * every reader carries `event_type`, and no column holds it. Design: the HTL-22 test design, row 150, behaviors 4-6 and
 * the exit cell (10), which turned with Stop A (HTL-23 row 191: the result's hash covers its `execution_result`, so the
 * write is built). Mirrors python/hiitl/sdk/tests/test_row150.py.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { LIFECYCLE_MESSAGES, eventType, type Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { LifecycleError, ServerError } from '../../src/exceptions.js';

const ORG = 'org_test000000000000000';
const SET = {
  version: 'v1.0.0', name: 'refunds', description: "The refund agent's refunds",
  scope: { org_id: ORG, environment: 'dev' },
};
const RULES = [
  {
    name: 'allow_refunds', priority: 100, description: 'Refunds are allowed',
    conditions: { field: 'action', operator: 'equals', value: 'refund' },
    decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
  },
  {
    name: 'block_wires', priority: 90, description: "Wire transfers are not this agent's",
    conditions: { field: 'action', operator: 'equals', value: 'wire_transfer' },
    decision: 'BLOCK', reason_code: 'WIRES_BLOCKED',
  },
];

const clients: HIITL[] = [];
const dirs: string[] = [];

function client(opts: Record<string, unknown> = {}): HIITL {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row150-'));
  dirs.push(dir);
  const file = path.join(dir, 'refunds.json');
  fs.writeFileSync(file, JSON.stringify({ ...SET, rules: RULES }));
  const h = new HIITL({
    environment: 'dev', agent_id: 'refund-agent', org_id: ORG, policy_path: file, audit_db_path: ':memory:',
    mode: 'RESPECT_POLICY', ...opts,
  });
  clients.push(h);
  return h;
}

function lifecycle(h: HIITL, actionId: string): unknown[] {
  return (h as any).auditLogger.lifecycle(ORG, 'dev', actionId).map((r: Record<string, unknown>) => r.event_type);
}

/** The call's answer, or what it threw. */
async function settled<T>(call: () => Promise<T>): Promise<T | Error> {
  try {
    return await call();
  } catch (e) {
    return e as Error;
  }
}

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('row 150: what a record is, and recordResult up to the write', () => {
  it('every reader carries event type', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const h = client({ signature_key: 'row150-local-signing-key-0123456789abcdef' });
    const allowed = h.evaluate({ action: 'refund' }) as Decision;
    const anyH = h as any;
    const build = anyH._buildEnvelope;
    anyH._buildEnvelope = (...args: unknown[]) => {
      const envelope = build.apply(h, args);
      envelope.parameters.amount = 1_000_000;
      return envelope;
    };
    const refused = h.evaluate({ action: 'refund', parameters: { amount: 10 } }) as Decision;
    anyH._buildEnvelope = build;
    expect([allowed.decision, refused.decision]).toEqual(['ALLOW', 'SIGNATURE_INVALID']);

    const log = anyH.auditLogger;
    const unsynced = log.getUnsynced(10) as Array<Record<string, unknown>>;
    const reads: Record<string, Array<Record<string, unknown>>> = {
      queryByOrgId: log.queryByOrgId(ORG),
      queryByActionId: [...log.queryByActionId(allowed.action_id), ...log.queryByActionId(refused.action_id)],
      queryByDecisionType: [...log.queryByDecisionType('ALLOW'), ...log.queryByDecisionType('SIGNATURE_INVALID')],
      get: unsynced.map((r) => log.get(r.event_id)),
      getUnsynced: unsynced,
      lifecycle: [...log.lifecycle(ORG, 'dev', allowed.action_id), ...log.lifecycle(ORG, 'dev', refused.action_id)],
    };
    for (const [reader, records] of Object.entries(reads)) {
      const carried = records.map((r) => [r.decision_type, r.event_type]).sort();
      expect(carried, reader).toEqual([['ALLOW', 'action.evaluated'], ['SIGNATURE_INVALID', 'signature.invalid']]);
    }
  });

  it('record result refuses as the spec says', async () => {
    const h = client();
    const allowed = h.evaluate({ action: 'refund' }) as Decision;
    const blocked = h.evaluate({ action: 'wire_transfer' }) as Decision;
    expect([allowed.decision, blocked.decision]).toEqual(['ALLOW', 'BLOCK']);
    const cases: Array<[string, () => Promise<unknown>]> = [
      ['RESULT_INVALID', () => h.recordResult(allowed.action_id, 'done')],
      ['ACTION_NOT_FOUND', () => h.recordResult('act_r150nevereval00000000', 'succeeded')],
      ['RESULT_ON_UNALLOWED_DECISION', () => h.recordResult(blocked.action_id, 'succeeded')],
    ];
    for (const [reason, call] of cases) {
      const refused = await settled(call);
      expect(refused, reason).toBeInstanceOf(LifecycleError);
      expect([(refused as LifecycleError).reason, (refused as Error).message]).toEqual([
        reason, `[${reason}] ${LIFECYCLE_MESSAGES[reason]}`,
      ]);
    }
    expect(lifecycle(h, allowed.action_id), 'nothing is written').toEqual(['action.evaluated']);
    expect(lifecycle(h, blocked.action_id)).toEqual(['action.evaluated']);
  });

  it('the hosted client sends the result and reads its answer', async () => {
    const actionId = 'act_r150hosted0000000000';
    const record = { event_id: 'evt_r150hosted', action_id: actionId, event_type: 'action.executed' };
    const refusal = {
      detail: {
        error: 'RESULT_ON_UNALLOWED_DECISION', message: LIFECYCLE_MESSAGES.RESULT_ON_UNALLOWED_DECISION,
        details: { action_id: actionId },
      },
    };
    const reply = (status: number, body: unknown) =>
      ({ status, ok: status >= 200 && status < 300, headers: new Headers(), json: () => Promise.resolve(body) }) as Response;
    const fetch = vi.fn()
      .mockResolvedValueOnce(reply(200, record))
      .mockResolvedValueOnce(reply(409, refusal))
      .mockResolvedValueOnce(reply(401, { detail: { error: 'UNAUTHORIZED', message: 'No API key was sent.' } }));
    vi.stubGlobal('fetch', fetch);
    const h = new HIITL({
      environment: 'dev', agent_id: 'refund-agent', org_id: ORG, api_key: 'sk_test_1234567890abcdef',
      server_url: 'https://ecp.example', evaluation: 'remote', max_retries: 0, signature_key: 's'.repeat(32),
      audit_db_path: ':memory:', // its own store (row 192)
    });
    clients.push(h);

    expect(await h.recordResult(actionId, 'succeeded', { duration_ms: 12 })).toEqual(record);
    const refused = await settled(() => h.recordResult(actionId, 'succeeded'));
    const unauthorized = await settled(() => h.recordResult(actionId, 'succeeded'));

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(`https://ecp.example/v1/actions/${actionId}/result`);
    expect(JSON.parse(init.body)).toEqual({ status: 'succeeded', duration_ms: 12 });
    expect(refused).toBeInstanceOf(LifecycleError);
    expect((refused as LifecycleError).reason).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(unauthorized).toBeInstanceOf(ServerError);
    expect([(unauthorized as ServerError).status_code, (unauthorized as ServerError).error_code]).toEqual([
      401, 'UNAUTHORIZED',
    ]);
  });

  // The exit cell (behavior 10; HTL-23 row 191 behavior 5): the write is built once the hash covers the result
  it('a result recorded for an evaluated action reads back with its lifecycle', async () => {
    const h = client();
    const d = h.evaluate({ action: 'refund' }) as Decision;
    const record = await h.recordResult(d.action_id, 'succeeded', { duration_ms: 12 });
    expect(record.event_type).toBe(eventType(d.decision, { status: 'succeeded' }));
    expect(lifecycle(h, d.action_id)).toEqual(['action.evaluated', 'action.executed']);
    expect(await h.recordResult(d.action_id, 'succeeded', { duration_ms: 12 })).toEqual(record);
    const refused = await settled(() => h.recordResult(d.action_id, 'failed', { error: 'card declined' }));
    expect((refused as LifecycleError).reason).toBe('RESULT_ALREADY_RECORDED');
  });
});
