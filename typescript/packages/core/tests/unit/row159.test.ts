/**
 * Row 159 (HTL-22): the error decisions are one set, the spec's.
 *
 * decision_response.md, Error Handling: "All errors produce structured decision responses", and its error decisions.
 * The spec is read at its producer: the decision schema's enum and the Error Handling list. Design: the HTL-22 test
 * design, row 159, behavior 10. Mirrors core/tests/test_row159.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ERROR_DECISIONS, ERROR_MESSAGES, auditWriteFailed, errorDecision } from '../../src/error-decisions.js';
import { DecisionType, PRODUCED_DECISIONS } from '../../src/types.js';

const SPEC = readFileSync(join(__dirname, '../../../../../docs/specs/decision_response.md'), 'utf8');

function schemaDecisions(): Set<string> {
  const m = SPEC.match(/"decision": \{\s*"type": "string",\s*"enum": (\[[^\]]*\])/);
  return new Set(JSON.parse(m![1]));
}

function errorHandlingDecisions(): Set<string> {
  const section = SPEC.split('## Error Handling')[1].split('**Error decisions**:')[1].split('\n\n')[0];
  return new Set([...section.matchAll(/^- `([A-Z_]+)`/gm)].map((m) => m[1]));
}

describe('row 159: an error is a decision', () => {
  it('the error decisions are the spec s', () => {
    const listed = [...errorHandlingDecisions()].sort();
    expect([...ERROR_DECISIONS].sort()).toEqual(listed);
    expect([...schemaDecisions()].sort()).toEqual(Object.values(DecisionType).sort());
    for (const d of listed) {
      expect(schemaDecisions().has(d)).toBe(true);
      expect(d in PRODUCED_DECISIONS, `${d} is the path's, never a rule's to write`).toBe(true);
    }
  });

  it('an error decision carries its decision as its code and its cause as its reason', () => {
    const d = errorDecision('act_r159core00000000000', 'POLICY_ERROR', 'POLICY_NOT_FOUND', ERROR_MESSAGES.POLICY_NOT_FOUND);
    expect([d.decision, d.allowed, d.reason_codes, d.error?.code]).toEqual([
      'POLICY_ERROR', false, ['POLICY_NOT_FOUND'], 'POLICY_ERROR',
    ]);
    const blocked = auditWriteFailed(d);
    expect([blocked.decision, blocked.allowed, blocked.error?.code]).toEqual(['BLOCK', false, 'AUDIT_WRITE_FAILED']);
  });
});
