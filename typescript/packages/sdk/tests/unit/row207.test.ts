/**
 * Row 207 (HTL-23): a set variable no setting reads is refused.
 *
 * Ruled 2026-11-06: "a set `HIITL_*` variable no setting reads is refused at construction, naming its replacement, by
 * Principle 11 and ontology §4.3". The families the SDK's specs give it are refused (sync_engine.md §9, the
 * `HIITL_SYNC_*` names; telemetry_schema.md §5, the `HIITL_TELEMETRY_*` names), with each name an earlier release read
 * (§5, "Names earlier releases read"). The tables are read from the specs and the read names from `ENV_SETTINGS`, the
 * SDK's reader; no name is listed here. Design: the HTL-23 test design, row 207. Mirrors
 * python/hiitl/sdk/tests/test_row207.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { EARLIER_NAMES, ENV_SETTINGS } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { EARLIER, FAMILIES, SYNC, TELEMETRY, code } from './settings-tables.js';

const PREFIXES = Object.keys(FAMILIES);
const READ = ENV_SETTINGS.map(([name]) => name).filter((name) => PREFIXES.some((p) => name.startsWith(p)));
// Each family name a spec table names and no setting reads (computed: the tables less the reader)
const UNREAD = Object.values(FAMILIES).flat().filter((name) => !READ.includes(name)).sort();
// a row states a default as a code span
const DEFAULTS: Record<string, string> = Object.fromEntries(
  [...SYNC, ...TELEMETRY].filter((row) => row[3].includes('`')).map((row) => [code(row[2]), code(row[3])]),
);

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // no ambient setting reaches a cell
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row207-'));
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    delete process.env[name];
  }
  Object.assign(process.env, ambient);
  rmSync(dir, { recursive: true, force: true });
});

function construct(): void {
  new HIITL({ audit_db_path: path.join(dir, 'audit.db') }).close();
}

/** The message the client's construction is refused with. */
function refused(): string {
  try {
    construct();
  } catch (e) {
    expect(e).toBeInstanceOf(ConfigurationError);
    return (e as Error).message;
  }
  return expect.unreachable('construction was not refused');
}

describe('row 207: a set variable no setting reads is refused at construction', () => {
  it.each(Object.keys(EARLIER).sort())(
    'test_an_earlier_name_is_refused_naming_its_replacement[%s]',
    (earlier) => {
      process.env[earlier] = DEFAULTS[EARLIER[earlier]];
      const message = refused();
      expect(message).toContain(earlier);
      expect(message).toContain(EARLIER[earlier]);
    },
  );

  it.each(PREFIXES.sort())('test_an_unread_family_name_is_refused_naming_the_family[%s]', (family) => {
    const unread = `${family}R207_UNREAD`;
    process.env[unread] = '1';
    const message = refused();
    expect(message).toContain(unread);
    expect(READ.filter((name) => name.startsWith(family) && !message.includes(name)), message).toEqual([]);
  });

  it.each(UNREAD)('test_a_name_a_table_names_and_no_setting_reads_is_refused[%s]', (unread) => {
    process.env[unread] = DEFAULTS[unread] ?? '1';
    expect(refused()).toContain(unread);
  });

  it('test_the_sdks_table_is_the_specs', () => {
    expect(EARLIER_NAMES).toEqual(EARLIER);
  });

  it('test_a_name_a_setting_reads_constructs', () => {
    for (const name of READ) process.env[name] = DEFAULTS[name] ?? '1';
    expect(construct, 'a name a setting reads constructs').not.toThrow();
  });
});
