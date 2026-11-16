/**
 * Row 225 (HTL-27): the `tool_name` alias leaves at envelope schema 2.0.
 *
 * Ruled 2026-11-08: "the `tool_name` alias leaves at 2.0. An envelope carrying `tool_name` is refused as undefined,
 * naming `action`". By the 2.0 ruling's "no acceptance window, no dual handling" and B.foundation.6 (one representation
 * per fact). The rename is read at its producer, envelope_schema.json (1.1, "Renamed tool_name to action");
 * policy_format.md 2.17 reads a path as written. Design: the HTL-27 test design, row 225, behaviors 1, 3 and 7, and
 * Codex's review condition 2 with its class (C2.1-C2.8, C2.10): a name the input supplies is a member only where the
 * object holds it as data, never one it inherits. Mirrors core/tests/test_row225.py (the lint is the Python core's).
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { compileSetLimits } from '../../src/rate-limits.js';
import { RouteUnanswered, answerFields, authHeaders, payload } from '../../src/routing.js';
import { ENVELOPE_RENAMED, ENVELOPE_SCHEMA_VERSION, EnvelopeSchema } from '../../src/types.js';

const SCHEMA = JSON.parse(readFileSync(join(__dirname, '../../../../../docs/specs/envelope_schema.json'), 'utf8'));
const OLD = 'tool_name';
const NEW = 'action';

const envelope = (fields: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_r225renamed000000', environment: 'prod',
  agent_id: 'billing-agent', action_id: 'act_r225renamed0000000000', idempotency_key: 'idem_r225',
  action: 'send_invoice', timestamp: '2026-11-08T12:00:00Z', signature: 'a'.repeat(64), ...fields,
});

const policySet = (condition: unknown) => ({
  name: 'invoice_controls', version: 'v1.0.0', description: 'Invoice controls for the billing agent',
  scope: { org_id: 'org_r225renamed000000', environment: 'prod' },
  rules: [{ name: 'rule_0', description: 'Invoices to this customer need approval', priority: 100,
    conditions: condition, decision: 'REQUIRE_APPROVAL', reason_code: 'INVOICE_REVIEW', route: 'finance-review' }],
});

/** The refusal's issues, each located as the conformance runner locates it (an undefined key's path ends in it). */
function issues(data: unknown): Array<{ at: string; code: string; message: string }> {
  const result = EnvelopeSchema.safeParse(data);
  expect(result.success).toBe(false);
  if (result.success) return [];
  return result.error.issues.flatMap((i) =>
    i.code === z.ZodIssueCode.unrecognized_keys
      ? i.keys.map((k) => ({ at: [...i.path, k].join('.'), code: i.code, message: i.message }))
      : [{ at: i.path.join('.'), code: i.code, message: i.message }],
  );
}

describe('row 225: the tool_name alias leaves at 2.0', () => {
  it('the rename record is the schema\'s', () => {
    expect(ENVELOPE_RENAMED).toEqual({ [OLD]: NEW });
    for (const [old, renamed] of Object.entries(ENVELOPE_RENAMED)) {
      expect(old in SCHEMA.properties).toBe(false);
      expect(renamed in SCHEMA.properties).toBe(true);
      expect(SCHEMA.$comment).toContain(`Renamed ${old} to ${renamed}`);
    }
  });

  it('the 1.x envelope is refused, naming action', () => {
    const { action, ...legacy } = envelope({ [OLD]: 'send_invoice' });
    const alone = issues(legacy);
    expect(alone.map((i) => i.at).sort()).toEqual([NEW, OLD]);
    const undefinedField = alone.find((i) => i.at === OLD)!;
    expect(undefinedField.message).toContain(NEW);
    expect(alone.find((i) => i.at === NEW)!.message).toBe('Required');

    const beside = issues(envelope({ [OLD]: action }));
    expect(beside.map((i) => i.at)).toEqual([OLD]);
    expect(beside[0].message).toContain(NEW);
  });

  it('another undefined field is refused as before', () => {
    expect(issues(envelope({ amount_usd: 120 }))[0].message).toBe("Unrecognized key(s) in object: 'amount_usd'");
  });

  it.each([
    [{ field: `parameters.${OLD}`, operator: 'equals', value: 'crm_sync' }, true],
    [{ field: `parameters.${OLD}`, operator: 'equals', value: 'send_invoice' }, false],
    [{ field: OLD, operator: 'equals', value: 'send_invoice' }, false],
  ])('a path is read as written: %j matches %s', (condition, matches) => {
    const decision = new PolicyEvaluator().evaluate(
      envelope({ parameters: { [OLD]: 'crm_sync', [NEW]: 'send_invoice' } }), policySet(condition));
    expect(decision.decision === 'REQUIRE_APPROVAL').toBe(matches);
  });
});

// Codex's review of PR #13, condition 2 and its class (policy_format.md 2.17): each part of a name the input supplies is a
// member the object holds as data. Each language's own names, read in both evaluators (Path B).
const NOT_DATA = ['toString', 'constructor', '__proto__', '__class__', 'model_dump', 'parameters.toString',
  'parameters.tags.length', 'parameters.tags.0', 'timestamp.year', 'cost_estimate.model_dump', 'cost_estimate.toString'];
const DATA = ['parameters.constructor', 'parameters.tags', 'cost_estimate.dollars'];
const award = () => envelope({ parameters: { constructor: 'Halden Build Ltd', tags: ['school', 'riverside'] },
  cost_estimate: { dollars: 12.5 } });
/** The invoice rule on every send_invoice call, with `extra` written over it. */
const rule = (extra: Record<string, unknown>) => {
  const set = policySet({ field: 'action', operator: 'equals', value: 'send_invoice' });
  return { ...set, rules: [{ ...set.rules[0], ...extra }] };
};

describe("row 225, Codex's condition 2: a name the input supplies is read as data", () => {
  it.each(['toString', 'constructor'])('C2.1: an own %s key is refused with the undefined-field message alone', (key) => {
    const found = issues({ ...envelope(), [key]: 'x' });
    expect(found.map((i) => [i.at, i.message])).toEqual([[key, `Unrecognized key(s) in object: '${key}'`]]);
  });

  it.each([...NOT_DATA.map((f) => [f, false]), ...DATA.map((f) => [f, true])])(
    'C2.3: exists true on %s matches: %s', (field, matches) => {
      const decision = new PolicyEvaluator().evaluate(award(), policySet({ field, operator: 'exists', value: true }));
      expect(decision.decision === 'REQUIRE_APPROVAL').toBe(matches);
    });

  it.each(['toString', 'constructor', '__proto__', '__class__', 'model_dump'])(
    'C2.5: a rollout hashed on %s skips the rule', (field) => {
      const decision = new PolicyEvaluator().evaluate(envelope({ user_id: 'usr_4471' }),
        rule({ scope: { percentage: 90, rollout_hash_field: field } }));
      expect(decision.decision).not.toBe('REQUIRE_APPROVAL');
    });

  it('C2.5: a rollout hashed on a field the call carries buckets it as before', () => {
    // usr_4471's bucket is 69: SHA-256, the first four bytes big-endian, mod 100
    const decision = new PolicyEvaluator().evaluate(envelope({ user_id: 'usr_4471' }),
      rule({ scope: { percentage: 90, rollout_hash_field: 'user_id' } }));
    expect(decision.decision).toBe('REQUIRE_APPROVAL');
  });

  it.each([
    [{ scope: 'constructor', limit: 10, window: 'minute' }, "scope 'constructor' is not one of"],
    [{ scope: 'org', limit: 10, window: 'toString' }, "window 'toString' is not one of"],
  ])('C2.6: a set-level limit naming %j is refused', (entry, refusal) => {
    const { problems } = compileSetLimits({ ...policySet(null), metadata: { rate_limits: [entry] } });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain(refusal);
  });

  it('C2.7: a route reads the payload, the answer and the secret as data', () => {
    const route = { name: 'vendor-check', direction: 'bidirectional',
      context: { fields: [{ field_path: 'parameters.constructor' }, { field_path: 'parameters.amount' }] },
      response_schema: { required_fields: ['constructor'], optional_fields: ['note'] },
      auth: { type: 'bearer_token', secret_ref: 'env:constructor' } };
    expect(payload(route, 'rule_0', envelope({ parameters: { amount: 1200 } })).fields)
      .toEqual({ 'parameters.constructor': null, 'parameters.amount': 1200 });
    expect(() => answerFields(route, { note: 'checked' })).toThrow(RouteUnanswered);
    expect(answerFields(route, { constructor: 'Halden Build Ltd' })).toEqual({ constructor: 'Halden Build Ltd' });
    expect(() => authHeaders(route, { VENDOR_TOKEN: 'tok_live' })).toThrow(RouteUnanswered);   // unset: not sent (row 140)
    expect(authHeaders({ ...route, auth: { ...route.auth, secret_ref: 'env:VENDOR_TOKEN' } }, { VENDOR_TOKEN: 'tok_live' }))
      .toEqual({ Authorization: 'Bearer tok_live' });
  });

  it.each([[{}], [{ 'kyc-check': { verified: true } }]])(
    'C2.8: a ROUTE rule naming route constructor binds when the enrichment %j lacks it', (enrichment) => {
      const set = rule({ decision: 'ROUTE', reason_code: 'VENDOR_CHECK', route: 'constructor' });
      expect(new PolicyEvaluator().evaluate(envelope(), set, 'RESPECT_POLICY', enrichment).decision).toBe('ROUTE');
    });

  it('C2.10: no `in` in the source reads a name the input supplies', () => {
    // the class's gate, by the compiler's grammar: a computed name is read with Object.hasOwn; a literal left names
    // no member every object inherits
    const inherited = new Set(Object.getOwnPropertyNames(Object.prototype));
    const src = join(__dirname, '../../src');
    const found: string[] = [];
    for (const f of readdirSync(src, { recursive: true }).map(String).filter((f) => f.endsWith('.ts'))) {
      const file = ts.createSourceFile(f, readFileSync(join(src, f), 'utf8'), ts.ScriptTarget.Latest, true);
      const walk = (n: ts.Node): void => {
        if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.InKeyword
          && !(ts.isStringLiteralLike(n.left) && !inherited.has(n.left.text))) {
          found.push(`${f}:${file.getLineAndCharacterOfPosition(n.getStart()).line + 1}: ${n.getText()}`);
        }
        ts.forEachChild(n, walk);
      };
      walk(file);
    }
    expect(found).toEqual([]);
  });
});
