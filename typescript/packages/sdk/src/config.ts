/**
 * SDK configuration using Zod for runtime validation.
 *
 * Configuration can be provided via:
 * 1. Constructor arguments (highest priority)
 * 2. Environment variables (HIITL_* prefix)
 * 3. Default values (lowest priority)
 *
 * @example
 * ```typescript
 * import { createConfig } from '@hiitl/sdk';
 *
 * const config = createConfig({
 *   environment: 'dev',
 *   agent_id: 'payment-agent',
 *   org_id: 'org_mycompany123456789',
 *   policy_path: './policy.yaml',
 * });
 * ```
 *
 * Environment variables:
 *   HIITL_ENVIRONMENT: dev, stage, or prod
 *   HIITL_AGENT_ID: Agent identifier
 *   HIITL_ORG_ID: Organization ID (must match pattern)
 *   HIITL_POLICY_PATH: Path to policy file
 *   HIITL_AUDIT_DB_PATH: Path to SQLite database (default: ./hiitl_audit.db)
 *   HIITL_ENABLE_RATE_LIMITING: Enable rate limiting (default: true)
 *   HIITL_SIGNATURE_KEY: HMAC signature key (optional)
 */

import { z } from 'zod';

/**
 * Environment enum - must match core Environment type.
 */
const EnvironmentSchema = z.enum(['dev', 'stage', 'prod']);
export type Environment = z.infer<typeof EnvironmentSchema>;

/**
 * org_id validation schema.
 *
 * Pattern: org_[a-z0-9]{18,}
 * - Must start with 'org_'
 * - Followed by at least 18 lowercase alphanumeric characters
 *
 * Examples:
 * - org_mycompany123456789 ✓
 * - org_abcdefghij0123456789 ✓
 * - org_short ✗ (too short)
 * - org_HAS_UPPERCASE00000 ✗ (has uppercase)
 * - mycompany123456789 ✗ (missing prefix)
 */
const OrgIdSchema = z.string().regex(
  /^org_[a-z0-9]{18,}$/,
  "Invalid org_id. Must match pattern 'org_[a-z0-9]{18,}'. Example: 'org_mycompany123456789'"
);

/**
 * Local mode configuration schema.
 *
 * All fields are validated at runtime using Zod.
 */
export const LocalModeConfigSchema = z.object({
  /**
   * Execution environment: dev, stage, or prod.
   */
  environment: EnvironmentSchema.default('dev'),

  /**
   * Agent identifier (arbitrary string, used in envelopes).
   */
  agent_id: z.string().min(1, 'agent_id cannot be empty').default('default'),

  /**
   * Organization ID (must match pattern org_[a-z0-9]{18,}).
   */
  org_id: OrgIdSchema.default('org_devlocal0000000000'),

  /**
   * Policy evaluation mode: OBSERVE_ALL or RESPECT_POLICY.
   * Default: OBSERVE_ALL (zero-config: everything observed, nothing blocked).
   */
  mode: z.enum(['OBSERVE_ALL', 'RESPECT_POLICY']).default('OBSERVE_ALL'),

  /**
   * Path to policy file (JSON or YAML format).
   * Optional for OBSERVE_ALL mode (zero-config).
   */
  policy_path: z.string().min(1, 'policy_path cannot be empty').optional(),

  /**
   * Path to SQLite audit database file.
   * Default: ./hiitl_audit.db
   */
  audit_db_path: z.string().default('./hiitl_audit.db'),

  /**
   * Whether to enforce rate limits from policy metadata.
   * Default: true
   */
  enable_rate_limiting: z.boolean().default(true),

  /**
   * Path to directory containing route config files (YAML/JSON).
   * If not set, route config resolution is skipped for escalation decisions.
   */
  routes_path: z.string().optional(),

  /**
   * HMAC-SHA256 key for envelope signing (optional, for testing).
   */
  signature_key: z.string().optional(),

  /**
   * API key for future sync engine (optional, stored for hybrid mode).
   */
  api_key: z.string().optional(),
});

/**
 * Local mode configuration type (inferred from schema).
 */
export type LocalModeConfig = z.infer<typeof LocalModeConfigSchema>;

/**
 * Input type for createConfig (all fields except defaults are required unless from env vars).
 */
export interface LocalModeConfigInput {
  environment?: Environment;
  agent_id?: string;
  org_id?: string;
  mode?: 'OBSERVE_ALL' | 'RESPECT_POLICY';
  policy_path?: string;
  audit_db_path?: string;
  enable_rate_limiting?: boolean;
  routes_path?: string;
  signature_key?: string;
  api_key?: string;
}

/**
 * Hosted mode configuration schema.
 *
 * For use when evaluating against a remote ECP server.
 */
export const HostedModeConfigSchema = z.object({
  environment: EnvironmentSchema,

  agent_id: z.string().min(1, 'agent_id cannot be empty'),

  org_id: OrgIdSchema,

  /** API key for server authentication (Bearer token). */
  api_key: z.string().min(8, 'api_key must be at least 8 characters'),

  /** ECP server URL (must start with http:// or https://). */
  server_url: z
    .string()
    .url('server_url must be a valid URL (e.g. https://api.hiitl.com)')
    .refine(
      (url) => url.startsWith('http://') || url.startsWith('https://'),
      'server_url must use http:// or https://'
    )
    .transform((url) => url.replace(/\/+$/, '')),

  /** Request timeout in milliseconds. Default: 5000. */
  timeout: z.number().min(100).max(30000).default(5000),

  /** Maximum retry attempts on transient failures. Default: 3. */
  max_retries: z.number().int().min(0).max(10).default(3),

  /** HMAC-SHA256 key for envelope signing (optional). */
  signature_key: z.string().optional(),
});

export type HostedModeConfig = z.infer<typeof HostedModeConfigSchema>;

export interface HostedModeConfigInput {
  environment?: Environment;
  agent_id?: string;
  org_id?: string;
  api_key?: string;
  server_url?: string;
  timeout?: number;
  max_retries?: number;
  signature_key?: string;
}

/** Input type for HIITL constructor. Mode is auto-detected from api_key/server_url presence. */
export interface HIITLConfigInput {
  environment?: Environment;
  agent_id?: string;
  org_id?: string;
  mode?: 'OBSERVE_ALL' | 'RESPECT_POLICY';
  policy_path?: string;
  audit_db_path?: string;
  enable_rate_limiting?: boolean;
  routes_path?: string;
  signature_key?: string;
  api_key?: string;
  server_url?: string;
  timeout?: number;
  max_retries?: number;
  /** Enable sync when api_key is provided (default: true). Set to false to force pure local. */
  sync?: boolean;
}

/**
 * Parse environment variables with HIITL_ prefix.
 *
 * Returns an object with all recognized environment variables.
 * Undefined values are omitted so they don't override constructor args.
 */
function parseEnvVars(): Record<string, unknown> {
  const env = process.env;
  const result: Record<string, unknown> = {};

  if (env.HIITL_ENVIRONMENT) result.environment = env.HIITL_ENVIRONMENT;
  if (env.HIITL_AGENT_ID) result.agent_id = env.HIITL_AGENT_ID;
  if (env.HIITL_ORG_ID) result.org_id = env.HIITL_ORG_ID;
  if (env.HIITL_POLICY_PATH) result.policy_path = env.HIITL_POLICY_PATH;
  if (env.HIITL_AUDIT_DB_PATH) result.audit_db_path = env.HIITL_AUDIT_DB_PATH;
  if (env.HIITL_ENABLE_RATE_LIMITING === 'false') result.enable_rate_limiting = false;
  else if (env.HIITL_ENABLE_RATE_LIMITING === 'true') result.enable_rate_limiting = true;
  if (env.HIITL_ROUTES_PATH) result.routes_path = env.HIITL_ROUTES_PATH;
  if (env.HIITL_SIGNATURE_KEY) result.signature_key = env.HIITL_SIGNATURE_KEY;
  if (env.HIITL_API_KEY) result.api_key = env.HIITL_API_KEY;
  if (env.HIITL_SERVER_URL) result.server_url = env.HIITL_SERVER_URL;
  if (env.HIITL_TIMEOUT) result.timeout = Number(env.HIITL_TIMEOUT);
  if (env.HIITL_MAX_RETRIES) result.max_retries = Number(env.HIITL_MAX_RETRIES);
  if (env.HIITL_SYNC === 'false') result.sync = false;
  else if (env.HIITL_SYNC === 'true') result.sync = true;

  return result;
}

/**
 * Create and validate local mode configuration.
 *
 * Merges environment variables with provided options (options take precedence).
 *
 * @param options - Configuration options (overrides environment variables)
 * @returns Validated LocalModeConfig object
 * @throws {z.ZodError} If validation fails
 */
export function createConfig(options: LocalModeConfigInput): LocalModeConfig {
  const merged = mergeWithEnv(options as Record<string, unknown>);
  return LocalModeConfigSchema.parse(merged);
}

/**
 * Create and validate hosted mode configuration.
 *
 * @param options - Configuration options (overrides environment variables)
 * @returns Validated HostedModeConfig object
 * @throws {z.ZodError} If validation fails
 */
export function createHostedConfig(options: HostedModeConfigInput): HostedModeConfig {
  const merged = mergeWithEnv(options as Record<string, unknown>);
  return HostedModeConfigSchema.parse(merged);
}

function mergeWithEnv(options: Record<string, unknown>): Record<string, unknown> {
  const envConfig = parseEnvVars();
  const merged: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(envConfig)) {
    if (value !== undefined) {
      merged[key] = value;
    }
  }

  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined) {
      merged[key] = value;
    }
  }

  return merged;
}
