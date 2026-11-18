/**
 * An action's lifecycle, read from its records (Principle 4: "Every action is modeled as a lifecycle"; the Stop 1
 * ruling, HTL-20: "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle fields
 * (`event_type`; `execution_result` on a result), appended against the decision's `action_id`"). One definition, read
 * by the SDK's store. Mirrors python/hiitl/core/lifecycle.py.
 *
 * A record's `event_type` is derived from what the record carries, its decision and its `execution_result`, so it is
 * computed wherever a record is read and stored in no column (derived state is computed, never stored).
 * event_format.md, "Event types", is its table.
 *
 * A result is recorded once, on an action its decision allowed or its review let run. An action that was not allowed
 * never executed, so it has no result (Principle 4: BLOCKED is terminal), and a second, different result for one action
 * is refused (Infrastructure spec 2: "idempotent state transitions"). The same result again is the record already
 * carrying it. A writer that holds no review case names the review it could not read, and the reader that holds the
 * case reads it (row 217, event_format.md "A result whose writer holds no case").
 */

import { canonicalJson } from './canonical.js';
import { z } from 'zod';

/** event_format.md's `execution_result.status`. */
export const RESULT_STATUSES = ['succeeded', 'failed', 'canceled'] as const;
export type ResultStatus = (typeof RESULT_STATUSES)[number];
/** The result body's numeric declaration, shared by admission and diagnostics. */
export const ResultNumberSchema=z.object({status:z.enum(RESULT_STATUSES),error:z.string().optional(),duration_ms:z.number().min(0).optional()}).strict();

/** event_format.md's `execution_result`. */
export interface ExecutionResult {
  status: ResultStatus;
  error?: string;
  duration_ms?: number;
}

/** A record as the lifecycle reads it: its decision, and its result when it carries one. */
export interface LifecycleRecord {
  decision: { allowed?: unknown; [k: string]: unknown };
  execution_result?: ExecutionResult | null;
  [k: string]: unknown;
}

/** The event a result is, by its status (event_format.md "Event types"). */
const RESULT_EVENTS: Readonly<Record<ResultStatus, string>> = {
  succeeded: 'action.executed',
  failed: 'action.failed',
  canceled: 'action.canceled',
};
/** The error decisions that are their own event; every other decision is the action evaluated. */
const DECISION_EVENTS: Readonly<Record<string, string>> = {
  SIGNATURE_INVALID: 'signature.invalid',
  CONTROL_PLANE_UNAVAILABLE: 'control_plane.unavailable',
};
export const EVALUATED = 'action.evaluated';

/** Why a result is not recorded, by its reason code. The hosted service answers the same codes. */
export const LIFECYCLE_MESSAGES: Readonly<Record<string, string>> = {
  RESULT_INVALID:
    "The result is not one hiitl records: `status` is one of succeeded, failed or canceled; " +
    '`error`, when sent, is a string; `duration_ms`, when sent, is a non-negative number.',
  ACTION_NOT_FOUND:
    'No decision is recorded for this action_id in this org and environment, so a result has nothing to attach ' +
    'to. Send the action_id of the decision evaluate() returned.',
  RESULT_ON_UNALLOWED_DECISION:
    "The action's decision did not allow it, and no review let it execute, so it never executed and has no result. " +
    'Record a result only for a decision whose `allowed` is true, or one held for review whose review let it ' +
    'execute.',
  RESULT_ALREADY_RECORDED:
    'A different result is already recorded for this action, and an action\'s result is recorded once. Sending ' +
    'the same result again returns the record that holds it.',
};

/**
 * The codes under which the hosted service refuses a record for its own content (sync_engine.md section 2.1; row 224,
 * ruled 2026-11-08). Its answer is final, so a store keeps the record as written, marks it refused with the code and
 * never sends it again. Every other code is retried, one a store does not know among them (a false final is the
 * dangerous direction). The service refuses a record's content under no other code.
 */
export const RECORD_REFUSALS = [
  'MISSING_EVENT_ID', 'CONTENT_HASH_MISMATCH', 'TIMESTAMP_INVALID', 'RESULT_INVALID', 'REDACTION_INVALID',
  'REVIEW_INVALID', 'RESULT_ON_UNALLOWED_DECISION', 'EVENT_TYPE_MISMATCH', 'RESULT_ALREADY_RECORDED',
] as const;

const isStatus = (s: unknown): s is ResultStatus => (RESULT_STATUSES as readonly unknown[]).includes(s);

/**
 * The record's event, from its decision and its `execution_result` (event_format.md "Event types").
 *
 * @throws {Error} `execution_result` has a status event_format.md does not name
 */
export function eventType(decision: string, executionResult?: { status?: unknown } | null): string {
  if (executionResult) {
    const status = executionResult.status;
    if (!isStatus(status)) {
      throw new Error(`execution_result.status ${JSON.stringify(status)} is not one of ${RESULT_STATUSES.join(', ')}`);
    }
    return RESULT_EVENTS[status];
  }
  return DECISION_EVENTS[decision] ?? EVALUATED;
}

/**
 * The result as event_format.md's `execution_result` carries it: `status`, and `error` and `duration_ms` when given.
 *
 * @throws {Error} a member is not what event_format.md says it is (LIFECYCLE_MESSAGES.RESULT_INVALID)
 */
export function executionResult(status: unknown, error?: unknown, durationMs?: unknown): ExecutionResult {
  const number = typeof durationMs === 'number';
  if (
    !isStatus(status) ||
    (error !== undefined && error !== null && typeof error !== 'string') ||
    (durationMs !== undefined && durationMs !== null && !(number && Number.isFinite(durationMs) && durationMs >= ResultNumberSchema.shape.duration_ms.unwrap().minValue!))
  ) {
    throw new Error(LIFECYCLE_MESSAGES.RESULT_INVALID);
  }
  const result: ExecutionResult = { status };
  if (typeof error === 'string') result.error = error;
  if (typeof durationMs === 'number') result.duration_ms = durationMs;
  return result;
}

const same = (a: unknown, b: unknown): boolean => canonicalJson(a) === canonicalJson(b);

/** A review of a held action: its case's latest transition and the case's `timeout_action`. */
export interface Review {
  status?: unknown;
  timeout_action?: unknown;
}

/** The review a writer holding no case names: the held decision's `resume_token` (event_format.md `review`). */
export interface UnreadReview {
  unread: string;
}

/**
 * Whether a review let its held action execute, as the gateway reads the case (routes.md "A review case"):
 * `approved`; `modified`; or a recorded `timed_out` under `timeout_action` `fail_open`. Any other, or none, did not.
 */
function reviewExecutes(review: unknown): boolean {
  if (typeof review !== 'object' || review === null) return false;
  const { status, timeout_action } = review as Review;
  return status === 'approved' || status === 'modified' || (status === 'timed_out' && timeout_action === 'fail_open');
}

/**
 * The review a writer holding no case names for `decision` (event_format.md `review`; row 217): on a held decision,
 * one not allowed that carries a `resume_token` (decision_response.md, the handle "to resume or cancel the action
 * after review"), `{ unread: <its resume_token> }`; on any other, null: an allowed decision is held for nothing, and
 * a decision with no token is held for no review.
 */
export function unreadReview(decision: LifecycleRecord['decision']): UnreadReview | null {
  const token = decision.resume_token;
  return typeof token === 'string' && token !== '' && decision.allowed !== true ? { unread: token } : null;
}

/**
 * Why a result does not attach to `decision`, or null.
 *
 * An allowed decision takes it. A held decision takes it when its `review` let it execute (the latest transition
 * across the action's review cases, with that case's `timeout_action`; row 196, ruled 2026-11-06), or when `review`
 * is the decision's unread review: its writer holds no case and names the review it could not read, which the reader
 * holding the case reads (row 217). Any other decision, or a held one under any other review, never executed.
 */
export function decisionRefusal(
  decision: LifecycleRecord['decision'],
  review: Review | UnreadReview | null = null,
): string | null {
  if (decision.allowed === true) return null;
  const held = unreadReview(decision);
  const unread = typeof review === 'object' && review !== null && held !== null && same(review, held);
  if (held && (unread || reviewExecutes(review))) return null;
  return 'RESULT_ON_UNALLOWED_DECISION';
}

/**
 * Why `result` is not recorded on the action whose records are `lifecycle` (oldest first), or null.
 *
 * The action's decision is its latest record that carries no result: the answer the caller acted on, read by
 * `decisionRefusal` under `review`, the review as the writer holds it (a case's, or the decision's unread review).
 */
export function resultRefusal(
  lifecycle: readonly LifecycleRecord[],
  result: ExecutionResult,
  review: Review | UnreadReview | null = null,
): string | null {
  const decisions = lifecycle.filter((r) => !r.execution_result);
  if (decisions.length === 0) return 'ACTION_NOT_FOUND';
  return decisionRefusal(decisions[decisions.length - 1].decision, review) ?? resultConflict(lifecycle, result);
}

/**
 * Whether the action whose records are `lifecycle` holds a result other than `result`: an action's result is recorded
 * once, by every writer of it, the sync ingest included (gap row 265, ruled 2026-11-11).
 */
export function resultConflict(lifecycle: readonly LifecycleRecord[], result: ExecutionResult): string | null {
  if (lifecycle.some((r) => r.execution_result && !same(r.execution_result, result))) return 'RESULT_ALREADY_RECORDED';
  return null;
}

/** The first record of `lifecycle` carrying `result`, or null: the same result again returns it. */
export function recordedResult<R extends LifecycleRecord>(lifecycle: readonly R[], result: ExecutionResult): R | null {
  return lifecycle.find((r) => r.execution_result && same(r.execution_result, result)) ?? null;
}
