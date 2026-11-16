/**
 * One canonical serialisation for the content hashes (docs/specs/sync_engine.md §2.1 and §2.2; Trevor, 2026-10-10):
 * the JSON Canonicalization Scheme, RFC 8785 — the same bytes as the Python `hiitl.core.canonical`, proved by the
 * conformance cases `tests/conformance/audit_hash/` and `tests/conformance/policy_hash/`.
 *
 *     audit record:             content_hash = SHA-256( "{event_id}:{C(envelope)}:{C(decision)}" )   UTF-8, lowercase hex
 *     policy set, route config: content_hash = SHA-256( C(content) )                                 UTF-8, lowercase hex
 *     envelope:                 signature     = HMAC-SHA256( secret, S(envelope) )                    UTF-8, lowercase hex
 *                               envelope_hash = SHA-256( S(envelope) )
 *
 * S is the envelope's signed form (the security architecture §1.3; row 127, Trevor 2026-11-04: "one canonical form
 * everywhere"), proved by `tests/conformance/envelope_signature/`.
 */
import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

/** RFC 8785: keys sorted by UTF-16 code units, no whitespace, minimal string escapes, ECMAScript numbers. */
export function canonicalJson(value: unknown): string {
  return _canonicalJson(value);
}

/** Unchanged C algorithm; supplied-input admission is a separate call. */
export function _canonicalJson(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`${value} has no JSON form`);
    return Object.is(value, -0) ? '0' : String(value);
  }
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map((v) => _canonicalJson(v)).join(',') + ']';
  if (typeof value === 'object') {
    const o = value as Record<string, unknown>;
    const keys = Object.keys(o).filter((k) => o[k] !== undefined).sort();
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + _canonicalJson(o[k])).join(',') + '}';
  }
  throw new Error(`${typeof value} is not a JSON value`);
}

/** A policy set's or route config's content hash: SHA-256 over its canonical form. */
export function canonicalHash(value: unknown): string {
  return createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');
}

/**
 * The members an audit record carries beyond its envelope and decision, each a further term of its content hash, in
 * the hash's order (event_format.md `content_hash`; row 191, ruled 2026-11-06). The one copy: the SDK's store reads it
 * here. Mirrors canonical.py `AUDIT_FURTHER`.
 */
export const AUDIT_FURTHER = ['execution_result', 'redaction', 'review'] as const;

/**
 * The audit record's content hash over its JSON values exactly as uploaded.
 *
 * Each member of `AUDIT_FURTHER` the record carries joins as a further term, in that order, `further` keyed by the
 * record's own member names. A member is a term because the record carries it (any value but `undefined`, which JSON
 * does not hold); a record carrying none hashes over the first three. A name `AUDIT_FURTHER` does not hold is
 * refused: it would hash without its term, unseen.
 */
export function auditContentHash(
  eventId: string,
  envelope: unknown,
  decision: unknown,
  further: Partial<Record<(typeof AUDIT_FURTHER)[number], unknown>> = {},
): string {
  return _auditContentHash(eventId, envelope, decision, further);
}

/** Historical C computation; not exported from the package entry point. */
export function _auditContentHash(
  eventId: string, envelope: unknown, decision: unknown,
  further: Partial<Record<(typeof AUDIT_FURTHER)[number], unknown>> = {},
): string {
  const unnamed = Object.keys(further).filter((k) => !(AUDIT_FURTHER as readonly string[]).includes(k)).sort();
  if (unnamed.length > 0) {
    throw new TypeError(
      `auditContentHash takes no term ${unnamed.join(', ')}; a record's further terms are ${AUDIT_FURTHER.join(', ')}`,
    );
  }
  const terms = [eventId, _canonicalJson(envelope), _canonicalJson(decision)];
  for (const member of AUDIT_FURTHER) {
    if (further[member] !== undefined) terms.push(_canonicalJson(further[member]));
  }
  return createHash('sha256').update(terms.join(':'), 'utf8').digest('hex');
}

/**
 * The envelope's signed form: the canonical JSON of the envelope without its `signature`, and without a principal the
 * hosted service verified — the service's addition after the caller signed, marked by its own `verified_by`. The
 * signature and `envelope_hash` are both over it, so the record alone re-derives each.
 */
export function auditHashMatches(
  expected: string, eventId: string, envelope: unknown, decision: unknown,
  further: Partial<Record<(typeof AUDIT_FURTHER)[number], unknown>> = {},
): boolean {
  return expected === _auditContentHash(eventId, envelope, decision, further);
}

export function envelopeSignedForm(envelope: Record<string, unknown>): string {
  const principal = envelope.principal as { verified_by?: unknown } | null | undefined;
  const added = typeof principal === 'object' && principal !== null && principal.verified_by === 'hosted';
  const signed = Object.fromEntries(
    Object.entries(envelope).filter(([k]) => k !== 'signature' && !(added && k === 'principal'))
  );
  return canonicalJson(signed);
}

/** HMAC-SHA256 over the signed form, under the key's signing secret. */
export function envelopeSignature(secret: string, envelope: Record<string, unknown>): string {
  return createHmac('sha256', secret).update(envelopeSignedForm(envelope), 'utf8').digest('hex');
}

/** Whether the envelope's `signature` is the signature of its signed form (a constant-time compare). */
export function envelopeVerifies(secret: string, envelope: Record<string, unknown>): boolean {
  const expected = Buffer.from(envelopeSignature(secret, envelope), 'utf8');
  const given = Buffer.from(String(envelope.signature ?? ''), 'utf8');
  return expected.length === given.length && timingSafeEqual(expected, given);
}

/** The decision's envelope_hash (Tier 1): SHA-256 over the signed form; the caller recomputes it from what it sent. */
export function envelopeHash(envelope: Record<string, unknown>): string {
  return createHash('sha256').update(envelopeSignedForm(envelope), 'utf8').digest('hex');
}
