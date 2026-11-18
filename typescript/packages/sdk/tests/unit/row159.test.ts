/**
 * Row 159 (HTL-22): an error is a decision, in the SDK too.
 *
 * decision_response.md, Error Handling: "All errors produce structured decision responses", and "Even error decisions
 * produce audit records". The Stop 2 ruling: "The SDKs raise a typed hiitl error only where no envelope exists yet."
 * Infrastructure spec 3: "Audit write failures in fail-closed mode must block the action". Design: the HTL-22 test
 * design, row 159, behaviors 4-8. Mirrors python/hiitl/sdk/tests/test_row159.py.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { ServerError } from '../../src/exceptions.js';

const ORG = 'org_test000000000000000';
const SET = {
  version: 'v1.0.0', name: 'refunds', description: "The refund agent's refunds",
  scope: { org_id: ORG, environment: 'dev' },
};
const SENTINEL = 'r159-cause-the-caller-never-reads';
const ALLOW_REFUNDS = {
  name: 'allow_refunds', priority: 100, description: 'Refunds are allowed',
  conditions: { field: 'action', operator: 'equals', value: 'refund' },
  decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
};

const clients: HIITL[] = [];
const dirs: string[] = [];

function policyFile(rules: object[] = [ALLOW_REFUNDS]): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row159-'));
  dirs.push(dir);
  const file = path.join(dir, 'refunds.json');
  fs.writeFileSync(file, JSON.stringify({ ...SET, rules }));
  return file;
}

function client(opts: Record<string, unknown> = {}, file = policyFile()): HIITL {
  const h = new HIITL({
    environment: 'dev', agent_id: 'refund-agent', org_id: ORG, policy_path: file, audit_db_path: ':memory:',
    mode: 'RESPECT_POLICY', ...opts,
  });
  clients.push(h);
  return h;
}

function records(h: HIITL): string[] {
  return ((h as any).auditLogger.getUnsynced(10) as Array<Record<string, any>>).map((r) => r.decision.decision);
}

/** The file changes under a client that already read it: a later mtime, so the loader reads it again. */
function rewrite(file: string, content: string): void {
  fs.writeFileSync(file, content);
  const later = new Date(Date.now() + 60_000);
  fs.utimesSync(file, later, later);
}

/** The call's decision, or what it threw: once an envelope exists, nothing throws. */
function settled<T>(call: () => T): T | Error {
  try {
    return call();
  } catch (e) {
    return e as Error;
  }
}

function storeDown(): never {
  throw new Error(SENTINEL);
}

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('row 159: an error is a decision, in the SDK too', () => {
  it.each(['RESPECT_POLICY', 'OBSERVE_ALL'])('a failed audit write blocks and writes nothing, %s', (mode) => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const h = client({ mode });
    const logger = (h as any).auditLogger;
    const write = logger.write;
    logger.write = storeDown;
    const d = h.evaluate({ action: 'refund' }) as Decision;
    expect([d.decision, d.allowed, d.error?.code]).toEqual(['BLOCK', false, 'AUDIT_WRITE_FAILED']);
    logger.write = write;
    expect(records(h)).toEqual([]);
  });

  // Behavior 5. TypeScript reads the policy file at construction, before any envelope exists, so a file missing then
  // throws there; a file that changes under the client is read again at evaluate.
  it.each([
    ['unparseable-file', (h: HIITL, file: string) => rewrite(file, '{"version": "v1.0.0", "rules": ['), 'POLICY_VALIDATION_ERROR'],
    ['missing-file', (h: HIITL, file: string) => fs.rmSync(file), 'POLICY_NOT_FOUND'],
    ['evaluator-raises', (h: HIITL) => { (h as any).evaluator.evaluate = storeDown; }, 'POLICY_EVALUATION_FAILED'],
  ])('local errors are decisions with records, %s', (_id, arm, reason) => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const file = policyFile();
    const h = client({}, file);
    arm(h, file);
    const d = settled(() => h.evaluate({ action: 'refund' }) as Decision);
    expect(d, 'an envelope exists, so the failure is a decision').not.toBeInstanceOf(Error);
    if (d instanceof Error) return;
    expect([d.decision, d.allowed, d.reason_codes, d.error?.code]).toEqual([
      'POLICY_ERROR', false, [reason], 'POLICY_ERROR',
    ]);
    expect(records(h)).toEqual(['POLICY_ERROR']);
  });

  it.each([
    ['limiter', 'RATE_LIMIT_SERVICE_ERROR', () => {
      const h = client({ enable_rate_limiting: true });
      (h as any).rateLimiter = { checkAndIncrement: storeDown };
      return h;
    }],
    ['evaluator', 'POLICY_ERROR', () => {
      const h = client();
      (h as any).evaluator.evaluate = storeDown;
      return h;
    }],
    // The schema's own error quotes the value it refused, so a decision no rule may write carries the sentinel
    ['policy-load', 'POLICY_ERROR', () => {
      const file = policyFile();
      const h = client({}, file);
      rewrite(file, JSON.stringify({ ...SET, rules: [{ ...ALLOW_REFUNDS, decision: SENTINEL }] }));
      return h;
    }],
    ['audit-write', 'AUDIT_WRITE_FAILED', () => {
      const h = client();
      (h as any).auditLogger.write = storeDown;
      return h;
    }],
  ])('no error message carries the caught exception s text, %s', (_id, code, arrive) => {
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
    const d = arrive().evaluate({ action: 'refund' }) as Decision;
    expect([d.allowed, d.error?.code]).toEqual([false, code]);
    expect(JSON.stringify(d)).not.toContain(SENTINEL);
    expect(logged.mock.calls.flat().join(' ')).toContain(SENTINEL);
  });

  function hosted(): HIITL {
    const h = new HIITL({
      environment: 'dev', agent_id: 'refund-agent', org_id: ORG, api_key: 'sk_test_1234567890abcdef',
      server_url: 'https://ecp.example', evaluation: 'remote', max_retries: 0, signature_key: 's'.repeat(32),
      audit_db_path: ':memory:', // its own store (row 192)
    });
    clients.push(h);
    return h;
  }

  function answer(status: number, body: Record<string, unknown>): void {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status, ok: status >= 200 && status < 300, headers: new Headers(), json: () => Promise.resolve(body),
    } as Response));
  }

  function decisionBody(decision: string, reason: string, code: string, message: string): Record<string, unknown> {
    return {
      action_id: 'act_r159hosted0000000000', decision, allowed: false, reason_codes: [reason], policy_version: '',
      timing: { total_ms: 0.4 }, error: { code, message },
    };
  }

  it.each([
    ['403-signature-invalid', 403, decisionBody('SIGNATURE_INVALID', 'ENVELOPE_SIGNATURE_VERIFICATION_FAILED',
      'SIGNATURE_INVALID', 'The envelope does not verify under the key it was signed with.')],
    ['500-audit-write-failed', 500, decisionBody('BLOCK', 'AUDIT_WRITE_FAILED', 'AUDIT_WRITE_FAILED',
      'The audit record could not be written, so the action is blocked.')],
  ])('the hosted client reads a decision body on any status, %s', async (_id, status, body) => {
    answer(status, body);
    const d = await Promise.resolve(hosted().evaluate({ action: 'refund' })).catch((x: Error) => x);
    expect(d, 'a decision body is the decision on any status').not.toBeInstanceOf(Error);
    if (d instanceof Error) return;
    expect([d.decision, d.allowed, d.reason_codes, d.error?.code, d.error?.message]).toEqual([
      body.decision, false, body.reason_codes, (body.error as any).code, (body.error as any).message,
    ]);
  });

  it('a response with no decision body still raises', async () => {
    answer(401, { detail: { error: 'UNAUTHORIZED', message: 'No API key was sent.' } });
    const e = await Promise.resolve(hosted().evaluate({ action: 'refund' })).catch((x) => x);
    expect(e).toBeInstanceOf(ServerError);
    expect([e.status_code, e.error_code]).toEqual([401, 'UNAUTHORIZED']);
  });

  it('a refused envelope is not the first decision under its key', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const h = client({ signature_key: 'row159-local-signing-key-0123456789abcdef' });
    const anyH = h as any;
    const build = anyH._buildEnvelope;
    anyH._buildEnvelope = (...args: unknown[]) => {
      const envelope = build.apply(h, args);
      envelope.parameters.amount = 1_000_000;
      return envelope;
    };
    const call = { action: 'refund', parameters: { amount: 10 }, idempotency_key: 'refund-K' };
    const refused = h.evaluate(call) as Decision;
    anyH._buildEnvelope = build;
    const corrected = h.evaluate(call) as Decision;
    const again = h.evaluate(call) as Decision;
    expect([refused.decision, corrected.decision, again.decision]).toEqual(['SIGNATURE_INVALID', 'ALLOW', 'ALLOW']);
    expect(again.action_id).toBe(corrected.action_id);
    expect(records(h)).toEqual(['SIGNATURE_INVALID', 'ALLOW']);
  });
});
