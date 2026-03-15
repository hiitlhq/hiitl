/**
 * Core types for HIITL policy evaluation (TypeScript implementation).
 *
 * These types are derived from the language-neutral specifications:
 * - envelope_schema.json
 * - policy_format.md
 * - decision_response.md
 *
 * Uses Zod for runtime validation and TypeScript type inference.
 */

import { z } from 'zod';

// ============================================================================
// Enums
// ============================================================================

/**
 * Environment enumeration.
 */
export const Environment = {
  DEV: 'dev',
  STAGE: 'stage',
  PROD: 'prod',
} as const;

export type Environment = typeof Environment[keyof typeof Environment];

/**
 * CRUD operation types.
 */
export const Operation = {
  READ: 'read',
  WRITE: 'write',
  CREATE: 'create',
  DELETE: 'delete',
  EXECUTE: 'execute',
  UPDATE: 'update',
} as const;

export type Operation = typeof Operation[keyof typeof Operation];

/**
 * Sensitivity classifications.
 */
export const Sensitivity = {
  MONEY: 'money',
  IDENTITY: 'identity',
  PERMISSIONS: 'permissions',
  REGULATED: 'regulated',
  IRREVERSIBLE: 'irreversible',
  PII: 'pii',
  SENSITIVE_DATA: 'sensitive_data',
} as const;

export type Sensitivity = typeof Sensitivity[keyof typeof Sensitivity];

/**
 * Valid decision outcomes.
 */
export const DecisionType = {
  ALLOW: 'ALLOW',
  OBSERVE: 'OBSERVE',
  BLOCK: 'BLOCK',
  PAUSE: 'PAUSE',
  REQUIRE_APPROVAL: 'REQUIRE_APPROVAL',
  SANDBOX: 'SANDBOX',
  RATE_LIMIT: 'RATE_LIMIT',
  KILL_SWITCH: 'KILL_SWITCH',
  ESCALATE: 'ESCALATE',
  ROUTE: 'ROUTE',
  SIGNATURE_INVALID: 'SIGNATURE_INVALID',
  CONTROL_PLANE_UNAVAILABLE: 'CONTROL_PLANE_UNAVAILABLE',
} as const;

export type DecisionType = typeof DecisionType[keyof typeof DecisionType];

/**
 * Condition comparison operators.
 */
export const ConditionOperator = {
  // Equality
  EQUALS: 'equals',
  NOT_EQUALS: 'not_equals',
  // Numeric comparison
  GREATER_THAN: 'greater_than',
  GREATER_THAN_OR_EQUAL: 'greater_than_or_equal',
  LESS_THAN: 'less_than',
  LESS_THAN_OR_EQUAL: 'less_than_or_equal',
  // String/array operations
  CONTAINS: 'contains',
  NOT_CONTAINS: 'not_contains',
  STARTS_WITH: 'starts_with',
  ENDS_WITH: 'ends_with',
  MATCHES: 'matches',
  // Set operations
  IN: 'in',
  NOT_IN: 'not_in',
  // Existence
  EXISTS: 'exists',
} as const;

export type ConditionOperator = typeof ConditionOperator[keyof typeof ConditionOperator];

// ============================================================================
// Zod Schemas for Validation
// ============================================================================

/**
 * Zod schema for Environment enum.
 */
const EnvironmentSchema = z.enum(['dev', 'stage', 'prod']);

/**
 * Zod schema for Operation enum.
 */
const OperationSchema = z.enum(['read', 'write', 'create', 'delete', 'execute', 'update']);

/**
 * Zod schema for Sensitivity enum.
 */
const SensitivitySchema = z.enum([
  'money',
  'identity',
  'permissions',
  'regulated',
  'irreversible',
  'pii',
  'sensitive_data',
]);

/**
 * Zod schema for DecisionType enum.
 */
const DecisionTypeSchema = z.enum([
  'ALLOW',
  'OBSERVE',
  'BLOCK',
  'PAUSE',
  'REQUIRE_APPROVAL',
  'SANDBOX',
  'RATE_LIMIT',
  'KILL_SWITCH',
  'ESCALATE',
  'ROUTE',
  'SIGNATURE_INVALID',
  'CONTROL_PLANE_UNAVAILABLE',
]);

/**
 * Zod schema for ConditionOperator enum.
 */
const ConditionOperatorSchema = z.enum([
  'equals',
  'not_equals',
  'greater_than',
  'greater_than_or_equal',
  'less_than',
  'less_than_or_equal',
  'contains',
  'not_contains',
  'starts_with',
  'ends_with',
  'matches',
  'in',
  'not_in',
  'exists',
]);

// ============================================================================
// Envelope Types (from envelope_schema.json)
// ============================================================================

/**
 * Cost estimate for an action.
 */
export const CostEstimateSchema = z.object({
  tokens: z.number().int().nonnegative().optional(),
  dollars: z.number().nonnegative().optional(),
  api_calls: z.number().int().nonnegative().optional(),
});

export type CostEstimate = z.infer<typeof CostEstimateSchema>;

/**
 * Execution envelope - normalized action representation.
 *
 * Source of truth: specs/envelope_schema.json
 */
const EnvelopeSchemaInner = z.object({
  // Required fields
  schema_version: z.string().regex(/^v[0-9]+\.[0-9]+$/),
  org_id: z.string().regex(/^org_[a-zA-Z0-9]{16,}$/),
  environment: EnvironmentSchema,
  agent_id: z.string().min(1).max(128),
  action_id: z.string().regex(/^act_[a-zA-Z0-9]{20,}$/),
  idempotency_key: z.string().min(1).max(255),
  action: z.string().min(1).max(128),
  timestamp: z.string().datetime(), // ISO 8601 datetime string
  signature: z.string().regex(/^[a-f0-9]{64}$/),

  // Fields with defaults (sparse envelope support)
  operation: OperationSchema.default('execute'),
  target: z.record(z.any()).default({}),
  parameters: z.record(z.any()).default({}),

  // Optional fields
  agent_instance_id: z.string().min(1).max(128).optional(),
  user_id: z.string().min(1).max(128).optional(),
  session_id: z.string().min(1).max(128).optional(),
  correlation_id: z.string().min(1).max(128).optional(),
  trace_id: z.string().min(1).max(128).optional(),
  action_type: z.string().min(1).max(128).optional(),
  sensitivity: z.array(SensitivitySchema).optional(),
  cost_estimate: CostEstimateSchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  requested_scopes: z.array(z.string()).optional(),
  reason: z.string().max(500).optional(),
  prompt_hash: z.string().min(1).max(128).optional(),
  policy_refs: z.array(z.string()).optional(),
  signature_version: z.string().optional().default('hmac-sha256-v1'),
  metadata: z.record(z.any()).optional(),
});

/**
 * Envelope schema with backward compatibility for tool_name → action.
 */
export const EnvelopeSchema = z.preprocess(
  (data) => {
    if (data && typeof data === 'object' && 'tool_name' in data && !('action' in data)) {
      const { tool_name, ...rest } = data as Record<string, unknown>;
      return { ...rest, action: tool_name };
    }
    return data;
  },
  EnvelopeSchemaInner
);

export type Envelope = z.infer<typeof EnvelopeSchemaInner>;

// ============================================================================
// Policy Types (from policy_format.md)
// ============================================================================

/**
 * Atomic condition - field comparison.
 */
export const ConditionSchema = z.object({
  field: z.string(),
  operator: ConditionOperatorSchema,
  value: z.any(),
});

export type Condition = z.infer<typeof ConditionSchema>;

/**
 * Logical condition - combines multiple conditions.
 *
 * Supports:
 * - all_of (AND)
 * - any_of (OR)
 * - none_of (NOT)
 */
export interface LogicalCondition {
  all_of?: Array<Condition | LogicalCondition>;
  any_of?: Array<Condition | LogicalCondition>;
  none_of?: Array<Condition | LogicalCondition>;
}

/**
 * Zod schema for LogicalCondition (recursive).
 */
export const LogicalConditionSchema: z.ZodType<LogicalCondition> = z
  .object({
    all_of: z.lazy(() => z.array(z.union([ConditionSchema, LogicalConditionSchema]))).optional(),
    any_of: z.lazy(() => z.array(z.union([ConditionSchema, LogicalConditionSchema]))).optional(),
    none_of: z.lazy(() => z.array(z.union([ConditionSchema, LogicalConditionSchema]))).optional(),
  })
  .refine(
    (data) => {
      const setOps = [data.all_of, data.any_of, data.none_of].filter((op) => op !== undefined);
      return setOps.length === 1;
    },
    { message: 'Exactly one of all_of, any_of, or none_of must be set' }
  );

/**
 * Union of Condition and LogicalCondition.
 */
export const ConditionUnionSchema = z.union([ConditionSchema, LogicalConditionSchema]);

export type ConditionUnion = Condition | LogicalCondition;

/**
 * Remediation type — determines the structure of remediation.details.
 *
 * Source of truth: docs/specs/decision_response.md (Remediation Types section)
 */
export const RemediationType = {
  FIELD_RESTRICTION: 'field_restriction',
  THRESHOLD: 'threshold',
  SCOPE: 'scope',
  RATE_LIMIT: 'rate_limit',
  TEMPORAL: 'temporal',
  CUSTOM: 'custom',
} as const;

export const RemediationTypeSchema = z.enum([
  'field_restriction',
  'threshold',
  'scope',
  'rate_limit',
  'temporal',
  'custom',
]);

/**
 * Structured remediation guidance for BLOCK/RATE_LIMIT decisions.
 *
 * Present when ECP successfully enforced a policy (not when ECP itself failed).
 * Mutually exclusive with error on Decision.
 *
 * Source of truth: docs/specs/decision_response.md (Remediation Types section)
 */
export const RemediationSchema = z.object({
  message: z.string(), // Human-readable explanation
  suggestion: z.string(), // Actionable next step
  type: RemediationTypeSchema,
  details: z.record(z.any()).optional(), // Type-specific structured fields
});

export type Remediation = z.infer<typeof RemediationSchema>;

/**
 * Policy rule - atomic unit of policy.
 *
 * Source of truth: docs/specs/policy_format.md
 */
export const RuleSchema = z.object({
  name: z.string(),
  description: z.string(),
  enabled: z.boolean(),
  priority: z.number().int(),
  conditions: ConditionUnionSchema,
  decision: DecisionTypeSchema,
  reason_code: z.string(),
  route: z.string().optional(), // Route config name for escalation decisions
  remediation: z.lazy(() => RemediationSchema).optional(), // Guidance when this rule blocks
  metadata: z.record(z.any()).optional(),
  mode: z.enum(['observe', 'enforce']).default('enforce'),
});

export type Rule = z.infer<typeof RuleSchema>;

/**
 * Policy set - collection of rules.
 *
 * Source of truth: docs/specs/policy_format.md
 */
export const PolicySetSchema = z.object({
  name: z.string(),
  version: z.string(),
  description: z.string().optional(),
  scope: z.record(z.string()).optional(),
  rules: z.array(RuleSchema),
  metadata: z.record(z.any()).optional(),
});

export type PolicySet = z.infer<typeof PolicySetSchema>;

// ============================================================================
// Decision Response Types (from decision_response.md)
// ============================================================================

/**
 * Timing metadata for transparency.
 */
export const TimingSchema = z.object({
  ingest_ms: z.number(),
  evaluation_ms: z.number(),
  total_ms: z.number(),
});

export type Timing = z.infer<typeof TimingSchema>;

/**
 * Rate limit state.
 */
export const RateLimitSchema = z.object({
  scope: z.string(),
  window: z.string(),
  limit: z.number().int(),
  current: z.number().int(),
  reset_at: z.string().datetime(),
});

export type RateLimit = z.infer<typeof RateLimitSchema>;

/**
 * Approval workflow metadata.
 */
export const ApprovalMetadataSchema = z.object({
  approval_id: z.string(),
  sla_hours: z.number().optional(),
  reviewer_role: z.string().optional(),
  resume_url: z.string().optional(),
});

export type ApprovalMetadata = z.infer<typeof ApprovalMetadataSchema>;

/**
 * Sandbox routing metadata.
 */
export const SandboxMetadataSchema = z.object({
  sandbox_endpoint: z.string(),
  sandbox_environment: z.string().optional(),
});

export type SandboxMetadata = z.infer<typeof SandboxMetadataSchema>;

/**
 * Rule that matched during evaluation.
 */
export const MatchedRuleSchema = z.object({
  rule_name: z.string(),
  policy_set: z.string(),
  priority: z.number().int(),
});

export type MatchedRule = z.infer<typeof MatchedRuleSchema>;

/**
 * Error details for failed evaluations.
 *
 * Per decision_response.md spec:
 * Errors must include both machine-readable codes and human-readable messages
 * to provide helpful guidance to developers.
 */
export const ErrorDetailSchema = z.object({
  code: z.string(), // Machine-readable error code
  message: z.string(), // Human-readable explanation
});

export type ErrorDetail = z.infer<typeof ErrorDetailSchema>;

/**
 * Decision response after policy evaluation.
 *
 * Source of truth: docs/specs/decision_response.md
 */
export const DecisionSchema = z.object({
  action_id: z.string(),
  decision: DecisionTypeSchema,
  allowed: z.boolean(),
  reason_codes: z.array(z.string()),
  policy_version: z.string(),
  timing: TimingSchema,
  matched_rules: z.array(MatchedRuleSchema).optional(),
  rate_limit: RateLimitSchema.optional(),
  approval_metadata: ApprovalMetadataSchema.optional(),
  sandbox_metadata: SandboxMetadataSchema.optional(),
  resume_token: z.string().optional(), // Token to correlate escalation with reviewer response
  route_ref: z.string().optional(), // Route artifact name from matched rule
  escalation_context: z.record(z.any()).optional(), // Populated by SDK/server, not evaluator
  error: ErrorDetailSchema.optional(),
  remediation: RemediationSchema.optional(), // Guidance for BLOCK/RATE_LIMIT decisions
  would_be: z.string().optional(), // Original decision type when in OBSERVE mode
  would_be_reason_codes: z.array(z.string()).optional(), // Original reason codes when in OBSERVE mode
}).refine(
  (d) => !(d.error && d.remediation),
  {
    message:
      "Decision cannot have both 'error' and 'remediation'. " +
      "'error' indicates ECP failure; 'remediation' indicates intentional policy enforcement.",
  }
);

export type Decision = z.infer<typeof DecisionSchema>;
