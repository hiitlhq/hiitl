/**
 * Row 146 (HTL-20), the decision-model members: what a Decision declares is produced, and a code-level override in
 * production is said.
 *
 * ecp_evaluate_spec.md, Resolved Design Decision 1: "Production uses RESPECT_POLICY ... If a code-level override is
 * active in a production environment, the SDK logs a warning." Hosted mode evaluates on the server, which applies
 * its own mode, so the hosted client does not warn. decision_response.md's schema is the one field set: the
 * DecisionSchema declares what it declares, and escalation_context is the shape resolveEscalationContext emits from
 * a route. python/hiitl/sdk/tests/test_row146d.py holds the Python side.
 */

import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { DecisionSchema, RouteSchema } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { resolveEscalationContext } from '../../src/route-loader.js';

const SPEC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../docs/specs/decision_response.md');
// declared by the schema, modeled by neither SDK: none (row 174 modeled `metadata`, the outage decision's, HTL-22)
const HELD_SPEC = new Set<string>();

const POLICY = {
  name: 'p', version: 'v1.0.0', description: 'The p set', scope: { org_id: 'org_devlocal0000000000', environment: 'prod' }, rules: [{
    name: 'allow', description: 'd', priority: 1, decision: 'ALLOW', reason_code: 'OK',
    conditions: { field: 'action', operator: 'exists', value: true },
  }],
};

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row146d-'));
});

afterEach(() => {
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

function schema(): { properties: Record<string, { properties?: Record<string, unknown> }> } {
  const text = readFileSync(SPEC, 'utf-8');
  const block = text.slice(text.indexOf('```json') + '```json'.length);
  return JSON.parse(block.slice(0, block.indexOf('```')));
}

function warnings(spy: MockInstance<typeof console.warn>): string[] {
  return spy.mock.calls.map((c) => String(c[0])).filter((m) => m.includes('OBSERVE_ALL in the prod environment'));
}

describe('a code-level OBSERVE_ALL in prod', () => {
  it.each([
    ['prod', 'OBSERVE_ALL', true],
    ['prod', 'RESPECT_POLICY', false],
    ['dev', 'OBSERVE_ALL', false],
    ['stage', 'OBSERVE_ALL', false],
  ] as const)('logs a warning: %s %s -> %s', (environment, mode, warned) => {
    const p = path.join(dir, 'policy.json');
    writeFileSync(p, JSON.stringify(POLICY));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    new HIITL({ environment, mode, policy_path: p, audit_db_path: ':memory:' }).close();
    const found = warnings(warn);
    expect(found).toHaveLength(warned ? 1 : 0);
    if (warned) {
      expect(found[0]).toContain("new HIITL({ mode: 'RESPECT_POLICY' })");
      expect(found[0]).toContain('HIITL_MODE=RESPECT_POLICY');
    }
  });

  it('the hosted client does not warn', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    new HIITL({
      environment: 'prod', api_key: 'sk_test_1234567890abcdef', server_url: 'https://ecp.example', evaluation: 'remote',
      signature_key: 's'.repeat(32), audit_db_path: ':memory:',
    });
    expect(warnings(warn)).toEqual([]);
  });
});

describe('the Decision declares what decision_response.md declares', () => {
  it('the schema and the model declare one field set', () => {
    const model = new Set(Object.keys(DecisionSchema.shape));
    const spec = new Set(Object.keys(schema().properties).filter((p) => !HELD_SPEC.has(p)));
    expect([...model].sort()).toEqual([...spec].sort());
  });

  it('escalation_context is the shape resolveEscalationContext emits from a route', () => {
    const route = RouteSchema.parse({
      name: 'finance-review', version: 'v1.0.0', direction: 'bidirectional', timing: 'sync', purpose: ['review'],
      endpoint: 'https://review.example.com/api/v1/review', protocol: 'webhook',
      context: {
        fields: [{ field_path: 'parameters.amount', label: 'Amount', format: 'currency' }],
        risk_framing: { severity: 'high', summary: 'Large payment requires approval' },
      },
      response_schema: { decision_options: ['approve', 'deny'] },
      sla: { timeout: '4h', timeout_action: 'escalate' },
      escalation_ladder: { levels: [{ level: 1, route: 'ciso-review', after: '30m' }], max_escalation_depth: 2,
        final_timeout_action: 'fail_closed' },
      correlation: { token_field: 'resume_token' },
    });
    const emitted = Object.keys(resolveEscalationContext(route)).sort();
    expect(emitted).toEqual(Object.keys(schema().properties.escalation_context.properties ?? {}).sort());
  });
});
