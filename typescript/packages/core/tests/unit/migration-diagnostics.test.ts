/** Existing envelope migration guidance also belongs to sparse shipped tests. */
import { expect, it } from 'vitest';
import { PolicySetSchema, RuleSchema, RuleTestSchema } from '../../src/types.js';

const member = (envelope: Record<string, unknown>) => ({
  name: 'pay-rule', description: 'Pay rule', priority: 1,
  conditions: {field: 'action', operator: 'equals', value: 'pay'}, decision: 'ALLOW', reason_code: 'PAY',
  tests: [{envelope, expect: 'ALLOW'}],
});
const policy = (envelope: Record<string, unknown>) => ({
  name: 'payments', version: 'v1.0.0', description: 'Payments',
  scope: {org_id: 'org_test000000000000', environment: 'dev'}, rules: [member(envelope)],
});

it.each(['test', 'rule', 'policy'] as const)('sparse envelope names the replacement at the %s boundary', boundary => {
  const envelope = {tool_name: 'pay', unfamiliar: 1};
  const before = structuredClone(envelope);
  const result = boundary === 'test' ? RuleTestSchema.safeParse({envelope, expect: 'ALLOW'})
    : boundary === 'rule' ? RuleSchema.safeParse(member(envelope)) : PolicySetSchema.safeParse(policy(envelope));
  expect(result.success).toBe(false);
  if (result.success) return;
  const prefix = boundary === 'test' ? ['envelope'] : boundary === 'rule' ? ['tests', 0, 'envelope']
    : ['rules', 0, 'tests', 0, 'envelope'];
  const unknown = result.error.issues.filter(issue => issue.code === 'unrecognized_keys');
  expect(unknown.map(issue => ({path: issue.path, keys: issue.keys}))).toEqual([
    {path: prefix, keys: ['tool_name']}, {path: prefix, keys: ['unfamiliar']},
  ]);
  expect(unknown[0].message).toContain('tool_name is a field the envelope schema does not define: the schema renamed it action');
  expect(unknown[1].message).not.toContain('renamed');
  expect(envelope).toStrictEqual(before);
});

it.each(['unfamiliar', 'constructor', 'toString', '__proto__'])('sparse unknown %s receives no invented rename', key => {
  const result = RuleTestSchema.safeParse({envelope: Object.fromEntries([[key, 'pay']]), expect: 'ALLOW'});
  expect(result.success).toBe(false);
  if (result.success) return;
  expect(result.error.issues.map(issue => ({code: issue.code, path: issue.path}))).toEqual([
    {code: 'unrecognized_keys', path: ['envelope']},
  ]);
  expect(result.error.issues[0].message).not.toContain('renamed');
});

it('sparse open values keep old spellings and do not acquire absent defaults', () => {
  const envelope = {parameters: {tool_name: null, tools: ['pay'], enabled: false, mode: 'observe'}};
  const parsed = RuleTestSchema.safeParse({envelope, expect: 'ALLOW'});
  expect(parsed.success).toBe(true);
  if (!parsed.success) return;
  expect(parsed.data.envelope).toStrictEqual(envelope);
  expect(Object.keys(parsed.data.envelope)).toEqual(['parameters']);
});
