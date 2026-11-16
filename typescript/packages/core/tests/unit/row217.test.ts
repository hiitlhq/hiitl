/**
 * Row 217 (HTL-24): a result for a held action, written where no review case is held.
 *
 * Ruled 2026-11-07: "the local store writes the result, naming the review it cannot read … the service, which holds
 * the case, reads the case at sync ingest and refuses the record when the case did not let the action run; in local
 * mode the record stands as named … One rule in the store and one read at ingest; no per-mode branching." By the
 * ontology §4 commitment 3 and Principle 4. The one rule takes the review as its writer holds it; a writer holding no
 * case passes the decision's unread review (event_format.md 1.6). Design: the HTL-24 test design, row 217, behavior
 * 1. Mirrors python/hiitl/core/tests/test_row217.py.
 */
import { describe, expect, it } from 'vitest';
import { decisionRefusal, resultRefusal, unreadReview, type ExecutionResult } from '../../src/lifecycle.js';

const RESULT: ExecutionResult = { status: 'succeeded' };
const TOKEN = 'rtk_5e0c2a9d41b7';
const HELD = { decision: 'REQUIRE_APPROVAL', allowed: false, resume_token: TOKEN };
const PAUSED = { decision: 'PAUSE', allowed: false, resume_token: 'rtk_0b9e4c7d2a61' };
const BLOCKED = { decision: 'BLOCK', allowed: false };
const ALLOWED = { decision: 'ALLOW', allowed: true };

describe('row 217: a result for a held action, written where no review case is held', () => {
  it("the unread review names a held decision's token", () => {
    expect(unreadReview(HELD)).toEqual({ unread: TOKEN });
    expect(unreadReview(PAUSED)).toEqual({ unread: PAUSED.resume_token });
    expect([unreadReview(ALLOWED), unreadReview(BLOCKED)]).toEqual([null, null]);
    expect(unreadReview({ ...ALLOWED, resume_token: TOKEN })).toBeNull();
  });

  it('a held decision takes its result when the review is unread', () => {
    expect(decisionRefusal(HELD, unreadReview(HELD))).toBeNull();
    expect(resultRefusal([{ decision: HELD }], RESULT, unreadReview(HELD))).toBeNull();
  });

  it.each([
    ["another decision's", { unread: PAUSED.resume_token }], ['a second member', { unread: TOKEN, case: 'rc_1' }],
    ['no token', { unread: null }], ['an empty token', { unread: '' }], ['empty', {}], ['a bare token', TOKEN],
    ['none', null],
  ])('any other review (%s) leaves a held decision unexecuted', (_, review) => {
    expect(decisionRefusal(HELD, review as never)).toBe('RESULT_ON_UNALLOWED_DECISION');
  });

  it.each([
    [null], [{ unread: TOKEN }], [{ status: 'approved', timeout_action: 'fail_closed' }],
  ])('a decision held for no review is refused whatever the review (%j)', (review) => {
    expect(decisionRefusal(BLOCKED, review as never)).toBe('RESULT_ON_UNALLOWED_DECISION');
    expect(resultRefusal([{ decision: BLOCKED }], RESULT, review as never)).toBe('RESULT_ON_UNALLOWED_DECISION');
  });

  it('an allowed decision needs no review', () => {
    expect(decisionRefusal(ALLOWED, null)).toBeNull();
    expect(decisionRefusal(ALLOWED, unreadReview(ALLOWED))).toBeNull();
  });

  it('the result rule reads the decision rule', () => {
    const review = unreadReview(HELD);
    expect(resultRefusal([], RESULT, review)).toBe('ACTION_NOT_FOUND');
    const recorded = [{ decision: HELD }, { decision: HELD, execution_result: { status: 'failed' as const } }];
    expect(resultRefusal(recorded, RESULT, review)).toBe('RESULT_ALREADY_RECORDED');
  });
});
