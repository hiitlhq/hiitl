/**
 * Row 221 (HTL-24): `HIITL_SYNC_RL_INTERVAL`, as built.
 *
 * Ruled 2026-11-07: "as built … sync_engine.md §9 names row 131 beside it." The class is a §9 row no setting reads:
 * it states no default and names the gap row that would build it; its variable, set, is refused (row 207's cells),
 * and its constructor option is refused as an undefined option, naming it. The rows are read from §9 and the read
 * names from `ENV_SETTINGS`; no name is listed here. Design: the HTL-24 test design, row 221. Mirrors
 * python/hiitl/sdk/tests/test_row221.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { ENV_SETTINGS } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { SYNC, code } from './settings-tables.js';

const READ = ENV_SETTINGS.map(([name]) => name);
const UNBUILT = SYNC.filter((row) => !READ.includes(code(row[2])));

let dir: string;
let ambient: Record<string, string | undefined>;
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'row221-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  rmSync(dir, { recursive: true, force: true });
});

describe('row 221: a §9 row no setting reads', () => {
  it('names its gap row and no default', () => {
    // The spec identifies unbuilt settings independently of what the implementation happens to read.
    expect(UNBUILT).toEqual(SYNC.filter((row) => /\(gap row \d+\)/.test(row[3])));
    for (const row of UNBUILT) {
      expect(row[3].includes('`'), row[2]).toBe(false);
      expect(row[3]).toMatch(/\(gap row \d+\)/);
    }
    expect(SYNC.filter((row) => READ.includes(code(row[2])) && !row[3].includes('`'))).toEqual([]);
  });

  it.each(UNBUILT.map((row) => [code(row[1])]))('the option %s is refused, naming it', (option) => {
    let refused: unknown;
    try {
      new HIITL({ audit_db_path: path.join(dir, 'audit.db'), [option]: 60 } as never).close();
    } catch (e) {
      refused = e;
    }
    expect(refused, `${option} constructs`).toBeInstanceOf(Error);
    expect((refused as Error).message).toContain(option);
  });
});
