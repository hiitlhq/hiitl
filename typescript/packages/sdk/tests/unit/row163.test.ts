/**
 * Row 163 (HTL-22) (a), (c) and (e): the SDK's store and the org's declaration, the store's value-hash key, and a
 * declared path the call does not carry.
 *
 * Mirrors python/hiitl/sdk/tests/test_row163.py. The contract is docs/specs/event_format.md §Redaction; these are
 * the row's test design cells 2, 3, 10 and 13 ((e) turned with Stop A, HTL-23 row 191).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync, realpathSync, renameSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import fs from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { randomBytes } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { HASH_PREFIX, KEY_BYTES, MARKER, Redaction, auditContentHash, valueHash } from '@hiitl/core';
import { ENVELOPE_SCHEMA_VERSION } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';

import { AuditLogger } from '../../src/audit.js';
import { HIITL } from '../../src/client.js';
import { AuditLogError } from '../../src/exceptions.js';
import { SUFFIX, keyPath } from '../../src/hash-key.js';
import type { Logger } from '../../src/logger.js';
import { SyncCache } from '../../src/sync-cache.js';
import { SyncClient } from '../../src/sync-client.js';
import { SyncEngine } from '../../src/sync-engine.js';

const silent: Logger = { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} };
const ORG = 'org_test0123456789ab';
const ENV = 'dev';
const PARAMETERS = { account_number: 'GB29NWBK60161331926819', amount: 1250 };
const TARGET = { email: 'dana@example.com', vendor_id: 'vnd_42' };

const envelope = (i: number): Envelope => ({
  schema_version: ENVELOPE_SCHEMA_VERSION,
  org_id: ORG,
  environment: ENV,
  agent_id: 'payout-agent',
  action_id: `act_${String(i).padStart(20, '0')}`,
  idempotency_key: `k${i}`,
  action: 'pay',
  operation: 'execute',
  target: TARGET,
  parameters: PARAMETERS,
  timestamp: '2026-11-05T10:30:00Z',
  signature: '0'.repeat(64),
});
const DECISION: Decision = {
  action_id: 'act_00000000000000000000',
  decision: 'ALLOW',
  allowed: true,
  reason_codes: ['OK'],
  policy_version: 'v1',
  timing: { ingest_ms: 0, evaluation_ms: 0, total_ms: 0 },
};

const stored = (logger: AuditLogger) =>
  logger.getUnsynced() as Array<{ envelope: { parameters: Record<string, unknown>; target: Record<string, unknown> } }>;

let dir: string;
let ambient: Record<string, string | undefined>;
beforeEach(() => {
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row163-'));
});
afterEach(() => {
  Object.assign(process.env, ambient);
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
});

function engineWith(redactionPolicy: unknown) {
  const body: Record<string, unknown> = { policies: [], version: 'v2', etag: 'e2' };
  if (redactionPolicy !== undefined) body.redaction_policy = redactionPolicy;
  const client = new SyncClient({
    server_url: 'https://api.test', api_key: 'k', org_id: ORG, environment: ENV, max_retries: 0, timeout: 5,
    logger: silent,
    fetchImpl: async () => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  });
  const cache = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: silent });
  const engine = new SyncEngine({
    sync_config: { server_url: 'https://api.test' }, sync_cache: cache,
    audit_logger: { getUnsynced: () => [], markSynced: () => 0 }, api_key: 'k', org_id: ORG, environment: ENV,
    logger: silent, sync_client: client,
  });
  return { cache, sync: () => (engine as unknown as { _syncPolicies: () => Promise<boolean> })._syncPolicies() };
}

describe('row 163(a): the pull and the union', () => {
  it('test_the_pull_caches_the_orgs_declaration', async () => {
    const { cache, sync } = engineWith({ manual_redact_fields: ['target.email', 'parameters.iban'] });
    expect(cache.getRedactionFields()).toEqual([]);
    expect(await sync()).toBe(true);
    expect(cache.getRedactionFields()).toEqual(['target.email', 'parameters.iban']);
    const restarted = new SyncCache({ cache_dir: path.join(dir, 'cache'), org_id: ORG, environment: ENV, logger: silent });
    await restarted.loadFromDisk();
    expect(restarted.getRedactionFields()).toEqual(['target.email', 'parameters.iban']);
  });

  for (const [label, redactionPolicy] of [
    ['absent', undefined],
    ['the member missing', {}],
    ['not a list', { manual_redact_fields: 'target.email' }],
    ['not a declared field', { manual_redact_fields: ['org_id'] }],
  ] as const) {
    it(`test_a_pull_without_the_declaration_is_refused (${label})`, async () => {
      const { cache, sync } = engineWith(redactionPolicy);
      await cache.updatePolicies(
        { policies: [{ name: 'seed' }], version: 'v1', redaction_policy: { manual_redact_fields: ['target.email'] } },
        'e1'
      );
      const err = await sync().catch((e) => e);
      expect(err).toMatchObject({ name: 'SyncError', channel: 'policy' });
      expect(String(err.message)).toContain('redaction_policy');
      expect([cache.getPoliciesEtag(), cache.getRedactionFields()]).toEqual(['e1', ['target.email']]);
    });
  }

  it('test_the_store_applies_the_union_at_each_write', () => {
    const org: string[] = [];
    const logger = new AuditLogger(path.join(dir, 'audit.db'), Redaction.declared(['parameters.account_number']), () => org);
    logger.write(envelope(0), DECISION);
    org.push('target.email', 'parameters.account_number');
    logger.write(envelope(1), DECISION);
    const [before, after] = stored(logger).map((r) => r.envelope);
    expect([before.parameters.account_number, before.target.email]).toEqual([MARKER, TARGET.email]);
    expect(after.parameters).toEqual({ account_number: MARKER, amount: 1250 });
    expect(after.target).toEqual({ email: MARKER, vendor_id: 'vnd_42' });
    logger.close();
  });

  it('test_a_hybrid_client_writes_the_orgs_declaration_locally', async () => {
    vi.spyOn(SyncEngine.prototype, 'initialSync').mockResolvedValue(true);
    vi.spyOn(SyncEngine.prototype, 'start').mockImplementation(() => {});
    const h = new HIITL({
      api_key: 'sk_test_1234567890abcdef', org_id: ORG, environment: ENV, mode: 'OBSERVE_ALL',
      cache_dir: path.join(dir, 'cache'), audit_db_path: path.join(dir, 'audit.db'),
      redact_fields: ['parameters.account_number'],
    });
    const inside = h as unknown as { _initialSyncPromise: Promise<boolean>; syncCache: SyncCache; auditLogger: AuditLogger };
    await inside._initialSyncPromise;
    // What the pull lands in the client's cache
    await inside.syncCache.updatePolicies(
      { policies: [], version: 'v2', redaction_policy: { manual_redact_fields: ['target.email'] } }, 'e2'
    );
    await h.evaluate({ action: 'pay', parameters: PARAMETERS, target: TARGET });
    const [row] = stored(inside.auditLogger).map((r) => r.envelope);
    expect(row.parameters).toEqual({ account_number: MARKER, amount: 1250 });
    expect(row.target).toEqual({ email: MARKER, vendor_id: 'vnd_42' });
    h.close();
  });
});

const GATEWAY = Redaction.declared([], { pay: [] });

/**
 * The store a release before HTL-29's condition 3 left when it was given `name`, a symbolic link to `db`: a record
 * hashed under the key it made beside the name it was given, and no key beside the file. Returns that key.
 */
function earlierRelease(db: string, name: string): Buffer {
  mkdirSync(path.dirname(name), { recursive: true });
  symlinkSync(db, name);
  const logger = new AuditLogger(db, GATEWAY);
  logger.write(envelope(0), DECISION);
  logger.close();
  renameSync(keyPath(db), `${name}${SUFFIX}`);
  return readFileSync(`${name}${SUFFIX}`);
}

/** The filesystem's reading of a name, `..` after a link to a directory included. */
const real = realpathSync.native;

/**
 * A store and the names into it an operator makes: a link beside it, relative, and one absolute; a link in the
 * directory below, written up through `..`; and a link to that directory beside the store's own. Returns the store.
 */
function tree(root: string): string {
  mkdirSync(path.join(root, 'real', 'sub'), { recursive: true });
  symlinkSync('audit.db', path.join(root, 'real', 'middle.db'));
  symlinkSync(path.join(root, 'real', 'audit.db'), path.join(root, 'real', 'abs.db'));
  symlinkSync(path.join('..', 'middle.db'), path.join(root, 'real', 'sub', 'outer.db'));
  symlinkSync(path.join('real', 'sub'), path.join(root, 'alias'));
  return path.join(root, 'real', 'audit.db');
}

/**
 * [a name for the store, a link on its way], each relative to `root`. The names are spelled from the tree's own
 * directory names and `..`, joined as text and never normalised, up to the tree's depth and one more, through every
 * directory of the tree they reach; the links are each one the filesystem passes from that name to the store, named in
 * the directory the filesystem finds it in. Mirrors the Python `_alias_cases`.
 */
function aliasCases(root: string): Array<[string, string]> {
  const store = tree(root);
  writeFileSync(store, '');
  const names = new Set<string>(['..']);
  let deepest = 0;
  const walk = (at: string, depth: number) => {
    deepest = Math.max(deepest, depth);
    for (const e of readdirSync(at, { withFileTypes: true })) {
      if (e.isDirectory() || (e.isSymbolicLink() && statSync(path.join(at, e.name)).isDirectory())) names.add(e.name);
      if (e.isDirectory()) walk(path.join(at, e.name), depth + 1);
    }
  };
  walk(root, 0);
  const home = real(root);
  const cases: Array<[string, string]> = [];
  let spellings: string[][] = [[]];
  for (let n = 1; n <= deepest + 1; n++) {
    spellings = spellings.flatMap((s) => [...names].sort().map((name) => [...s, name]));
    for (const parts of spellings) {
      const spelled = parts.join('/');
      if (parts[0] === '..' || !existsSync(`${root}/${spelled}`) || !statSync(`${root}/${spelled}`).isDirectory()) continue;
      const here = real(`${root}/${spelled}`);
      if (path.relative(home, here).startsWith('..')) continue;
      for (const entry of readdirSync(here).sort()) {
        let hop = `${here}/${entry}`;
        if (!lstatSync(hop).isSymbolicLink() || real(hop) !== real(store)) continue;
        while (lstatSync(hop).isSymbolicLink()) {
          cases.push([`${spelled}/${entry}`, path.relative(home, hop)]);
          const target = readlinkSync(hop);
          const beyond = path.isAbsolute(target) ? target : `${path.dirname(hop)}/${target}`;
          hop = `${real(path.dirname(beyond))}/${path.basename(beyond)}`;
        }
      }
    }
  }
  return cases;
}

/**
 * The tree a release before this one left when it was given a name whose way passes `hop`: a record hashed under the
 * key it made beside that link, and no key beside the file. Returns the store, that key's file and the key.
 */
function upgrade(root: string, hop: string): { db: string; left: string; old: Buffer } {
  const db = tree(root);
  const logger = new AuditLogger(db, GATEWAY);
  logger.write(envelope(0), DECISION);
  logger.close();
  const left = `${real(root)}/${hop}${SUFFIX}`;
  renameSync(keyPath(db), left);
  return { db, left, old: readFileSync(left) };
}

describe("row 163(c): the store's value-hash key", () => {
  it('test_the_key_is_made_beside_the_store_once', () => {
    const db = path.join(dir, 'gateway', 'audit.db');
    const first = new AuditLogger(db, GATEWAY);
    const file = keyPath(db);
    expect(path.dirname(file)).toBe(realpathSync(path.dirname(db)));   // beside the file the name resolves to
    expect(statSync(file).mode & 0o777).toBe(0o600);
    const key = readFileSync(file);
    expect(key.length).toBe(KEY_BYTES);
    first.write(envelope(0), DECISION);
    first.close();

    const second = new AuditLogger(db, GATEWAY);
    second.write(envelope(1), DECISION);
    const [a, b] = stored(second).map((r) => r.envelope.parameters);
    const expected = Object.fromEntries(Object.entries(PARAMETERS).map(([k, v]) => [k, valueHash(v, key)]));
    expect([a, b]).toEqual([expected, expected]);
    expect(JSON.stringify(stored(second))).not.toContain(key.toString('hex'));
    expect(readFileSync(db).includes(key)).toBe(false);
    second.close();
  });

  it('test_a_name_through_a_link_reads_the_one_key_beside_the_file', () => {
    // The key is beside the file the store's name resolves to, where SQLite keeps its journal, so a name through a
    // symbolic link reads the key the file's own path made and makes none beside the link (HTL-29 review, condition 3)
    const db = path.join(dir, 'audit.db');
    const first = new AuditLogger(db, GATEWAY);
    first.write(envelope(0), DECISION);
    first.close();
    mkdirSync(path.join(dir, 'links'));
    const link = path.join(dir, 'links', 'audit.db');
    symlinkSync(db, link);

    const second = new AuditLogger(link, GATEWAY);
    second.write(envelope(1), DECISION);
    const [a, b] = stored(second).map((r) => r.envelope.parameters);
    expect(b).toEqual(a);
    expect(readdirSync(path.join(dir, 'links'))).toEqual(['audit.db']);
    second.close();
  });

  it('test_a_first_start_through_a_link_makes_the_key_beside_the_file', () => {
    // The key is read once the store has opened, so a first start through a link to a file not yet made makes the key
    // beside the file SQLite made, never beside the link (HTL-29 review, condition 3)
    mkdirSync(path.join(dir, 'links'));
    const link = path.join(dir, 'links', 'audit.db');
    symlinkSync(path.join(dir, 'audit.db'), link);
    new AuditLogger(link, GATEWAY).close();
    expect(readdirSync(path.join(dir, 'links'))).toEqual(['audit.db']);
    expect(existsSync(keyPath(path.join(dir, 'audit.db')))).toBe(true);
  });

  it('test_a_key_an_earlier_release_left_beside_the_link_is_the_stores_key', () => {
    // A release before this one made the key beside the name it was given, a link to the file. The next start through
    // that name reads that key and writes it beside the file, leaving it where it was, so a value hashes the same
    // across the upgrade; the file's own name then reads it, and the two equal keys on the way are one (HTL-29 second
    // review, condition 3; event_format.md "a value hashes the same across restarts and two records of one store
    // compare")
    const db = path.join(dir, 'audit.db');
    const link = path.join(dir, 'links', 'audit.db');
    const old = earlierRelease(db, link);
    for (const [i, name] of [link, db, link].entries()) {
      const logger = new AuditLogger(name, GATEWAY);
      logger.write(envelope(i + 1), DECISION);
      logger.close();
      expect(existsSync(keyPath(db))).toBe(true);           // the key is written beside the file
      expect(readFileSync(keyPath(db))).toEqual(old);
    }
    const reader = new AuditLogger(db, GATEWAY);
    const hashed = Object.fromEntries(Object.entries(PARAMETERS).map(([k, v]) => [k, valueHash(v, old)]));
    expect(stored(reader).map((r) => r.envelope.parameters)).toEqual([hashed, hashed, hashed, hashed]);
    reader.close();
    expect(statSync(keyPath(db)).mode & 0o777).toBe(0o600);
    expect(existsSync(`${link}${SUFFIX}`)).toBe(true);     // and never removed from where it was
    expect(readFileSync(`${link}${SUFFIX}`)).toEqual(old);
  });

  it('test_a_key_beside_a_link_the_name_passes_through_is_the_stores_key', () => {
    // A name can reach the file through more than one link, each written relative to its own directory; a key beside
    // any of them is one a release before this one made for the name it was given, and is the store's key
    const db = path.join(dir, 'audit.db');
    const first = path.join(dir, 'links', 'first.db');
    const old = earlierRelease(db, first);
    const second = path.join(dir, 'more', 'second.db');
    mkdirSync(path.dirname(second));
    symlinkSync(path.join('..', 'links', 'first.db'), second);
    const logger = new AuditLogger(second, GATEWAY);
    logger.write(envelope(1), DECISION);
    const hashed = Object.fromEntries(Object.entries(PARAMETERS).map(([k, v]) => [k, valueHash(v, old)]));
    expect(stored(logger).map((r) => r.envelope.parameters)).toEqual([hashed, hashed]);
    logger.close();
    expect(readFileSync(keyPath(db))).toEqual(old);
    expect(existsSync(`${second}${SUFFIX}`)).toBe(false);  // no key is made beside the name written
  });

  it('test_keys_on_the_way_that_differ_fail_the_start_naming_each', () => {
    // The store was given two names under a release before this one, each of which made its own key. Its records were
    // hashed under one or both, and nothing on disk says which: the start fails naming each file, and none is chosen,
    // written or removed
    const db = path.join(dir, 'audit.db');
    const link = path.join(dir, 'links', 'audit.db');
    const old = earlierRelease(db, link);
    new AuditLogger(db, GATEWAY).close();                 // the file's own name, which passes through no link
    const made = readFileSync(keyPath(db));
    expect(made).not.toEqual(old);
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(AuditLogError);
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(keyPath(db));
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(`${link}${SUFFIX}`);
    expect(readFileSync(keyPath(db))).toEqual(made);
    expect(readFileSync(`${link}${SUFFIX}`)).toEqual(old);
  });

  it('test_a_key_another_start_wrote_beside_the_file_meanwhile_that_differs_fails_the_start', () => {
    // Two starts of one store upgrade together: one through the file's own name, which reaches no link and makes a new
    // key, and one through the link, which writes the earlier release's key beside the file. The first lands; the
    // second reads a key beside the file that is not the one on its way, and fails naming each, as two keys found
    // together do
    const db = path.join(dir, 'audit.db');
    const link = path.join(dir, 'links', 'audit.db');
    const old = earlierRelease(db, link);
    const other = randomBytes(KEY_BYTES);
    const linkFile = fs.linkSync;
    vi.spyOn(fs, 'linkSync').mockImplementation((src, dst) => {
      writeFileSync(dst, other);                            // the other start's key lands beside the file first
      linkFile(src, dst);
    });
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(AuditLogError);
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(keyPath(db));
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(`${link}${SUFFIX}`);
    expect(readFileSync(keyPath(db))).toEqual(other);
    expect(readFileSync(`${link}${SUFFIX}`)).toEqual(old);
  });

  it('test_every_name_through_a_link_to_a_directory_reads_the_key_on_its_way', () => {
    // Every name for the store the tree's names spell, `..` after a link to a directory included, passes the links the
    // filesystem passes, so a key a release before this one left beside any of them is the store's key: written beside
    // the file, left where it was, and every record hashes under it (HTL-29 third review, condition 3; event_format.md
    // "Every name, the one given and each on the way, is read as the filesystem reads it")
    const cases = aliasCases(path.join(dir, 'tree'));
    expect(cases.map(([name]) => name)).toEqual(expect.arrayContaining(['alias/../middle.db', 'alias/outer.db']));
    const missed: unknown[] = [];
    cases.forEach(([name, hop], i) => {
      const root = path.join(dir, String(i));
      const { db, left, old } = upgrade(root, hop);
      const hashed = Object.fromEntries(Object.entries(PARAMETERS).map(([k, v]) => [k, valueHash(v, old)]));
      let held: unknown;
      try {
        const logger = new AuditLogger(`${root}/${name}`, GATEWAY);
        logger.write(envelope(1), DECISION);
        held = isDeepStrictEqual(stored(logger).map((r) => r.envelope.parameters), [hashed, hashed]) &&
          readFileSync(keyPath(db)).equals(old) && readFileSync(left).equals(old);
        logger.close();
      } catch (e) {
        held = String(e);   // a start that fails is a name read otherwise than the filesystem reads it
      }
      if (held !== true) missed.push([name, hop, held]);
    });
    expect(missed).toEqual([]);
  });

  it('test_every_name_through_a_link_to_a_directory_refuses_a_key_on_its_way_that_differs', () => {
    // The same names, with another key beside the file: the start fails naming each, and none is chosen, written or
    // removed (HTL-29 third review, condition 3)
    const missed: unknown[] = [];
    aliasCases(path.join(dir, 'tree')).forEach(([name, hop], i) => {
      const root = path.join(dir, String(i));
      const { db, left, old } = upgrade(root, hop);
      const other = randomBytes(KEY_BYTES);
      writeFileSync(keyPath(db), other);
      let held: unknown = 'started';
      try {
        new AuditLogger(`${root}/${name}`, GATEWAY).close();
      } catch (e) {
        const said = String(e);
        held = (e instanceof AuditLogError && said.includes(`audit.db${SUFFIX}`) &&
          said.includes(`${path.basename(hop)}${SUFFIX}`) && readFileSync(keyPath(db)).equals(other) &&
          readFileSync(left).equals(old)) || said;
      }
      if (held !== true) missed.push([name, hop, held]);
    });
    expect(missed).toEqual([]);
  });

  it('test_a_key_on_the_way_of_another_length_fails_the_start', () => {
    const db = path.join(dir, 'audit.db');
    const link = path.join(dir, 'links', 'audit.db');
    earlierRelease(db, link);
    writeFileSync(`${link}${SUFFIX}`, Buffer.alloc(KEY_BYTES / 2));
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(AuditLogError);
    expect(() => new AuditLogger(link, GATEWAY)).toThrow(`${link}${SUFFIX}`);
    expect(existsSync(keyPath(db))).toBe(false);           // nothing is written beside the file
  });

  it('test_a_key_file_of_another_length_fails_the_start', () => {
    const db = path.join(dir, 'audit.db');
    writeFileSync(keyPath(db), Buffer.alloc(KEY_BYTES / 2));
    expect(() => new AuditLogger(db, GATEWAY)).toThrow(AuditLogError);
    expect(() => new AuditLogger(db, GATEWAY)).toThrow(keyPath(db));
  });

  it('test_an_in_memory_store_keeps_its_key_in_memory', () => {
    const logger = new AuditLogger(':memory:', GATEWAY);
    logger.write(envelope(0), DECISION);
    const [row] = stored(logger).map((r) => r.envelope.parameters);
    expect(Object.values(row).every((v) => String(v).startsWith(HASH_PREFIX))).toBe(true);
    expect(existsSync(keyPath(':memory:'))).toBe(false);
    logger.close();
  });

  it('test_a_store_that_hashes_nothing_makes_no_key', () => {
    for (const [i, redaction] of [Redaction.declared(), Redaction.declared(['parameters.account_number'])].entries()) {
      const db = path.join(dir, `${i}.db`);
      const logger = new AuditLogger(db, redaction);
      logger.write(envelope(i), DECISION);
      logger.close();
      expect(existsSync(keyPath(db))).toBe(false);
    }
  });
});

describe('row 163(e): a declared path the call does not carry', () => {
  // HTL-23 row 191 behavior 6: the record's `redaction` names it, in the declaration's order (the store's own, then
  // the org's), and the record's hash covers it; a record whose every declared path is present carries no `redaction`
  it('test_a_declared_path_the_call_does_not_carry_is_named', () => {
    const db = path.join(dir, 'audit.db');
    const all = path.join(dir, 'all.db');
    const logger = new AuditLogger(db, Redaction.declared(['parameters.ssn', 'target.email']), () => [
      'target.phone', 'parameters.ssn',
    ]);
    logger.write(envelope(0), DECISION);
    const whole = new AuditLogger(all, Redaction.declared(['target.email']));
    whole.write(envelope(1), DECISION);

    const [absent] = logger.getUnsynced() as Array<Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
    const [present] = whole.getUnsynced() as Array<Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(absent.redaction).toEqual({ absent: ['parameters.ssn', 'target.phone'] });
    expect(logger.verifyIntegrity(absent.event_id)).toBe(true);
    expect(auditContentHash(absent.event_id, absent.envelope, absent.decision, { redaction: absent.redaction }))
      .toBe(absent.content_hash);
    expect('redaction' in present).toBe(false);
    expect(auditContentHash(present.event_id, present.envelope, present.decision)).toBe(present.content_hash);
    logger.close();
    whole.close();
  });
});
