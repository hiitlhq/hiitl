/**
 * Row 196 (HTL-23): the result rule takes the action's review.
 *
 * Ruled 2026-11-06 as the row reads: "a result attaches to an action whose review case resolved approved, read from
 * the case's transitions", by Principle 4 (QUEUED → EXECUTING). The review is the case's latest transition and the
 * case's `timeout_action`; the resolutions under which the action executes are the gateway's (routes.md "A review
 * case"). A decision is held for review when it carries a `resume_token` (decision_response.md). Design:
 * the HTL-23 test design, row 196, behavior 4. Mirrors python/hiitl/core/tests/test_row196.py.
 */
import { describe, expect, it } from 'vitest';
import { resultRefusal, type ExecutionResult, type LifecycleRecord } from '../../src/lifecycle.js';

const RESULT: ExecutionResult = { status: 'succeeded' };
const HELD: LifecycleRecord[] = [
  { decision: { decision: 'REQUIRE_APPROVAL', allowed: false, resume_token: 'rtk_5e0c2a9d41b7' } },
];
const BLOCKED: LifecycleRecord[] = [{ decision: { decision: 'BLOCK', allowed: false } }];

describe('row 196: the result rule takes the action\'s review', () => {
  it.each([
    ['approved', 'fail_closed'], ['modified', 'fail_closed'], ['timed_out', 'fail_open'],
  ])('test_a_resolution_that_executes_lets_the_result_attach (%s, %s)', (status, timeout_action) => {
    expect(resultRefusal(HELD, RESULT, { status, timeout_action })).toBeNull();
  });

  it.each([
    ['pending', 'fail_open'], ['rejected', 'fail_open'], ['timed_out', 'fail_closed'], ['timed_out', 'escalate'],
    ['timed_out', 'extend'],
  ])('test_any_other_leaves_the_action_unexecuted (%s, %s)', (status, timeout_action) => {
    expect(resultRefusal(HELD, RESULT, { status, timeout_action })).toBe('RESULT_ON_UNALLOWED_DECISION');
  });

  it('test_with_no_review_read_the_decision_answers_alone', () => {
    expect(resultRefusal(HELD, RESULT)).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(resultRefusal(HELD, RESULT, null)).toBe('RESULT_ON_UNALLOWED_DECISION');
  });

  it('test_a_review_reaches_only_a_decision_held_for_one', () => {
    expect(resultRefusal(BLOCKED, RESULT, { status: 'approved', timeout_action: 'fail_closed' }))
      .toBe('RESULT_ON_UNALLOWED_DECISION');
  });

  it('test_the_other_refusals_stand_with_a_review', () => {
    const review = { status: 'approved', timeout_action: 'fail_closed' };
    expect(resultRefusal([], RESULT, review)).toBe('ACTION_NOT_FOUND');
    const recorded = [...HELD, { decision: HELD[0].decision, execution_result: { status: 'failed' as const } }];
    expect(resultRefusal(recorded, RESULT, review)).toBe('RESULT_ALREADY_RECORDED');
  });
});
