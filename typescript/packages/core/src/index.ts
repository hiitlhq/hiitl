/**
 * @hiitl/core - HIITL Policy Evaluator for TypeScript
 *
 * Core runtime enforcement engine for policy-based execution control.
 * Evaluates policies (JSON objects) against execution envelopes and returns decisions.
 *
 * @example
 * ```typescript
 * import { PolicyEvaluator, evaluate } from '@hiitl/core';
 *
 * // Option 1: Use the convenience function
 * const decision = evaluate(envelope, policy);
 * if (decision.allowed) {
 *   await executeAction();
 * }
 *
 * // Option 2: Create an evaluator instance (reusable)
 * const evaluator = new PolicyEvaluator();
 * const decision = evaluator.evaluate(envelope, policy);
 * ```
 *
 * @packageDocumentation
 */

// ============================================================================
// Primary exports - Main API
// ============================================================================

/**
 * PolicyEvaluator class - deterministic rule evaluation engine.
 *
 * @see {@link PolicyEvaluator}
 */
export { PolicyEvaluator } from './evaluator.js';

/**
 * Convenience function for one-off evaluations.
 *
 * @see {@link evaluate}
 */
export { evaluate } from './evaluator.js';

/**
 * Observe mode, and a windowed rule's refusal and a limiter's failure as decisions (ecp_evaluate_spec.md **Observe
 * Mode**; policy_format.md **Rate-limit rules**) — one definition, used by the evaluator and the SDK's limiter.
 */
export { observe } from './evaluator.js';
/** The kill switches a version makes live (sync_engine.md 2.4; HTL-29 row 131). */
export { liveKillSwitches } from './evaluator.js';
export { counterState, tightest, withCounter, limitExceeded, limiterFailed } from './rate-limits.js';
/** An error is a decision (decision_response.md "Error Handling"; HTL-22 row 159). */
export {
  ERROR_DECISIONS, ERROR_MESSAGES, FAIL_OPEN_MESSAGES, FAIL_MODES, errorDecision, auditWriteFailed, outage, errorBlock,
} from './error-decisions.js';
export type { FailMode } from './error-decisions.js';
export {
  RESULT_STATUSES, ResultNumberSchema, EVALUATED, LIFECYCLE_MESSAGES, RECORD_REFUSALS, eventType, executionResult, unreadReview,
  decisionRefusal, resultRefusal, resultConflict, recordedResult,
} from './lifecycle.js';
export type { ResultStatus, ExecutionResult, LifecycleRecord, Review, UnreadReview } from './lifecycle.js';
export type { Enrichment } from './evaluator.js';
export * as routing from './routing.js';
/** Where hiitl sends: an `https` URL naming a host, a route's `endpoint` and a `server_url` alike (row 140). */
export { httpsRefusal } from './transport.js';
/** A date-time, read by RFC 3339's grammar: every field the specs type `date-time` (HTL-29 review, condition 5). */
export { dateTimeRefusal, readDateTime, DateTimeSchema } from './date-time.js';

// ============================================================================
// Type exports - TypeScript types for type safety
// ============================================================================

/**
 * Envelope type - execution envelope structure.
 */
export type { Envelope } from './types.js';

/**
 * CostEstimate type - the envelope's cost estimate (envelope_schema.json v1.4).
 */
export type { CostEstimate } from './types.js';

/**
 * PolicySet type - policy set structure.
 */
export type { PolicySet } from './types.js';

/**
 * Decision type - decision response structure.
 */
export type { Decision, DecisionMetadata } from './types.js';

/**
 * Rule type - individual rule structure.
 */
export type { Rule } from './types.js';

/**
 * Condition type - atomic condition structure.
 */
export type { Condition } from './types.js';

/**
 * LogicalCondition type - logical condition structure (all_of, any_of, none_of).
 */
export type { LogicalCondition } from './types.js';

/**
 * MatchedRule type - matched rule metadata in decision response.
 */
export type { MatchedRule } from './types.js';

/**
 * Remediation type - structured remediation guidance.
 */
export type { Remediation } from './types.js';

/**
 * StagedObservation type - "would have" observations from staged rules.
 *
 * Staged rules don't bind decisions but their matches are recorded
 * on every Decision via `Decision.staged_observations` (always an
 * array, empty when no staged rule matched). See Block 1B / 9b for
 * the side-by-side evaluation model.
 */
export type { StagedObservation } from './types.js';

/**
 * T-130: a matching windowed RATE_LIMIT rule (R-0852), the rate-limit
 * window, the verified principal (A7).
 */
export type { RateLimitRule, RateLimitWindow, Principal } from './types.js';
/** A rule read with a field the call does not carry, skipped and flagged (`Decision.missing_fields`; HTL-22 row 176). */
export type { MissingField } from './types.js';
export { PRODUCED_DECISIONS } from './types.js'; // the decisions a rule never writes (policy_format.md 2.10)
export { hasPlaceholder, PLACEHOLDER_KEY, DECLARED_KEY, FIELD_REF_KEY, fieldRef, conforms, schemaError, PrincipalSchema } from './types.js';
export { AUDIT_FURTHER, canonicalJson, canonicalHash, auditContentHash, envelopeSignedForm, envelopeSignature, envelopeVerifies, envelopeHash } from './canonical.js';

/** What a store writes: each declared field's value replaced (event_format.md §Redaction; HTL-20 row 139). */
export { Redaction, MARKER, valueHash, HASH_PREFIX, KEY_BYTES, ORG_FIELDS } from './redaction.js';

// ============================================================================
// Schema exports - Zod schemas for runtime validation
// ============================================================================

/**
 * EnvelopeSchema - Zod schema for envelope validation.
 *
 * Use this to validate envelope objects at runtime.
 *
 * @example
 * ```typescript
 * import { EnvelopeSchema } from '@hiitl/core';
 *
 * const result = EnvelopeSchema.safeParse(data);
 * if (result.success) {
 *   console.log('Valid envelope:', result.data);
 * } else {
 *   console.error('Invalid envelope:', result.error);
 * }
 * ```
 */
export { EnvelopeSchema, ORG_ID_PATTERN, DEDUP_WINDOW_SECONDS } from './types.js';
export { ENVELOPE_SCHEMA_VERSION, ENVELOPE_MIGRATION_NOTE, ENVELOPE_RENAMED, renamedNote } from './types.js';

/**
 * PolicySetSchema - Zod schema for policy set validation.
 */
export { PolicySetSchema, PolicySetScopeSchema, VERSION_PATTERN } from './types.js';

/** The decision types and sensitivity labels, the sources a route's filter values are taken from (HTL-29 row 131). */
export { DecisionTypeSchema, SensitivitySchema } from './types.js';

/**
 * DecisionSchema - Zod schema for decision response validation.
 */
export { DecisionSchema, DecisionMetadataSchema } from './types.js';

/**
 * RemediationSchema - Zod schema for remediation validation.
 */
export { RemediationSchema } from './types.js';

// ============================================================================
// Enum constant exports - For programmatic access to enum values
// ============================================================================

/**
 * DecisionType enum constants.
 *
 * @example
 * ```typescript
 * import { DecisionType } from '@hiitl/core';
 *
 * if (decision.decision === DecisionType.ALLOW) {
 *   // ...
 * }
 * ```
 */
export { DecisionType } from './types.js';

/**
 * ConditionOperator enum constants.
 */
export { ConditionOperator } from './types.js';

/**
 * Environment enum constants.
 */
export { Environment } from './types.js';

/**
 * Operation enum constants.
 */
export { Operation } from './types.js';

/**
 * Sensitivity enum constants.
 */
export { Sensitivity } from './types.js';

/**
 * RemediationType enum constants.
 */
export { RemediationType } from './types.js';

// ============================================================================
// Route type exports - Route model types for route configuration
// ============================================================================

/**
 * Route type - route configuration structure.
 */
export type { Route, RouteInput } from './route-types.js';

/**
 * RouteSchema - Zod schema for route validation.
 *
 * @example
 * ```typescript
 * import { RouteSchema } from '@hiitl/core';
 *
 * const result = RouteSchema.safeParse(data);
 * if (result.success) {
 *   console.log('Valid route:', result.data);
 * }
 * ```
 */
export { RouteSchema } from './route-types.js';

/**
 * Route enum constants.
 */
export { RouteDirection, RouteTiming, RoutePurpose, RouteProtocol } from './route-types.js';
export { TimeoutAction, RouteDecisionOption, BackoffStrategy } from './route-types.js';

// HTL43: one numeric admission helper, shared by model and SDK boundaries.
export { assertNumericDomain, NumericDomainError, NUMERIC_BOUND } from './numeric-domain.js';
export { integer } from './integer.js';

// Verify historical stored bytes without creating a new admitted record.
export { auditHashMatches } from './canonical.js';

// Typed operand failures carry only authored operator/path diagnostics.
export { OperatorKindError } from './operator-kinds.js';

export { numericInput, assertSchemaNumbers, parseAdmittedNumbers, copySuppliedInput } from "./own-data.js";

export { prepareInputSchemas } from './own-data.js';
