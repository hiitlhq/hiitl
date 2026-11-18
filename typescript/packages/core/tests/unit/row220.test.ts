/**
 * Row 220 (HTL-24): a rule's name is unique within its set.
 *
 * Ruled 2026-11-07: "each core model refuses a set holding two rules of one name, naming it". By policy_format.md,
 * `name`: "Unique rule identifier within policy set", and row 147's class (each model refuses what its spec refuses).
 * The refusal follows the compilation of a set's `metadata.rate_limits`, so a compiled rule is held to it too, and the
 * compiled rule is named by the entry it carries (`metadata.compiled_from`). Design: the HTL-24 test design, row 220,
 * behavior 1. Mirrors python/hiitl/core/tests/test_row220.py.
 */
import { describe, expect, it } from 'vitest';
import { PolicySetSchema } from '../../src/types.js';

const rule = (name: string, decision = 'BLOCK') => ({
  name, description: `${name}, as written`, priority: 10, decision, reason_code: 'PAYOUT_OVER_LIMIT',
  conditions: { field: 'parameters.amount', operator: 'greater_than', value: 5000 },
});

const set = (rules: object[], fields: Record<string, unknown> = {}) => ({
  name: 'payouts', version: 'v1.0.0', description: 'payout limits',
  scope: { org_id: 'org_test0123456789ab', environment: 'dev' }, rules, ...fields,
});

const refusal = (data: object): string => {
  const parsed = PolicySetSchema.safeParse(data);
  expect(parsed.success).toBe(false);
  const issues = parsed.success ? [] : parsed.error.issues;
  expect(issues).toHaveLength(1);
  return issues[0].message;
};

describe("row 220: a rule's name is unique within its set", () => {
  it('a set of distinct names loads', () => {
    const loaded = PolicySetSchema.parse(set([rule('over_limit'), rule('review_large', 'REQUIRE_APPROVAL')]));
    expect(loaded.rules.map((r) => r.name)).toEqual(['over_limit', 'review_large']);
  });

  it.each([[0, 1], [0, 2], [1, 2]])('two rules of one name (rules[%i], rules[%i]) are refused, naming both', (first, second) => {
    const rules: Array<Record<string, unknown>> = [rule('over_limit'), rule('review_large', 'REQUIRE_APPROVAL'), rule('hold_new', 'PAUSE')];
    rules[second] = { ...rules[second], name: rules[first].name };
    const message = refusal(set(rules));
    expect(message).toContain(`'${rules[first].name}'`);
    expect(message).toContain(`rules[${first}]`);
    expect(message).toContain(`rules[${second}]`);
    expect(message).toContain('Unique rule identifier within policy set');
  });

  it('a compiled rule is held to it, named by its entry', () => {
    const message = refusal(set([rule('metadata.rate_limits[0]')], { metadata: { rate_limits: [{ limit: 10 }] } }));
    expect(message).toContain("'metadata.rate_limits[0]'");
    expect(message).toContain('rules[0]');
    expect(message).toContain('compiled from metadata.rate_limits[0]');
  });

  it('the refusal names each name held twice', () => {
    const message = refusal(set([rule('a'), rule('b'), rule('a'), rule('b')]));
    expect(message).toContain("'a'");
    expect(message).toContain("'b'");
    for (const i of [0, 1, 2, 3]) expect(message).toContain(`rules[${i}]`);
  });
});
