/**
 * Row 208 (HTL-23): one telemetry family.
 *
 * Ruled 2026-11-06: "One telemetry family: the spec names the interval, buffer size, sample rate and parameter tools
 * as `HIITL_TELEMETRY_*` beside `HIITL_TELEMETRY_LEVEL` (spec before cells), both SDKs read them, and the stale
 * `HIITL_SYNC_TELEMETRY_*` names are refused under row 207. By row 172's ruling and B.foundation.6." Each row of
 * telemetry_schema.md §5's family table is read at its producer: its variable, set, is read into the option it names,
 * and a value outside its range is refused at construction naming the range. No name, bound or member is listed here.
 * The SDK ships no collector (§5), so the reader is what holds the value. The stale names are row 207's cells. Design:
 * the HTL-23 test design, row 208. Mirrors python/hiitl/sdk/tests/test_row208.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { ENV_SETTINGS, resolveSettings } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { SyncEngine } from '../../src/sync-engine.js';
import { TELEMETRY, code } from './settings-tables.js';

const BOUNDS = /^(-?\d+(?:\.\d+)?)–(-?\d+(?:\.\d+)?)/;

/** [values inside the range, values outside it, the words a refusal names], read from the row's cells. */
function kind(row: string[]): [string[], string[], string[]] {
  const [defaultValue, range] = [code(row[3]), row[4]];
  const members = [...range.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  if (members.length) return [members.filter((m) => m !== defaultValue).slice(0, 1), ['r208-outside'], members];
  const bounds = BOUNDS.exec(range);
  if (bounds) {
    const [low, high] = [bounds[1], bounds[2]];
    const inside = [high, low].filter((b) => Number(b) !== Number(defaultValue)).slice(0, 1);
    return [inside, [String(Number(low) - 1), String(Number(high) + 1)], [low, high]];
  }
  const form = /\(an? ([^)]+)\)/.exec(row[2])![1];
  expect(form, `${code(row[2])}: a form the cell does not read`).toBe('JSON list');
  return [['["r208_action"]'], ['r208_action'], [form]];
}

const ROWS = TELEMETRY.map((row) => [code(row[1]), code(row[2]), ...kind(row)] as const);

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // no ambient setting reaches a cell
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row208-'));
  vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(false);
  vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    delete process.env[name];
  }
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const at = (options: Record<string, any>, key: string): unknown => key.split('.').reduce<any>((v, k) => v?.[k], options);

function same(held: unknown, text: string): boolean {
  if (text.startsWith('[')) return JSON.stringify(held) === JSON.stringify(JSON.parse(text));
  return typeof held === 'number' ? held === Number(text) : held === text;
}

function hybrid(): void {
  new HIITL({
    api_key: 'sk_test_row208', org_id: 'org_r208telemetry00000', audit_db_path: path.join(dir, 'audit.db'),
    cache_dir: path.join(dir, 'cache'),
  }).close();
}

const whole = (word: string, text: string) =>
  new RegExp(`(?<![\\w.])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w.])`).test(text);

describe('row 208: one telemetry family', () => {
  it('test_the_table_is_the_family', () => {
    const variables = ROWS.map(([, variable]) => variable);
    expect(ENV_SETTINGS.filter(([variable]) => variable.startsWith('HIITL_TELEMETRY_'))
      .map(([variable, option]) => [variable, option]).sort())
      .toEqual(TELEMETRY.map((row) => [code(row[2]), code(row[1])]).sort());
    expect(variables.filter((v) => !v.startsWith('HIITL_TELEMETRY_'))).toEqual([]);
  });

  it.each(ROWS)('test_each_setting_is_read_under_its_spec_name[%s ← %s]', (option, variable, inside) => {
    for (const value of inside) {
      process.env[variable] = value;
      let settings: ReturnType<typeof resolveSettings> | undefined;
      expect(() => {
        settings = resolveSettings({});
      }, `${variable}=${value} was refused, not read`).not.toThrow();
      const held = at(settings!, option);
      expect(same(held, value), `${variable}=${value}: ${option} is ${JSON.stringify(held)}`).toBe(true);
      hybrid();
    }
  });

  it.each(ROWS)('test_a_value_outside_the_range_is_refused_naming_it[%s ← %s]', (_option, variable, _inside,
    outside, words) => {
    for (const value of outside) {
      process.env[variable] = value;
      let refused: unknown;
      try {
        hybrid();
      } catch (e) {
        refused = e;
      }
      expect(refused, `${variable}=${value} was not refused`).toBeInstanceOf(ConfigurationError);
      const message = (refused as Error).message;
      expect(words.filter((w) => !whole(w, message)), `${variable}=${value}: ${message}`).toEqual([]);
    }
  });
});
