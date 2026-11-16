/**
 * Row 174 (HTL-22): the outage decision's `metadata` is the spec's.
 *
 * decision_response.md, the decision schema's `metadata`: "Present on CONTROL_PLANE_UNAVAILABLE: the fail mode the
 * outage applied, and the hosted client's circuit breaker after the call (Example 9)". Read at its producer: the schema
 * block and Example 9's JSON. Design: the HTL-22 test design, row 174, behaviors 7 and 8. Mirrors
 * core/tests/test_row174.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ERROR_MESSAGES, errorDecision } from '../../src/error-decisions.js';
import { DecisionMetadataSchema, DecisionSchema } from '../../src/types.js';

const SPEC = readFileSync(join(__dirname, '../../../../../docs/specs/decision_response.md'), 'utf8');

function jsonAfter(heading: string): any {
  return JSON.parse(SPEC.split(heading)[1].split('```json')[1].split('```')[0]);
}

describe('row 174: the outage decision s metadata', () => {
  it('metadata is the spec s', () => {
    const schema = jsonAfter('### JSON Schema').properties.metadata;
    const shape = DecisionMetadataSchema.shape;
    expect(Object.keys(shape).sort()).toEqual(Object.keys(schema.properties).sort());
    expect([...schema.required].sort()).toEqual(Object.keys(shape).sort());
    expect([...shape.fail_mode.options].sort()).toEqual([...schema.properties.fail_mode.enum].sort());
    expect([...shape.circuit_breaker_state.options].sort()).toEqual([...schema.properties.circuit_breaker_state.enum].sort());
    expect(schema.additionalProperties).toBe(false);
    expect(DecisionMetadataSchema.safeParse({ fail_mode: 'FAIL_CLOSED', circuit_breaker_state: 'open', retry_after_ms: 1000 }).success)
      .toBe(false);
  });

  it('example 9 is a decision', () => {
    const example = jsonAfter('### Example 9:');
    const d = DecisionSchema.parse(example);
    expect([d.decision, d.allowed, d.error?.code]).toEqual(['CONTROL_PLANE_UNAVAILABLE', false, 'CONTROL_PLANE_UNAVAILABLE']);
    expect(d.metadata).toEqual(example.metadata);
    expect(d.error?.message, 'the example s message is the cause s').toBe(ERROR_MESSAGES[d.reason_codes[0]]);
  });

  it('the error decision carries its metadata', () => {
    const meta = { fail_mode: 'FAIL_CLOSED' as const, circuit_breaker_state: 'half_open' as const };
    const d = errorDecision('act_r174core00000000000', 'CONTROL_PLANE_UNAVAILABLE', 'CONTROL_PLANE_UNREACHABLE',
      ERROR_MESSAGES.CONTROL_PLANE_UNREACHABLE, { metadata: meta });
    expect(d.metadata).toEqual(meta);
    const none = errorDecision('act_r174core00000000000', 'POLICY_ERROR', 'POLICY_NOT_FOUND', ERROR_MESSAGES.POLICY_NOT_FOUND);
    expect('metadata' in none).toBe(false);
  });
});
