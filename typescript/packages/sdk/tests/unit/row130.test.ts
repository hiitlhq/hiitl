/**
 * Row 130 (HTL-20): the same arguments give the same mode in both SDKs.
 *
 * docs-site/concepts/deployment-modes.mdx: hosted evaluation "is an explicit opt-in", so an api_key with a server_url is hybrid
 * (the server_url is the sync target), and hosted takes `evaluation: 'remote'`. Principle 10: no language gets a
 * structural advantage. python/hiitl/sdk/tests/test_row130.py holds the same table, and each SDK's configuration
 * page states it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HIITL } from '../../src/client.js';
import type { HIITLConfigInput } from '../../src/config.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { SyncEngine } from '../../src/sync-engine.js';
import { declaredTable } from '../../../../test-support/declarations.js';

const KEY = 'sk_test_1234567890abcdef';
const URL = 'https://ecp.example';
// every mode takes the signing secret; hosted needs it (row 134)
const SIGNING_SECRET = 's'.repeat(32);
const PAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../docs-site/sdk/typescript-configuration.mdx');

type Mode = 'local' | 'hybrid' | 'hosted' | typeof ConfigurationError;

// the constructor options → the mode, or the error a client without what it needs throws
const MODES: Array<[HIITLConfigInput, Mode]> = [
  [{}, 'local'],
  [{ api_key: KEY }, 'hybrid'],
  [{ api_key: KEY, server_url: URL }, 'hybrid'],
  [{ api_key: KEY, sync: false }, 'local'],
  [{ api_key: KEY, server_url: URL, evaluation: 'remote' }, 'hosted'],
  [{ server_url: URL, evaluation: 'remote' }, 'local'],
  [{ api_key: KEY, evaluation: 'remote' }, ConfigurationError],
];

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row130-'));
  vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(true);
  vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
});

afterEach(() => {
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

function modeOf(options: HIITLConfigInput): string {
  const h = new HIITL({
    ...options, signature_key: SIGNING_SECRET, audit_db_path: ':memory:', cache_dir: path.join(dir, 'cache'),
  });
  const mode = h.mode;
  h.close();
  return mode;
}

function check(options: HIITLConfigInput, mode: Mode): void {
  if (typeof mode === 'string') {
    expect([options, modeOf(options)]).toEqual([options, mode]);
  } else {
    expect(() => modeOf(options)).toThrow(mode);
  }
}

/** The page's "Auto-detection rules" table: each row's options and the mode it names. */
function pageTable(): Array<[HIITLConfigInput, Mode]> {
  const text = readFileSync(PAGE, 'utf-8');
  const rows = declaredTable(text, '### Auto-detection rules');
  const out: Array<[HIITLConfigInput, Mode]> = [];
  for (const row of rows) {
    const [apiKey, serverUrl, evaluation, sync, mode] = row;
    const options: HIITLConfigInput = {};
    if (apiKey.startsWith('present')) options.api_key = KEY;
    if (serverUrl.startsWith('present')) options.server_url = URL;
    if (evaluation.includes('remote')) options.evaluation = 'remote';
    if (sync.includes('false')) options.sync = false;
    const named = /\*\*(\w+)\*\*/.exec(mode);
    out.push([options, named ? (named[1] as Mode) : ConfigurationError]);
  }
  return out;
}

describe('the mode table (deployment-modes.mdx; client.py)', () => {
  it('the mode table', () => {
    for (const [options, mode] of MODES) check(options, mode);
  });

  it('an unknown evaluation is refused, naming the valid ones', () => {
    expect(() => modeOf({ api_key: KEY, evaluation: 'remot' as 'remote' })).toThrow(/Must be one of: local, remote\./);
  });

  it("the configuration page's table is what the client does", () => {
    const table = pageTable();
    for (const [options, mode] of table) check(options, mode);
    // The complete mapping, including each answer; neither missing nor duplicate rows pass.
    const key = ([options, mode]: [HIITLConfigInput, Mode]) =>
      JSON.stringify([Object.entries(options).sort(), typeof mode === 'string' ? mode : mode.name]);
    expect(table.map(key).sort()).toEqual(MODES.map(key).sort());
  });
});
