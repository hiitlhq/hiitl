/**
 * Row 147 (HTL-20): every model refuses what its spec refuses, naming the field (R-0872 / R-0881 swept).
 *
 * R-0872: "no field is ever silently dropped". R-0881: "every policy-format model refuses an undefined field". The specs
 * are read at their producer: envelope_schema.json (v1.4), policy_format.md 2.10 (the decisions a rule writes, the
 * scope's environments), routes.md 1.3. Design: the HTL-20 test design, row 147. Mirrors core/tests/test_row147.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { RouteSchema } from '../../src/route-types.js';
import { DecisionType, EnvelopeSchema, PolicySetSchema, RuleSchema, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const SPECS = join(__dirname, '../../../../../docs/specs');
const ENVELOPE_SCHEMA = JSON.parse(readFileSync(join(SPECS, 'envelope_schema.json'), 'utf8'));

const envelope = (fields: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_test123456789012', environment: 'dev', agent_id: 'agent-147',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_row147', action: 'send_invoice',
  timestamp: '2026-11-04T12:00:00Z', signature: 'a'.repeat(64), ...fields,
});

const rule = (fields: Record<string, unknown> = {}) => ({
  name: 'invoice_rule', description: 'Invoices are allowed', priority: 100,
  conditions: { field: 'action', operator: 'equals', value: 'send_invoice' },
  decision: 'ALLOW', reason_code: 'INVOICE_ALLOWED', ...fields,
});

const route = (fields: Record<string, unknown> = {}) => ({
  name: 'finance-review', version: 'v1.0.0', direction: 'bidirectional', timing: 'sync',
  endpoint: 'https://hooks.example.com/review', response_schema: { decision_options: ['approve', 'deny'] },
  sla: { timeout: '4h', timeout_action: 'fail_closed' }, ...fields,
});

/** The keys a failed parse refused as undefined, each with the path of the object it sat in. */
function refused(schema: z.ZodTypeAny, data: unknown): string[] {
  const result = schema.safeParse(data);
  expect(result.success).toBe(false);
  if (result.success) return [];
  return result.error.issues
    .filter((i) => i.code === z.ZodIssueCode.unrecognized_keys)
    .flatMap((i) => (i as z.core.$ZodIssueUnrecognizedKeys).keys.map((k) => [...i.path, k].join('.')));
}

/** The rows (value, description) of the first table under a heading. */
function table(text: string, heading: string): Array<[string, string]> {
  const section = text.slice(text.indexOf(heading)).split('\n---')[0];
  return [...section.matchAll(/^\| `([A-Z_]+)` \| ([^|]*)\|/gm)].map((m) => [m[1], m[2].trim()]);
}

describe('row 147: no field is ever silently dropped (R-0872)', () => {
  it('an envelope refuses an undefined field, naming it', () => {
    expect(refused(EnvelopeSchema, envelope({ amount_usd: 120 }))).toEqual(['amount_usd']);
    expect(refused(EnvelopeSchema, envelope({ tool_name: 'send_payment' }))).toEqual(['tool_name']);
    // alone, it is refused too, naming action (row 225; row225.test.ts)
  });

  it('a cost estimate refuses an undefined key, naming it', () => {
    expect(refused(EnvelopeSchema, envelope({ cost_estimate: { usd_cents: 3 } }))).toEqual(['cost_estimate.usd_cents']);
    const defined = Object.keys(ENVELOPE_SCHEMA.properties.cost_estimate.properties);
    expect(EnvelopeSchema.safeParse(envelope({ cost_estimate: Object.fromEntries(defined.map((k) => [k, 1])) })).success).toBe(true);
  });

  it('tokens is a number, kept as written', () => {
    expect(ENVELOPE_SCHEMA.properties.cost_estimate.properties.tokens.type).toBe('number');
    const parsed = EnvelopeSchema.safeParse(envelope({ cost_estimate: { tokens: 1.5 } }));
    expect(parsed.success && parsed.data.cost_estimate?.tokens).toBe(1.5);
    expect(EnvelopeSchema.safeParse(envelope({ cost_estimate: { tokens: -1 } })).success).toBe(false);
  });

  it('a rule writes only the decisions the spec lists', () => {
    const rows = table(readFileSync(join(SPECS, 'policy_format.md'), 'utf8'), '### Valid Decisions');
    const errors = table(readFileSync(join(SPECS, 'decision_response.md'), 'utf8'), '### Error Decisions');
    const written = new Set(rows.filter(([, d]) => !d.includes('not written in rules')).map(([v]) => v));
    const produced = Object.values(DecisionType).filter((d) => !written.has(d)).sort();
    // every decision a rule does not write is one the spec says the evaluator or the control point produces
    expect(produced).toEqual(
      [...rows.filter(([, d]) => d.includes('not written in rules')).map(([v]) => v), ...errors.map(([v]) => v)].sort(),
    );
    for (const value of produced) {
      const result = PolicySetSchema.safeParse({ name: 'p', version: 'v1.0.0', description: 'A rule writes only the decisions the spec lists', scope: { org_id: 'org_test123456789012', environment: 'dev' }, rules: [rule({ decision: value })] });
      expect(result.success).toBe(false);
      const text = result.success ? '' : JSON.stringify(result.error.issues);
      expect(text).toContain('invoice_rule'); // the refusal names the rule
      expect(text).toContain(value); // and the value
    }
    for (const value of written) {
      expect(RuleSchema.safeParse(rule({ decision: value, ...(value === 'ROUTE' ? { route: 'finance-review' } : {}) })).success).toBe(true);
    }
  });

  it("a scope takes only the envelope's environments", () => {
    for (const env of ENVELOPE_SCHEMA.properties.environment.enum as string[]) {
      expect(RuleSchema.safeParse(rule({ scope: { environments: [env] } })).success).toBe(true);
    }
    const result = RuleSchema.safeParse(rule({ scope: { environments: ['prod', 'staging'] } }));
    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((i) => i.path.join('.'))).toContain('scope.environments.1');
    expect(result.success ? '' : JSON.stringify(result.error.issues)).toContain('staging');
  });

  it('a route refuses an undefined field at every depth', () => {
    expect(refused(RouteSchema, route({ owner: 'finance' }))).toEqual(['owner']);
    expect(refused(RouteSchema, route({ scope: { org_id: 'org_test123456789012', region: 'eu' } }))).toEqual(['scope.region']);
    expect(refused(RouteSchema, route({ sla: { timeout: '4h', timeout_action: 'fail_closed', escalate_after: '1h' } })))
      .toEqual(['sla.escalate_after']);
    expect(refused(RouteSchema, route({ context: { risk_framing: { consequences: { if_approved: 'paid', if_late: 'x' } } } })))
      .toEqual(['context.risk_framing.consequences.if_late']);
    const parsed = RouteSchema.safeParse(route({ metadata: { owner: 'finance' } }));
    expect(parsed.success && parsed.data.metadata).toEqual({ owner: 'finance' });
  });

  it('every object an artifact is read through is strict', () => {
    // Walk each artifact's schema by what each zod definition holds, never by a list of names or of wrappers: a
    // schema member of the definition, a list or map of them, an object of them (a shape), or what a member with no
    // argument returns (an object's shape, a lazy schema's getter).
    const objects: Array<{ path: string; strict: boolean }> = [];
    const seen = new Set<z.ZodTypeAny>();
    const held = (value: unknown, path: string, depth = 0): Array<[string, z.ZodTypeAny]> => {
      if (value instanceof z.ZodType) return [[path, value]];
      if (typeof value === 'function' && value.length === 0 && depth === 0) return held(value(), path, 1);
      if (Array.isArray(value)) return value.flatMap((v) => held(v, path, 1));
      if (value instanceof Map) return [...value.values()].flatMap((v) => held(v, path, 1));
      if (value && typeof value === 'object' && depth <= 1) {
        return Object.entries(value).flatMap(([k, v]) => (v instanceof z.ZodType ? [[`${path}.${k}`, v] as [string, z.ZodTypeAny]] : []));
      }
      return [];
    };
    const walk = (s: z.ZodTypeAny, path: string): void => {
      if (seen.has(s)) return;
      seen.add(s);
      const def = (s as any)._def;
      if (s instanceof z.ZodObject) objects.push({ path, strict: def.catchall instanceof z.ZodNever });
      for (const [child, sub] of Object.values(def).flatMap((v) => held(v, path))) walk(sub, child);
    };
    const roots = { Envelope: EnvelopeSchema, PolicySet: PolicySetSchema, Route: RouteSchema };
    for (const [name, root] of Object.entries(roots)) walk(root, name);
    for (const name of Object.keys(roots)) {
      expect(objects.map((o) => o.path)).toContain(name);
      expect(objects.some((o) => o.path.startsWith(`${name}.`)), `the walk reaches ${name}'s nested objects`).toBe(true);
    }
    expect(objects.filter((o) => !o.strict).map((o) => o.path)).toEqual([]);
  });
});
