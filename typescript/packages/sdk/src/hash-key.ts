/**
 * The store's value-hash key (event_format.md §Redaction; HTL-22 row 163(c)), the same rule as the Python
 * `hiitl.sdk.hash_key`.
 *
 * Ruled by Trevor on HTL-20: "(c) the gateway's hash is keyed (HMAC)". The key is a file next to the audit database,
 * made once with mode 0600 and read at every later start. It is never in a record, an upload or a log. A key a release
 * before this one made beside a name on the way to the file is the store's key, written beside the file and left where
 * it was; keys that differ fail the start (HTL-29 second review, condition 3). An in-memory store keeps an in-memory
 * key.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { KEY_BYTES } from '@hiitl/core';

export const SUFFIX = '.value_hash.key';

/**
 * Where the key of the store at `dbPath` lives: beside the file its name resolves to, which SQLite opens "by its
 * canonical name" and keeps its journal beside, so every name through a symbolic link reads one key (HTL-29 review,
 * condition 3). The name is resolved as the filesystem resolves it, by realpath(3): `..` after a link to a directory
 * is the parent of the directory the link reaches, where JavaScript's `realpathSync` resolves `..` from the name's
 * text first (HTL-29 third review, condition 3). A name that reaches no file yet is read as written. Mirrors the
 * Python `key_path`.
 */
export function keyPath(dbPath: string): string {
  return `${fs.existsSync(dbPath) ? fs.realpathSync.native(dbPath) : dbPath}${SUFFIX}`;
}

/**
 * The names on the way from `dbPath` as written to its file: the name written and each symbolic link it passes through,
 * a link's target read against the link's own directory. A name is joined as text and never normalised, so the
 * filesystem reads each `..` in it after the links before it (HTL-29 third review, condition 3). A link met twice ends
 * the way. Mirrors the Python `_names`.
 */
function namesOnTheWay(dbPath: string): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  let name = dbPath;
  for (;;) {
    names.push(name);
    let st: fs.BigIntStats;
    try {
      st = fs.lstatSync(name, { bigint: true });
    } catch {
      return names;
    }
    const id = `${st.dev}:${st.ino}`;
    if (!st.isSymbolicLink() || seen.has(id)) return names;
    seen.add(id);
    const target = fs.readlinkSync(name);
    name = path.isAbsolute(target) ? target : `${path.dirname(name)}${path.sep}${target}`;
  }
}

function read(file: string): Buffer {
  const key = fs.readFileSync(file);
  if (key.length !== KEY_BYTES) {
    throw new Error(
      `The value-hash key ${file} holds ${key.length} bytes, and a store's key is ${KEY_BYTES}. It is the key the ` +
        "store's records were hashed under: restore it, or move the store and its key aside to start a new one."
    );
  }
  return key;
}

/**
 * Each key beside the file, or beside a name on the way, where a release before this one made it beside the name it
 * was given: one per file, by the name it was found at (HTL-29 second review, condition 3).
 */
function found(dbPath: string): Map<string, Buffer> {
  const keys = new Map<string, Buffer>();
  const files = new Set<string>();
  for (const file of [keyPath(dbPath), ...namesOnTheWay(dbPath).map((name) => `${name}${SUFFIX}`)]) {
    if (!fs.existsSync(file) || files.has(fs.realpathSync.native(file))) continue;
    files.add(fs.realpathSync.native(file));
    keys.set(file, read(file));
  }
  return keys;
}

const differ = (files: string[]): string =>
  `The value-hash keys ${files.join(', ')} differ. A release before this one made a key beside each name the ` +
  'store was given, so its records were hashed under one or more of them and nothing on disk says which, and ' +
  'none is chosen: keep the key its records were hashed under and move the others aside.';

/** Writes `key` at `file`, mode 0600, unless a key lands there first. */
function place(file: string, key: Buffer): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
  const fd = fs.openSync(tmp, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o600);
  try {
    fs.fchmodSync(fd, 0o600);
    fs.writeSync(fd, key);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    fs.linkSync(tmp, file);
  } catch (e: any) {
    if (e?.code !== 'EEXIST') throw e;
  } finally {
    fs.unlinkSync(tmp);
  }
}

/**
 * The store's key: the one beside the store's file, or one a release before this one made beside a name on the way,
 * written beside the file and left where it was; made there at the store's first start (mode 0600) when there is none.
 * Two processes that start together keep the one that lands first. Throws, naming each file, for keys that differ and
 * for a key file of another length.
 */
export function storeKey(dbPath: string): Buffer {
  if (dbPath === ':memory:') return crypto.randomBytes(KEY_BYTES);
  const file = keyPath(dbPath);
  const keys = found(dbPath);
  const [known] = keys.values();
  if ([...keys.values()].some((k) => !k.equals(known))) throw new Error(differ([...keys.keys()]));
  if (!fs.existsSync(file)) place(file, known ?? crypto.randomBytes(KEY_BYTES));
  const key = read(file);
  // another start wrote another key beside the file meanwhile
  if (known !== undefined && !key.equals(known)) throw new Error(differ([file, ...keys.keys()]));
  return key;
}
