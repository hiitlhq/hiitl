/**
 * Row 165 (HTL-22), the TypeScript SDK: an option the constructor does not define is refused, naming it.
 *
 * R-0872: "no field is ever silently dropped". The options are strict: `new HIITL({ orgID })` is refused, naming
 * `orgID` and the option it resembles, `org_id`; a sync setting the SDK does not define is refused the same way. The
 * Python constructor refuses the same key (python/hiitl/sdk/tests/test_row165.py). Design:
 * the HTL-22 test design, row 165, behavior 10.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { HIITL } from '../../src/client.js';
import type { HIITLConfigInput } from '../../src/config.js';
import { ConfigurationError } from '../../src/exceptions.js';

const ORG_ID = 'org_test000000000000000';

describe('row 165: the options are strict', () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'row165-')); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  const refused = (options: Record<string, unknown>): ConfigurationError => {
    try {
      new HIITL({ audit_db_path: path.join(dir, 'audit.db'), ...options } as unknown as HIITLConfigInput).close();
    } catch (e) {
      expect(e).toBeInstanceOf(ConfigurationError);
      return e as ConfigurationError;
    }
    return expect.fail(`the options were accepted: ${JSON.stringify(options)}`);
  };

  it('new HIITL with orgID is refused, naming orgID and org_id', () => {
    const e = refused({ orgID: ORG_ID });
    expect(e.message).toContain("'orgID'");
    expect(e.message).toContain("'org_id'");
  });

  it('a sync setting the SDK does not define is refused, naming it', () => {
    const e = refused({ org_id: ORG_ID, sync_config: { auditSyncInterval: 5 } });
    expect(e.message).toContain("'auditSyncInterval'");
  });

  it('the options it defines are taken, and the zero-config set loads', () => {
    const hiitl = new HIITL({ org_id: ORG_ID, environment: 'stage', audit_db_path: path.join(dir, 'audit.db') });
    try {
      const decision = hiitl.evaluate({ action: 'send_email' });
      expect([decision.decision, decision.policy_version]).toEqual(['OBSERVE', 'v0.0.0']);
    } finally {
      hiitl.close();
    }
  });
});
