/**
 * Route model types for HIITL ECP (TypeScript implementation).
 *
 * These types are derived from the language-neutral route specification:
 * - docs/specs/routes.md (JSON Schema)
 *
 * Routes are the third core artifact alongside envelopes and policies.
 * They define how ECP communicates with external systems — outbound
 * (ECP sends), inbound (external sends to ECP), or bidirectional
 * (ECP sends context, waits for response).
 *
 * Uses Zod for runtime validation and TypeScript type inference.
 * Mirrors python/hiitl/core/route_types.py exactly.
 */

import { z } from 'zod';

// ============================================================================
// Enums (from routes.md JSON Schema)
// ============================================================================

export const RouteDirection = {
  OUTBOUND: 'outbound',
  INBOUND: 'inbound',
  BIDIRECTIONAL: 'bidirectional',
} as const;
export type RouteDirection = typeof RouteDirection[keyof typeof RouteDirection];

export const RouteTiming = {
  ASYNC: 'async',
  SYNC: 'sync',
} as const;
export type RouteTiming = typeof RouteTiming[keyof typeof RouteTiming];

export const RoutePurpose = {
  OBSERVABILITY: 'observability',
  COMPLIANCE: 'compliance',
  REVIEW: 'review',
  SECURITY: 'security',
  POLICY_MANAGEMENT: 'policy-management',
  ASSESSMENT: 'assessment',
} as const;
export type RoutePurpose = typeof RoutePurpose[keyof typeof RoutePurpose];

export const RouteProtocol = {
  HTTP: 'http',
  GRPC: 'grpc',
  WEBHOOK: 'webhook',
} as const;
export type RouteProtocol = typeof RouteProtocol[keyof typeof RouteProtocol];

export const AuthType = {
  API_KEY: 'api_key',
  BEARER_TOKEN: 'bearer_token',
  HMAC_SHA256: 'hmac_sha256',
  MTLS: 'mtls',
  OAUTH2: 'oauth2',
} as const;
export type AuthType = typeof AuthType[keyof typeof AuthType];

export const ContextFieldFormat = {
  TEXT: 'text',
  CURRENCY: 'currency',
  DATE: 'date',
  JSON: 'json',
  CODE: 'code',
  URL: 'url',
} as const;
export type ContextFieldFormat = typeof ContextFieldFormat[keyof typeof ContextFieldFormat];

export const RiskSeverity = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical',
} as const;
export type RiskSeverity = typeof RiskSeverity[keyof typeof RiskSeverity];

export const RouteDecisionOption = {
  APPROVE: 'approve',
  DENY: 'deny',
  MODIFY: 'modify',
  DELEGATE: 'delegate',
  REQUEST_MORE_INFO: 'request_more_info',
  CONDITIONAL_APPROVE: 'conditional_approve',
  PARTIAL_APPROVE: 'partial_approve',
} as const;
export type RouteDecisionOption = typeof RouteDecisionOption[keyof typeof RouteDecisionOption];

export const TimeoutAction = {
  ESCALATE: 'escalate',
  FAIL_CLOSED: 'fail_closed',
  FAIL_OPEN: 'fail_open',
  EXTEND: 'extend',
} as const;
export type TimeoutAction = typeof TimeoutAction[keyof typeof TimeoutAction];

export const EscalationFinalAction = {
  FAIL_CLOSED: 'fail_closed',
  FAIL_OPEN: 'fail_open',
} as const;
export type EscalationFinalAction = typeof EscalationFinalAction[keyof typeof EscalationFinalAction];

export const BackoffStrategy = {
  EXPONENTIAL: 'exponential',
  LINEAR: 'linear',
  FIXED: 'fixed',
} as const;
export type BackoffStrategy = typeof BackoffStrategy[keyof typeof BackoffStrategy];

export const InboundAuthType = {
  BEARER_TOKEN: 'bearer_token',
  HMAC_SHA256: 'hmac_sha256',
} as const;
export type InboundAuthType = typeof InboundAuthType[keyof typeof InboundAuthType];

export const InboundAcceptanceMode = {
  PROPOSE: 'propose',
  AUTO_ACCEPT: 'auto_accept',
} as const;
export type InboundAcceptanceMode = typeof InboundAcceptanceMode[keyof typeof InboundAcceptanceMode];

export const ModifyConstraintType = {
  REDUCE_ONLY: 'reduce_only',
  INCREASE_ONLY: 'increase_only',
  ANY: 'any',
  SELECT_FROM: 'select_from',
} as const;
export type ModifyConstraintType = typeof ModifyConstraintType[keyof typeof ModifyConstraintType];

// ============================================================================
// Zod Schemas — Enums
// ============================================================================

const RouteDirectionSchema = z.enum(['outbound', 'inbound', 'bidirectional']);
const RouteTimingSchema = z.enum(['async', 'sync']);
const RoutePurposeSchema = z.enum([
  'observability', 'compliance', 'review', 'security', 'policy-management', 'assessment',
]);
const RouteProtocolSchema = z.enum(['http', 'grpc', 'webhook']);
const AuthTypeSchema = z.enum(['api_key', 'bearer_token', 'hmac_sha256', 'mtls', 'oauth2']);
const ContextFieldFormatSchema = z.enum(['text', 'currency', 'date', 'json', 'code', 'url']);
const RiskSeveritySchema = z.enum(['low', 'medium', 'high', 'critical']);
const DecisionOptionSchema = z.enum([
  'approve', 'deny', 'modify', 'delegate', 'request_more_info',
  'conditional_approve', 'partial_approve',
]);
const TimeoutActionSchema = z.enum(['escalate', 'fail_closed', 'fail_open', 'extend']);
const EscalationFinalActionSchema = z.enum(['fail_closed', 'fail_open']);
const BackoffStrategySchema = z.enum(['exponential', 'linear', 'fixed']);
const InboundAuthTypeSchema = z.enum(['bearer_token', 'hmac_sha256']);
const InboundAcceptanceModeSchema = z.enum(['propose', 'auto_accept']);
const ModifyConstraintTypeSchema = z.enum(['reduce_only', 'increase_only', 'any', 'select_from']);

// ============================================================================
// Zod Schemas — Sub-Models
// ============================================================================

/** Tenant and environment scope for a route. */
export const RouteScopeSchema = z.object({
  org_id: z.string().regex(/^org_[a-zA-Z0-9]{16,}$/),
  environment: z.string().regex(/^(dev|stage|prod)$/).optional(),
});
export type RouteScope = z.infer<typeof RouteScopeSchema>;

/** Authentication configuration for outbound/bidirectional requests. */
export const RouteAuthSchema = z.object({
  type: AuthTypeSchema,
  secret_ref: z.string(),
  header: z.string().default('Authorization').optional(),
  hmac_header: z.string().default('X-HIITL-Signature').optional(),
});
export type RouteAuth = z.infer<typeof RouteAuthSchema>;

/** A field to include in outbound/bidirectional payloads. */
export const ContextFieldSchema = z.object({
  field_path: z.string(),
  label: z.string().optional(),
  format: ContextFieldFormatSchema.default('text').optional(),
});
export type ContextField = z.infer<typeof ContextFieldSchema>;

/** What happens depending on the decision. */
export const RiskConsequencesSchema = z.object({
  if_approved: z.string().optional(),
  if_denied: z.string().optional(),
});
export type RiskConsequences = z.infer<typeof RiskConsequencesSchema>;

/** How to frame the risk/severity for the recipient. */
export const RiskFramingSchema = z.object({
  severity: RiskSeveritySchema.optional(),
  summary: z.string().optional(),
  consequences: RiskConsequencesSchema.optional(),
});
export type RiskFraming = z.infer<typeof RiskFramingSchema>;

/** What data to send on outbound/bidirectional routes. */
export const RouteContextSchema = z.object({
  fields: z.array(ContextFieldSchema).optional(),
  include_policy_ref: z.boolean().default(true).optional(),
  include_audit_context: z.boolean().default(false).optional(),
  risk_framing: RiskFramingSchema.optional(),
});
export type RouteContext = z.infer<typeof RouteContextSchema>;

/** When this route activates. */
export const RouteFiltersSchema = z.object({
  decisions: z.array(z.string()).optional(),
  tools: z.array(z.string()).optional(),
  agents: z.array(z.string()).optional(),
  sensitivity: z.array(z.string()).optional(),
});
export type RouteFilters = z.infer<typeof RouteFiltersSchema>;

/** Retry configuration for failed deliveries. */
export const RouteRetrySchema = z.object({
  max_attempts: z.number().int().min(1).max(10).default(3).optional(),
  backoff: BackoffStrategySchema.default('exponential').optional(),
  initial_delay_ms: z.number().int().min(100).max(60000).default(1000).optional(),
});
export type RouteRetry = z.infer<typeof RouteRetrySchema>;

/** Batching configuration for async routes. */
export const RouteQueueSchema = z.object({
  batch_size: z.number().int().min(1).max(1000).default(100).optional(),
  flush_interval: z.string().regex(/^\d+(s|m|h)$/).default('30s').optional(),
});
export type RouteQueue = z.infer<typeof RouteQueueSchema>;

/** Constraint on parameter modifications (Phase 2). */
export const ModifyConstraintSchema = z.object({
  field_path: z.string(),
  constraint: ModifyConstraintTypeSchema,
  options: z.array(z.any()).optional(),
});
export type ModifyConstraint = z.infer<typeof ModifyConstraintSchema>;

/** Expected response format for bidirectional routes. */
export const RouteResponseSchemaSchema = z.object({
  decision_options: z.array(DecisionOptionSchema).min(2),
  required_fields: z.array(z.string()).default(['decision']).optional(),
  optional_fields: z.array(z.string()).optional(),
  reason_required_for: z.array(z.string()).optional(),
  modify_constraints: z.array(ModifyConstraintSchema).optional(),
});
export type RouteResponseSchema = z.infer<typeof RouteResponseSchemaSchema>;

/** Response time expectations for bidirectional routes. */
export const RouteSLASchema = z.object({
  timeout: z.string().regex(/^\d+(s|m|h)$/),
  timeout_action: TimeoutActionSchema,
  auto_approve_flag: z.boolean().default(false).optional(),
});
export type RouteSLA = z.infer<typeof RouteSLASchema>;

/** A single level in an escalation ladder. */
export const EscalationLevelSchema = z.object({
  level: z.number().int().min(1),
  route: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/),
  after: z.string().regex(/^\d+(s|m|h)$/),
});
export type EscalationLevel = z.infer<typeof EscalationLevelSchema>;

/** Multi-level escalation for bidirectional routes. */
export const RouteEscalationLadderSchema = z.object({
  levels: z.array(EscalationLevelSchema).optional(),
  max_escalation_depth: z.number().int().min(1).max(10).optional(),
  final_timeout_action: EscalationFinalActionSchema.default('fail_closed').optional(),
});
export type RouteEscalationLadder = z.infer<typeof RouteEscalationLadderSchema>;

/** How request and response are matched for bidirectional routes. */
export const RouteCorrelationSchema = z.object({
  token_field: z.string().default('resume_token').optional(),
});
export type RouteCorrelation = z.infer<typeof RouteCorrelationSchema>;

/** Authentication for inbound routes. */
export const InboundAuthSchema = z.object({
  type: InboundAuthTypeSchema.optional(),
  token_ref: z.string().optional(),
});
export type InboundAuth = z.infer<typeof InboundAuthSchema>;

/** How to extract structured signals from external payloads. */
export const InboundPayloadMappingSchema = z.object({
  signal_type: z.string().optional(),
  agent_ref: z.string().optional(),
  severity: z.string().optional(),
  metadata: z.record(z.string()).optional(),
});
export type InboundPayloadMapping = z.infer<typeof InboundPayloadMappingSchema>;

/** What an inbound route is authorized to do. */
export const InboundPermissionsSchema = z.object({
  can_enforce: z.boolean().default(false).optional(),
  can_propose: z.boolean().default(false).optional(),
  can_signal: z.boolean().default(false).optional(),
  enforce_scope: z.array(z.string()).optional(),
}).refine(
  (data) => (data.can_enforce || data.can_propose || data.can_signal),
  {
    message:
      "At least one permission must be true (can_enforce, can_propose, or can_signal). " +
      "An inbound route with all permissions false has no effect.",
  }
).refine(
  (data) => !(data.enforce_scope && !data.can_enforce),
  {
    message:
      "enforce_scope requires can_enforce=true. " +
      "Set can_enforce to true or remove enforce_scope.",
  }
);
export type InboundPermissions = z.infer<typeof InboundPermissionsSchema>;

/** Configuration for inbound routes (Phase 2). */
export const RouteInboundSchema = z.object({
  url: z.string().optional(),
  auth: InboundAuthSchema.optional(),
  payload_mapping: InboundPayloadMappingSchema.optional(),
  permissions: InboundPermissionsSchema,
  acceptance_mode: InboundAcceptanceModeSchema.default('propose').optional(),
}).refine(
  (data) => {
    if (data.acceptance_mode === 'auto_accept') {
      // Need to check inner permissions — since InboundPermissionsSchema
      // is refined, we access the raw data before refinement
      const perms = data.permissions as { can_propose?: boolean };
      return perms.can_propose === true;
    }
    return true;
  },
  {
    message:
      "acceptance_mode 'auto_accept' requires can_propose=true. " +
      "Set can_propose to true or use 'propose' mode.",
  }
);
export type RouteInbound = z.infer<typeof RouteInboundSchema>;

/** Route metadata. */
export const RouteMetadataSchema = z.record(z.any());

// ============================================================================
// Root Schema: Route
// ============================================================================

/**
 * Route configuration — the third core artifact.
 *
 * Routes define how ECP communicates with external systems. They are
 * referenced by name from policy rules (via the 'route' field) and
 * resolved by the SDK/server after evaluation.
 *
 * Source of truth: docs/specs/routes.md
 *
 * Direction determines which fields are required/forbidden:
 * - outbound: requires endpoint; forbids inbound, response_schema, sla,
 *   escalation_ladder, correlation
 * - bidirectional: requires endpoint, response_schema, sla; forbids inbound;
 *   requires timing=sync
 * - inbound: requires inbound.permissions; forbids endpoint, context,
 *   response_schema, sla, escalation_ladder, correlation
 */
export const RouteSchema = z.object({
  // Required fields
  name: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/),
  version: z.string().regex(/^v\d+\.\d+\.\d+$/),
  direction: RouteDirectionSchema,
  timing: RouteTimingSchema,

  // Recommended fields
  description: z.string().optional(),
  purpose: z.array(RoutePurposeSchema).min(1).optional(),

  // Scope
  scope: RouteScopeSchema.optional(),

  // Connection
  endpoint: z.string().optional(),
  auth: RouteAuthSchema.optional(),
  protocol: RouteProtocolSchema.default('webhook').optional(),

  // Context
  context: RouteContextSchema.optional(),

  // Filters
  filters: RouteFiltersSchema.optional(),

  // Resilience
  retry: RouteRetrySchema.optional(),
  queue: RouteQueueSchema.optional(),

  // Response (bidirectional)
  response_schema: RouteResponseSchemaSchema.optional(),
  sla: RouteSLASchema.optional(),
  escalation_ladder: RouteEscalationLadderSchema.optional(),
  correlation: RouteCorrelationSchema.optional(),

  // Inbound (Phase 2)
  inbound: RouteInboundSchema.optional(),

  // Metadata
  metadata: RouteMetadataSchema.optional(),
}).superRefine((data, ctx) => {
  const { direction, timing } = data;

  if (direction === 'outbound') {
    if (!data.endpoint) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "outbound routes require 'endpoint'. " +
          "Specify the target URL where ECP sends events.",
        path: ['endpoint'],
      });
    }
    const forbidden: Array<[string, unknown]> = [
      ['inbound', data.inbound],
      ['response_schema', data.response_schema],
      ['sla', data.sla],
      ['escalation_ladder', data.escalation_ladder],
      ['correlation', data.correlation],
    ];
    for (const [fieldName, value] of forbidden) {
      if (value !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            `outbound routes must not have '${fieldName}'. ` +
            `Remove it or change direction to 'bidirectional'.`,
          path: [fieldName],
        });
      }
    }
  }

  if (direction === 'bidirectional') {
    if (!data.endpoint) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "bidirectional routes require 'endpoint'. " +
          "Specify the URL where ECP sends context and waits for response.",
        path: ['endpoint'],
      });
    }
    if (!data.response_schema) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "bidirectional routes require 'response_schema'. " +
          "Define what the external system can respond with " +
          "(at minimum: decision_options with 'approve' and 'deny').",
        path: ['response_schema'],
      });
    }
    if (!data.sla) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "bidirectional routes require 'sla'. " +
          "Define timeout and timeout_action for the response.",
        path: ['sla'],
      });
    }
    if (data.inbound !== undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "bidirectional routes must not have 'inbound'. " +
          "Use direction 'inbound' for external-to-ECP routes.",
        path: ['inbound'],
      });
    }
    if (timing !== 'sync') {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "bidirectional routes must use timing 'sync'. " +
          "Bidirectional implies waiting for a response.",
        path: ['timing'],
      });
    }
  }

  if (direction === 'inbound') {
    if (!data.inbound) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "inbound routes require 'inbound' with permissions. " +
          "Define what the external system is authorized to do.",
        path: ['inbound'],
      });
    }
    const forbidden: Array<[string, unknown]> = [
      ['endpoint', data.endpoint],
      ['context', data.context],
      ['response_schema', data.response_schema],
      ['sla', data.sla],
      ['escalation_ladder', data.escalation_ladder],
      ['correlation', data.correlation],
    ];
    for (const [fieldName, value] of forbidden) {
      if (value !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            `inbound routes must not have '${fieldName}'. ` +
            `Remove it or change direction.`,
          path: [fieldName],
        });
      }
    }
  }

  // Timing constraints
  if (timing === 'sync' && data.queue !== undefined) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message:
        "sync routes must not use 'queue'. " +
        "Batching is only for async routes.",
      path: ['queue'],
    });
  }
});

export type Route = z.infer<typeof RouteSchema>;
