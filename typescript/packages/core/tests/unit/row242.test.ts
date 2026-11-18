/**
 * Row 242 (HTL-29 review, condition 5), in core: a date-time is read by RFC 3339's grammar, by one reader, in every
 * field the core's schemas type `date-time`.
 *
 * ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar": section 5.6's form and its note's lower case `t`
 * and `z`, sections 5.6 and 5.7's ranges, a refusal naming the element and its range, the instant held to the
 * millisecond. Design: the HTL-29 test design, row 137, behaviors 12-14. Mirrors python/hiitl/core/tests/test_row242.py:
 * both read the table in tests/conformance/date_time/.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { YEAR, dateTimeRefusal, readDateTime } from '../../src/date-time.js';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { ENVELOPE_SCHEMA_VERSION, EnvelopeSchema, PolicySetSchema, RateLimitSchema } from '../../src/types.js';
import type { Envelope, PolicySet } from '../../src/types.js';

const ROOT = join(__dirname, '../../../../..');
const TABLE = join(ROOT, 'tests/conformance/date_time/case_001_written_date_times.json');
const ROWS: Array<[unknown, string | null, string?]> = JSON.parse(readFileSync(TABLE, 'utf8')).date_times;
const ORG = 'org_test123456789012';
const NOW = Date.now();
const MINUTE = 60_000;

// The table holds microseconds; this core holds milliseconds, truncated
const ms = (held: string): string => `${held.slice(0, 23)}Z`;

describe('row 242: one reader reads each written value as the table does', () => {
  it.each(ROWS.map((row) => [JSON.stringify(row[0]).slice(0, 40), row] as const))('%s', (_, row) => {
    const [written, held, refusal] = row;
    if (held === null) {
      expect(dateTimeRefusal(written)).toBe(refusal);
      expect(() => readDateTime(written)).toThrow(refusal);
    } else {
      expect(dateTimeRefusal(written)).toBeNull();
      expect(new Date(readDateTime(written)).toISOString()).toBe(ms(held));
    }
  });
});

// Every field the core's schemas carry that the specs type `date-time`, read from the specs: the envelope's schema, the
// decision's JSON, and the rule table's `string (date-time)` rows
function* schemaFields(node: unknown, path: string[] = []): Generator<string> {
  if (Array.isArray(node)) {
    for (const value of node) yield* schemaFields(value, path);
  } else if (node !== null && typeof node === 'object') {
    if ((node as Record<string, unknown>).format === 'date-time') {
      yield path.filter((p) => p !== 'properties' && p !== 'items').join('.');
    }
    for (const [key, value] of Object.entries(node)) yield* schemaFields(value, [...path, key]);
  }
}

function* jsonBlocks(name: string): Generator<unknown> {
  const text = readFileSync(join(ROOT, 'docs/specs', name), 'utf8');
  for (const [, block] of text.matchAll(/```json\n([\s\S]*?)```/g)) {
    try {
      yield JSON.parse(block);
    } catch {
      continue;
    }
  }
}

function specFields(): Set<string> {
  const envelope = [...schemaFields(JSON.parse(readFileSync(join(ROOT, 'docs/specs/envelope_schema.json'), 'utf8')))];
  const decision = [...jsonBlocks('decision_response.md')].flatMap((block) => [...schemaFields(block)]);
  const rule = [...readFileSync(join(ROOT, 'docs/specs/policy_format.md'), 'utf8')
    .matchAll(/^\| `([a-z_]+)` \| string \(date-time\) \|/gm)].map((m) => m[1]);
  return new Set([
    ...envelope.map((f) => `envelope.${f}`), ...decision.map((f) => `decision.${f}`), ...rule.map((f) => `rule.${f}`),
  ]);
}

const envelope = (fields: Record<string, unknown> = {}): Record<string, unknown> => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: ORG, environment: 'dev', agent_id: 'refund-agent',
  action_id: 'act_01234567890123456789', idempotency_key: 'idem_242', action: 'refund',
  timestamp: new Date(NOW).toISOString(), signature: 'a'.repeat(64), ...fields,
});

const rule = (window: Record<string, unknown> = {}) => ({
  name: 'refunds_in_window', description: 'Refunds are allowed in the window', priority: 100,
  conditions: { field: 'action', operator: 'equals', value: 'refund' }, decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
  ...window,
});

const policy = (...rules: object[]) => ({
  name: 'refunds', version: 'v1.0.0', description: "The refund agent's refunds",
  scope: { org_id: ORG, environment: 'dev' }, rules,
});

const CARRIERS: Record<string, (v: unknown) => unknown> = {
  'envelope.timestamp': (v) => EnvelopeSchema.parse(envelope({ timestamp: v })).timestamp,
  'envelope.principal.verified_at': (v) => EnvelopeSchema.parse(
    envelope({ principal: { sub: 'user-7', verified_by: 'hosted', verified_at: v } })).principal?.verified_at,
  'rule.valid_from': (v) => (PolicySetSchema.parse(policy(rule({ valid_from: v }))) as PolicySet).rules[0].valid_from,
  'rule.valid_to': (v) => (PolicySetSchema.parse(policy(rule({ valid_to: v }))) as PolicySet).rules[0].valid_to,
  'decision.rate_limit.reset_at': (v) =>
    RateLimitSchema.parse({ scope: 'agent', window: '60s', limit: 2, current: 2, reset_at: v }).reset_at,
};

describe('row 242: every date-time field is read by the one reader', () => {
  it('every date-time field the specs type has its cell', () => {
    expect(new Set(Object.keys(CARRIERS))).toEqual(specFields());
  });

  it.each(Object.keys(CARRIERS).sort())('%s', (field) => {
    const carry = CARRIERS[field];
    const name = field.split('.').pop();
    expect(() => carry('2026-01-02T03:04:05+01:60'))
      .toThrow(`${name} has offset minute 60; an offset's minute is 00 to 59`);
    expect(() => carry('2026-01-02 03:04:05Z')).toThrow(`${name} is not in RFC 3339's date-time form`);
    // Written in the year 0000, an instant inside the years held in UTC: refused in both cores, so a rule's window
    // loads in neither (HTL-29 second review, condition 5)
    expect(() => carry('0000-12-31T23:59:59-00:01')).toThrow(`${name} ${YEAR}`);
    expect(carry('2026-01-02t03:04:05z')).toBe('2026-01-02t03:04:05z');
    expect(carry('2026-01-02T03:04:05+01:00')).toBe('2026-01-02T03:04:05+01:00');
  });
});

/** The instant, written in another offset. */
function inOffset(instant: number, hours: number): string {
  const wall = new Date(instant + hours * 60 * MINUTE).toISOString().slice(0, 23);
  const sign = hours < 0 ? '-' : '+';
  return `${wall}${sign}${String(Math.abs(hours)).padStart(2, '0')}:00`;
}

const reasons = (window: Record<string, unknown>, timestamp?: string) =>
  new PolicyEvaluator().evaluate(
    envelope(timestamp ? { timestamp } : {}) as unknown as Envelope, policy(rule(window)) as unknown as PolicySet,
  ).reason_codes;

describe("row 242: the evaluator reads a date-time as the instant it writes", () => {
  it("a rule's window is the instant it writes", () => {
    const past = NOW - 30 * MINUTE;
    const toCome = NOW + 30 * MINUTE;
    expect(reasons({ valid_to: inOffset(past, 1) })).toEqual(['NO_MATCHING_RULE']);
    expect(reasons({ valid_from: inOffset(toCome, -1) })).toEqual(['NO_MATCHING_RULE']);
    expect(reasons({ valid_from: inOffset(past, 1), valid_to: inOffset(toCome, -1) })).toEqual(['REFUND_ALLOWED']);
    expect(reasons({ valid_to: new Date(toCome).toISOString().replace('T', 't').replace('Z', 'z') }))
      .toEqual(['REFUND_ALLOWED']);
  });

  it("temporal current_time is the call's instant in UTC", () => {
    const temporal = {
      ...rule(), decision: 'BLOCK', reason_code: 'OUTSIDE_HOURS',
      remediation: { type: 'temporal', message: 'Refunds run in business hours', suggestion: 'Retry at 09:00', details: {} },
    };
    for (const [written, current] of [
      ['2026-02-14t16:30:00.250+01:00', '2026-02-14T15:30:00.250Z'],
      ['0050-06-15T12:00:00.9999Z', '0050-06-15T12:00:00.999Z'],
    ]) {
      const decision = new PolicyEvaluator().evaluate(
        envelope({ timestamp: written }) as unknown as Envelope, policy(temporal) as unknown as PolicySet);
      expect(decision.remediation?.details).toEqual({ current_time: current });
    }
  });
});
