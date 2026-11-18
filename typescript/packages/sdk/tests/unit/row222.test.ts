/**
 * Row 222 (HTL-24): the SDK's families are its own.
 *
 * Ruled 2026-11-07: "each component refuses the unread names of its own families (the gateway `HIITL_MCP_*`, the
 * scanner `HIITL_SCAN_*`) … The SDK holds no copy of another component's settings (one representation per fact)." The
 * SDK's families are those its specs' tables give it (sync_engine.md §9, telemetry_schema.md §5), and a set name of
 * no family of its own constructs. Design: the HTL-24 test design, row 222, behavior 4 (behavior 1 is the Python
 * SDK's twin).
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { SETTING_FAMILIES } from '../../src/config.js';
import { HIITL } from '../../src/client.js';
import { FAMILIES } from './settings-tables.js';

let dir: string;
let ambient: Record<string, string | undefined>;
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'row222-'));
});
afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) delete process.env[name];
  Object.assign(process.env, ambient);
  rmSync(dir, { recursive: true, force: true });
});

describe("row 222: the SDK's families are its own", () => {
  it("are the families its specs' tables give it", () => {
    expect([...SETTING_FAMILIES].sort()).toEqual(Object.keys(FAMILIES).sort());
    for (const [family, names] of Object.entries(FAMILIES)) {
      expect(names.filter((name) => !name.startsWith(family))).toEqual([]);
    }
  });

  it('a set name of no family of its own constructs', () => {
    process.env.HIITL_R222OTHER_UNREAD = '1';
    const construct = () => new HIITL({ audit_db_path: path.join(dir, 'audit.db') }).close();
    expect(construct, 'a name of no family of its own constructs').not.toThrow();
  });
});
