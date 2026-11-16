/**
 * Row 150 (HTL-22): what a record is, and an action's lifecycle up to the result write.
 *
 * The Stop 1 ruling (HTL-20): "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle
 * fields (`event_type`; `execution_result` on a result), appended against the decision's `action_id`". Principle 4:
 * BLOCKED is terminal. Infrastructure spec 2: "idempotent state transitions". The spec is read at its producer:
 * event_format.md's Event Types table. Design: the HTL-22 test design, row 150, behaviors 1-3. Mirrors
 * core/tests/test_row150.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  LIFECYCLE_MESSAGES,
  RESULT_STATUSES,
  eventType,
  executionResult,
  recordedResult,
  resultRefusal,
  type ExecutionResult,
  type LifecycleRecord,
} from '../../src/lifecycle.js';
import { DecisionType } from '../../src/types.js';

const SPEC = readFileSync(join(__dirname, '../../../../../docs/specs/event_format.md'), 'utf8');

const ALLOWED: LifecycleRecord = { decision: { decision: 'ALLOW', allowed: true } };
const BLOCKED: LifecycleRecord = { decision: { decision: 'BLOCK', allowed: false } };
const DONE: ExecutionResult = { status: 'succeeded', duration_ms: 12 };

/** The Event Types table's rows: [event_type, record, decision, execution_result.status]. */
function table(): string[][] {
  const section = SPEC.split('## Event Types')[1].split('**Names earlier versions')[0];
  return [...section.matchAll(/^\| `([a-z_.]+)` \| (a [a-z]+ record) \| ([^|]+?) \| ([^|]+?) \|$/gm)].map((m) =>
    m.slice(1)
  );
}

const result = (r: ExecutionResult): LifecycleRecord => ({ ...ALLOWED, execution_result: r });
const strip = (s: string): string => s.replace(/`/g, '');

describe('row 150: what a record is, and the lifecycle up to the write', () => {
  it('event type is the spec s table', () => {
    const rows = table();
    const named = Object.fromEntries(rows.filter(([, , d, s]) => s === 'none' && d !== 'any other').map(([e, , d]) => [strip(d), e]));
    const other = rows.filter(([, , d, s]) => s === 'none' && d === 'any other').map(([e]) => e);
    const byStatus = Object.fromEntries(rows.filter(([, , , s]) => s !== 'none').map(([e, , , s]) => [strip(s), e]));
    expect(other).toHaveLength(1);
    expect(Object.keys(byStatus).sort(), "the table's statuses are the result's").toEqual([...RESULT_STATUSES].sort());
    const decisions = Object.values(DecisionType) as string[];
    for (const d of Object.keys(named)) expect(decisions).toContain(d);
    for (const d of decisions) {
      expect(eventType(d), d).toBe(named[d] ?? other[0]);
      for (const [status, event] of Object.entries(byStatus)) expect(eventType(d, { status }), `${d} ${status}`).toBe(event);
    }
  });

  it.each([
    ['unnamed-status', 'done', undefined, undefined],
    ['no-status', undefined, undefined, undefined],
    ['error-not-a-string', 'succeeded', 404, undefined],
    ['negative-duration', 'failed', undefined, -1],
    ['bool-duration', 'failed', undefined, true],
    ['duration-not-finite', 'succeeded', undefined, Number.NaN],
    ['duration-a-string', 'succeeded', undefined, '12'],
  ])('a result that is not the spec s is refused, %s', (_id, status, error, durationMs) => {
    expect(() => executionResult(status, error, durationMs)).toThrow(LIFECYCLE_MESSAGES.RESULT_INVALID);
  });

  it('an unnamed status is no event', () => {
    expect(() => eventType('ALLOW', { status: 'done' })).toThrow();
  });

  it('a result carries only what was sent', () => {
    expect(executionResult('succeeded')).toEqual({ status: 'succeeded' });
    expect(executionResult('failed', 'card declined', 12.5)).toEqual({
      status: 'failed', error: 'card declined', duration_ms: 12.5,
    });
  });

  it('the lifecycle refuses as the spec says', () => {
    expect(resultRefusal([], DONE)).toBe('ACTION_NOT_FOUND');
    expect(resultRefusal([BLOCKED], DONE)).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(resultRefusal([ALLOWED], DONE)).toBeNull();
    expect(resultRefusal([ALLOWED, result(DONE)], DONE), 'the same result again is no refusal').toBeNull();
    expect(resultRefusal([ALLOWED, result(DONE)], { status: 'failed' })).toBe('RESULT_ALREADY_RECORDED');
    // The decision a result attaches to is the latest record carrying no result
    expect(resultRefusal([ALLOWED, BLOCKED], DONE)).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(resultRefusal([BLOCKED, ALLOWED], DONE)).toBeNull();
  });

  it('the same result again is the first record', () => {
    const first = result(DONE);
    const later = result(DONE);
    expect(recordedResult([ALLOWED, first, later], DONE)).toBe(first);
    expect(recordedResult([ALLOWED], DONE)).toBeNull();
    expect(recordedResult([ALLOWED, first], { status: 'succeeded' }), 'a result differing by a member').toBeNull();
  });
});
