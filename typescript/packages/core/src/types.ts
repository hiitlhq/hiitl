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
import { assertPolicyValues, PolicyValueError } from './policy-values.js';
import { enumRefusal } from './enum-refusal.js';
import { integer } from './integer.js';
import { compileSetLimits } from './rate-limits.js';
import { DateTimeSchema } from './date-time.js';
import { dataRecord, dataObject, checkMembers, numericInput, declaredMemberShape } from './own-data.js';

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
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  POLICY_ERROR: 'POLICY_ERROR',
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
  // Schema conformance (policy_format.md 2.6 "Parameter schema") — never a regex
  CONFORMS_TO: 'conforms_to',
} as const;

export type ConditionOperator = typeof ConditionOperator[keyof typeof ConditionOperator];

// ============================================================================
// Zod Schemas for Validation
// ============================================================================

/**
 * Zod schema for Environment enum.
 */
const EnvironmentSchema = z.enum(['dev', 'stage', 'prod'], { error: enumRefusal });

/**
 * The organisation id's form, as envelope_schema.json states it: one pattern, read by the envelope, a route's scope and
 * the SDK's configuration (sync_engine.md §8: "sync requests can only read/write data for the `org_id` associated with
 * the `api_key`", so the SDK takes every id the service mints).
 */
export const ORG_ID_PATTERN = /^org_[a-zA-Z0-9]{16,}$/;

/**
 * A version's form (policy_format.md's Policy Set Fields and Version Requirements; routes.md): semver,
 * `v{major}.{minor}.{patch}`. One pattern, read by a policy set and a route.
 */
export const VERSION_PATTERN = /^v\d+\.\d+\.\d+$/;

/**
 * The dedup window's default (the security architecture §1.3: "The dedup window is configurable (default: 24
 * hours)"), read by each SDK's local store: a repeated idempotency key within it returns the first decision
 * (row 143).
 */
export const DEDUP_WINDOW_SECONDS = 24 * 60 * 60;

/**
 * The envelope schema's version (envelope_schema.json `$id`, `schema_version`): one fact, read by the SDK's builder.
 * The schema takes this major only and refuses another, naming the version read, this one and the migration note, a
 * heading of the envelope's docs page (R-0007: "Migration path documented before breaking changes"; no acceptance
 * window, ruled 2026-11-07, row 223).
 */
export const ENVELOPE_SCHEMA_VERSION = 'v2.0';
export const ENVELOPE_MIGRATION_NOTE = 'Migrating from schema 1.x';

/**
 * Each field the envelope schema renamed, old name to new (envelope_schema.json 1.1: "Renamed tool_name to action").
 * An old name has no alias from 2.0 (gap row 225, ruled 2026-11-08): it is refused as any field the schema does not
 * define is, and the refusal names the field it became.
 */
export const ENVELOPE_RENAMED: Readonly<Record<string, string>> = { tool_name: 'action' };

/** The refusal's words for a field the schema renamed. */
export function renamedNote(old: string): string {
  const renamed = ENVELOPE_RENAMED[old];
  return `${old} is a field the envelope schema does not define: the schema renamed it ${renamed}, with no alias from ` +
    `2.0. Send ${renamed}.`;
}

const major = (version: string): string => version.split('.')[0];

/**
 * Zod schema for Operation enum.
 */
const OperationSchema = z.enum(['read', 'write', 'create', 'delete', 'execute', 'update'], { error: enumRefusal });

/**
 * Zod schema for Sensitivity enum.
 */
export const SensitivitySchema = z.enum([
  'money',
  'identity',
  'permissions',
  'regulated',
  'irreversible',
  'pii',
  'sensitive_data',
], { error: enumRefusal });

/**
 * Zod schema for DecisionType enum.
 */
export const DecisionTypeSchema = z.enum([
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
  'VALIDATION_ERROR',
  'POLICY_ERROR',
], { error: enumRefusal });

/**
 * The decisions a rule never writes, each with who produces it (policy_format.md 2.10 "Valid Decisions";
 * decision_response.md "Error Decisions"). A rule writes every other decision. Mirrors types.py.
 */
export const PRODUCED_DECISIONS: Partial<Record<z.infer<typeof DecisionTypeSchema>, string>> = {
  OBSERVE: "the evaluator's own in observe mode; a rule that observes without enforcing is `lifecycle_stage: staged`",
  SIGNATURE_INVALID: "the control point's, when an envelope's signature does not verify",
  CONTROL_PLANE_UNAVAILABLE: "the hosted client's, when the hosted service cannot be reached and its fail mode applies",
  VALIDATION_ERROR: "the control point's, when an envelope fails validation",
  POLICY_ERROR: "the control point's, when the policy cannot be loaded, parsed or evaluated",
};

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
  'conforms_to',
], { error: enumRefusal });

// ============================================================================
// Envelope Types (from envelope_schema.json)
// ============================================================================

/**
 * Cost estimate for an action (envelope_schema.json v1.4: closed; `tokens` a number).
 */
export const CostEstimateSchema = z
  .object({
    tokens: z.number().nonnegative().optional(),
    dollars: z.number().nonnegative().optional(),
    api_calls: integer().nonnegative().optional(),
  })
  .strict();

export type CostEstimate = z.infer<typeof CostEstimateSchema>;

/**
 * Execution envelope - normalized action representation.
 *
 * Source of truth: docs/specs/envelope_schema.json
 */
/**
 * The verified principal (envelope_schema.json v1.2 `principal`):
 * subject and scopes of a token a verifier
 * checked. Set only by a verifier; never a free value.
 */
export const PrincipalSchema = z
  .object({
    sub: z.string().min(1).max(256),
    scopes: z.array(z.string()).optional(),
    iss: z.string().optional(),
    aud: z.string().optional(),
    verified_by: z.enum(['sdk_verifier', 'mcp_proxy', 'hosted'], { error: enumRefusal }),
    verified_at: DateTimeSchema.optional(),
  })
  .strict();
export type Principal = z.infer<typeof PrincipalSchema>;

/**
 * The envelope (envelope_schema.json). A field the schema does not define is refused, naming it (R-0872); a renamed
 * one's refusal also names the field it became (ENVELOPE_RENAMED).
 */
const EnvelopeObjectSchema = z.object({
  // Required fields
  schema_version: z
    .string()
    .regex(/^v[0-9]+\.[0-9]+$/)
    .superRefine((v, ctx) => {
      if (major(v) !== major(ENVELOPE_SCHEMA_VERSION)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            `schema_version ${v} is refused: this release takes envelope schema ${ENVELOPE_SCHEMA_VERSION}, and an ` +
            `envelope of another major version is refused, with no acceptance window. Build the envelope at ` +
            `${ENVELOPE_SCHEMA_VERSION}; the envelope's docs page, '${ENVELOPE_MIGRATION_NOTE}', names each change.`,
        });
      }
    }),
  org_id: z.string().regex(ORG_ID_PATTERN),
  environment: EnvironmentSchema,
  agent_id: z.string().min(1).max(128),
  action_id: z.string().regex(/^act_[a-zA-Z0-9]{20,}$/),
  idempotency_key: z.string().min(1).max(255),
  // Preserve the required-action diagnostic alongside the alias-removal guidance (row 225).
  action: z.string({ error: (issue) => issue.input === undefined ? 'Required' : undefined }).min(1).max(128),
  timestamp: DateTimeSchema, // RFC 3339 date-time, read by its grammar (date-time.ts)
  signature: z.string().regex(/^[a-f0-9]{64}$/),

  // Fields with defaults (sparse envelope support)
  operation: OperationSchema.default('execute'),
  target: dataRecord(z.any()).default({}),
  parameters: dataRecord(z.any()).default({}),

  // Optional fields
  agent_instance_id: z.string().min(1).max(128).optional(),
  user_id: z.string().min(1).max(128).optional(),
  session_id: z.string().min(1).max(128).optional(),
  correlation_id: z.string().min(1).max(128).optional(),
  trace_id: z.string().regex(/^[0-9a-f]{32}$/).optional(), // W3C Trace Context's form (schema 1.5, row 210)
  action_type: z.string().min(1).max(128).optional(),
  sensitivity: z.array(SensitivitySchema).optional(),
  cost_estimate: CostEstimateSchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  requested_scopes: z.array(z.string()).optional(),
  principal: PrincipalSchema.optional(), // verified only (A7)
  reason: z.string().max(500).optional(),
  prompt_hash: z.string().min(1).max(128).optional(),
  signature_version: z.enum(['hmac-sha256-v1'], { error: enumRefusal }).optional().default('hmac-sha256-v1'), // the schema's enum (row 206)
  metadata: dataRecord(z.any()).optional(),
}, {
  error: (issue) => {
    if (issue.code !== z.ZodIssueCode.unrecognized_keys) return undefined;
    const renamed = issue.keys.filter((k) => Object.hasOwn(ENVELOPE_RENAMED, k));
    const unknown = `Unrecognized key(s) in object: ${issue.keys.map((k) => `'${k}'`).join(', ')}`;
    return { message: [unknown, ...renamed.map(renamedNote)].join('. ') };
  },
}).strict(); // no field is ever silently dropped (R-0872): a field the schema does not define is refused, naming it

export const EnvelopeSchema = numericInput(EnvelopeObjectSchema);

export type Envelope = z.infer<typeof EnvelopeSchema>;

// ============================================================================
// Policy Types (from policy_format.md)
// ============================================================================

/**
 * Atomic condition - field comparison.
 */
import { literalKindOK, OperatorKindError } from './operator-kinds.js';

const ParameterSchema=z.object({
  type:z.literal('object').optional(),
  properties:dataRecord(z.object({type:z.enum(['string','number','integer','boolean','array','object']).optional()}).strict()).optional(),
  required:z.array(z.string()).optional(),additionalProperties:z.boolean().optional(),
}).strict();


const OperandMembers={
  $field:z.union([z.string(),dataRecord(z.any()).refine(v=>Object.hasOwn(v,'$declared'),{message:'A declared field reference names $declared'}).superRefine((v,c)=>checkMembers(v,{$declared:z.string()},c)).meta({...declaredMemberShape({$declared:z.string()},true),required:['$declared']})]),
  $declared:z.string(),$uncalibrated:z.string(),
};
const operandDeclaration={allOf:Object.entries(OperandMembers).map(([key,schema])=>({if:{required:[key]},then:{...declaredMemberShape({[key]:schema},true)}}))};
const { $schema:_parameterSchemaDialect,...parameterDeclaration }=z.toJSONSchema(ParameterSchema,{io:'input',unrepresentable:'any'});

export const ConditionSchema = z
  .object({
    field: z.string(),
    operator: ConditionOperatorSchema,
    value: z.any().meta(operandDeclaration).optional(),
  })
  .strict() // no field is dropped (policy_format.md; S2)
  .superRefine((c, ctx) => {
    checkOperand(c.value,ctx,['value']);
    // the value is a literal, a typed placeholder, or a field reference; conforms_to takes a parameter schema (2.6)
    const ref = fieldRef(c.value);
    if (ref !== undefined && !(typeof ref === 'string' && ref) && !hasPlaceholder(ref)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: `\`${c.field}\`: a field reference is {"${FIELD_REF_KEY}": "<envelope path>"}` });
    }
    if (c.operator === 'exists' && ref !== undefined) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: `\`${c.field}\`: \`exists\` takes true or false, never a field reference` });
    }
    if (ref === undefined && !hasPlaceholder(c.value) && !literalKindOK(c.operator, c.value)) {
      ctx.addIssue({code: 'custom', path: ['value'], message: new OperatorKindError(c.operator, c.field).message});
    }
    if (c.operator === 'conforms_to' && ref === undefined && !hasPlaceholder(c.value)) {
      const result=ParameterSchema.safeParse(c.value);
      if(!result.success)for(const issue of result.error.issues)ctx.addIssue({...issue,path:['value',...issue.path]});
    }
  }).meta({allOf:[{if:{properties:{operator:{const:'conforms_to'}},required:['operator']},then:{properties:{value:{anyOf:[parameterDeclaration,{...declaredMemberShape({$field:OperandMembers.$field},true),required:['$field']}]}}}}]});

/** A field reference as a condition's value — resolved against the same envelope at evaluation (policy_format.md 2.6). */
export const FIELD_REF_KEY = '$field';
const SCHEMA_TYPES = new Set(['string', 'number', 'integer', 'boolean', 'array', 'object']);


/** The same closed schema grammar is read after a field reference resolves. */
export function parameterSchemaValid(value: unknown): boolean { return ParameterSchema.safeParse(value).success; }

/** Tagged child types are declared; extra reserved-form/literal grammar remains a separate open ruling. */
function checkOperand(value:unknown,ctx:z.RefinementCtx,path:(string|number)[]):void {
  if(value===null || typeof value!=='object' || Array.isArray(value))return;
  for(const [key,item] of Object.entries(value)) {
    const schema=Object.hasOwn(OperandMembers,key)?OperandMembers[key as keyof typeof OperandMembers]:undefined;
    if(schema){const result=schema.safeParse(item);if(!result.success)for(const issue of result.error.issues)ctx.addIssue({...issue,path:[...path,key,...issue.path]});}
  }
}

/** The path a field-reference value names (a string, or a placeholder staff will set), else undefined. */
export function fieldRef(v: unknown): unknown {
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    const keys = Object.keys(v as Record<string, unknown>);
    if (keys.length === 1 && keys[0] === FIELD_REF_KEY) return (v as Record<string, unknown>)[FIELD_REF_KEY];
  }
  return undefined;
}

/** Why `s` is not a parameter schema (policy_format.md 2.6), or null. Mirrors types.py schema_error. */
export function schemaError(s: unknown): string | null {
  if (s === null || typeof s !== 'object' || Array.isArray(s)) return 'a parameter schema is an object';
  const o = s as Record<string, unknown>;
  const extra = Object.keys(o).filter((k) => !['type', 'properties', 'required', 'additionalProperties'].includes(k));
  if (extra.length) return `a parameter schema takes type, properties, required, additionalProperties — not ${extra.sort().join(', ')}`;
  if ((o.type ?? 'object') !== 'object') return "a parameter schema's type is `object`";
  const props = o.properties ?? {};
  if (props === null || typeof props !== 'object' || Array.isArray(props)) return '`properties` maps a name to its schema';
  for (const [name, p] of Object.entries(props as Record<string, unknown>)) {
    const pk = p !== null && typeof p === 'object' && !Array.isArray(p) ? Object.keys(p as object) : null;
    const t = pk ? (p as Record<string, unknown>).type : undefined;
    if (!pk || pk.some((k) => k !== 'type') || (t !== undefined && !SCHEMA_TYPES.has(t as string))) {
      return `property \`${name}\` is {} or {"type": one of ${[...SCHEMA_TYPES].sort().join(', ')}}`;
    }
  }
  const req = o.required ?? [];
  if (!Array.isArray(req) || !req.every((r) => typeof r === 'string')) return '`required` is a list of names';
  if (typeof (o.additionalProperties ?? true) !== 'boolean') return '`additionalProperties` is true or false';
  return null;
}

/** Whether `value` conforms to the parameter schema. Mirrors types.py conforms. */
export function conforms(value: unknown, schema: Record<string, any>): boolean {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  const props: Record<string, { type?: string }> = schema.properties ?? {};
  // a name the value holds as data, never one it inherits (policy_format.md 2.17)
  if ((schema.required ?? []).some((r: string) => !Object.hasOwn(v, r))) return false;
  if (schema.additionalProperties === false && Object.keys(v).some((k) => !Object.hasOwn(props, k))) return false;
  const is: Record<string, (x: unknown) => boolean> = {
    string: (x) => typeof x === 'string', boolean: (x) => typeof x === 'boolean',
    integer: (x) => typeof x === 'number' && Number.isInteger(x), number: (x) => typeof x === 'number',
    array: (x) => Array.isArray(x), object: (x) => x !== null && typeof x === 'object' && !Array.isArray(x),
  };
  return Object.entries(props).every(([k, p]) => p.type === undefined || !Object.hasOwn(v, k) || is[p.type](v[k]));
}

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
  .strict()
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
], { error: enumRefusal });

/**
 * Structured remediation guidance for BLOCK/RATE_LIMIT decisions.
 *
 * Present when ECP successfully enforced a policy (not when ECP itself failed).
 * Mutually exclusive with error on Decision.
 *
 * Source of truth: docs/specs/decision_response.md (Remediation Types section)
 */
/** Supplied details follow their owning subtype table; unlisted/custom data remain open. */
const RemediationDetails={
  field_restriction:dataObject({blocked_fields:z.union([z.array(z.string()),z.object({ref:z.string().min(1),filter:z.array(z.string())}).strict()]),allowed_fields:z.array(z.string()),field_ref:z.string()}),
  threshold:dataObject({threshold:z.number(),current_value:z.number(),max_allowed:z.number(),field:z.string()}),
  scope:dataObject({required_scope:z.string(),current_scope:z.string(),allowed_scopes:z.array(z.string()),scope_type:z.string()}),
  rate_limit:dataObject({limit:integer(),current:integer(),reset_at:DateTimeSchema,scope:z.string(),window:z.string()}),
  temporal:dataObject({allowed_window:dataRecord(z.any()),timezone:z.string(),next_allowed_at:DateTimeSchema,current_time:z.string()}),
  custom:dataRecord(z.any()),
};

export const RemediationSchema = z
  .object({
    message: z.string(), // Human-readable explanation
    suggestion: z.string(), // Actionable next step
    type: RemediationTypeSchema,
    details: dataRecord(z.any()).optional(), // Type-specific structured fields
  })
  .strict()
  .superRefine((rem, ctx) => {
    if(rem.details!==undefined) {
      const result=RemediationDetails[rem.type].safeParse(rem.details);
      if(!result.success)for(const issue of result.error.issues)ctx.addIssue({...issue,path:['details',...issue.path]});
    }
    // A field_restriction's `blocked_fields` is a list, or `{ref, filter}` computed from the call (policy_format.md
    // **Remediation on Rules**); any other shape is refused at load, naming it. Mirrors types.py.
    const bf = rem.type === 'field_restriction' ? rem.details?.blocked_fields : undefined;
    if (bf === undefined || bf === null || Array.isArray(bf)) return;
    const isRefFilter =
      typeof bf === 'object' &&
      Object.keys(bf).sort().join(',') === 'filter,ref' &&
      typeof bf.ref === 'string' && bf.ref.length > 0 &&
      Array.isArray(bf.filter) && bf.filter.every((v: unknown) => typeof v === 'string');
    if (isRefFilter) return;
    const shape = typeof bf === 'object' ? `an object with keys [${Object.keys(bf).sort().map((k) => `'${k}'`).join(', ')}]` : `a ${typeof bf}`;
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['details', 'blocked_fields'],
      message:
        `remediation.details.blocked_fields is ${shape}. A field_restriction's blocked_fields is either a list of ` +
        'field names, copied as written, or {ref, filter}: `ref` the envelope path whose values are checked (a ' +
        'non-empty string), `filter` the list of blocked values (strings), computed from the call (policy_format.md ' +
        '"Remediation on Rules").',
    });
  }).meta({allOf:Object.entries(RemediationDetails).map(([type,schema])=>({
    if:{properties:{type:{const:type}},required:['type']},then:{properties:{details:z.toJSONSchema(schema,{io:'input',unrepresentable:'any'})}},
  }))});

export type Remediation = z.infer<typeof RemediationSchema>;



/**
 * Policy rule - atomic unit of policy.
 *
 * Source of truth: docs/specs/policy_format.md
 */
/**
 * Per-rule lifecycle stage. Replaces the old `enabled` boolean and `mode` field
 * as the single source of truth for whether a rule is evaluated and how it
 * behaves. See docs/specs/policy_format.md.
 */
export const LifecycleStageSchema = z.enum([
  'draft',     // Created, not evaluating yet
  'staged',    // Evaluating against live traffic; "would have" only. Block 1B records observations.
  'active',    // Enforcing. The rule's decision is binding.
  'disabled',  // Explicitly turned off. Visible in UI but skipped by evaluator.
  'archived',  // Was once active, superseded by newer version.
], { error: enumRefusal });
export type LifecycleStage = z.infer<typeof LifecycleStageSchema>;

/**
 * Optional scope filters for a rule. All fields optional; absent = applies to all.
 */
export const RuleScopeSchema = z.object({
  agents: z.array(z.string()).optional(),
  users: z.array(z.string()).optional(),
  environments: z.array(EnvironmentSchema).optional(), // the envelope's environment values (2.10)
  percentage: integer().min(0).max(100).optional(),
  rollout_hash_field: z.string().optional(),
}).strict();
export type RuleScope = z.infer<typeof RuleScopeSchema>;

/** The typed uncalibrated placeholder (policy_format.md "Uncalibrated bounds"). */
export const PLACEHOLDER_KEY = '$uncalibrated';
/** A value only staff can set — declared, never observed (T49; policy_format.md 2.5). */
export const DECLARED_KEY = '$declared';

/** Whether a value carries a typed placeholder anywhere. Mirrors types.py has_placeholder. */
export function hasPlaceholder(x: unknown): boolean {
  if (Array.isArray(x)) return x.some(hasPlaceholder);
  if (x !== null && typeof x === 'object') {
    const o = x as Record<string, unknown>;
    if (Object.hasOwn(o, PLACEHOLDER_KEY) || Object.hasOwn(o, DECLARED_KEY)) return true;
    return Object.values(x as Record<string, unknown>).some(hasPlaceholder);
  }
  return false;
}

const BoundSchema = z.union([
  integer().positive(),
  z.object({ [PLACEHOLDER_KEY]: z.string() }).strict(),
]);

/** The window a RATE_LIMIT rule meters (policy_format.md "Rate-limit rules"; R-0852). */
export const RateLimitWindowSchema = z
  .object({
    limit: BoundSchema,
    window_seconds: BoundSchema,
    scope: z.enum(['action', 'agent', 'user', 'org', 'user_action'], { error: enumRefusal }).default('action'),
  })
  .strict();
export type RateLimitWindow = z.infer<typeof RateLimitWindowSchema>;

/** A test a rule ships with (policy_format.md "Tests shipped with a rule"). */
export const RuleTestSchema = z
  .object({
    envelope: dataRecord(z.any()).superRefine((data,ctx)=>checkMembers(data,EnvelopeObjectSchema.shape,ctx,true,
      key=>Object.hasOwn(ENVELOPE_RENAMED,key) ? renamedNote(key) : undefined)).meta(declaredMemberShape(EnvelopeObjectSchema.shape,true)),
    expect: z.string(),
  })
  .strict();

/** Lineage written by accept. */
export const SuggestedBySchema = z.object({
  suggestion_id: z.string(),
  source: z.string(),
  atom_id: z.string().optional(),
  assessment_id: z.string().optional(),
  action_key: z.string().optional(),
}).strict();

export const RequirementCitationSchema = z.object({
  atom_id: z.string().optional(),
  standard: z.string().optional(),
  regulatory_trigger: z.string().optional(),
  determination: z
    .object({ assessment_id: z.string(), grain: z.string(), action_id: z.string().optional() })
    .strict()
    .optional(),
  prompt: z.object({ file: z.string(), line: integer(), quoted: z.string() }).strict().optional(),
}).strict();

// What a rule's condition reads that the envelope does not yet carry — a promotion gate (policy_format.md 2.3).
export const WaitsOnSchema = z.object({
  kind: z.enum(['verifier', 'envelope_field', 'route', 'hiitl_record'], { error: enumRefusal }), // §K2, §K5′
  target: z.string(),
}).strict();

const RuleObjectSchema = z.object({
  name: z.string(),
  description: z.string(),
  priority: integer(),
  conditions: ConditionUnionSchema,
  decision: DecisionTypeSchema,
  reason_code: z.string(),
  lifecycle_stage: LifecycleStageSchema.default('active'),
  scope: RuleScopeSchema.optional(),
  valid_from: DateTimeSchema.optional(),
  valid_to: DateTimeSchema.optional(),
  observation_window_days: integer().default(7),
  route: z.string().optional(),
  remediation: z.lazy(() => RemediationSchema).optional(),
  metadata: dataRecord(z.any()).optional(),
  rate_limit: RateLimitWindowSchema.optional(), // RATE_LIMIT rules: the window they meter (R-0852)
  tests: z.array(RuleTestSchema).optional(), // shipped tests, run by the lint (C7)
  suggested_by: SuggestedBySchema.optional(), // lineage, written by accept (B2)
  // one citation, or a list when one rule answers several determinations (folded, §K1)
  requirement_citation: z.union([RequirementCitationSchema, z.array(RequirementCitationSchema)]).optional(),
  waits_on: WaitsOnSchema.optional(), // an unmet dependency: a promotion gate (§K2)
});

/**
 * No field is dropped (policy_format.md "No field is dropped"; S2): a field this spec does not define is refused, and
 * the retired `enabled` / `mode` keys are refused naming `lifecycle_stage` — ignoring `enabled: false` ran disabled
 * rules, kill switches among them, live.
 */
export const RuleSchema = z.preprocess((d, ctx) => {
  try { assertPolicyValues(d, "rule"); } catch(error) { if(!(error instanceof PolicyValueError))throw error; for(const path of error.paths)ctx.addIssue({code:"custom",path,message:error.message}); return z.NEVER; }
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    for (const key of ['enabled', 'mode']) {
      if (Object.hasOwn(d, key)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            `rule '${(d as Record<string, unknown>).name}': \`${key}\` was replaced by \`lifecycle_stage\` (draft | staged ` +
            '| active | disabled | archived) — `enabled: false` is `lifecycle_stage: disabled`, `enabled: true` the ' +
            'default `active`, per-rule observe `staged`. The key is refused rather than ignored: ignoring ' +
            '`enabled: false` ran disabled rules, kill switches among them, live.',
        });
      }
    }
  }
  return d;
}, RuleObjectSchema.strict().superRefine((r, ctx) => {
  const produced = PRODUCED_DECISIONS[r.decision];
  if (produced === undefined) return;
  const written = DecisionTypeSchema.options.filter((d) => !Object.hasOwn(PRODUCED_DECISIONS, d)).join(' | ');
  ctx.addIssue({
    code: z.ZodIssueCode.custom,
    path: ['decision'],
    message:
      `rule '${r.name}': decision ${r.decision} is never written in a rule — it is ${produced} (policy_format.md ` +
      `'Valid Decisions'). A rule writes one of ${written}.`,
  });
}));

export type Rule = z.infer<typeof RuleObjectSchema>;

/**
 * Where a policy set applies (policy_format.md "Scope Fields (Schema Support)"): the organisation and environment whose
 * envelopes it governs, each in the envelope's own form, are required; team, project and agent are the schema's further
 * dimensions.
 */
export const PolicySetScopeSchema = z
  .object({
    org_id: z.string().regex(ORG_ID_PATTERN),
    environment: EnvironmentSchema,
    team_id: z.string().optional(),
    project_id: z.string().optional(),
    agent_id: z.string().optional(),
  })
  .strict();

/**
 * Policy set - collection of rules.
 *
 * Source of truth: docs/specs/policy_format.md. Its Policy Set Fields table requires the name, a semver version, a
 * description, the scope and the rules (HTL-22 row 165).
 */
const LegacyRateLimitSchema=z.object({scope:z.string().optional(),window:z.string().optional(),window_seconds:BoundSchema.optional(),limit:BoundSchema.optional()}).strict();
const PolicyMetadataSchema=dataObject({
  author:z.string(),created_at:DateTimeSchema,updated_at:DateTimeSchema,tags:z.array(z.string()),
  intended_use_case:z.string(),target_agent_types:z.array(z.string()),
  template:dataObject({source:z.string(),source_version:z.string(),customizations:z.array(z.string())}),
  display:dataObject({sections:z.array(dataRecord(z.any()))}),compliance_references:z.array(dataRecord(z.any())),grading:dataRecord(z.any()),
  rate_limits:z.array(LegacyRateLimitSchema),
});

const PolicySetObjectSchema = z
  .object({
    name: z.string(),
    version: z.string().regex(VERSION_PATTERN),
    description: z.string(),
    scope: PolicySetScopeSchema,
    // How a rule reads a field the call does not carry (policy_format.md "A field the call does not carry"; HTL-22
    // row 176): `skip` reads it as today, `fail_closed` decides BLOCK (MISSING_FIELD)
    on_missing: z.enum(['skip', 'fail_closed'], { error: enumRefusal }).default('skip'),
    rules: z.array(RuleSchema),
    metadata: PolicyMetadataSchema.optional(),
  })
  .strict()
  // policy_format.md, a rule's `name`: "Unique rule identifier within policy set" (row 220). Read after the set-level
  // throttles compile, so a compiled rule is held to it, named by the entry it carries. Mirrors types.py.
  .superRefine((set, ctx) => {
    const held = new Map<string, string[]>();
    set.rules.forEach((rule, i) => {
      const source = (rule.metadata as Record<string, unknown> | undefined)?.compiled_from;
      const path = source && typeof source === 'object' ? (source as { path?: unknown }).path : undefined;
      const where = held.get(rule.name) ?? [];
      where.push(path ? `the rule compiled from ${path}` : `rules[${i}]`);
      held.set(rule.name, where);
    });
    const twice = [...held].filter(([, where]) => where.length > 1);
    if (twice.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['rules'],
        message: `${twice.map(([name, where]) => `'${name}' is held by ${where.join(' and ')}`).join('; ')}. A rule's ` +
          `name is the "Unique rule identifier within policy set" (policy_format.md): a lifecycle transition, a kill ` +
          `switch and a review address a rule by it. Give each rule a name of its own.`,
      });
    }
  });

/** T47: one rate-window representation — a set's `metadata.rate_limits` is compiled to windowed RATE_LIMIT rules on
 * load (rate-limits.ts, mirroring hiitl/core/rate_limits.py). */
export const PolicySetSchema = numericInput(PolicySetObjectSchema, (d, ctx) => {
  try { assertPolicyValues(d); } catch(error) { if(!(error instanceof PolicyValueError))throw error; for(const path of error.paths)ctx.addIssue({code:"custom",path,message:error.message}); return z.NEVER; }
  if(d!==null && typeof d==='object' && !Array.isArray(d) && Object.hasOwn(d,'metadata') && (d as Record<string,unknown>).metadata!==undefined) {
    const result=PolicyMetadataSchema.safeParse((d as Record<string,unknown>).metadata);
    if(!result.success){for(const issue of result.error.issues)ctx.addIssue({...issue,path:['metadata',...issue.path]});return d;}
  }
  const { data, problems } = compileSetLimits(d);
  for (const message of problems) ctx.addIssue({ code: z.ZodIssueCode.custom, message });
  return problems.length ? d : data;
});

export type PolicySet = z.infer<typeof PolicySetObjectSchema>;

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
  limit: integer(),
  current: integer(),
  reset_at: DateTimeSchema,
});

export type RateLimit = z.infer<typeof RateLimitSchema>;

/**
 * Rule that matched during evaluation.
 */
export const MatchedRuleSchema = z.object({
  rule_name: z.string(),
  policy_set: z.string(),
  priority: integer(),
});

export type MatchedRule = z.infer<typeof MatchedRuleSchema>;

/**
 * A "would have" observation produced by a staged rule (Block 1B, 9b).
 *
 * Staged rules run alongside active rules but never bind a decision.
 * Each staged rule whose conditions match is recorded here so the
 * regression report can compare staged-rule behavior against what the
 * active rules actually decided. The first staged match is flagged
 * `would_be_binding=true` — it's the decision the staged rules would
 * have produced collectively if they were active. Lower-priority
 * staged matches are still informative (they would catch envelopes
 * the binding staged rule's narrower scope misses) but don't drive
 * the regression outcome.
 *
 * Source of truth: docs/specs/decision_response.md (Block 1B addition).
 */
export const StagedObservationSchema = z.object({
  rule_name: z.string(),
  policy_set: z.string(),
  priority: integer(),
  would_be_decision: DecisionTypeSchema,
  would_be_reason_codes: z.array(z.string()),
  would_be_binding: z.boolean(),
});

export type StagedObservation = z.infer<typeof StagedObservationSchema>;

/**
 * A matching active RATE_LIMIT rule with a window (decision_response.md
 * `rate_limit_rules`): it does not bind; the post-evaluation limiter counts
 * it when the binding decision is ALLOW.
 */
export const RateLimitRuleSchema = z.object({
  rule_name: z.string(),
  policy_set: z.string(),
  priority: integer(),
  reason_code: z.string(),
  limit: integer(),
  window_seconds: integer(),
  scope: z.enum(['action', 'agent', 'user', 'org', 'user_action'], { error: enumRefusal }),
  // The rule's own remediation, details computed from the call; the limiter puts it on the refusal (R-0059).
  remediation: RemediationSchema.optional(),
});
export type RateLimitRule = z.infer<typeof RateLimitRuleSchema>;

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

/** A sync route asked in this evaluation (decision_response.md 1.7; policy_format.md 2.7; TICKET-046). */
export const RouteAskedSchema = z.object({
  rule_name: z.string(),
  route: z.string(),
  outcome: z.enum(['answered', 'unanswered', 'failed_open'], { error: enumRefusal }),
  fields: z.array(z.string()).optional(),
  error: z.string().optional(),
});
export type RouteAsked = z.infer<typeof RouteAskedSchema>;

/** A rule the walk read whose outcome a field the call does not carry left open, and the field (decision_response.md
 * `missing_fields`; HTL-22 row 176). */
export const MissingFieldSchema = z.object({
  rule_name: z.string(),
  policy_set: z.string(),
  field: z.string(),
});
export type MissingField = z.infer<typeof MissingFieldSchema>;

/**
 * The fail mode an outage decision applied, and the hosted client's circuit breaker when it was answered
 * (decision_response.md, the schema's `metadata`; Example 9). Present on `CONTROL_PLANE_UNAVAILABLE`.
 *
 * The fail mode is the hosted client's `fail_mode` setting: FAIL_CLOSED by default, FAIL_OPEN opt-in (Stop B (ii),
 * ruled 2026-11-06). Mirrors types.py.
 */
export const DecisionMetadataSchema = z.object({
  fail_mode: z.enum(['FAIL_CLOSED', 'FAIL_OPEN'], { error: enumRefusal }),
  circuit_breaker_state: z.enum(['closed', 'open', 'half_open'], { error: enumRefusal }), // the SDK's CircuitState
}).strict();
export type DecisionMetadata = z.infer<typeof DecisionMetadataSchema>;

/**
 * Decision response after policy evaluation.
 *
 * Source of truth: docs/specs/decision_response.md
 */
export const DecisionSchema = numericInput(z.object({
  action_id: z.string(),
  decision: DecisionTypeSchema,
  allowed: z.boolean(),
  reason_codes: z.array(z.string()),
  policy_version: z.string(),
  timing: TimingSchema,
  matched_rules: z.array(MatchedRuleSchema).optional(),
  rate_limit: RateLimitSchema.optional(),
  resume_token: z.string().optional(), // Token to correlate escalation with reviewer response
  route_ref: z.string().optional(), // Route artifact name from matched rule
  escalation_context: dataRecord(z.any()).optional(), // Populated by SDK/server, not evaluator
  // SHA-256 of the evaluated envelope's signed form, in every mode (Security Tier 1; canonical.ts envelopeHash)
  envelope_hash: z.string().regex(/^[a-f0-9]{64}$/).optional(),
  error: ErrorDetailSchema.optional(),
  remediation: RemediationSchema.optional(), // Guidance for BLOCK/RATE_LIMIT decisions
  would_be: z.string().optional(), // Original decision type when in OBSERVE mode
  would_be_reason_codes: z.array(z.string()).optional(), // Original reason codes when in OBSERVE mode
  // Block 1B: staged-rule "would have" matches. ALWAYS emitted as an
  // array (possibly empty) — Python emits `[]` by default and the TS
  // evaluator does the same (see evaluator.ts). Marking this `.default([])`
  // instead of `.optional()` so the inferred type is
  // `StagedObservation[]` (never `undefined`), matching the runtime
  // contract documented in decision_response.md ("Always an array
  // (empty when no staged rules matched) so consumers can iterate
  // without null-checks"). Audit 2026-05-16 caught the prior
  // `.optional()` as a real cross-language type-contract divergence.
  staged_observations: z.array(StagedObservationSchema).default([]),
  // Matching windowed RATE_LIMIT rules (R-0852): they meter, never bind. Always an array.
  rate_limit_rules: z.array(RateLimitRuleSchema).default([]),
  // A sync route's answer re-entering evaluation (policy_format.md 2.7; TICKET-046): the enrichment context the last
  // evaluation read and each route asked. Set by the SDK / server's routing loop, never by the caller.
  enrichment: dataRecord(dataRecord(z.unknown())).optional(),
  routes: z.array(RouteAskedSchema).optional(),
  // Each rule read with a field the call does not carry, skipped and flagged (HTL-22 row 176); absent when none was
  missing_fields: z.array(MissingFieldSchema).optional(),
  // TICKET-121 (TS) / TICKET-116 (Python): SDK cache state at evaluation
  // time. Local + hybrid SDKs stamp this on every Decision so callers
  // can detect cold-start / stale-cache situations. Possible values:
  //   "synced"    — policies came from a successful in-process sync
  //   "from_disk" — policies came from disk cache (warm start); no
  //                 successful sync this process yet
  //   "empty"     — no policies in memory; evaluator is OBSERVE_ALL
  // Hosted-mode evaluations leave this null (the server has authority;
  // cache_status doesn't apply). Optional in the schema for backward
  // compat with conformance fixtures that pre-date the field.
  cache_status: z.enum(['synced', 'from_disk', 'empty'], { error: enumRefusal }).nullable().optional(),
  // The outage decision's fail mode and circuit state (row 174); set by the hosted client, absent on every other
  metadata: DecisionMetadataSchema.optional(),
}).refine(
  (d) => !(d.error && d.remediation),
  {
    message:
      "Decision cannot have both 'error' and 'remediation'. " +
      "'error' indicates ECP failure; 'remediation' indicates intentional policy enforcement.",
  }
));

export type Decision = z.infer<typeof DecisionSchema>;
