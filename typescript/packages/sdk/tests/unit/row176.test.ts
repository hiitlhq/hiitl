/**
 * Row 176 (HTL-22): the hosted client reads `missing_fields` into the decision.
 *
 * The evaluate spec's Resolved Design Decision 2: "skip the policy, flag it in the audit trail ("policy X exists but
 * couldn't evaluate — envelope missing field Y")". decision_response.md 1.11 declares `missing_fields`, and the service
 * sends it (the hosted service's own row 176 cell). Design: the HTL-22 test design, row 176, behavior 10.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { envelopeSignature, ENVELOPE_SCHEMA_VERSION } from '@hiitl/core';
import type { Envelope } from '@hiitl/core';
import { createHostedConfig } from '../../src/config.js';
import { HostedClient } from '../../src/http-client.js';

const ORG_ID = 'org_mycompany123456789';
const SIGNING_SECRET = 'test-signing-secret-0123456789abcdef';
const FLAG = [{ rule_name: 'approve_large_payments', policy_set: 'payments_policy', field: 'parameters.amount' }];

function envelope(): Envelope {
  const env: Record<string, unknown> = {
    schema_version: ENVELOPE_SCHEMA_VERSION,
    org_id: ORG_ID,
    environment: 'dev',
    agent_id: 'agent_finance_bot',
    action_id: 'act_0123456789abcdefghij',
    idempotency_key: 'idem_row176',
    timestamp: '2026-11-05T10:00:00.000Z',
    action: 'process_payment',
    operation: 'execute',
    target: { account_id: 'acct_123' },
    parameters: { currency: 'usd' },
    signature: '0'.repeat(64),
  };
  env.signature = envelopeSignature(SIGNING_SECRET, env);
  return env as unknown as Envelope;
}

describe('row 176: the hosted client reads the flag', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('carries missing_fields from the response into the decision', async () => {
    const body = {
      action_id: 'act_0123456789abcdefghij',
      decision: 'ALLOW',
      allowed: true,
      reason_codes: ['KNOWN_ACCOUNT'],
      policy_version: 'v1.0.0',
      timing: { total_ms: 2.0 },
      missing_fields: FLAG,
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () => Promise.resolve(body),
      headers: new Headers(),
      statusText: 'OK',
    } as Response));
    const client = new HostedClient(createHostedConfig({
      environment: 'dev',
      agent_id: 'agent_finance_bot',
      org_id: ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      audit_db_path: ':memory:', // its own store (row 192)
    }));

    const decision = await client.evaluate(envelope());

    expect(decision.missing_fields).toEqual(FLAG);
  });
});
