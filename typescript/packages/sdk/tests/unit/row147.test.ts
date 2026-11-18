/**
 * Row 147 (HTL-20) through the SDK: a cached policy is read through the model before it is taken, and the caller's
 * cost estimate is the envelope's.
 *
 * R-0872: "no field is ever silently dropped". sync_engine.md §6: "Precedence: Server cache > local policy files >
 * empty"; envelope_schema.json v1.4 `cost_estimate`. Design: the HTL-20 test design, row 147. Mirrors
 * sdk/tests/test_row147_sdk.py.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import { EnvelopeValidationError } from '../../src/exceptions.js';
import { SyncCache } from '../../src/sync-cache.js';

const rule = (name: string, decision: string) => ({
  name, description: `Invoices: ${decision}`, priority: 100,
  conditions: { field: 'action', operator: 'equals', value: 'send_invoice' }, decision, reason_code: `INVOICE_${decision}`,
});

const clients: HIITL[] = [];
const dirs: string[] = [];

function client(): HIITL {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row147-'));
  dirs.push(dir);
  const policyPath = path.join(dir, 'invoices.json');
  fs.writeFileSync(policyPath, JSON.stringify({ version: 'v1.0.0', description: 'The file_policy set', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'file_policy', rules: [rule('file_rule', 'ALLOW')] }));
  const hiitl = new HIITL({
    environment: 'dev', agent_id: 'billing-agent', org_id: 'org_test000000000000000', policy_path: policyPath,
    audit_db_path: ':memory:', mode: 'RESPECT_POLICY',
  });
  clients.push(hiitl);
  return hiitl;
}

/**
 * The sync cache a hybrid client reads, holding the given server policies as a pull lands them: the cache reads them
 * through the model where they are received (sync_engine.md Numeric domain; HTL-43 gap 295).
 */
async function cache(hiitl: HIITL, ...contents: object[]): Promise<void> {
  const held = new SyncCache({ cache_dir: path.join(dirs[dirs.length - 1], 'cache'), org_id: 'org_test000000000000000', environment: 'dev' });
  await held.updatePolicies({ policies: contents.map((content, i) => ({ name: `server_${i}`, active: true, content })) });
  (hiitl as any).syncCache = held;
}

afterEach(() => {
  vi.restoreAllMocks();
  clients.splice(0).forEach((c) => c.close());
  dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true }));
});

describe('row 147 through the SDK', () => {
  it('a cached policy the model refuses is skipped, naming the field', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const hiitl = client();
    const refused = { version: 'v1.0.0', description: 'A cached policy the model refuses is skipped, naming the field', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'server_policy', rules: [{ ...rule('server_rule', 'BLOCK'), enabled_for: 'all' }] };
    await cache(hiitl, refused);
    let d: ReturnType<HIITL['evaluate']> | undefined;
    expect(() => {
      d = hiitl.evaluate({ action: 'send_invoice' });
    }).not.toThrow(); // a refused policy never fails the call
    expect(d?.matched_rules?.map((m) => m.rule_name)).toEqual(['file_rule']); // the next source decides
    const said = warn.mock.calls.map((c) => String(c[0])).join('\n');
    expect(said).toContain("Failed to parse cached policy 'server_0'");
    expect(said).toContain('enabled_for'); // the field is named

    await cache(hiitl, refused, { version: 'v1.0.0', description: 'A cached policy the model refuses is skipped, naming the field', scope: { org_id: 'org_test000000000000000', environment: 'dev' }, name: 'server_policy', rules: [rule('server_rule', 'BLOCK')] });
    expect(hiitl.evaluate({ action: 'send_invoice' }).matched_rules?.map((m) => m.rule_name)).toEqual(['server_rule']);
  });

  it("the cost estimate is the envelope's", () => {
    const hiitl = client();
    expect(hiitl.evaluate({ action: 'send_invoice', cost_estimate: { dollars: 0.03, tokens: 1.5 } }).decision).toBe('ALLOW');
    let thrown: unknown;
    try {
      hiitl.evaluate({ action: 'send_invoice', cost_estimate: { usd_cents: 3 } as any });
    } catch (e) {
      thrown = e;
    }
    expect(thrown).toBeInstanceOf(EnvelopeValidationError);
    expect((thrown as EnvelopeValidationError).validation_errors.join('\n')).toContain('usd_cents'); // named
  });
});
