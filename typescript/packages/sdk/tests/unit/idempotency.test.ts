/**
 * Row 143 (HTL-20): in the local store, a repeated idempotency key returns the first decision and writes no record.
 * Mirrors python/hiitl/sdk/tests/test_row143_local.py.
 *
 * Principle 5: "Embrace idempotency, retries, deduplication, and partial failure as first-class concerns." The
 * security architecture §1.3: "A replayed envelope produces a dedup hit, not a re-evaluation. The dedup window is
 * configurable (default: 24 hours)."
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { AuditLogger } from '../../src/audit.js';

function client(
  options: Record<string, unknown> = {},
  db = join(mkdtempSync(join(tmpdir(), 'hiitl-row143-')), 'a.db')
): { h: HIITL; records: () => Array<Record<string, any>> } {
  const h = new HIITL({ audit_db_path: db, ...options });
  return { h, records: () => new AuditLogger(db).getUnsynced(10) as Array<Record<string, any>> };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('row 143: a repeated idempotency key returns the first decision', () => {
  it('a retry under the same key returns the first decision and writes one record', () => {
    const { h, records } = client();

    const first = h.evaluate({ action: 'refund', parameters: { amount: 10 }, idempotency_key: 'idem_row143_ts' }) as Decision;
    const retry = h.evaluate({ action: 'refund', parameters: { amount: 900 }, idempotency_key: 'idem_row143_ts' }) as Decision;

    const recs = records();
    expect(recs).toHaveLength(1);
    expect(retry.action_id).toBe(first.action_id);
    expect(retry.action_id).toBe(recs[0].envelope.action_id);
    expect(retry.decision).toBe(first.decision);
    expect(retry.envelope_hash).toBe(first.envelope_hash);
  });

  it('without a key each call is its own action', () => {
    const { h, records } = client();

    const first = h.evaluate({ action: 'refund' }) as Decision;
    const second = h.evaluate({ action: 'refund' }) as Decision;

    expect(second.action_id).not.toBe(first.action_id);
    expect(records()).toHaveLength(2);
  });

  it('the same key in another environment is evaluated afresh', () => {
    const dev = client({ environment: 'dev' });
    const prod = client({ environment: 'prod' }, (dev.h as any).config.audit_db_path);

    const a = dev.h.evaluate({ action: 'refund', idempotency_key: 'idem_row143_env' }) as Decision;
    const b = prod.h.evaluate({ action: 'refund', idempotency_key: 'idem_row143_env' }) as Decision;

    expect(b.action_id).not.toBe(a.action_id);
    expect(dev.records()).toHaveLength(2);
  });

  it('a key reused after the window is evaluated afresh', () => {
    const { h, records } = client({ dedup_window_seconds: 60 });
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date());

    const first = h.evaluate({ action: 'refund', idempotency_key: 'idem_row143_later' }) as Decision;
    vi.setSystemTime(new Date(Date.now() + 120_000));
    const later = h.evaluate({ action: 'refund', idempotency_key: 'idem_row143_later' }) as Decision;

    expect(later.action_id).not.toBe(first.action_id);
    expect(records()).toHaveLength(2);
  });
});
