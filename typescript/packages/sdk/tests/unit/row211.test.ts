/**
 * Row 211 (HTL-23): the window before the first pull.
 *
 * Ruled 2026-11-06 as the row reads: "the cold-start sentence governs, by that sentence". sync_engine.md §5:
 * "`warn-and-observe` (default) logs a warning and evaluates against an empty policy set, in the client's own mode,
 * with `cache_status: "empty"` until a sync succeeds". So a record written in the window is written, never held, under
 * the SDK's own declaration; the first pull that lands carries the org's, and the next write takes both
 * (event_format.md §Redaction, Open). Design: the HTL-23 test design, row 211. Mirrors
 * python/hiitl/sdk/tests/test_row211.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { MARKER } from '@hiitl/core';

import type { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import type { SyncCache } from '../../src/sync-cache.js';
import { SyncEngine } from '../../src/sync-engine.js';

const ORG = 'org_r211window0000000';
const PARAMETERS = { account_number: 'GB29NWBK60161331926819', amount: 1250 };
const TARGET = { email: 'dana@example.com', vendor_id: 'vnd_42' };

let dir: string;
let ambient: Record<string, string | undefined>;
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row211-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

describe('row 211: the window before the first pull', () => {
  it('test_the_window_takes_the_sdks_declaration_and_the_pull_brings_the_orgs', async () => {
    vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(false); // the first pull has not landed
    vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
    const warned = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const h = new HIITL({
      api_key: 'sk_test_row211', org_id: ORG, environment: 'dev', agent_id: 'payout-agent',
      cache_dir: path.join(dir, 'cache'), audit_db_path: path.join(dir, 'audit.db'),
      redact_fields: ['parameters.account_number'],
    });
    const inside = h as unknown as { _initialSyncPromise: Promise<boolean>; syncCache: SyncCache; auditLogger: AuditLogger };
    await inside._initialSyncPromise;
    expect(warned.mock.calls.map(([message]) =>
      /cache_status='([^']+)'/.exec(String(message))?.[1])).toEqual(['empty']);

    const before = await h.evaluate({ action: 'pay', parameters: PARAMETERS, target: TARGET });
    expect(before.cache_status).toBe('empty');
    // the first pull lands, as the engine writes it
    await inside.syncCache.updatePolicies(
      { policies: [], version: 'v1', redaction_policy: { manual_redact_fields: ['target.email'] } }, 'e1'
    );
    const after = await h.evaluate({ action: 'pay', parameters: PARAMETERS, target: TARGET });
    const [first, second] = (inside.auditLogger.getUnsynced() as Array<{
      envelope: { parameters: Record<string, unknown>; target: Record<string, unknown> } }>).map((r) => r.envelope);
    h.close();

    // in the window: the SDK's declaration only, and the record is written, never held
    expect([first.parameters.account_number, first.target.email]).toEqual([MARKER, TARGET.email]);
    // after the pull: the union
    expect([second.parameters.account_number, second.target.email]).toEqual([MARKER, MARKER]);
    expect(after.cache_status).toBe('synced');
  });
});
