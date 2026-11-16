/**
 * What a store writes: the record with each declared field's value replaced (HTL-20 row 139, 2026-11-04), the same
 * rule as the Python `hiitl.core.redaction`. The contract is docs/specs/event_format.md §Redaction.
 *
 * A store calls `record` on the envelope and decision it is about to write. It does so after the envelope's signature
 * and `envelope_hash` are computed over the envelope as sent, and before the record's `content_hash`, which is over
 * the record as stored. A field is redacted because it is declared; nothing here reads a field's name or content to
 * decide ("No content detection").
 *
 * The gateway's hash of an argument it records by name is HMAC-SHA256 under a key the gateway's store makes at its first
 * start and keeps beside itself, never synced and never in a record (HTL-22 row 163(c)). The SDK store unions the org's
 * declaration, which the hybrid policy pull carries, with its own (row 163(a)).
 */
import { createHash, createHmac } from 'node:crypto';
import { canonicalJson } from './canonical.js';

export const MARKER = '[REDACTED]';
export const HASH_PREFIX = 'hmac-sha256:';

/** The value hash's key length: the hash's own output length, the least RFC 2104 §3 allows without "strongly discouraged". */
export const KEY_BYTES = createHash('sha256').digest().length;

/** The member of the org's declaration that names its fields (PUT /v1/redaction-policy; the hybrid policy pull). */
export const ORG_FIELDS = 'manual_redact_fields';

/**
 * decision_response.md's remediation details that state the call's value at an envelope field, by remediation type:
 * the member that holds the field's path, and the member that holds the value found there.
 */
export const VALUE_AT_FIELD: Readonly<Record<string, readonly [string, string]>> = {
  threshold: ['field', 'current_value'],
  field_restriction: ['field_ref', 'blocked_fields'],
};

const SPEC = 'event_format.md §Redaction';

type Json = any; // a JSON value as the store serialises it

const own = (o: object, key: string): boolean => Object.prototype.hasOwnProperty.call(o, key);

/**
 * How the gateway records an argument it was not told to record: HMAC-SHA256 under the store's key, over the value's
 * canonical form.
 */
export function valueHash(value: unknown, key: Uint8Array): string {
  return HASH_PREFIX + createHmac('sha256', key).update(canonicalJson(value), 'utf8').digest('hex');
}

function toPath(entry: unknown, source: string): string[] {
  const segments = typeof entry === 'string' ? entry.split('.') : [];
  if (segments.length < 2 || segments.some((s) => s === '')) {
    throw new Error(
      `${source} entry ${JSON.stringify(entry)} is not a declared field. A declared field is a member of one of the ` +
        "envelope's objects, written as a dotted path such as 'parameters.account_number' or 'target.email'; a " +
        `top-level field is how the record is found, and is never redacted (${SPEC}).`
    );
  }
  return segments;
}

function replaceAt(node: Json, segments: string[], treat: (v: Json) => Json): void {
  if (Array.isArray(node)) {
    for (const item of node) replaceAt(item, segments, treat);
    return;
  }
  if (node === null || typeof node !== 'object' || !own(node, segments[0])) return;
  if (segments.length === 1) node[segments[0]] = treat(node[segments[0]]);
  else replaceAt(node[segments[0]], segments.slice(1), treat);
}

/**
 * Whether the envelope holds a value at `segments` under `node`, walked as `replaceAt` walks it: through objects, and
 * through every item of an array met (any item holding one holds it).
 */
function holds(node: Json, segments: string[]): boolean {
  if (Array.isArray(node)) return node.some((item) => holds(item, segments));
  if (node === null || typeof node !== 'object' || !own(node, segments[0])) return false;
  return segments.length === 1 || holds(node[segments[0]], segments.slice(1));
}

/** Every remediation the decision carries, wherever a `remediation` member sits. */
function* remediations(node: Json): Generator<Record<string, Json>> {
  if (Array.isArray(node)) {
    for (const item of node) yield* remediations(item);
  } else if (node !== null && typeof node === 'object') {
    for (const [key, value] of Object.entries(node)) {
      if (key === 'remediation' && value !== null && typeof value === 'object' && !Array.isArray(value)) {
        yield value as Record<string, Json>;
      }
      yield* remediations(value);
    }
  }
}

const redacted = (): string => MARKER;

/**
 * A store's declaration: the fields it redacts, and, at the gateway, the parameters it records as given.
 * `recordedParameters` is undefined when parameters are recorded as given (the SDK's default). When it is set
 * (`{action: [parameter names]}`), every other member of `parameters` is recorded as `valueHash(value, key)`, under the
 * store's key (`keyed`).
 */
export class Redaction {
  private constructor(
    readonly fields: readonly string[][],
    readonly recordedParameters?: Readonly<Record<string, readonly string[]>>,
    private readonly key?: Uint8Array
  ) {}

  /** Validate a declaration. Throws, naming the entry, for a path that is not a declared field. */
  static declared(
    fields?: readonly string[],
    recordedParameters?: Record<string, readonly string[]>,
    source = 'redact_fields'
  ): Redaction {
    if (typeof fields === 'string') {
      throw new Error(`${source} is a list of field paths, got the string ${JSON.stringify(fields)} (${SPEC}).`);
    }
    const paths = (fields ?? []).map((entry) => toPath(entry, source));
    let recorded: Record<string, readonly string[]> | undefined;
    if (recordedParameters !== undefined && recordedParameters !== null) {
      if (typeof recordedParameters !== 'object' || Array.isArray(recordedParameters)) {
        throw new Error(`recorded_parameters maps an action to the parameter names recorded as given (${SPEC}).`);
      }
      recorded = {};
      for (const [action, names] of Object.entries(recordedParameters)) {
        if (!Array.isArray(names) || !names.every((n) => typeof n === 'string' && n !== '')) {
          throw new Error(
            `recorded_parameters[${JSON.stringify(action)}] is a list of parameter names, got ` +
              `${JSON.stringify(names)} (${SPEC}).`
          );
        }
        Object.defineProperty(recorded,action,{value:[...names],enumerable:true,writable:true,configurable:true});
      }
    }
    return new Redaction(paths, recorded);
  }

  /** This declaration under the store's value-hash key. */
  keyed(key: Uint8Array): Redaction {
    if (!(key instanceof Uint8Array) || key.length < KEY_BYTES) {
      throw new Error(`The value hash's key is ${KEY_BYTES} bytes or more (RFC 2104 §3; ${SPEC}).`);
    }
    return new Redaction(this.fields, this.recordedParameters, key);
  }

  /** This declaration with `fields` added: the store redacts each path either declares (row 163(a)). */
  joined(fields: readonly string[], source: string): Redaction {
    if (typeof fields === 'string') {
      throw new Error(`${source} is a list of field paths, got the string ${JSON.stringify(fields)} (${SPEC}).`);
    }
    const have = new Set(this.fields.map((f) => f.join('.')));
    const added: string[][] = [];
    for (const entry of fields) {
      const path = toPath(entry, source);
      if (!have.has(path.join('.'))) {
        have.add(path.join('.'));
        added.push(path);
      }
    }
    return added.length ? new Redaction([...this.fields, ...added], this.recordedParameters, this.key) : this;
  }

  get active(): boolean {
    return this.fields.length > 0 || this.recordedParameters !== undefined;
  }

  private readonly hash = (value: Json): string => valueHash(value, this.key!);

  private recordedFor(action: string | undefined): readonly string[] {
    const recorded = this.recordedParameters ?? {};
    return action !== undefined && own(recorded, action) ? recorded[action] : [];
  }

  /**
   * How a value found at `path` is recorded: a declared field's (the path is one, lies under one, or holds one), a
   * hashed parameter's, or as given (undefined).
   */
  private treatment(path: string, action: string | undefined): ((v: Json) => Json) | undefined {
    const segments = path.split('.');
    for (const declared of this.fields) {
      const n = Math.min(declared.length, segments.length);
      if (declared.slice(0, n).every((s, i) => s === segments[i])) return redacted;
    }
    if (
      this.recordedParameters !== undefined &&
      segments[0] === 'parameters' &&
      (segments.length === 1 || !this.recordedFor(action).includes(segments[1]))
    ) {
      return this.hash;
    }
    return undefined;
  }

  /**
   * The declared fields at which `envelope` holds no value, in the declaration's order (the store's own, then the
   * org's as joined): what the record's `redaction` member names, `{"absent": [...]}` (row 163 (e): "named in the
   * record, never skipped silently").
   */
  absent(envelope: unknown): string[] {
    return this.fields.filter((path) => !holds(envelope, path)).map((path) => path.join('.'));
  }

  /** The envelope and decision as stored. The inputs are never changed. */
  record<E, D>(envelope: E, decision: D): [E, D] {
    if (!this.active) return [envelope, decision];
    if (this.recordedParameters !== undefined && this.key === undefined) {
      throw new Error(
        "recorded_parameters hashes each other parameter under the store's key, and this declaration has none: key " +
          `it with the store's (Redaction.keyed; ${SPEC}).`
      );
    }
    const env: Json = structuredClone(envelope);
    const dec: Json = structuredClone(decision);
    for (const declared of this.fields) replaceAt(env, declared, redacted);
    const action: string | undefined = env.action;
    const params = env.parameters;
    if (this.recordedParameters !== undefined && params !== null && typeof params === 'object' && !Array.isArray(params)) {
      const recorded = this.recordedFor(action);
      env.parameters = Object.fromEntries(
        Object.entries(params).map(([name, value]) => [
          name,
          recorded.includes(name) || value === MARKER ? value : this.hash(value),
        ])
      );
    }
    for (const remediation of remediations(dec)) {
      const members = own(VALUE_AT_FIELD, remediation.type) ? VALUE_AT_FIELD[remediation.type] : undefined;
      const details = remediation.details;
      if (!members || details === null || typeof details !== 'object' || typeof details[members[0]] !== 'string') {
        continue;
      }
      const treat = this.treatment(details[members[0]], action);
      if (treat !== undefined && own(details, members[1])) details[members[1]] = treat(details[members[1]]);
    }
    return [env as E, dec as D];
  }
}
