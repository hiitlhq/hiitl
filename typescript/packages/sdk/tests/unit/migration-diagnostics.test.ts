/** Customer JSON/YAML policy files retain sparse-envelope migration guidance. */
import {mkdtempSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {dump} from 'js-yaml';
import {expect, it} from 'vitest';
import {PolicyLoader} from '../../src/policy-loader.js';
import {PolicyLoadError} from '../../src/exceptions.js';

function policy(envelope: Record<string, unknown>) {
  return {name: 'payments', version: 'v1.0.0', description: 'Payments',
    scope: {org_id: 'org_test000000000000', environment: 'dev'}, rules: [{
      name: 'pay-rule', description: 'Pay rule', priority: 1,
      conditions: {field: 'action', operator: 'equals', value: 'pay'}, decision: 'ALLOW', reason_code: 'PAY',
      tests: [{envelope, expect: 'ALLOW'}],
    }]};
}

it.each(['json', 'yaml'] as const)('sparse-envelope migration guidance survives the %s file loader', wire => {
  const directory = mkdtempSync(join(tmpdir(), 'hiitl-migration-'));
  try {
    const load = (name: string, envelope: Record<string, unknown>) => {
      const path = join(directory, `${name}.${wire}`);
      const value = policy(envelope);
      writeFileSync(path, wire === 'json' ? JSON.stringify(value) : dump(value));
      return new PolicyLoader(path).load();
    };
    expect(load('control', {action: 'pay'}).name).toBe('payments');
    let failure: unknown;
    try { load('renamed', {tool_name: 'pay'}); } catch (error) { failure = error; }
    expect(failure).toBeInstanceOf(PolicyLoadError);
    expect((failure as Error).message).toContain('tool_name is a field the envelope schema does not define: the schema renamed it action');
    let unrelated: unknown;
    try { load('unrelated', {unfamiliar: 'pay'}); } catch (error) { unrelated = error; }
    expect(unrelated).toBeInstanceOf(PolicyLoadError);
    expect((unrelated as Error).message).not.toContain('renamed');
  } finally { rmSync(directory, {recursive: true, force: true}); }
});
