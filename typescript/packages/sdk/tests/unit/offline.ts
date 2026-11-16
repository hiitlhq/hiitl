/**
 * The unit suite runs with the network refused (HTL-22 row 180).
 *
 * Trevor's ruling on HTL-20: "the unit suites run with the network refused, by the mode table's CI/CD row", the table
 * that names Pure Local the mode for "Dev, CI/CD, air-gapped". A vitest setup file (vitest.config.ts `setupFiles`):
 * every test file in this directory runs as an offline machine would, from its first line. A connect to any host but
 * the loopback fails at once with ECONNREFUSED, naming the host. The guard sits on `net.Socket.prototype.connect`,
 * which `fetch`, `http`, `https`, `tls` and `net` all connect through, and it acts before the name is looked up.
 * Loopback and local (IPC) sockets stay open. The integration suite and the smoke suites run apart: a file outside this
 * directory has the network back before its hooks and tests run. Mirrors python/conftest.py.
 *
 * Each test runs in a directory of its own (HTL-23). A client given no store path opens `hiitl_audit.db` in the working
 * directory, and a hosted client pushes what that store holds before its call (row 192); a store shared across tests
 * and runs would hand one test what another left.
 */

import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

export const REFUSED = 'the unit suites run with the network refused (HTL-22 row 180)';

const UNIT = path.dirname(fileURLToPath(import.meta.url));
const LOOPBACK = new net.BlockList();
LOOPBACK.addSubnet('127.0.0.0', 8, 'ipv4');
LOOPBACK.addAddress('::1', 'ipv6');

/** Whether `host` stays on this machine: the loopback addresses, and `localhost`, which RFC 6761 reserves for them.
 *  No host is Node's default, localhost. */
export function isLoopback(host: string | undefined): boolean {
  if (host === undefined || ['', 'localhost'].includes(host.toLowerCase())) return true;
  const address = host.replace(/^\[(.*)\]$/, '$1');
  const family = net.isIP(address);
  return family !== 0 && LOOPBACK.check(address, family === 4 ? 'ipv4' : 'ipv6');
}

/** The host a `connect` call names, or null for a local (IPC) socket. Node passes its normalized arguments as one
 *  array; a caller passes `(options)`, `(port, host?)` or `(path)`. */
function connectHost(args: unknown[]): string | undefined | null {
  const [first, second] = Array.isArray(args[0]) ? (args[0] as unknown[]) : args;
  if (first !== null && typeof first === 'object') {
    const options = first as { path?: string | null; host?: string };
    return options.path ? null : options.host; // net's own test: a socket with a path is a pipe (`!!path`)
  }
  if (typeof first === 'number' || (typeof first === 'string' && /^\d+$/.test(first))) {
    return typeof second === 'string' ? second : undefined;
  }
  return null;
}

// the original: the setup runs once per file, and each file ends with it restored
const connect = net.Socket.prototype.connect;

function refusing(this: net.Socket, ...args: unknown[]): net.Socket {
  const host = connectHost(args);
  if (host === null || isLoopback(host)) return (connect as (...a: unknown[]) => net.Socket).apply(this, args);
  const error = Object.assign(new Error(`connect ECONNREFUSED ${host}: ${REFUSED}`), { code: 'ECONNREFUSED', host });
  process.nextTick(() => this.destroy(error));
  return this;
}

net.Socket.prototype.connect = refusing as typeof net.Socket.prototype.connect;

beforeAll(({}, suite) => {
  if (!(suite as { filepath?: string }).filepath?.startsWith(UNIT + path.sep)) net.Socket.prototype.connect = connect;
});

afterAll(() => {
  net.Socket.prototype.connect = connect;
});

const HOME = process.cwd();

beforeEach(() => {
  process.chdir(fs.mkdtempSync(path.join(os.tmpdir(), 'hiitl-cwd-')));
});

afterEach(() => {
  const own = process.cwd();
  process.chdir(HOME);
  fs.rmSync(own, { recursive: true, force: true });
});
