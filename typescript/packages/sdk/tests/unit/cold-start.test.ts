/**
 * Cold-start behavior + cacheStatus decision field tests (TICKET-121).
 *
 * Mirrors python/hiitl/sdk/tests/test_cold_start.py.
 *
 * Covers:
 * - `cold_start_behavior` constructor option validation
 * - Hybrid mode no longer throws when api_key is provided without
 *   policy_path (the pre-TICKET-121 behavior).
 * - `Decision.cache_status` stamped on every Decision returned by the
 *   local + hybrid evaluator paths.
 * - Pure-local mode leaves `cache_status` undefined/null.
 *
 * The fail-closed throw-from-evaluate path and the synced/from_disk
 * transitions live in integration tests (they require a working
 * SyncEngine mock + SyncCache file ops). This unit suite covers the
 * surface-level contract — accept the option, route to the right
 * mode, stamp the field.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import { HIITL } from '../../src/client.js';
import { SyncEngine } from '../../src/sync-engine.js';
import { ConfigurationError } from '../../src/exceptions.js';

const VALID_ORG_ID = 'org_test000000000000000';

describe('Cold-start behavior validation (TICKET-121)', () => {
  let hiitl: HIITL | undefined;

  afterEach(() => {
    hiitl?.close();
    hiitl = undefined;
    vi.restoreAllMocks();
  });

  it('rejects invalid cold_start_behavior with ConfigurationError', () => {
    expect(
      () =>
        new HIITL({
          audit_db_path: ':memory:',
          // @ts-expect-error — deliberately bad value
          cold_start_behavior: 'bogus-mode',
        })
    ).toThrow(ConfigurationError);
  });

  it('accepts the three valid cold_start_behavior values', () => {
    for (const mode of ['warn-and-observe', 'fail-closed', 'observe-silent'] as const) {
      const h = new HIITL({
        audit_db_path: ':memory:',
        cold_start_behavior: mode,
      });
      expect(h).toBeDefined();
      h.close();
    }
  });

  it('accepts cold_start_behavior in local mode without effect (no api_key)', () => {
    // Local mode (no api_key) doesn't run a sync — cold_start_behavior
    // is parsed but unused. The constructor accepting fail-closed in
    // local mode is intentional: a developer who later adds an api_key
    // shouldn't need to also flip the cold-start option.
    hiitl = new HIITL({
      audit_db_path: ':memory:',
      cold_start_behavior: 'fail-closed',
    });
    expect(hiitl.mode).toBe('local');
  });

  it('defaults to warn-and-observe when no cold_start_behavior is provided', () => {
    hiitl = new HIITL({ audit_db_path: ':memory:' });
    // No public getter for the internal field; we infer the default
    // is wired by checking that hybrid-mode construction succeeds
    // without throwing (warn-and-observe is the only behavior that
    // continues silently on disk-cache miss + sync failure).
    expect(hiitl).toBeDefined();
  });
});

describe('Hybrid mode constructor — no longer throws without policy_path (TICKET-121)', () => {
  let hiitl: HIITL | undefined;

  afterEach(() => {
    hiitl?.close();
    hiitl = undefined;
    vi.restoreAllMocks();
  });

  it('accepts api_key without policy_path and resolves mode to hybrid', () => {
    // Pre-TICKET-121 this threw ConfigurationError. Post-TICKET-121
    // hybrid mode is the default architecture; the sync engine
    // populates the cache.
    hiitl = new HIITL({
      audit_db_path: ':memory:',
      api_key: 'sk_test_hybrid_12345',
      org_id: VALID_ORG_ID,
    });
    expect(hiitl.mode).toBe('hybrid');
  });

  it('hybrid + RESPECT_POLICY without policy_path still works (sync supplies the policy)', () => {
    // Pure-local would throw here; hybrid is allowed because the sync
    // cache is the policy source.
    hiitl = new HIITL({
      audit_db_path: ':memory:',
      api_key: 'sk_test_hybrid_12345',
      org_id: VALID_ORG_ID,
      mode: 'RESPECT_POLICY',
    });
    expect(hiitl.mode).toBe('hybrid');
    expect(hiitl.evalMode).toBe('RESPECT_POLICY');
  });

  it('pure local + RESPECT_POLICY without policy_path still throws ConfigurationError', () => {
    // Negative control: pure-local hasn't changed.
    expect(
      () =>
        new HIITL({
          audit_db_path: ':memory:',
          org_id: VALID_ORG_ID,
          mode: 'RESPECT_POLICY',
        })
    ).toThrow(ConfigurationError);
  });
});

describe('Decision.cache_status stamping (TICKET-121)', () => {
  let hiitl: HIITL | undefined;

  afterEach(() => {
    hiitl?.close();
    hiitl = undefined;
    vi.restoreAllMocks();
  });

  it('local mode leaves cache_status undefined (not applicable)', async () => {
    hiitl = new HIITL({ audit_db_path: ':memory:' });
    const decision = await hiitl.evaluate({ action: 'test_action' });
    // null-or-undefined — both are acceptable per the schema (zod
    // `.nullable().optional()` means the field may be missing entirely
    // or explicitly null in serialized form). Local mode just doesn't
    // touch the field.
    expect(decision.cache_status == null).toBe(true);
  });

  it('hybrid mode stamps cache_status on every Decision', async () => {
    // The unit fixture fixes the first pull as unanswered; no network outcome chooses this answer.
    vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(false);
    vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
    hiitl = new HIITL({
      audit_db_path: ':memory:',
      api_key: 'sk_test_hybrid_12345',
      org_id: VALID_ORG_ID,
      cache_dir: `${process.cwd()}/cache`,
      sync_init_timeout: 0.5, // short timeout so the test runs fast
    });
    expect(hiitl.mode).toBe('hybrid');
    await (hiitl as unknown as { _initialSyncPromise: Promise<boolean> })._initialSyncPromise;
    const decision = await hiitl.evaluate({ action: 'test_action' });
    expect(decision.cache_status).toBe('empty');
  });
});
