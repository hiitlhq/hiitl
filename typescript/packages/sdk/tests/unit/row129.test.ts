/**
 * Row 129 (HTL-20): a documented setting has an effect.
 *
 * config.ts's precedence: an option passed wins, then its HIITL_* variable, then its default. ENV_SETTINGS is the
 * reader, so each variable is driven into the option it names, and the client is checked to act on what it read.
 * python/hiitl/sdk/tests/test_row129.py holds ENV_SETTINGS to the Python SDK's readers, name and option
 * (Principle 10).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { ENV_SETTINGS, resolveSettings } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncEngine } from '../../src/sync-engine.js';
import type { Logger } from '../../src/logger.js';
import { HOSTED, TELEMETRY, code } from './settings-tables.js';

// each kind's text, and the value it is read as
const SAMPLE = {
  string: ['x-value', 'x-value'], number: ['7', 7], boolean: ['false', false], list: ['["x"]', ['x']],
} as const;

// a number the spec bounds is set to its low bound, inside the range and not its default (the Python cell's
// _candidate reads the same bounds at the field)
const LOW: Record<string, number> = Object.fromEntries(
  [...TELEMETRY, ...HOSTED].flatMap((row) => {
    const low = /^(\d+(?:\.\d+)?)–/.exec(row[4]);
    return low ? [[code(row[2]), Number(low[1])]] : [];
  }),
);

function sample(name: string, kind: keyof typeof SAMPLE): readonly [string, unknown] {
  return kind === 'number' && name in LOW ? [String(LOW[name]), LOW[name]] : SAMPLE[kind];
}

const BLOCK_REFUNDS = {
  name: 'p', version: 'v1.0.0', description: 'The p set', scope: { org_id: 'org_x0000000000000000', environment: 'dev' }, rules: [{
    name: 'no_refunds', description: 'd', priority: 10, decision: 'BLOCK', reason_code: 'NO_REFUNDS',
    conditions: { field: 'action', operator: 'equals', value: 'refund' },
  }],
};

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // each cell sets the variables it reads; none comes from the shell that runs the suite
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row129-'));
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

function at(options: Record<string, any>, key: string): unknown {
  return key.split('.').reduce<any>((v, k) => v?.[k], options);
}

function policyFile(): string {
  const p = path.join(dir, 'policy.json');
  writeFileSync(p, JSON.stringify(BLOCK_REFUNDS));
  return p;
}

function quietSync(initialOk = true) {
  vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(initialOk);
  vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
}

function internals(h: HIITL): { syncEngine?: any; syncCache?: any; _initialSyncPromise: Promise<boolean> } {
  return h as unknown as { syncEngine?: any; syncCache?: any; _initialSyncPromise: Promise<boolean> };
}

describe('each HIITL_* variable is read into the option it names', () => {
  it.each(ENV_SETTINGS.map(([name, key, kind]) => [name, key, kind] as const))(
    '%s is read into %s',
    (name, key, kind) => {
      const [text, value] = sample(name, kind);
      process.env[name] = text;
      expect(at(resolveSettings({}), key)).toEqual(value);
    }
  );

  it('a boolean variable reads the spellings the Python SDK reads', () => {
    for (const [text, value] of [['yes', true], ['On', true], ['1', true], ['no', false], ['OFF', false], ['0', false]] as const) {
      process.env.HIITL_SYNC = text;
      expect(resolveSettings({}).sync).toBe(value);
    }
  });

  it('a value its kind cannot read is refused, naming the variable', () => {
    process.env.HIITL_TIMEOUT = 'soon';
    expect(() => new HIITL({ audit_db_path: ':memory:' })).toThrow(/HIITL_TIMEOUT='soon' is not a number/);
    delete process.env.HIITL_TIMEOUT;
    process.env.HIITL_SYNC = 'maybe';
    expect(() => new HIITL({ audit_db_path: ':memory:' })).toThrow(ConfigurationError);
    expect(() => new HIITL({ audit_db_path: ':memory:' })).toThrow(/HIITL_SYNC='maybe' is not a boolean/);
  });
});

describe('the client acts on what it read', () => {
  it('HIITL_ENVIRONMENT is read', () => {
    process.env.HIITL_ENVIRONMENT = 'stage';
    expect(new HIITL({ audit_db_path: ':memory:' }).config?.environment).toBe('stage');
  });

  it('HIITL_POLICY_PATH and HIITL_MODE are read', async () => {
    process.env.HIITL_POLICY_PATH = policyFile();
    process.env.HIITL_MODE = 'RESPECT_POLICY';
    const d = await new HIITL({ audit_db_path: ':memory:' }).evaluate({ action: 'refund' });
    expect([d.allowed, d.reason_codes]).toEqual([false, ['NO_REFUNDS']]);
  });

  it('an argument outranks its variable', async () => {
    process.env.HIITL_ENVIRONMENT = 'stage';
    process.env.HIITL_MODE = 'RESPECT_POLICY';
    process.env.HIITL_POLICY_PATH = policyFile();
    const h = new HIITL({ environment: 'dev', mode: 'OBSERVE_ALL', audit_db_path: ':memory:' });
    expect(h.config?.environment).toBe('dev');
    expect((await h.evaluate({ action: 'refund' })).decision).toBe('OBSERVE');
  });

  it('a given sync_config keeps the variables it leaves unset', () => {
    process.env.HIITL_SYNC_AUDIT_INTERVAL = '45';
    expect(resolveSettings({ sync_config: { policy_sync_interval: 600 } }).sync_config).toEqual({
      audit_sync_interval: 45,
      policy_sync_interval: 600,
    });
  });

  it('HIITL_API_KEY starts hybrid mode with the variables sync target', async () => {
    quietSync();
    process.env.HIITL_API_KEY = 'sk_from_the_environment';
    process.env.HIITL_SERVER_URL = 'https://sync.example';
    process.env.HIITL_CACHE_DIR = path.join(dir, 'cache');
    const h = new HIITL({ audit_db_path: ':memory:' });
    await internals(h)._initialSyncPromise;
    expect(h.mode).toBe('hybrid');
    const engine = internals(h).syncEngine;
    expect(engine.config.server_url).toBe('https://sync.example');
    expect(engine.client.defaultHeaders.Authorization).toBe('Bearer sk_from_the_environment');
    expect(internals(h).syncCache.baseDir.startsWith(path.join(dir, 'cache'))).toBe(true);
    h.close();
  });

  it('each HIITL_SYNC_* setting reaches the sync engine', async () => {
    quietSync();
    process.env.HIITL_API_KEY = 'sk_from_the_environment';
    process.env.HIITL_CACHE_DIR = path.join(dir, 'cache');
    const sync = ENV_SETTINGS.filter(([name, key]) => name.startsWith('HIITL_SYNC_') && key.startsWith('sync_config.'));
    sync.forEach(([name], i) => (process.env[name] = String(1000 + i)));
    const h = new HIITL({ audit_db_path: ':memory:' });
    await internals(h)._initialSyncPromise;
    const { syncEngine, syncCache } = internals(h);
    sync.forEach(([name, key], i) => {
      const option = key.split('.')[1];
      // the stale age is the cache's (sync_engine.md section 9: the disk cache's max age)
      const read = option === 'max_cache_stale_age' ? syncCache.maxStaleAge : syncEngine.config[option];
      expect([name, read]).toEqual([name, 1000 + i]);
    });
    h.close();
  });

  it('HIITL_SYNC=false keeps a keyed client local', () => {
    quietSync();
    process.env.HIITL_API_KEY = 'sk_from_the_environment';
    process.env.HIITL_SYNC = 'false';
    const h = new HIITL({ audit_db_path: ':memory:' });
    expect(h.mode).toBe('local');
    expect(SyncEngine.prototype.initialSync).not.toHaveBeenCalled();
    h.close();
  });

  it('HIITL_EVALUATION=remote with a server url is hosted', () => {
    process.env.HIITL_API_KEY = 'sk_from_the_environment';
    process.env.HIITL_EVALUATION = 'remote';
    expect(() => new HIITL()).toThrow(/server_url is required/);
    process.env.HIITL_SERVER_URL = 'https://ecp.example';
    process.env.HIITL_SIGNATURE_KEY = 's'.repeat(32); // hosted signs what it sends (row 134)
    const h = new HIITL();
    expect([h.mode, h.hostedConfig?.server_url]).toEqual(['hosted', 'https://ecp.example']);
  });
});

describe('BUFFER_FULL (sync_engine.md section 7)', () => {
  it('is emitted once per crossing, by records or by bytes', () => {
    const warned: string[] = [];
    const log: Logger = { debug: () => {}, info: () => {}, warn: (m: string) => warned.push(m), error: () => {} };
    const backlog = { count: 0, size: 0 };
    const org = 'org_x0000000000000000';
    const engine = new SyncEngine({
      sync_config: { server_url: 'https://api.test', max_buffer_records: 100, max_buffer_size_bytes: 1048576 },
      sync_cache: new SyncCache({ cache_dir: dir, org_id: org, environment: 'dev', logger: log }),
      audit_logger: { getUnsynced: () => [], markSynced: () => 0, unsyncedBacklog: () => [backlog.count, backlog.size] },
      api_key: 'sk_test_1234567890abcdef',
      org_id: org,
      environment: 'dev',
      logger: log,
    });
    const check = () => (engine as unknown as { _checkAuditBuffer: () => void })._checkAuditBuffer();
    const full = () => warned.filter((m) => m.startsWith('BUFFER_FULL'));
    backlog.count = 99;
    check();
    expect(full()).toEqual([]);
    backlog.count = 100;
    check();
    check();
    expect(full()).toHaveLength(1);
    backlog.count = 10;
    check();
    backlog.size = 1048576;
    check();
    expect(full()).toHaveLength(2);
    expect(full()[1]).toContain('No record is dropped');
  });
});
