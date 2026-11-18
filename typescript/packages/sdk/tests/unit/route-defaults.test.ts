/** HTL-39: actual SDK route reading and complete serialized context. */
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { RouteLoader, resolveEscalationContext } from '../../src/route-loader.js';
import { allCases, expectedContext } from '../../../../../tests/conformance/route_defaults/generate.mjs';

it.each(allCases())('loads defaults and the complete context: $id', row => {
  const directory = mkdtempSync(join(tmpdir(), 'hiitl-route-default-'));
  vi.stubEnv('HTL39_ROUTE_FIXTURE', 'local-route-fixture');
  try {
    writeFileSync(join(directory, `${row.input.name}.json`), JSON.stringify(row.input));
    const route = new RouteLoader(directory).get(row.input.name)!;
    expect(route).toStrictEqual(row.expected);
    expect(JSON.parse(JSON.stringify(resolveEscalationContext(route)))).toStrictEqual(expectedContext(row.expected));
  } finally {
    vi.unstubAllEnvs();
    rmSync(directory, {recursive:true,force:true});
  }
});
