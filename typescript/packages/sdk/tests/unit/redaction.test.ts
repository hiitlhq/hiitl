/**
 * Row 139 (HTL-20): the SDK's local audit store applies the SDK's declared redaction list before every write.
 *
 * Mirrors python/hiitl/sdk/tests/test_row139.py (row 139 test design cells 7-8). The
 * contract is docs/specs/event_format.md §Redaction. A hosted SDK's refusal of a declaration turned with Stop B (i)
 * (HTL-23 row 192): the hosted client now writes its outage records, under the declaration (row192.test.ts).
 */

import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { auditContentHash, MARKER } from '@hiitl/core';
import type { Decision } from '@hiitl/core';
import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';

const POLICY = {
  name: 'payouts',
  version: 'v1.0.0',
  description: 'The payouts set',
  scope: { org_id: 'org_test000000000000000', environment: 'dev' },
  rules: [
    {
      name: 'no-payouts-to-frozen-accounts',
      description: 'A frozen account is never paid',
      priority: 900,
      decision: 'BLOCK',
      reason_code: 'FROZEN_ACCOUNT',
      conditions: {
        all_of: [
          { field: 'action', operator: 'equals', value: 'pay' },
          { field: 'parameters.account_number', operator: 'in', value: ['GB82WEST12345698765432'] },
        ],
      },
    },
    {
      name: 'allow-otherwise',
      description: 'Everything else',
      priority: 1,
      decision: 'ALLOW',
      reason_code: 'ALLOWED',
      conditions: { field: 'action', operator: 'exists', value: true },
    },
  ],
};

let open: HIITL | undefined;
afterEach(() => open?.close());

describe('the local store (row 139)', () => {
  it('test_the_local_store_holds_the_declared_field_redacted', () => {
    const dir = mkdtempSync(join(tmpdir(), 'hiitl-redaction-'));
    const policyPath = join(dir, 'policy.json');
    writeFileSync(policyPath, JSON.stringify(POLICY));
    const db = join(dir, 'audit.db');
    open = new HIITL({
      environment: 'dev',
      agent_id: 'payout-agent',
      org_id: 'org_test000000000000000',
      policy_path: policyPath,
      mode: 'RESPECT_POLICY',
      audit_db_path: db,
      redact_fields: ['parameters.account_number', 'target.email'],
    });

    const frozen = open.evaluate({
      action: 'pay',
      parameters: { account_number: 'GB82WEST12345698765432', amount: 1250 },
      target: { email: 'dana@example.com', vendor_id: 'vnd_42' },
    }) as Decision;
    const paid = open.evaluate({ action: 'pay', parameters: { account_number: 'GB29NWBK60161331926819', amount: 80 } }) as Decision;
    expect([frozen.decision, frozen.reason_codes]).toEqual(['BLOCK', ['FROZEN_ACCOUNT']]); // evaluation saw it whole
    expect(paid.decision).toBe('ALLOW');
    open.close();
    open = undefined;

    const logger = new AuditLogger(db);
    const rows = logger.queryByOrgId('org_test000000000000000').reverse();
    expect(rows).toHaveLength(2);
    rows.forEach((row, i) => {
      const envelope = JSON.parse(row.envelope);
      expect(envelope.parameters).toEqual({ account_number: MARKER, amount: [1250, 80][i] });
      expect(row.envelope + row.decision).not.toMatch(/GB82WEST|GB29NWBK|dana@example\.com/);
      // Each content member the record carries joins the hash as a further term (row 191, ruled 2026-11-06): the
      // second call holds no target.email, so its record carries `redaction.absent`
      expect(row.content_hash).toBe(auditContentHash(row.event_id, envelope, JSON.parse(row.decision), {
        execution_result: row.execution_result ?? undefined,
        redaction: row.redaction ?? undefined,
      }));
      expect(logger.verifyIntegrity(row.event_id)).toBe(true);
    });
    expect(rows.map((r) => r.redaction ?? null)).toEqual([null, { absent: ['target.email'] }]);
    expect(JSON.parse(rows[0].envelope).target).toEqual({ email: MARKER, vendor_id: 'vnd_42' });
    const uploaded = logger.getUnsynced() as Array<{ envelope: { parameters: Record<string, unknown> } }>;
    expect(uploaded.map((u) => u.envelope.parameters.account_number)).toEqual([MARKER, MARKER]);
    logger.close();
  });

  it('test_a_declaration_that_is_not_a_field_is_refused', () => {
    const dir = mkdtempSync(join(tmpdir(), 'hiitl-redaction-'));
    expect(() => new HIITL({ audit_db_path: join(dir, 'a.db'), redact_fields: ['org_id'] })).toThrow(ConfigurationError);
    expect(() => new HIITL({ audit_db_path: join(dir, 'b.db'), redact_fields: ['org_id'] })).toThrow(
      /event_format\.md §Redaction/
    );
  });
});
