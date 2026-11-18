/**
 * Row 131 (HTL-29): the kill-switch tick is the change signal, and the version decides.
 *
 * policy_format.md "A version identifies what evaluates" and "Same envelope + same policy version = same decision.
 * Always."; sync_engine.md 2.4, the version the tick names against the version the SDK evaluates (condition 2,
 * 2026-11-10), and section 6 "Kill Switches — Server Wins, Through the Version". Design: the HTL-29 test design, row
 * 131, behaviors 3-5.
 * Mirrors python/hiitl/sdk/tests/test_row131.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { canonicalHash } from '@hiitl/core';

import { HIITL } from '../../src/client.js';
import type { Logger } from '../../src/logger.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const ORG = 'org_test0123456789ab';
const ENV = 'dev';
const ON_PAY = { field: 'action', operator: 'equals', value: 'pay' };
const REDACTION = { manual_redact_fields: [] };
const quiet: Logger = { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} };

const rule = (name: string, decision: string, stage = 'active') => ({
  name, description: name, priority: 100, conditions: ON_PAY, decision,
  reason_code: name.toUpperCase().replace(/-/g, '_'), lifecycle_stage: stage,
});
const content = (version: string, ...rules: object[]) => ({
  name: 'payments', version, description: 'payments', scope: { org_id: ORG, environment: ENV }, rules,
});
const HALTED = content('v1.0.1', rule('halt-payments', 'KILL_SWITCH'), rule('allow-pay', 'ALLOW'));
const RUNNING = content('v1.0.0', rule('halt-payments', 'KILL_SWITCH', 'disabled'), rule('allow-pay', 'ALLOW'));
const RESUMED = content('v1.0.2', rule('halt-payments', 'KILL_SWITCH', 'disabled'), rule('allow-pay', 'ALLOW'));

const policy = (c: ReturnType<typeof content>, active = true) => ({
  policy_id: `pol_${c.version}`, name: c.name, version: c.version, active, content: c, content_hash: canonicalHash(c),
});
const names = (...named: string[]) => named.map((n) => ({ rule_name: n, active: true, scope: { environment: ENV } }));

/** The tick as the service writes it for `c`: its live switches, and its `policy_set` (the set's own fields and those
 * switches). */
const tick = (c: ReturnType<typeof content>) => {
  const { rules, ...fields } = c;
  const live = (rules as Array<Record<string, unknown>>)
    .filter((r) => r.decision === 'KILL_SWITCH' && r.lifecycle_stage === 'active');
  return { kill_switches: names(...live.map((r) => String(r.name))), policy_set: { ...fields, rules: live } };
};

let dir: string;
const clients: HIITL[] = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row131-'));
});

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  fs.rmSync(dir, { recursive: true, force: true });
});

async function engine(t: ReturnType<typeof tick> | null, ...cached: object[]) {
  const pulls: string[] = [];
  const client = new SyncClient({
    server_url: 'https://api.test', api_key: 'k', org_id: ORG, environment: ENV, max_retries: 0, timeout: 5,
    logger: quiet,
    fetchImpl: async (url: string | URL | Request) => {
      const json = (body: unknown) => new Response(JSON.stringify(body),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
      if (String(url).endsWith('/v1/sync/kill-switches')) {
        return json({ kill_switches: [], policy_set: null, ...t, server_time: '2026-11-09T00:00:00+00:00' });
      }
      pulls.push(String(url));
      return json({ policies: [policy(HALTED)], version: 'v1.0.1', etag: 'e-v1.0.1', redaction_policy: REDACTION });
    },
  });
  const cache = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: quiet });
  await cache.updatePolicies({ policies: cached, version: 'cached', redaction_policy: REDACTION }, 'e-cached');
  const e = new SyncEngine({
    sync_config: { server_url: 'https://api.test' }, sync_cache: cache,
    audit_logger: { getUnsynced: () => [], markSynced: () => 0 }, api_key: 'k', org_id: ORG, environment: ENV,
    logger: quiet, sync_client: client,
  });
  const syncTick = () => (e as unknown as { _syncKillSwitches: () => Promise<void> })._syncKillSwitches();
  return { cache, pulls, syncTick };
}

const versions = (cache: SyncCache) =>
  ((cache.getPolicies()?.policies ?? []) as Array<{ version: string }>).map((p) => p.version);

describe('row 131: a tick that differs pulls the version (behavior 3)', () => {
  it('a tick naming a version other than the cached one pulls in that tick', async () => {
    const { cache, pulls, syncTick } = await engine(tick(HALTED), policy(RUNNING));
    await syncTick();
    expect(pulls).toHaveLength(1);
    expect(versions(cache)).toEqual(['v1.0.1']);   // the version the tick names
  });

  it('a tick naming the cached version downloads nothing', async () => {
    for (const cached of [RUNNING, HALTED]) {
      const { pulls, syncTick } = await engine(tick(cached), policy(cached));
      await syncTick();
      expect(pulls).toEqual([]);
    }
  });

  it('a tick that drops a switch pulls', async () => {
    const { pulls, syncTick } = await engine(tick(RESUMED), policy(HALTED));
    await syncTick();
    expect(pulls).toHaveLength(1);
  });
});

describe('row 131: the version is the one evaluate reads (behavior 4)', () => {
  it('the tick compares the version evaluate reads', async () => {
    const { pulls, syncTick } = await engine(tick(HALTED), policy(HALTED, false), policy(RUNNING));
    await syncTick();
    expect(pulls).toHaveLength(1);
  });
});

describe('row 131: the list never decides (behavior 5)', () => {
  it('a cached list naming a switch the version does not make live decides nothing', async () => {
    const { cache } = await engine(null, policy(RUNNING));
    await cache.updateKillSwitches({ kill_switches: names('halt-payments'), policy_set: null, server_time: '' }); // a tick carrying no policy_set (row 240)

    const policyPath = path.join(dir, 'local.json');
    fs.writeFileSync(policyPath, JSON.stringify(content('v0.0.1', rule('local-allow', 'ALLOW'))));
    const hiitl = new HIITL({
      environment: ENV, agent_id: 'payment-agent', org_id: ORG, policy_path: policyPath, audit_db_path: ':memory:',
      mode: 'RESPECT_POLICY',
    });
    clients.push(hiitl);
    (hiitl as unknown as { syncCache: SyncCache }).syncCache = cache;
    const d = hiitl.evaluate({ action: 'pay' });
    expect([d.decision, d.policy_version]).toEqual(['ALLOW', 'v1.0.0']);   // the cached version decides
    expect(d.matched_rules?.map((m) => m.rule_name)).toEqual(['allow-pay']);
  });
});
