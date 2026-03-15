/**
 * Policy evaluation engine - deterministic rule evaluation.
 */

import { randomUUID } from 'node:crypto';
import {
  EnvelopeSchema,
  PolicySetSchema,
  DecisionType,
  type Envelope,
  type PolicySet,
  type Decision,
  type Rule,
  type Condition,
  type LogicalCondition,
  type MatchedRule,
} from './types.js';
import { resolveFieldPath } from './utils.js';
import { evaluateOperator } from './operators.js';

/**
 * Policy evaluator - deterministic rule evaluation engine.
 *
 * This is the core runtime enforcement engine. It evaluates policies (JSON objects)
 * against execution envelopes and returns decisions.
 *
 * **Design principles:**
 * - Deterministic: same (envelope, policy) always produces same decision
 * - Side-effect free: evaluation does not modify state
 * - Fast: sub-millisecond evaluation for typical policies
 * - Safe-by-default: no matching rule → BLOCK
 *
 * **Evaluation semantics:**
 * - Rules evaluated by priority (descending order)
 * - First-match wins (returns decision from first matching rule)
 * - Disabled rules are skipped
 * - Logical operators: all_of (AND), any_of (OR), none_of (NOT)
 *
 * @example
 * ```typescript
 * const evaluator = new PolicyEvaluator();
 * const decision = evaluator.evaluate(envelope, policy);
 * if (decision.allowed) {
 *   await executeAction();
 * }
 * ```
 */
export class PolicyEvaluator {
  /**
   * Evaluate a policy against an execution envelope.
   *
   * This is the main entry point for policy evaluation. It validates inputs,
   * evaluates rules, and returns a decision response with timing metadata.
   *
   * **Timing breakdown:**
   * - `ingest_ms`: Input validation time (Zod schema parsing)
   * - `evaluation_ms`: Rule evaluation time
   * - `total_ms`: End-to-end time (ingest + evaluation)
   *
   * @param envelope - Execution envelope (validated against envelope schema)
   * @param policy - Policy set (validated against policy schema)
   * @returns Decision response with action decision, reason codes, and timing
   *
   * @throws {ZodError} If envelope or policy validation fails
   *
   * @example
   * ```typescript
   * const decision = evaluator.evaluate(
   *   { action_id: 'act_123', org_id: 'org_abc', ... },
   *   { name: 'payment-controls', version: '1.0', rules: [...] }
   * );
   * console.log(decision.decision);  // 'ALLOW' | 'BLOCK' | 'PAUSE' | ...
   * console.log(decision.allowed);   // true | false
   * console.log(decision.timing.total_ms);  // e.g., 0.42
   * ```
   */
  evaluate(
    envelope: Envelope | Record<string, unknown>,
    policy: PolicySet | Record<string, unknown>,
    mode: 'OBSERVE_ALL' | 'RESPECT_POLICY' = 'RESPECT_POLICY'
  ): Decision {
    const startTime = performance.now();

    // Step 1: Validate inputs (Zod schema parsing)
    const validatedEnvelope = EnvelopeSchema.parse(envelope);
    const validatedPolicy = PolicySetSchema.parse(policy);
    const ingestMs = performance.now() - startTime;

    // Step 2: Evaluate rules
    const evalStart = performance.now();
    const [decisionType, reasonCodes, matchedRules, matchedRuleObj] = this.evaluateRules(
      validatedEnvelope,
      validatedPolicy
    );
    const evaluationMs = performance.now() - evalStart;

    // Step 3: Build decision response
    const totalMs = performance.now() - startTime;

    // Map decision type to allowed flag
    // ALLOW and SANDBOX are the only "allowed" decisions
    const allowed = decisionType === DecisionType.ALLOW || decisionType === DecisionType.SANDBOX;

    // Remediation: pass through from matched rule (only for blocking decisions)
    const remediation =
      !allowed && matchedRuleObj?.remediation ? matchedRuleObj.remediation : undefined;

    // Check if this decision should be wrapped in OBSERVE mode
    let shouldObserve = false;
    if (mode === 'OBSERVE_ALL' && !allowed) {
      shouldObserve = true;
    } else if (
      mode === 'RESPECT_POLICY' &&
      matchedRuleObj &&
      (matchedRuleObj.mode ?? 'enforce') === 'observe' &&
      !allowed
    ) {
      shouldObserve = true;
    }

    if (shouldObserve) {
      const observeTotalMs = performance.now() - startTime;
      return {
        action_id: validatedEnvelope.action_id,
        decision: DecisionType.OBSERVE,
        allowed: true,
        reason_codes: ['OBSERVED'],
        would_be: decisionType,
        would_be_reason_codes: reasonCodes,
        policy_version: validatedPolicy.version,
        timing: {
          ingest_ms: Number(ingestMs.toFixed(3)),
          evaluation_ms: Number(evaluationMs.toFixed(3)),
          total_ms: Number(observeTotalMs.toFixed(3)),
        },
        matched_rules: matchedRules.length > 0 ? matchedRules : undefined,
      };
    }

    // Escalation fields: resume_token + route_ref
    const escalationTypes: Set<string> = new Set([DecisionType.REQUIRE_APPROVAL, DecisionType.PAUSE, DecisionType.ESCALATE]);
    let resumeToken: string | undefined;
    let routeRef: string | undefined;
    if (escalationTypes.has(decisionType)) {
      resumeToken = `rtk_${randomUUID().replace(/-/g, '')}`;
      if (matchedRuleObj?.route) {
        routeRef = matchedRuleObj.route;
      }
    }

    return {
      action_id: validatedEnvelope.action_id,
      decision: decisionType,
      allowed,
      reason_codes: reasonCodes,
      policy_version: validatedPolicy.version,
      timing: {
        ingest_ms: Number(ingestMs.toFixed(3)),
        evaluation_ms: Number(evaluationMs.toFixed(3)),
        total_ms: Number(totalMs.toFixed(3)),
      },
      matched_rules: matchedRules.length > 0 ? matchedRules : undefined,
      resume_token: resumeToken,
      route_ref: routeRef,
      remediation,
    };
  }

  /**
   * Evaluate all rules in a policy set.
   *
   * **Evaluation semantics:**
   * 1. Sort rules by priority (descending - highest priority first)
   * 2. Iterate through rules in order
   * 3. Skip disabled rules
   * 4. Return decision from first matching rule (first-match wins)
   * 5. If no rule matches, return BLOCK (safe-by-default)
   *
   * @param envelope - Validated execution envelope
   * @param policy - Validated policy set
   * @returns Tuple of [decision type, reason codes, matched rules]
   *
   * @private
   */
  private evaluateRules(
    envelope: Envelope,
    policy: PolicySet
  ): [DecisionType, string[], MatchedRule[], Rule | undefined] {
    // Step 1: Sort rules by priority (descending order)
    // Important: Create a copy to avoid mutating the original policy
    const sortedRules = [...policy.rules].sort((a, b) => b.priority - a.priority);

    // Step 2: First-match semantics - return on first matching rule
    for (const rule of sortedRules) {
      // Skip disabled rules
      if (!rule.enabled) {
        continue;
      }

      // Evaluate rule conditions
      if (this.evaluateCondition(envelope, rule.conditions)) {
        // Rule matched - return its decision
        const matchedRule: MatchedRule = {
          rule_name: rule.name,
          policy_set: policy.name,
          priority: rule.priority,
        };

        return [rule.decision, [rule.reason_code], [matchedRule], rule];
      }
    }

    // Step 3: Safe-by-default - no matching rule → BLOCK
    return [DecisionType.BLOCK, ['NO_MATCHING_RULE'], [], undefined];
  }

  /**
   * Evaluate a condition (atomic or logical).
   *
   * This method discriminates between atomic and logical conditions
   * using type discrimination on the 'field' property.
   *
   * @param envelope - Validated execution envelope
   * @param condition - Condition to evaluate (atomic or logical)
   * @returns True if condition matches, false otherwise
   *
   * @private
   */
  private evaluateCondition(envelope: Envelope, condition: Condition | LogicalCondition): boolean {
    // Type discrimination: check if it's an atomic condition (has 'field' property)
    if ('field' in condition) {
      return this.evaluateAtomicCondition(envelope, condition);
    } else {
      return this.evaluateLogicalCondition(envelope, condition);
    }
  }

  /**
   * Evaluate a logical condition (all_of, any_of, none_of).
   *
   * **Logical operators:**
   * - `all_of` (AND): All nested conditions must be true
   * - `any_of` (OR): At least one nested condition must be true
   * - `none_of` (NOT): None of the nested conditions may be true
   *
   * Uses short-circuit evaluation for performance:
   * - `all_of`: Stops on first false
   * - `any_of`: Stops on first true
   * - `none_of`: Stops on first true (then inverts)
   *
   * @param envelope - Validated execution envelope
   * @param condition - Logical condition
   * @returns True if logical condition matches, false otherwise
   *
   * @private
   */
  private evaluateLogicalCondition(envelope: Envelope, condition: LogicalCondition): boolean {
    if (condition.all_of) {
      // AND: all conditions must be true (short-circuit on first false)
      return condition.all_of.every((c) => this.evaluateCondition(envelope, c));
    } else if (condition.any_of) {
      // OR: at least one must be true (short-circuit on first true)
      return condition.any_of.some((c) => this.evaluateCondition(envelope, c));
    } else if (condition.none_of) {
      // NOT: none may be true (short-circuit on first true, then invert)
      return !condition.none_of.some((c) => this.evaluateCondition(envelope, c));
    }

    // Should never happen due to Zod validation (exactly one operator must be set)
    throw new Error('Logical condition must have all_of, any_of, or none_of');
  }

  /**
   * Evaluate an atomic condition.
   *
   * **Steps:**
   * 1. Resolve field path from envelope (e.g., "parameters.amount")
   * 2. Evaluate operator against field value and compare value
   *
   * **Null handling:**
   * - If field path resolves to null/undefined, operator evaluation handles it
   * - Most operators return false for null (except 'exists')
   *
   * @param envelope - Validated execution envelope
   * @param condition - Atomic condition with field, operator, and value
   * @returns True if atomic condition matches, false otherwise
   *
   * @private
   */
  private evaluateAtomicCondition(
    envelope: Envelope,
    condition: Condition & { field: string }
  ): boolean {
    // Step 1: Resolve field path (e.g., "parameters.amount" → 1000)
    const fieldValue = resolveFieldPath(envelope, condition.field);

    // Step 2: Evaluate operator (handles null values internally)
    return evaluateOperator(fieldValue, condition.operator, condition.value);
  }
}

/**
 * Convenience function for one-off evaluations.
 *
 * Creates a new PolicyEvaluator instance and evaluates the policy.
 * For repeated evaluations, create a PolicyEvaluator instance and reuse it.
 *
 * @param envelope - Execution envelope
 * @param policy - Policy set
 * @returns Decision response
 *
 * @example
 * ```typescript
 * import { evaluate } from '@hiitl/core';
 *
 * const decision = evaluate(envelope, policy);
 * if (decision.allowed) {
 *   await executeAction();
 * }
 * ```
 */
export function evaluate(
  envelope: Envelope | Record<string, unknown>,
  policy: PolicySet | Record<string, unknown>,
  mode: 'OBSERVE_ALL' | 'RESPECT_POLICY' = 'RESPECT_POLICY'
): Decision {
  const evaluator = new PolicyEvaluator();
  return evaluator.evaluate(envelope, policy, mode);
}
