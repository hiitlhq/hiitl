/**
 * Row 172 (HTL-22): one telemetry setting, the spec's.
 *
 * Trevor's ruling on HTL-20: "one telemetry setting, `HIITL_TELEMETRY_LEVEL` with `off`, top-level; the `HIITL_SYNC_`
 * name dropped". telemetry_schema.md §5 Configuration is read at its producer. This SDK ships no collector
 * (limits-and-roadmap.mdx), so it reads and checks the setting and sends nothing at any level. Design: the HTL-22 test
 * design, row 172, behaviors 1 and 5. Mirrors python/hiitl/sdk/tests/test_row172.py.
 */

import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ENV_SETTINGS, resolveSettings } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { SyncEngine } from '../../src/sync-engine.js';

// §5's Configuration table: each method and its setting
const spec = readFileSync(path.join(__dirname, '../../../../../docs/specs/telemetry_schema.md'), 'utf8');
const table = spec.slice(spec.indexOf('### Configuration')).split('\n\n')[1];
const CONFIGURATION = Object.fromEntries(
  table.split('\n').slice(2).map((line) => line.split(/(?<!\\)\|/).slice(1, -1).map((cell) => cell.trim()))
);
const [, OPTION, VALUES] = /^`(\w+): (.+)`$/.exec(CONFIGURATION['Constructor option'])!;
const LEVELS = [...VALUES.matchAll(/"(\w+)"/g)].map((m) => m[1]);
const VARIABLE = CONFIGURATION['Environment variable'].replace(/`/g, '');

let ambient: Record<string, string | undefined>;
let dir: string;

beforeEach(() => {
  // each cell sets the variables it reads; none comes from the shell that runs the suite
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row172-'));
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

describe('row 172: one telemetry setting, the spec\'s', () => {
  it("ENV_SETTINGS reads the spec's variable into the spec's option", () => {
    expect(ENV_SETTINGS.filter(([name]) => name === VARIABLE).map(([, key]) => key)).toEqual([OPTION]);
    process.env[VARIABLE] = LEVELS[0];
    expect((resolveSettings({}) as Record<string, unknown>)[OPTION]).toBe(LEVELS[0]);
  });

  it.each(LEVELS)("the client takes '%s'", (level) => {
    const h = new HIITL({ audit_db_path: ':memory:', [OPTION]: level });
    h.close();
  });

  it.each(['option', 'variable'])('a value outside the levels is refused by %s, naming each level', (given) => {
    if (given === 'variable') process.env[VARIABLE] = 'verbose';
    const options = given === 'option' ? { [OPTION]: 'verbose' } : {};
    let refused: unknown;
    try {
      new HIITL({ audit_db_path: ':memory:', ...options }).close();
    } catch (e) {
      refused = e;
    }
    expect(refused).toBeInstanceOf(ConfigurationError);
    const message = (refused as Error).message;
    expect(LEVELS.filter((level) => !message.includes(`'${level}'`))).toEqual([]);
  });

  it.each(LEVELS)("a hybrid client at '%s' hands its sync engine no collector, so it sends no telemetry", async (level) => {
    vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(true);
    vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
    const h = new HIITL({
      api_key: 'sk_test_row172', audit_db_path: ':memory:', cache_dir: path.join(dir, 'cache'), [OPTION]: level,
    });
    const engine = (h as unknown as { syncEngine: { telemetryCollector?: unknown } }).syncEngine;
    expect(h.mode).toBe('hybrid');
    expect(engine.telemetryCollector).toBeUndefined();
    h.close();
  });
});
