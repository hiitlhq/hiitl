/**
 * Row 240 (HTL-29): a kill switch binds in its scope under the version the tick names, until a pull lands.
 *
 * The ruling (HTL-29, 2026-11-09): "in the switch's scope the SDK decides `KILL_SWITCH` under the activation's version
 * the tick names; outside that scope the cached version binds until the pull lands, the pull retried each tick and the
 * miss logged at error". Condition 2 (ruled 2026-11-10): the version the tick names is compared by its version string,
 * and a switch the call cannot read under `fail_closed` blocks it, `MISSING_FIELD` naming the field, under the tick's
 * version. sync_engine.md 2.4, 6 and 7. Design: the HTL-29 test design, row 240, behaviors 3-10.
 * Mirrors python/hiitl/sdk/tests/test_row240.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { canonicalHash } from '@hiitl/core';

import { CircuitState } from '../../src/circuit-breaker.js';
import { HIITL } from '../../src/client.js';
import type { Logger } from '../../src/logger.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const ORG = 'org_test0123456789ab';
const ENV = 'dev';
const REDACTION = { manual_redact_fields: [] };
const quiet: Logger = { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} };

type Content = { name: string; version: string; rules: Array<Record<string, unknown>>; [k: string]: unknown };

const on = (action: string) => ({ field: 'action', operator: 'equals', value: action });
const rule = (name: string, decision: string, stage = 'active', conditions: object = on('pay')) => ({
  name, description: name, priority: 100, conditions, decision,
  reason_code: name.toUpperCase().replace(/-/g, '_'), lifecycle_stage: stage,
});
const content = (version: string, rules: object[], onMissing?: string): Content => ({
  name: 'payments', version, description: 'payments', scope: { org_id: ORG, environment: ENV },
  ...(onMissing ? { on_missing: onMissing } : {}), rules: rules as Array<Record<string, unknown>>,
});

const ALLOW_PAY = rule('allow-pay', 'ALLOW');
const ALLOW_REFUND = rule('allow-refund', 'ALLOW', 'active', on('refund'));
const RUNNING = content('v1.0.0', [rule('halt-payments', 'KILL_SWITCH', 'disabled'), ALLOW_PAY, ALLOW_REFUND]);
const HALTED = content('v1.0.1', [rule('halt-payments', 'KILL_SWITCH'), ALLOW_PAY, ALLOW_REFUND]);
const RESUMED = content('v1.0.2', [rule('halt-payments', 'KILL_SWITCH', 'disabled'), ALLOW_PAY, ALLOW_REFUND]);

const policy = (c: Content) => ({
  policy_id: `pol_${c.version}`, name: c.name, version: c.version, active: true, content: c,
  content_hash: canonicalHash(c),
});

/** The tick's `policy_set` as the service writes it: the set's own fields and its live switches. */
const part = (c: Content) => {
  const { rules, ...fields } = c;
  return { ...fields, rules: rules.filter((r) => r.decision === 'KILL_SWITCH' && r.lifecycle_stage === 'active') };
};

const tick = (c: Content | null, names?: string[]) => {
  const held = c ? part(c) : null;
  const named = names ?? (held ? held.rules.map((r) => String(r.name)) : []);
  return {
    kill_switches: named.map((n) => ({ rule_name: n, active: true, scope: { environment: ENV } })),
    policy_set: held, server_time: '2026-11-09T00:00:00+00:00',
  };
};

let dir: string;
const clients: HIITL[] = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row240-'));
});

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  fs.rmSync(dir, { recursive: true, force: true });
});

/** A cache holding `cached`, and an engine whose every policy pull fails until a test says otherwise. */
async function engine(cached: Content) {
  const state = {
    tick: tick(null) as ReturnType<typeof tick>,
    pull: 'fail' as 'fail' | 304 | Content,
    pulls: 0,
    errors: [] as string[],
  };
  const json = (body: unknown) => new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  const client = new SyncClient({
    server_url: 'https://api.test', api_key: 'k', org_id: ORG, environment: ENV, max_retries: 0, timeout: 5,
    logger: quiet,
    fetchImpl: async (url: string | URL | Request) => {
      if (String(url).endsWith('/v1/sync/kill-switches')) return json(state.tick);
      state.pulls += 1;
      if (state.pull === 'fail') return new Response('the service is unreachable', { status: 503 });
      if (state.pull === 304) return new Response(null, { status: 304 });
      const c = state.pull;
      return json({ policies: [policy(c)], version: c.version, etag: `e-${c.version}`, redaction_policy: REDACTION });
    },
  });
  const cache = new SyncCache({
    cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV,
    logger: { ...quiet, error: (m: string) => state.errors.push(m) },
  });
  await cache.updatePolicies(
    { policies: [policy(cached)], version: cached.version, redaction_policy: REDACTION }, `e-${cached.version}`
  );
  const e = new SyncEngine({
    sync_config: { server_url: 'https://api.test' }, sync_cache: cache,
    audit_logger: { getUnsynced: () => [], markSynced: () => 0 }, api_key: 'k', org_id: ORG, environment: ENV,
    logger: { ...quiet, error: (m: string) => state.errors.push(m) }, sync_client: client,
  });
  const tickOnce = async (t: ReturnType<typeof tick>) => {
    state.tick = t;
    await (e as unknown as { _syncKillSwitches: () => Promise<void> })._syncKillSwitches();
  };
  const breaker = (e as unknown as { breakers: Record<string, any> }).breakers.policy;
  return { cache, state, tickOnce, breaker };
}

function client(cache: SyncCache, mode: 'RESPECT_POLICY' | 'OBSERVE_ALL' = 'RESPECT_POLICY'): HIITL {
  const local = path.join(dir, 'local.json');
  fs.writeFileSync(local, JSON.stringify(content('v0.0.1', [rule('local-allow', 'ALLOW')])));
  const hiitl = new HIITL({
    environment: ENV, agent_id: 'payment-agent', org_id: ORG, policy_path: local, audit_db_path: ':memory:', mode,
  });
  clients.push(hiitl);
  (hiitl as unknown as { syncCache: SyncCache }).syncCache = cache;
  return hiitl;
}

const read = (d: any) => [d.decision, d.policy_version, (d.matched_rules ?? []).map((m: any) => m.rule_name)];

describe('row 240: a switch binds before its pull lands (behavior 3)', () => {
  it("a switch binds in its scope under the tick's version while its pull fails", async () => {
    const { cache, state, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));
    expect(state.pulls).toBe(1);
    const hiitl = client(cache);

    const d = hiitl.evaluate({ action: 'pay' }) as any;
    expect(read(d)).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);   // the tick's version decides its scope
    expect(d.reason_codes).toEqual(['HALT_PAYMENTS']);
    const [record] = (hiitl as any).auditLogger.queryByActionId(d.action_id);
    expect([record.decision_type, record.policy_version]).toEqual(['KILL_SWITCH', 'v1.0.1']);   // recorded so
    expect(read(hiitl.evaluate({ action: 'refund' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-refund']]);   // outside it
  });

  it("an evaluator that throws over the tick's part is POLICY_ERROR, recorded", async () => {
    const { cache, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));
    const hiitl = client(cache);
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    (hiitl as any).evaluator.evaluate = () => {
      throw new Error('the evaluator failed');
    };

    const d = hiitl.evaluate({ action: 'pay' }) as any;
    expect([d.decision, d.allowed, d.reason_codes]).toEqual(['POLICY_ERROR', false, ['POLICY_EVALUATION_FAILED']]);
    const [record] = (hiitl as any).auditLogger.queryByActionId(d.action_id);
    expect(record.decision_type).toBe('POLICY_ERROR');   // as over the cached version (row 159)
    spy.mockRestore();
  });
});

describe('row 240: observed in observe mode (behavior 4)', () => {
  it("OBSERVE_ALL observes the switch under the tick's version", async () => {
    const { cache, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));
    const hiitl = client(cache, 'OBSERVE_ALL');

    const d = hiitl.evaluate({ action: 'pay' }) as any;
    expect([d.decision, d.allowed, d.would_be, d.policy_version]).toEqual(['OBSERVE', true, 'KILL_SWITCH', 'v1.0.1']);
    expect(read(hiitl.evaluate({ action: 'refund' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-refund']]);
  });
});

describe('row 240: a switch the call cannot read under fail_closed blocks the call (behavior 5)', () => {
  const haltLarge = () => {
    const over = { field: 'parameters.amount', operator: 'greater_than', value: 100 };
    return content(
      'v1.0.1', [rule('halt-large', 'KILL_SWITCH', 'active', { all_of: [on('pay'), over] }), ALLOW_PAY], 'fail_closed'
    );
  };

  it("a fail_closed switch whose field the call lacks blocks the call under the tick's version", async () => {
    const { cache, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(haltLarge()));
    const hiitl = client(cache);

    const d = hiitl.evaluate({ action: 'pay' }) as any;
    expect(read(d)).toEqual(['BLOCK', 'v1.0.1', ['halt-large']]);   // the switch the call cannot read blocks it
    expect(d.reason_codes).toEqual(['MISSING_FIELD']);
    expect(d.remediation.details).toEqual({ fields: ['parameters.amount'] });   // naming the field
    const [record] = (hiitl as any).auditLogger.queryByActionId(d.action_id);
    expect([record.decision_type, record.policy_version]).toEqual(['BLOCK', 'v1.0.1']);   // recorded so
    expect(read(hiitl.evaluate({ action: 'pay', parameters: { amount: 500 } })))
      .toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-large']]);
    expect(read(hiitl.evaluate({ action: 'refund' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-refund']]);   // read
  });

  it('OBSERVE_ALL reads a fail_closed switch as skip and leaves the call to the cached version', async () => {
    const { cache, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(haltLarge()));
    const hiitl = client(cache, 'OBSERVE_ALL');

    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);   // binds nothing
    const d = hiitl.evaluate({ action: 'pay', parameters: { amount: 500 } }) as any;
    expect([d.decision, d.would_be, d.policy_version]).toEqual(['OBSERVE', 'KILL_SWITCH', 'v1.0.1']);
  });
});

describe("row 240: a pull that lands ends the tick's part (behavior 6)", () => {
  it("a 304 ends the tick's part", async () => {
    const { cache, state, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));
    const hiitl = client(cache);
    expect((hiitl.evaluate({ action: 'pay' }) as any).decision).toBe('KILL_SWITCH');

    state.pull = 304;   // the cached version is the server's
    await tickOnce(tick(HALTED));
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);
  });

  it('a new version that lands decides', async () => {
    const { cache, state, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));
    const hiitl = client(cache);
    expect((hiitl.evaluate({ action: 'pay' }) as any).decision).toBe('KILL_SWITCH');

    state.pull = RESUMED;
    await tickOnce(tick(HALTED));
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.2', ['allow-pay']]);
  });
});

describe('row 240: the pull is made every tick, past the breaker, each miss logged at error (behavior 7)', () => {
  it('pulls past the breaker, each miss recorded on it and logged at error', async () => {
    const { cache, state, tickOnce, breaker } = await engine(RUNNING);
    const ticks = breaker.failure_threshold + 2;   // past the miss that opens it

    for (let n = 1; n <= ticks; n += 1) {
      await tickOnce(tick(HALTED));
      expect(state.pulls).toBe(n);   // every tick pulls, the breaker open or not
    }
    expect(breaker.state).toBe(CircuitState.OPEN);   // each miss recorded on the breaker
    const misses = state.errors.filter((m) => m.includes('its pull failed'));   // not the breaker's own line
    expect(misses).toHaveLength(ticks);
    for (const m of misses) {
      expect(m).toContain('version v1.0.1 (switches [halt-payments])');
      expect(m).toContain('the cached version v1.0.0 (switches [])');
    }

    state.pull = HALTED;
    await tickOnce(tick(HALTED));
    expect(breaker.state).toBe(CircuitState.CLOSED);   // the pull that lands closes it
    expect(read(client(cache).evaluate({ action: 'pay' }))).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);
  });
});

describe('row 240: a deactivation holds until its pull lands (behavior 8)', () => {
  it('a deactivation binds by the cached version until its pull lands', async () => {
    const { cache, state, tickOnce } = await engine(HALTED);
    await tickOnce(tick(RESUMED));
    expect(state.pulls).toBe(1);
    expect(read(client(cache).evaluate({ action: 'pay' }))).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);
  });
});

describe("row 240: a restart keeps the tick's part (behavior 9)", () => {
  it('a tick read from disk at start keeps its part until a pull lands', async () => {
    const { tickOnce } = await engine(RUNNING);
    await tickOnce(tick(HALTED));

    const restarted = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: quiet });
    expect(await restarted.loadFromDisk()).toBe(true);
    const hiitl = client(restarted);
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);

    await restarted.updatePolicies(
      { policies: [policy(RUNNING)], version: 'v1.0.0', redaction_policy: REDACTION }, 'e-v1.0.0'
    );
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);   // a pull landed
  });

  it("an earlier SDK's list on disk loads and decides nothing", async () => {
    await engine(RUNNING);
    const at = { cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: quiet };
    // The file an earlier SDK wrote: the tick's list alone, as its cache wrote it
    await (new SyncCache(at) as any)._tryDiskWrite(
      'kill_switches.json', [{ rule_name: 'halt-payments', active: true, scope: { environment: ENV } }]
    );

    const restarted = new SyncCache(at);
    expect(await restarted.loadFromDisk().catch((e: unknown) => e)).toBe(true);   // the version still warm-starts
    expect([restarted.tickPart(), restarted.getKillSwitches()]).toEqual([null, null]);
    expect(restarted.getKillSwitchesAgeSeconds()).toBe(Infinity);   // no tick held
    expect(read(client(restarted).evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);
  });
});

describe('row 240: the rule decides, not the name (behavior 10)', () => {
  it('what a switch stops is its rule', async () => {
    const halted = content('v1.0.1', [rule('halt-payments', 'KILL_SWITCH', 'active', on('refund')), ALLOW_PAY]);
    const { cache, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(halted));
    const hiitl = client(cache);
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);
    expect(read(hiitl.evaluate({ action: 'refund' }))).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);
  });

  it('a tick carrying no policy_set decides nothing and still pulls', async () => {
    const { cache, state, tickOnce } = await engine(RUNNING);
    await tickOnce(tick(null, ['halt-payments']));
    expect(state.pulls).toBe(1);
    expect(read(client(cache).evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);
  });

  it("a switch edited under its own name is a new version and binds through the tick's part", async () => {
    // The same switch, its rule edited to stop refunds: the names agree and the version does not (condition 2)
    const edited = content('v1.0.3', [rule('halt-payments', 'KILL_SWITCH', 'active', on('refund')), ALLOW_PAY]);
    const { cache, state, tickOnce } = await engine(HALTED);
    await tickOnce(tick(edited));
    expect(state.pulls).toBe(1);
    expect(cache.tickPart()).not.toBeNull();
    const hiitl = client(cache);
    expect(read(hiitl.evaluate({ action: 'refund' }))).toEqual(['KILL_SWITCH', 'v1.0.3', ['halt-payments']]);
    expect(read(hiitl.evaluate({ action: 'pay' }))).toEqual(['KILL_SWITCH', 'v1.0.1', ['halt-payments']]);   // outside
  });

  it('a tick naming the cached version holds no part and pulls nothing', async () => {
    const { cache, state, tickOnce } = await engine(HALTED);
    await tickOnce(tick(HALTED));
    expect(state.pulls).toBe(0);
    expect(cache.tickPart()).toBeNull();
    expect(read(client(cache).evaluate({ action: 'refund' }))).toEqual(['ALLOW', 'v1.0.1', ['allow-refund']]);
  });

  it('a tick whose policy_set the model refuses decides nothing, is logged and still pulls', async () => {
    const { cache, state, tickOnce } = await engine(RUNNING);
    const { scope: _scope, ...unscoped } = tick(HALTED).policy_set as Record<string, unknown>;
    await tickOnce({ ...tick(HALTED), policy_set: unscoped } as ReturnType<typeof tick>).catch(() => {});
    const refused = state.errors.filter((m) => m.includes('policy_set cannot be read'));
    expect(refused).toHaveLength(1);
    expect(refused[0]).toContain('scope');
    expect(state.pulls).toBe(1);
    expect(read(client(cache).evaluate({ action: 'pay' }))).toEqual(['ALLOW', 'v1.0.0', ['allow-pay']]);
  });
});
