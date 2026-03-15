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

// ============================================================================
// Type exports - TypeScript types for type safety
// ============================================================================

/**
 * Envelope type - execution envelope structure.
 */
export type { Envelope } from './types.js';

/**
 * PolicySet type - policy set structure.
 */
export type { PolicySet } from './types.js';

/**
 * Decision type - decision response structure.
 */
export type { Decision } from './types.js';

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
export { EnvelopeSchema } from './types.js';

/**
 * PolicySetSchema - Zod schema for policy set validation.
 */
export { PolicySetSchema } from './types.js';

/**
 * DecisionSchema - Zod schema for decision response validation.
 */
export { DecisionSchema } from './types.js';

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
export type { Route } from './route-types.js';

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
