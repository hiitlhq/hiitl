/**
 * Policy evaluation engine - deterministic rule evaluation.
 */

import {assertSchemaNumbers,parseAdmittedNumbers} from './own-data.js';
import { createHash, randomUUID } from 'node:crypto';
import {
  EnvelopeSchema,
  PolicySetSchema,
  DecisionType,
  hasPlaceholder,
  fieldRef,
  type Envelope,
  type PolicySet,
  type Decision,
  type Rule,
  type RuleScope,
  type Condition,
  type LogicalCondition,
  type MatchedRule,
  type MissingField,
  type StagedObservation,
  type RateLimitRule,
  type Remediation,
} from './types.js';
import { assertNumericDomain } from './numeric-domain.js';
import { resolveFieldPath } from './utils.js';
import { readDateTime } from './date-time.js';
import { evaluateOperator } from './operators.js';
import { OperatorKindError, compareOperatorFailures } from './operator-kinds.js';

/**
 * The forbid class of a decision for precedence (policy_format.md "Rule
 * Precedence"; R-0846): KILL_SWITCH 0, BLOCK 1, every other decision 2.
 * Mirrors python/hiitl/core/precedence.py.
 */
export function forbidClass(decision: string): number {
  if (decision === DecisionType.KILL_SWITCH) return 0;
  if (decision === DecisionType.BLOCK) return 1;
  return 2;
}

/** A rule's precedence key: (class, −priority, definition order). Mirrors precedence.py `precedence_key`. */
type Key = [number, number, number];
const keyOf = (rule: Rule, index: number): Key => [forbidClass(rule.decision), -rule.priority, index];
/** The key a rule binds at when it decides BLOCK (a rule its set's `on_missing: fail_closed` could not read): the BLOCK
 * class, at the rule's own priority and place in the definition order. Mirrors precedence.py `as_block`. */
const asBlock = (key: Key): Key => [forbidClass(DecisionType.BLOCK), key[1], key[2]];
const before = (a: Key, b: Key): boolean => (a[0] - b[0] || a[1] - b[1] || a[2] - b[2]) < 0;

/** A path the envelope carries or lacks, not the enrichment context beside it (policy_format.md 2.7). */
const inEnvelope = (path: string): boolean => path.split('.', 1)[0] !== ENRICHMENT_ROOT;

/**
 * A missing-field BLOCK's remediation (policy_format.md "A field the call does not carry"): "treat as BLOCK, include
 * remediation telling the developer which field is needed". `custom`, the type for guidance no other fits; the rule's
 * own remediation is for the decision it makes when it matches. Mirrors evaluator.py `_unread`.
 */
function unreadRemediation(ruleName: string, policySet: string, fields: string[]): Remediation {
  const named = fields.join(', ');
  return {
    message:
      `Rule '${ruleName}' in policy set '${policySet}' reads ${named}, which the call does not carry, and ` +
      `the set's on_missing is fail_closed.`,
    suggestion: `Add ${named} to the call and evaluate it again.`,
    type: 'custom',
    details: { fields: [...fields] },
  };
}

/**
 * Observe mode (ecp_evaluate_spec.md **Observe Mode**): "A decision that allows (ALLOW, SANDBOX) comes back as itself.
 * Any other decision comes back as `OBSERVE` with `would_be` set to it". The evaluator returns it under OBSERVE_ALL,
 * and each SDK after its limiter, so a limit, a kill switch and a failed limiter are observed alike; the rule, the
 * counter state, the missing fields and an `error` are kept, and nothing that would hold the call (a resume token, a
 * route, a remediation) is. Mirrors evaluator.py `observe`.
 */
export function observe(decision: Decision): Decision {
  if (decision.allowed) return decision;
  const { resume_token, route_ref, remediation, escalation_context, ...kept } = decision;
  return {
    ...kept,
    decision: DecisionType.OBSERVE,
    allowed: true,
    reason_codes: ['OBSERVED'],
    would_be: decision.decision,
    would_be_reason_codes: [...decision.reason_codes],
  };
}

/** An instant as UTC ISO 8601 to the millisecond, `Z`-suffixed — the string both languages render. */
const utcMs = (ts: string): string => new Date(readDateTime(ts)).toISOString();

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
/** The enrichment context's root in a condition path (policy_format.md 2.7; TICKET-046). */
export const ENRICHMENT_ROOT = 'external';

/** The evaluation's enrichment context: {source: {field: value}} — a sync route's declared answer fields. */
export type Enrichment = Record<string, Record<string, unknown>>;
const SDK_ADMITTED=Symbol('the SDK\'s envelope from this call and the policy it holds');

export class PolicyEvaluator {
  // The enrichment context of the evaluation in progress (beside the envelope, never inside it). evaluate() is
  // synchronous, so one evaluator serves one evaluation at a time.
  private enrichment: Enrichment = {};
  // Where the SDK's evaluate() started, when the SDK is the caller: its clock covers the call's admission, envelope
  // build and signature check, and the evaluation's timing counts from there (decision_response.md Timing Metadata;
  // HTL-43 gap 303). Mirrors evaluator.py `_STARTED`.
  private sdkStarted: number | null = null;

  /**
   * Evaluate a policy against an execution envelope.
   *
   * This is the main entry point for policy evaluation. It validates inputs,
   * evaluates rules, and returns a decision response with timing metadata.
   *
   * **Timing breakdown:**
   * - `ingest_ms`: Input admission and validation time (the numeric walk and Zod schema parsing)
   * - `evaluation_ms`: Rule evaluation time
   * - `total_ms`: End-to-end time (ingest + evaluation), from where `evaluate()` starts
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
   *   { name: 'payment-controls', version: 'v1.0.0', description: '...', scope: {...}, rules: [...] }
   * );
   * console.log(decision.decision);  // 'ALLOW' | 'BLOCK' | 'PAUSE' | ...
   * console.log(decision.allowed);   // true | false
   * console.log(decision.timing.total_ms);  // e.g., 0.42
   * ```
   */
  evaluate(
    envelope: Envelope | Record<string, unknown>,
    policy: PolicySet | Record<string, unknown>,
    mode: 'OBSERVE_ALL' | 'RESPECT_POLICY' = 'RESPECT_POLICY',
    enrichment?: Enrichment | null,
    admission?:typeof SDK_ADMITTED
  ): Decision {
    // The clock starts where evaluate() starts, so the admission of the call's trees is counted in ingest_ms and
    // total_ms (decision_response.md timing; HTL-43 gap 303, ruled b88dd3e3). Mirrors evaluator.py.
    const startTime = this.sdkStarted ?? performance.now();
    if(admission!==SDK_ADMITTED){
      assertSchemaNumbers(envelope, EnvelopeSchema, ['envelope']);
      assertSchemaNumbers(policy, PolicySetSchema, ['policy']);
    }
    assertNumericDomain(enrichment, ['enrichment']);
    // `enrichment`: the sync routes' answers, read as external.<route>.<field>; a ROUTE rule whose route has answered
    // does not match again (policy_format.md 2.7). Mirrors evaluator.py.
    if (!enrichment || Object.keys(enrichment).length === 0) {
      return this.evaluateOnce(envelope, policy, mode, startTime); // the hot path: no route has answered, nothing to set
    }
    const previous = this.enrichment;
    this.enrichment = enrichment;
    try {
      return this.evaluateOnce(envelope, policy, mode, startTime);
    } finally {
      this.enrichment = previous;
    }
  }

  /**
   * @internal The SDK's entry: its envelope is built and admitted in this call, and the policy it holds was admitted
   * where it was supplied (its file at load, a pull or the disk cache at receipt, a kill-switch tick at receipt), so
   * neither is walked again (sync_engine.md Numeric domain; HTL-43 gap 295). A route's answer is still input.
   * `ingestedMs` is the SDK's own ingest for the call, from its evaluate() through the envelope's signature check; the
   * evaluation's clock starts that far back (HTL-43 gap 303). Mirrors evaluator.py `_evaluate_admitted_envelope`.
   */
  _evaluateAdmittedEnvelope(envelope:Envelope,policy:PolicySet,mode:'OBSERVE_ALL'|'RESPECT_POLICY',enrichment?:Enrichment|null,ingestedMs=0):Decision {
    this.sdkStarted=performance.now()-ingestedMs;
    try {return this.evaluate(envelope,policy,mode,enrichment,SDK_ADMITTED);}
    finally {this.sdkStarted=null;}
  }

  private evaluateOnce(
    envelope: Envelope | Record<string, unknown>,
    policy: PolicySet | Record<string, unknown>,
    mode: 'OBSERVE_ALL' | 'RESPECT_POLICY',
    startTime: number
  ): Decision {
    // Step 1: Validate inputs (Zod schema parsing)
    const validatedEnvelope = parseAdmittedNumbers(EnvelopeSchema,envelope);
    const validatedPolicy = parseAdmittedNumbers(PolicySetSchema,policy);
    const ingestMs = performance.now() - startTime;

    // Step 2: Evaluate rules
    const evalStart = performance.now();
    const [
      decisionType,
      reasonCodes,
      matchedRules,
      matchedRuleObj,
      stagedObservations,
      rateLimitRules,
      unreadRem,
      missingFields,
    ] = this.evaluateRules(validatedEnvelope, validatedPolicy, mode);
    const evaluationMs = performance.now() - evalStart;

    // Step 3: Build decision response
    const totalMs = performance.now() - startTime;

    // Map decision type to allowed flag
    // ALLOW and SANDBOX are the only "allowed" decisions
    const allowed = decisionType === DecisionType.ALLOW || decisionType === DecisionType.SANDBOX;

    // Remediation: the matched rule's, details computed from the call (only for blocking decisions)
    const remediation =
      unreadRem ??
      (!allowed && matchedRuleObj?.remediation
        ? this.resolveRemediation(validatedEnvelope, matchedRuleObj.remediation)
        : undefined);

    // Staged observations are always emitted as an array (possibly
    // empty) — Python's Decision.staged_observations defaults to []
    // (List[StagedObservation], Field(default_factory=list)), so the
    // field is always present in the serialized response. Matching
    // that exactly is required for byte-equivalent decisions across
    // languages — the conformance suite (Block 5b) depends on it.
    const stagedField = stagedObservations;

    // Escalation fields: resume_token + route_ref
    const escalationTypes: Set<string> = new Set([DecisionType.REQUIRE_APPROVAL, DecisionType.PAUSE, DecisionType.ESCALATE]);
    let resumeToken: string | undefined;
    let routeRef: string | undefined;
    if (escalationTypes.has(decisionType)) {
      resumeToken = `rtk_${randomUUID().replace(/-/g, '')}`;
      if (matchedRuleObj?.route) {
        routeRef = matchedRuleObj.route;
      }
    } else if (decisionType === DecisionType.ROUTE && matchedRuleObj?.route) {
      routeRef = matchedRuleObj.route; // the sync route the rule asks (decision_response.md 1.7)
    }

    const decision: Decision = {
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
      staged_observations: stagedField,
      rate_limit_rules: rateLimitRules,
      missing_fields: missingFields.length > 0 ? missingFields : undefined,
    };
    // Per-rule observe (the old `mode: "observe"` field) is `lifecycle_stage: "staged"` — staged rules never bind
    // (Block 1B). So the only path to OBSERVE here is the global OBSERVE_ALL toggle.
    return mode === 'OBSERVE_ALL' ? observe(decision) : decision;
  }

  /**
   * Evaluate all rules in a policy set (Block 5a — full parity port).
   *
   * **Side-by-side evaluation (Block 1B / 9b):** Active and staged rules
   * walk the priority-sorted list together in a single pass.
   *
   * - Active rules contend for the binding decision (first match in
   *   precedence order wins: DENY wins, then priority, then definition
   *   order — policy_format.md "Rule Precedence"; R-0846).
   * - Staged rules contend in parallel for a *would-be* decision; every
   *   staged match is recorded as a `StagedObservation`. The first
   *   staged match in the same order is flagged `would_be_binding=true`.
   * - `draft`, `disabled`, and `archived` rules are skipped entirely.
   *
   * **Per-rule gates (applied identically to active and staged rules):**
   * 1. Lifecycle stage filter (above)
   * 2. Temporal validity — skip if envelope time is outside
   *    `[valid_from, valid_to]`
   * 3. Scope whitelist — `scope.agents`, `scope.users`,
   *    `scope.environments` must include the envelope's value if set
   * 4. Percentage rollout — deterministic SHA-256 hash of a configurable
   *    envelope field (default `action_id`) into a bucket [0,100); rule
   *    applies if bucket < `scope.percentage`
   * 5. Conditions — most expensive, run last after cheap filters pass
   *
   * Staging means "behave as active for observation purposes," NOT
   * "ignore filters." Filters apply equally.
   *
   * A rule whose outcome an envelope path the call does not carry leaves
   * open (policy_format.md "A field the call does not carry") is read by
   * its set's `on_missing`. Under `skip`, the default, it reads as today
   * and is named in `missing_fields`; so is any such rule in observe mode
   * or in the staged lane. Under `fail_closed` an active one decides BLOCK
   * (MISSING_FIELD) at its own priority and place — the BLOCK class (DENY
   * wins) — so the walk reads every active rule that could still bind
   * below the binding key.
   *
   * @param envelope - Validated execution envelope
   * @param policy - Validated policy set
   * @param mode - OBSERVE_ALL reads `fail_closed` as `skip` ("In observe
   *   mode: skip the policy, flag it")
   * @returns Tuple of [decision type, reason codes, matched rules,
   *   matched rule object, staged observations, rate-limit rules, the
   *   missing-field BLOCK's remediation, missing fields]
   *
   * @private
   */
  private evaluateRules(
    envelope: Envelope,
    policy: PolicySet,
    mode: 'OBSERVE_ALL' | 'RESPECT_POLICY' = 'RESPECT_POLICY'
  ): [
    DecisionType,
    string[],
    MatchedRule[],
    Rule | undefined,
    StagedObservation[],
    RateLimitRule[],
    Remediation | undefined,
    MissingField[],
  ] {
    const failClosed = policy.on_missing === 'fail_closed' && mode !== 'OBSERVE_ALL';
    // Precedence order — DENY wins (policy_format.md "Rule Precedence";
    // R-0846): (class, -priority, definition order), KILL_SWITCH then BLOCK
    // then every other decision. Copy to avoid mutating the policy.
    const keyedRules = policy.rules
      .map((rule, i): [Key, Rule] => [keyOf(rule, i), rule])
      .sort((a, b) => (before(a[0], b[0]) ? -1 : before(b[0], a[0]) ? 1 : 0));

    let bindingResult:
      | [DecisionType, string[], MatchedRule[], Rule | undefined, Remediation | undefined]
      | undefined;
    let bindingKey: Key | undefined;
    const missingFields: MissingField[] = [];
    const stagedObservations: StagedObservation[] = [];
    const rateLimitRules: RateLimitRule[] = [];
    let stagedBindingSeen = false;
    const now = Date.now();

    for (const [key, rule] of keyedRules) {
      const stage = rule.lifecycle_stage ?? 'active';

      // Skip lifecycle stages that don't participate in either lane
      // (draft / disabled / archived).
      if (stage !== 'active' && stage !== 'staged') {
        continue;
      }
      // A rule carrying the uncalibrated placeholder never matches
      // (policy_format.md "Uncalibrated bounds").
      if (hasPlaceholder(rule.conditions) || hasPlaceholder(rule.rate_limit)) {
        continue;
      }
      // A ROUTE rule whose route has answered in this evaluation does not match again (policy_format.md 2.7)
      if (rule.route && rule.decision === DecisionType.ROUTE && Object.hasOwn(this.enrichment, rule.route)) {
        continue;
      }
      // A windowed RATE_LIMIT rule meters, never binds (R-0852).
      const meters = rule.decision === DecisionType.RATE_LIMIT && rule.rate_limit !== undefined;

      // Active short-circuit: once we've bound an active decision, the
      // only reason to keep walking is to capture lower-priority staged
      // matches. Stop evaluating remaining active rules — except, under
      // fail_closed, one whose missing-field BLOCK would bind below the
      // binding key.
      const reach = failClosed && before(asBlock(key), key) ? asBlock(key) : key;
      if (bindingKey !== undefined && stage === 'active' && !meters && !before(reach, bindingKey)) {
        continue;
      }

      // Temporal validity. Each is the written RFC 3339 date-time the schema took, read to the instant it writes
      // (date-time.ts).
      if (rule.valid_from !== undefined && now < readDateTime(rule.valid_from)) {
        continue;
      }
      if (rule.valid_to !== undefined && now > readDateTime(rule.valid_to)) {
        continue;
      }

      // Scope filters: agents / users / environments whitelists +
      // percentage rollout (whitelists are evaluated together since
      // both live on rule.scope).
      if (rule.scope !== undefined) {
        if (!this.ruleInScope(envelope, rule.scope)) {
          continue;
        }
        if (!this.rulePassesPercentage(envelope, rule.scope)) {
          continue;
        }
      }

      // Match conditions (most expensive — only run after cheap filters pass).
      const [matched, unread] = this.evaluateCondition(envelope, rule.conditions);
      if (unread.length > 0 && failClosed && stage === 'active') {
        if (bindingKey === undefined || before(asBlock(key), bindingKey)) {
          bindingResult = [
            DecisionType.BLOCK,
            ['MISSING_FIELD'],
            [{ rule_name: rule.name, policy_set: policy.name, priority: rule.priority }],
            undefined,
            unreadRemediation(rule.name, policy.name, unread),
          ];
          bindingKey = asBlock(key);
        }
        continue;
      }
      for (const field of unread) missingFields.push({ rule_name: rule.name, policy_set: policy.name, field });
      if (!matched) {
        continue;
      }

      if (stage === 'active' && meters) {
        const rl = rule.rate_limit!;
        rateLimitRules.push({
          rule_name: rule.name,
          policy_set: policy.name,
          priority: rule.priority,
          reason_code: rule.reason_code,
          limit: rl.limit as number,
          window_seconds: rl.window_seconds as number,
          scope: rl.scope,
          remediation: rule.remediation ? this.resolveRemediation(envelope, rule.remediation) : undefined,
        });
        continue;
      }

      if (stage === 'active') {
        if (bindingKey !== undefined && !before(key, bindingKey)) {
          continue; // read for a missing-field BLOCK below the binding key; it matched above it
        }
        const matchedRule: MatchedRule = {
          rule_name: rule.name,
          policy_set: policy.name,
          priority: rule.priority,
        };
        bindingResult = [rule.decision, [rule.reason_code], [matchedRule], rule, undefined];
        bindingKey = key;
        // Don't break — keep walking so lower-priority staged rules
        // get recorded as observations.
        continue;
      }

      // stage === 'staged'
      stagedObservations.push({
        rule_name: rule.name,
        policy_set: policy.name,
        priority: rule.priority,
        would_be_decision: rule.decision,
        would_be_reason_codes: [rule.reason_code],
        would_be_binding: !stagedBindingSeen && !meters,
      });
      stagedBindingSeen = stagedBindingSeen || !meters;
    }

    if (bindingResult !== undefined) {
      const [decisionType, reasonCodes, matchedRules, matchedRuleObj, unreadRem] = bindingResult;
      return [
        decisionType,
        reasonCodes,
        matchedRules,
        matchedRuleObj,
        stagedObservations,
        rateLimitRules,
        unreadRem,
        missingFields,
      ];
    }

    // Safe-by-default: no active rule matched → BLOCK. Staged
    // observations still flow through so the regression report can
    // show what staged rules would have done.
    return [
      DecisionType.BLOCK,
      ['NO_MATCHING_RULE'],
      [],
      undefined,
      stagedObservations,
      rateLimitRules,
      undefined,
      missingFields,
    ];
  }

  /**
   * Check whether an envelope passes a rule's scope whitelists.
   *
   * Each whitelist is independent: if `scope.agents` is set, the
   * envelope's `agent_id` must appear in it. If a field is unset on
   * the scope, it doesn't constrain anything. All set fields must
   * pass (AND semantics).
   *
   * @private
   */
  private ruleInScope(envelope: Envelope, scope: RuleScope): boolean {
    if (scope.environments !== undefined) {
      if (!scope.environments.includes(envelope.environment)) {
        return false;
      }
    }
    if (scope.agents !== undefined) {
      if (!scope.agents.includes(envelope.agent_id)) {
        return false;
      }
    }
    if (scope.users !== undefined) {
      // The envelope schema marks user_id optional. Treat a missing
      // user_id as failing a user whitelist — a rule scoped to specific
      // users should NOT fire on envelopes without one.
      const userId = (envelope as Envelope & { user_id?: string }).user_id;
      if (userId === undefined || !scope.users.includes(userId)) {
        return false;
      }
    }
    return true;
  }

  /**
   * Deterministic percentage rollout check.
   *
   * Hashes a configurable envelope field (default: `action_id`) with
   * SHA-256, truncates to 32 bits, mods 100 to produce a bucket in
   * [0,100). Rule applies iff bucket < `scope.percentage`.
   *
   * Determinism guarantee: the same envelope re-evaluated against the
   * same rule always lands in the same bucket — so retries don't flip
   * the decision.
   *
   * If `scope.percentage` is unset, ≥100, or ≤0, the function
   * short-circuits without hashing. Missing hash field returns false
   * (safe default: don't apply the rule).
   *
   * @private
   */
  private rulePassesPercentage(envelope: Envelope, scope: RuleScope): boolean {
    const pct = scope.percentage;
    if (pct === undefined || pct >= 100) {
      return true;
    }
    if (pct <= 0) {
      return false;
    }

    const hashField = scope.rollout_hash_field ?? 'action_id';
    // a field the envelope holds as data (policy_format.md 2.17)
    const fieldValue = Object.hasOwn(envelope, hashField)
      ? (envelope as unknown as Record<string, unknown>)[hashField] : undefined;
    if (fieldValue === undefined || fieldValue === null) {
      // Safe default: rule scope wanted a specific field that the
      // envelope doesn't have. Skip the rule rather than guess.
      return false;
    }

    const digest = createHash('sha256').update(String(fieldValue), 'utf-8').digest();
    // Match Python: int.from_bytes(digest[:4], "big") → uint32 big-endian.
    // readUInt32BE is exactly that.
    const intVal = digest.readUInt32BE(0);
    const bucket = intVal % 100;
    return bucket < pct;
  }

  /**
   * Evaluate a condition (atomic or logical).
   *
   * This method discriminates between atomic and logical conditions
   * using type discrimination on the 'field' property.
   *
   * @param envelope - Validated execution envelope
   * @param condition - Condition to evaluate (atomic or logical)
   * @returns Whether the condition matches, read as today (an absent field
   *   makes a condition false, `exists` excepted), and the envelope paths
   *   the call does not carry that leave its outcome open — empty when the
   *   fields the call carries decide it (policy_format.md "A field the call
   *   does not carry")
   *
   * @private
   */
  private evaluateCondition(envelope: Envelope, condition: Condition | LogicalCondition): [boolean, string[]] {
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
   * A child the call's fields decide settles the parent the way the
   * operator does: `all_of` by a false child, `any_of` and `none_of` by a
   * true one. Otherwise a child left open leaves the parent open, with each
   * open child's paths.
   *
   * @param envelope - Validated execution envelope
   * @param condition - Logical condition
   * @returns [matches, the paths that leave it open], as evaluateCondition
   *
   * @private
   */
  private evaluateLogicalCondition(envelope: Envelope, condition: LogicalCondition): [boolean, string[]] {
    let children: Array<Condition | LogicalCondition>;
    let settles: boolean;
    if (condition.all_of) {
      [children, settles] = [condition.all_of, false]; // AND: all conditions must be true
    } else if (condition.any_of) {
      [children, settles] = [condition.any_of, true]; // OR: at least one must be true
    } else if (condition.none_of) {
      [children, settles] = [condition.none_of, true]; // NOT: none may be true
    } else {
      // Should never happen due to Zod validation (exactly one operator must be set)
      throw new Error('Logical condition must have all_of, any_of, or none_of');
    }

    let values: boolean[] = [];
    let unread: string[] = [];
    let failures: OperatorKindError[] = [];
    for (const c of children) {
      let value: boolean, paths: string[];
      try { [value, paths] = this.evaluateCondition(envelope, c); }
      catch (error) { if (!(error instanceof OperatorKindError)) throw error; failures.push(error); continue; }
      if (value === settles && paths.length === 0) {
        [values, unread, failures] = [[value], [], []];
        break;
      }
      values.push(value);
      unread = [...unread, ...paths.filter((p) => !unread.includes(p))];
    }
    if (failures.length) throw failures.sort(compareOperatorFailures)[0];
    if (condition.all_of) return [values.every(Boolean), unread];
    return [condition.any_of ? values.some(Boolean) : !values.some(Boolean), unread];
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
   * A comparison on an envelope path the call does not carry is left open,
   * `exists` excepted (it reads the absence); `external.*` is the enrichment
   * context beside the envelope, never counted (policy_format.md 2.7).
   *
   * @param envelope - Validated execution envelope
   * @param condition - Atomic condition with field, operator, and value
   * @returns [matches, the paths that leave it open], as evaluateCondition
   *
   * @private
   */
  private evaluateAtomicCondition(
    envelope: Envelope,
    condition: Condition & { field: string }
  ): [boolean, string[]] {
    // Step 1: Resolve field path (e.g., "parameters.amount" → 1000)
    const fieldValue = this.resolve(envelope, condition.field);
    const unread =
      fieldValue == null && condition.operator !== 'exists' && inEnvelope(condition.field) ? [condition.field] : [];

    // A field reference as the value resolves against the same envelope (policy_format.md 2.6); one that resolves to
    // nothing makes the condition false, like an absent field
    let compareValue = condition.value;
    const ref = fieldRef(compareValue);
    if (typeof ref === 'string') {
      compareValue = this.resolve(envelope, ref);
      if (compareValue == null) {
        return [false, inEnvelope(ref) && !unread.includes(ref) ? [...unread, ref] : unread];
      }
    }

    // Step 2: Evaluate operator (handles null values internally)
    try { return [evaluateOperator(fieldValue, condition.operator, compareValue), unread]; }
    catch (error) {
      if (!(error instanceof OperatorKindError)) throw error;
      throw new OperatorKindError(condition.operator, condition.field, typeof ref === 'string' ? ref : undefined, error.requirement);
    }
  }

  /**
   * A rule's remediation, each detail that states a fact of the call computed from the call (policy_format.md
   * **Remediation on Rules**, the table; R-0059); every other field as written. Mirrors evaluator.py.
   */
  private resolveRemediation(envelope: Envelope, rem: Remediation): Remediation {
    const details: Record<string, any> = { ...(rem.details ?? {}) };
    const bf = details.blocked_fields;
    if (rem.type === 'field_restriction' && bf && typeof bf === 'object' && !Array.isArray(bf)) {
      const found = this.resolve(envelope, bf.ref);
      const values: unknown[] = Array.isArray(found) ? found : found === undefined || found === null ? [] : [found];
      const blocked: unknown[] = [];
      for (const v of values) {
        if (bf.filter.includes(v) && !blocked.includes(v)) blocked.push(v);
      }
      details.blocked_fields = blocked;
      details.field_ref = bf.ref;
    } else if (rem.type === 'threshold' && 'field' in details) {
      const value = this.resolve(envelope, details.field);
      if (value === undefined || value === null) delete details.current_value;
      else details.current_value = value;
    } else if (rem.type === 'temporal') {
      details.current_time = utcMs(envelope.timestamp);
    } else {
      return rem;
    }
    return { ...rem, details };
  }

  /** A path into the envelope, or — under `external.` — into the enrichment context, never the envelope. */
  private resolve(envelope: Envelope, path: string): any {
    if (path === ENRICHMENT_ROOT || path.startsWith(`${ENRICHMENT_ROOT}.`)) {
      return resolveFieldPath(this.enrichment, path.slice(ENRICHMENT_ROOT.length + 1));
    }
    return resolveFieldPath(envelope, path);
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
  mode: 'OBSERVE_ALL' | 'RESPECT_POLICY' = 'RESPECT_POLICY',
  enrichment?: Enrichment | null
): Decision {
  const evaluator = new PolicyEvaluator();
  return evaluator.evaluate(envelope, policy, mode, enrichment);
}

/**
 * The kill switches the version makes live, by name, sorted: each `KILL_SWITCH` rule the evaluator binds, the
 * `active` stage carrying no placeholder (sync_engine.md 2.4; HTL-29 row 131). The service's tick returns them and
 * builds its `policy_set` from them, and an SDK names them in its logs; the version decides, never the list. Mirrors
 * python/hiitl/core/evaluator.py live_kill_switches.
 */
export function liveKillSwitches(policy: PolicySet): string[] {
  return policy.rules
    .filter((rule) => rule.decision === 'KILL_SWITCH' && (rule.lifecycle_stage ?? 'active') === 'active'
      && !hasPlaceholder(rule.conditions) && !hasPlaceholder(rule.rate_limit))
    .map((rule) => rule.name)
    .sort();
}
