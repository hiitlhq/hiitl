/**
 * The settings tables the specs declare, read at their producer for the settings cells (HTL-23 rows 207-209).
 *
 * Each table is the first markdown table after its heading; a row is its cells. No name is listed here. Mirrors
 * python/hiitl/sdk/tests/settings_tables.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaredTable } from '../../../../test-support/declarations.js';

const SPECS = join(__dirname, '../../../../../docs/specs');

/** The rows of the first table after `heading` in `spec`, each its cells, the header and its rule left out. */
export function table(spec: string, heading: string): string[][] {
  const text = readFileSync(join(SPECS, spec), 'utf8');
  return declaredTable(text, heading);
}

/** The first code span of a cell, its quotes left off. */
export function code(cell: string): string {
  return /`([^`]*)`/.exec(cell)![1].replace(/^"+|"+$/g, '');
}

export const SYNC = table('sync_engine.md', '### Configuration Table');
export const TELEMETRY = table('telemetry_schema.md', '**The telemetry family');
export const EARLIER: Record<string, string> = Object.fromEntries(
  table('telemetry_schema.md', '**Names earlier releases read.**').map(([earlier, replacement]) =>
    [code(earlier), code(replacement)]),
);
export const HOSTED = table('decision_response.md', "**The hosted client's settings.**");

// Each family the SDK's specs give it, and the variables its tables name (row 207)
export const FAMILIES: Record<string, string[]> = {
  HIITL_SYNC_: SYNC.map((row) => code(row[2])).filter((name) => name.startsWith('HIITL_SYNC_')),
  HIITL_TELEMETRY_: TELEMETRY.map((row) => code(row[2])),
};
