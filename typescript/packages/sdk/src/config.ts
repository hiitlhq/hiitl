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
 * Environment variables: `ENV_SETTINGS` below names each one and the option it
 * sets; `new HIITL()` reads every one its options leave unset.
 */

import { z } from 'zod';
import { DEDUP_WINDOW_SECONDS, FAIL_MODES, assertNumericDomain, NumericDomainError, numericInput, assertSchemaNumbers, parseAdmittedNumbers, integer, ORG_ID_PATTERN, httpsRefusal } from '@hiitl/core';
import { ConfigurationError } from './exceptions.js';

/**
 * Environment enum - must match core Environment type.
 */
const EnvironmentSchema = z.enum(['dev', 'stage', 'prod']);
export type Environment = z.infer<typeof EnvironmentSchema>;

/**
 * org_id validation schema: the envelope's own pattern (`ORG_ID_PATTERN`, envelope_schema.json), so the SDK takes
 * every id the service mints.
 */
const OrgIdSchema = z.string().regex(
  ORG_ID_PATTERN,
  `Invalid org_id. Must match the envelope's org_id pattern ${String(ORG_ID_PATTERN)}. ` +
    "Use the org id your API key belongs to, e.g. 'org_mycompany123456789'"
);

/**
 * Local mode configuration schema.
 *
 * All fields are validated at runtime using Zod.
 */

const LocalModeConfigObject = z.object({
  /**
   * Execution environment: dev, stage, or prod.
   */
  environment: EnvironmentSchema.default('dev'),

  /**
   * Agent identifier (arbitrary string, used in envelopes).
   */
  agent_id: z.string().min(1, 'agent_id cannot be empty').default('default'),

  /**
   * Organization ID (must match the envelope's org_id pattern, ORG_ID_PATTERN).
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
   * The dedup window: a repeated idempotency_key within it returns the first decision and writes no record (row 143).
   * Default: 24 hours (DEDUP_WINDOW_SECONDS).
   */
  dedup_window_seconds: integer().default(DEDUP_WINDOW_SECONDS),

  /**
   * API key for future sync engine (optional, stored for hybrid mode).
   */
  api_key: z.string().optional(),
});

/**
 * Local mode configuration type (inferred from schema).
 */
export const LocalModeConfigSchema = numericInput(LocalModeConfigObject);

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
  dedup_window_seconds?: number;
  api_key?: string;
}

/**
 * A number within its range, a value outside it refused naming the range (decision_response.md, the hosted client's
 * settings: "naming the range"; row 209). Mirrors config.py `validate_range`.
 */
function ranged(name: string, low: number, high: number): z.ZodNumber {
  const message = `${name} must be from ${low} to ${high}`;
  return z.number().min(low, message).max(high, message);
}

/**
 * Hosted mode configuration schema.
 *
 * For use when evaluating against a remote ECP server.
 */
const HostedModeConfigObject = z.object({
  environment: EnvironmentSchema,

  agent_id: z.string().min(1, 'agent_id cannot be empty'),

  org_id: OrgIdSchema,

  /** API key for server authentication (Bearer token). */
  api_key: z.string().min(8, 'api_key must be at least 8 characters'),

  /** ECP server URL: an https URL naming a host (sync_engine.md section 8; row 140). */
  server_url: z
    .string()
    .superRefine((url, ctx) => {
      const refusal = serverUrlRefusal(url);
      if (refusal) ctx.addIssue({ code: z.ZodIssueCode.custom, message: refusal });
    })
    .transform((url) => url.replace(/\/+$/, '')),

  /** Request timeout in seconds, as in the Python SDK (`HIITL_TIMEOUT` too). Default: 5. Range: 0.1-30. */
  timeout: ranged('timeout (in seconds, as in the Python SDK: 5000 would be 5000 seconds)', 0.1, 30).default(5),

  /** Maximum retry attempts on transient failures. Default: 3. Range: 0-10. */
  max_retries: ranged('max_retries', 0, 10).int().default(3),

  /**
   * What an outage answers (decision_response.md, the hosted settings table; Stop B (ii)): FAIL_CLOSED, the default,
   * the action is not allowed; FAIL_OPEN, opt-in, the action is allowed without being evaluated, its warning recorded.
   */
  fail_mode: z.enum(FAIL_MODES, {
    error: (issue) => ({
      message: `Invalid fail_mode '${String(issue.input)}'. Must be one of: ${FAIL_MODES.join(', ')}. FAIL_CLOSED (the ` +
        'default) does not allow an action the hosted service could not decide; FAIL_OPEN allows it, with a warning.',
    }),
  }).default('FAIL_CLOSED'),

  /** The local store, where the client records an outage and holds what the service could not take (Stop B (i)). */
  audit_db_path: LocalModeConfigObject.shape.audit_db_path,

  /** HMAC-SHA256 key for envelope signing (optional). */
  signature_key: z.string().optional(),
});

export const HostedModeConfigSchema = numericInput(HostedModeConfigObject);

export type HostedModeConfig = z.infer<typeof HostedModeConfigSchema>;

export interface HostedModeConfigInput {
  environment?: Environment;
  agent_id?: string;
  org_id?: string;
  api_key?: string;
  server_url?: string;
  timeout?: number;
  max_retries?: number;
  fail_mode?: string;
  audit_db_path?: string;
  signature_key?: string;
}

/**
 * The sync engine's tuning settings (docs/specs/sync_engine.md section 9), each with its
 * HIITL_SYNC_* variable in `ENV_SETTINGS`, and the telemetry family's (telemetry_schema.md
 * section 5), each with its HIITL_TELEMETRY_* variable. Intervals and timeouts are in seconds.
 * This SDK ships no telemetry collector: the telemetry settings are read and checked, and send nothing.
 */
export interface SyncSettingsInput {
  audit_sync_interval?: number;
  policy_sync_interval?: number;
  route_sync_interval?: number;
  kill_switch_poll_interval?: number;
  audit_batch_size?: number;
  /** Unsynced audit records at which BUFFER_FULL is emitted. Default 10000. */
  max_buffer_records?: number;
  /** Unsynced audit bytes at which BUFFER_FULL is emitted. Default 52428800 (50 MB). */
  max_buffer_size_bytes?: number;
  circuit_breaker_threshold?: number;
  circuit_breaker_reset?: number;
  /** Seconds a disk cache may age before a cold start treats it as stale. Default 86400. */
  max_cache_stale_age?: number;
  sync_timeout?: number;
  sync_max_retries?: number;
  /** Seconds between telemetry uploads. Default 60. Range: 5-3600. */
  telemetry_sync_interval?: number;
  /** Max buffered telemetry records. Default 60. Range: 10-1000. */
  telemetry_buffer_size?: number;
  /** The fraction of evaluations whose parameter and target details are counted. Default 1.0. Range: 0-1. */
  telemetry_sample_rate?: number;
  /** The actions whose parameters telemetry counts (telemetry_schema.md section 6). Default: none. */
  telemetry_parameter_tools?: string[];
}

/** Where the API key and the records go when no `server_url` is set: the hosted service. */
export const DEFAULT_SERVER_URL = 'https://api.hiitl.com';

/**
 * Why `url` is not one the SDK sends its API key and records to, or null: an https URL naming a host (sync_engine.md
 * section 8; row 140), named by the variable it is read from.
 */
export function serverUrlRefusal(url: unknown): string | null {
  const [variable] = ENV_SETTINGS.find(([, option]) => option === 'server_url')!;
  return httpsRefusal(url, `server_url (${variable})`);
}

/** What hybrid telemetry sends, docs/specs/telemetry_schema.md section 5's levels; 'off' sends nothing. */
export const TELEMETRY_LEVELS = ['full', 'standard', 'minimal', 'off'] as const;
export type TelemetryLevel = (typeof TELEMETRY_LEVELS)[number];

/** Input type for HIITL constructor. Mode is auto-detected from api_key, evaluation and sync. */
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
  dedup_window_seconds?: number;
  /**
   * Envelope paths whose values the local audit store records as "[REDACTED]", e.g. ['parameters.account_number']
   * (event_format.md §Redaction; HTL-20 row 139). Evaluation sees the whole envelope. In hosted mode they apply to the
   * records the client holds during an outage; the service's record takes the organisation's redaction_policy.
   */
  redact_fields?: string[];
  /**
   * `{action: [parameter names]}`. When set, every other parameter is recorded as an HMAC-SHA256 hash of its value,
   * under a key kept beside the audit store (the MCP gateway sets it). In hybrid mode the store also redacts the fields
   * the organisation's redaction_policy declares.
   */
  recorded_parameters?: Record<string, string[]>;
  api_key?: string;
  server_url?: string;
  /** HTTP request timeout in seconds, hosted mode only (default: 5; 0.1-30). */
  timeout?: number;
  /** Max retry attempts on transient failures, hosted mode only (default: 3; 0-10). */
  max_retries?: number;
  /**
   * What a hosted outage answers: 'FAIL_CLOSED' (default), the action is not allowed, or 'FAIL_OPEN' (opt-in), the
   * action is allowed without being evaluated and the warning recorded. Hosted mode only.
   */
  fail_mode?: string;
  /** Enable sync when api_key is provided (default: true). Set to false to force pure local. */
  sync?: boolean;
  /**
   * Where evaluation runs: 'local' (default — in-process, hybrid when an api_key is given) or
   * 'remote', the explicit opt-in to hosted evaluation, which needs api_key and server_url.
   */
  evaluation?: 'local' | 'remote';
  /**
   * Cold-start behavior for hybrid mode (TICKET-121, mirrors Python TICKET-116).
   *
   * Controls what happens when no disk cache exists AND the initial
   * sync to the server times out or fails. Three values:
   *   - 'warn-and-observe' (default): log a WARNING and continue in
   *     OBSERVE_ALL. Every Decision carries cache_status='empty'
   *     until background sync succeeds.
   *   - 'fail-closed': evaluate() throws ColdStartError instead of
   *     running against an empty policy set. JS constructors can't be
   *     async so the throw happens on the first evaluate() after the
   *     initial sync resolves — not on `new HIITL(...)` as in Python.
   *   - 'observe-silent': log at INFO instead of WARNING. Opt-in; not
   *     recommended for new code.
   *
   * No effect in pure-local or pure-hosted modes.
   */
  cold_start_behavior?: 'warn-and-observe' | 'fail-closed' | 'observe-silent';
  /**
   * What hybrid telemetry sends (telemetry_schema.md section 5): 'full', 'standard' (default), 'minimal', or 'off'.
   * This SDK ships no telemetry collector, so it sends no telemetry at any level; the setting is read and checked
   * so one configuration means the same in both SDKs (row 172).
   */
  telemetry_level?: TelemetryLevel;
  /**
   * Override the disk cache directory (default: ~/.hiitl/cache/).
   * Only used in hybrid mode.
   */
  cache_dir?: string;
  /**
   * Initial-sync timeout in seconds (default: 10). Only used in hybrid
   * mode. After this elapses, cold_start_behavior decides what happens.
   */
  sync_init_timeout?: number;
  /** The sync engine's tuning settings. Only used in hybrid mode. */
  sync_config?: SyncSettingsInput;
  /**
   * The verified principal (T-130 A7; envelope_schema.json `principal`):
   * checks a token passed to evaluate({ principal_token }) — signature,
   * issuer, audience, expiry — and returns its claims, throwing on an
   * invalid token. The envelope's `principal` is set only from what it
   * returns; there is no free `principal` option.
   */
  principal_verifier?: PrincipalVerifier;
  /**
   * The fetch a sync route is asked with (TICKET-046; routes.md "A sync route's answer re-enters evaluation").
   * Default: the global fetch.
   */
  route_fetch?: typeof fetch;
}

/** Claims a principal verifier returns for a valid token. */
export interface PrincipalClaims {
  sub: string;
  scope?: string;
  scopes?: string[];
  iss?: string;
  aud?: string;
}

export type PrincipalVerifier = (token: string) => PrincipalClaims;

type EnvKind = 'string' | 'number' | 'boolean' | 'list';

/**
 * Every HIITL_* setting the SDK reads: the variable, the option it sets (`sync_config.<name>`
 * for a sync engine or telemetry setting) and how its text is read. The Python SDK reads the same
 * names (hiitl.sdk.config); the sync names are docs/specs/sync_engine.md section 9's and the
 * telemetry names telemetry_schema.md section 5's.
 */
export const ENV_SETTINGS: ReadonlyArray<readonly [string, string, EnvKind]> = [
  ['HIITL_ENVIRONMENT', 'environment', 'string'],
  ['HIITL_AGENT_ID', 'agent_id', 'string'],
  ['HIITL_ORG_ID', 'org_id', 'string'],
  ['HIITL_MODE', 'mode', 'string'],
  ['HIITL_POLICY_PATH', 'policy_path', 'string'],
  ['HIITL_AUDIT_DB_PATH', 'audit_db_path', 'string'],
  ['HIITL_ENABLE_RATE_LIMITING', 'enable_rate_limiting', 'boolean'],
  ['HIITL_ROUTES_PATH', 'routes_path', 'string'],
  ['HIITL_SIGNATURE_KEY', 'signature_key', 'string'],
  ['HIITL_DEDUP_WINDOW_SECONDS', 'dedup_window_seconds', 'number'],
  ['HIITL_API_KEY', 'api_key', 'string'],
  ['HIITL_SERVER_URL', 'server_url', 'string'],
  ['HIITL_EVALUATION', 'evaluation', 'string'],
  ['HIITL_SYNC', 'sync', 'boolean'],
  ['HIITL_COLD_START_BEHAVIOR', 'cold_start_behavior', 'string'],
  ['HIITL_TELEMETRY_LEVEL', 'telemetry_level', 'string'],
  ['HIITL_TIMEOUT', 'timeout', 'number'],
  ['HIITL_MAX_RETRIES', 'max_retries', 'number'],
  ['HIITL_FAIL_MODE', 'fail_mode', 'string'],
  ['HIITL_CACHE_DIR', 'cache_dir', 'string'],
  ['HIITL_SYNC_INIT_TIMEOUT', 'sync_init_timeout', 'number'],
  ['HIITL_SYNC_AUDIT_INTERVAL', 'sync_config.audit_sync_interval', 'number'],
  ['HIITL_SYNC_POLICY_INTERVAL', 'sync_config.policy_sync_interval', 'number'],
  ['HIITL_SYNC_ROUTE_INTERVAL', 'sync_config.route_sync_interval', 'number'],
  ['HIITL_SYNC_KS_INTERVAL', 'sync_config.kill_switch_poll_interval', 'number'],
  ['HIITL_SYNC_AUDIT_BATCH', 'sync_config.audit_batch_size', 'number'],
  ['HIITL_SYNC_MAX_BUFFER', 'sync_config.max_buffer_records', 'number'],
  ['HIITL_SYNC_MAX_BUFFER_BYTES', 'sync_config.max_buffer_size_bytes', 'number'],
  ['HIITL_SYNC_CB_THRESHOLD', 'sync_config.circuit_breaker_threshold', 'number'],
  ['HIITL_SYNC_CB_RESET', 'sync_config.circuit_breaker_reset', 'number'],
  ['HIITL_SYNC_MAX_STALE', 'sync_config.max_cache_stale_age', 'number'],
  ['HIITL_SYNC_TIMEOUT', 'sync_config.sync_timeout', 'number'],
  ['HIITL_SYNC_MAX_RETRIES', 'sync_config.sync_max_retries', 'number'],
  ['HIITL_TELEMETRY_INTERVAL', 'sync_config.telemetry_sync_interval', 'number'],
  ['HIITL_TELEMETRY_BUFFER_SIZE', 'sync_config.telemetry_buffer_size', 'number'],
  ['HIITL_TELEMETRY_SAMPLE_RATE', 'sync_config.telemetry_sample_rate', 'number'],
  ['HIITL_TELEMETRY_PARAMETER_TOOLS', 'sync_config.telemetry_parameter_tools', 'list'],
];

/**
 * The families the SDK's specs give it (sync_engine.md section 9, telemetry_schema.md section 5): a set name in one
 * that no setting reads is refused at construction (row 207).
 */
export const SETTING_FAMILIES = ['HIITL_SYNC_', 'HIITL_TELEMETRY_'] as const;
const [SYNC_FAMILY, TELEMETRY_FAMILY] = SETTING_FAMILIES;

/**
 * Each telemetry setting's earlier name, the sync prefix and its option's name (as the Python SDK's earlier releases
 * read it), and the name it is read under now (telemetry_schema.md section 5, "Names earlier releases read").
 */
export const EARLIER_NAMES: Record<string, string> = Object.fromEntries(
  ENV_SETTINGS.filter(([name]) => name.startsWith(TELEMETRY_FAMILY)).map(([name, option]) => [
    SYNC_FAMILY + option.split('.').pop()!.toUpperCase(),
    name,
  ]),
);

/**
 * Refuse each set variable of a family that no setting reads, naming its replacement or the names the family's
 * settings read (row 207: "a set `HIITL_*` variable no setting reads is refused at construction, naming its
 * replacement"). A variable set to the empty string carries no value and is not read.
 */
function refuseUnreadVariables(environ: NodeJS.ProcessEnv): void {
  const read = ENV_SETTINGS.map(([name]) => name);
  const refused: string[] = [];
  for (const variable of Object.keys(environ).sort()) {
    const family = SETTING_FAMILIES.find((f) => variable.toUpperCase().startsWith(f));
    if (!environ[variable] || family === undefined || read.includes(variable)) continue;
    const replacement = EARLIER_NAMES[variable.toUpperCase()];
    refused.push(
      replacement
        ? `${variable} is a name an earlier release read; this release reads ${replacement}. ` +
            `Set ${replacement} instead, and unset ${variable}.`
        : `${variable} is set, and no setting reads it. The ${family}* variables a setting reads: ` +
            `${read.filter((name) => name.startsWith(family)).sort().join(', ')}.`,
    );
  }
  if (refused.length) {
    throw new ConfigurationError(
      `${refused.join('\n')}\n\nA HIITL_SYNC_* or HIITL_TELEMETRY_* variable no setting reads is refused ` +
        '(docs/specs/sync_engine.md section 9; telemetry_schema.md section 5).',
    );
  }
}

/** The telemetry family's ranges (telemetry_schema.md section 5): a value outside one is refused naming it (row 208). */
const TelemetrySettingsSchema = z.object({
  telemetry_sync_interval: ranged('telemetry_sync_interval (HIITL_TELEMETRY_INTERVAL)', 5, 3600).int().optional(),
  telemetry_buffer_size: ranged('telemetry_buffer_size (HIITL_TELEMETRY_BUFFER_SIZE)', 10, 1000).int().optional(),
  telemetry_sample_rate: ranged('telemetry_sample_rate (HIITL_TELEMETRY_SAMPLE_RATE)', 0, 1).optional(),
  telemetry_parameter_tools: z
    .array(z.string(), { message: 'telemetry_parameter_tools is a list of action names' })
    .optional(),
});

// A diagnostic uses the settings' owning fields, not a second set of ranges.
// SyncSettingsInput declares numbers; the telemetry reader adds its narrower
// integer/range declarations. This shape is diagnostic, never a new validator.
export const SyncNumberSchema=z.object({
  ...Object.fromEntries(ENV_SETTINGS.filter(([,path,kind])=>path.startsWith('sync_config.')&&kind==='number')
    .map(([,path])=>[path.split('.')[1],z.number().optional()])),
  ...TelemetrySettingsSchema.shape,
});
const ConstructorNumberSchema=z.object({...LocalModeConfigObject.shape,...HostedModeConfigObject.shape,
  sync_init_timeout:z.number().optional(),sync_config:SyncNumberSchema.optional()});

// The boolean spellings the Python SDK's settings accept, so one value reads the same in both.
const TRUE_TEXT = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
const FALSE_TEXT = new Set(['0', 'off', 'f', 'false', 'n', 'no']);

function readEnvValue(name: string, text: string, kind: EnvKind): unknown {
  if (kind === 'string') return text;
  if (kind === 'list') {
    let list: unknown;
    try {
      list = JSON.parse(text);
    } catch {
      list = undefined;
    }
    if (!Array.isArray(list) || !list.every((item) => typeof item === 'string')) {
      throw new ConfigurationError(
        `${name}='${text}' is not a JSON list of action names. Set it to one, e.g. '["process_payment"]', or unset it.`,
      );
    }
    return list;
  }
  if (kind === 'number') {
    const n = Number(text);
    if (text.trim() === '' || !Number.isFinite(n)) {
      throw new ConfigurationError(`${name}='${text}' is not a number. Set it to a number, or unset it.`);
    }
    return n;
  }
  const t = text.trim().toLowerCase();
  if (TRUE_TEXT.has(t)) return true;
  if (FALSE_TEXT.has(t)) return false;
  throw new ConfigurationError(`${name}='${text}' is not a boolean. Set it to true or false, or unset it.`);
}

/**
 * Read every `ENV_SETTINGS` variable that is set (and not empty) into the options it sets.
 * Unset variables are omitted so they don't override constructor args.
 */
function parseEnvVars(): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [name, key, kind] of ENV_SETTINGS) {
    const text = process.env[name];
    if (text === undefined || text === '') continue;
    const value = readEnvValue(name, text, kind);
    const [head, tail] = key.split('.');
    if (tail === undefined) {
      result[head] = value;
    } else {
      result[head] = { ...(result[head] as Record<string, unknown> | undefined), [tail]: value };
    }
  }
  return result;
}

/**
 * Every option the constructor takes, and every sync setting, read from `HIITLConfigInput` and `SyncSettingsInput`
 * themselves: the compiler holds each record to its interface both ways.
 */
const DEFINED_OPTIONS = {
  environment: true, agent_id: true, org_id: true, mode: true, policy_path: true, audit_db_path: true,
  enable_rate_limiting: true, routes_path: true, signature_key: true, dedup_window_seconds: true, redact_fields: true,
  recorded_parameters: true, api_key: true, server_url: true, timeout: true, max_retries: true, fail_mode: true,
  sync: true,
  evaluation: true, cold_start_behavior: true, cache_dir: true, sync_init_timeout: true, sync_config: true,
  principal_verifier: true, route_fetch: true, telemetry_level: true,
} satisfies Record<keyof HIITLConfigInput, true>;

const DEFINED_SYNC_SETTINGS = {
  audit_sync_interval: true, policy_sync_interval: true, route_sync_interval: true, kill_switch_poll_interval: true,
  audit_batch_size: true, max_buffer_records: true, max_buffer_size_bytes: true, circuit_breaker_threshold: true,
  circuit_breaker_reset: true, max_cache_stale_age: true, sync_timeout: true, sync_max_retries: true,
  telemetry_sync_interval: true, telemetry_buffer_size: true, telemetry_sample_rate: true,
  telemetry_parameter_tools: true,
} satisfies Record<keyof SyncSettingsInput, true>;

/**
 * The options are strict: a key the constructor does not define is refused, naming it, with the option it most likely
 * meant where exactly one matches it once case and underscores are set aside (`orgID` → `org_id`). No field is ever
 * silently dropped (R-0872; HTL-22 row 165).
 */
function refuseUnknownKeys(given: object, known: object, where: string): void {
  const fold = (k: string) => k.toLowerCase().replace(/_/g, '');
  const unknown = Object.keys(given).filter((k) => !Object.prototype.hasOwnProperty.call(known, k));
  if (!unknown.length) return;
  const named = unknown.map((k) => {
    const like = Object.keys(known).filter((o) => fold(o) === fold(k));
    return like.length === 1 ? `'${k}' (did you mean '${like[0]}'?)` : `'${k}'`;
  });
  throw new ConfigurationError(
    `Unknown ${where}: ${named.join(', ')}. The ${where === 'option' ? 'options' : 'sync settings'} are ` +
      `${Object.keys(known).join(', ')}.`
  );
}

/**
 * The constructor's settings: each option passed wins, then its HIITL_* variable, then
 * (left unset here) its default. `sync_config` merges setting by setting.
 */
export function resolveSettings(options: HIITLConfigInput): HIITLConfigInput {
  refuseUnreadVariables(process.env);
  refuseUnknownKeys(options, DEFINED_OPTIONS, 'option');
  if (options.sync_config) refuseUnknownKeys(options.sync_config, DEFINED_SYNC_SETTINGS, 'sync setting');
  const merged = mergeWithEnv(options as Record<string, unknown>);
  assertSchemaNumbers(merged,ConstructorNumberSchema);
  const envSync = parseEnvVars().sync_config as SyncSettingsInput | undefined;
  if (envSync || options.sync_config) {
    merged.sync_config = { ...envSync, ...definedOnly(options.sync_config ?? {}) };
    const telemetry = TelemetrySettingsSchema.safeParse(merged.sync_config);
    if (!telemetry.success) {
      throw new ConfigurationError(
        `Invalid telemetry setting: ${telemetry.error.issues.map((issue) => issue.message).join('; ')}`,
      );
    }
  }
  return merged as HIITLConfigInput;
}

function definedOnly(o: object): Record<string, unknown> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));
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
  return { ...parseEnvVars(), ...definedOnly(options) };
}

/** @internal The constructor already admitted the owned resolved settings. */
export const _createResolvedConfig=(options:LocalModeConfigInput):LocalModeConfig=>parseAdmittedNumbers(LocalModeConfigSchema,options);
/** @internal No new source or environment read occurs between resolution and this parse. */
export const _createResolvedHostedConfig=(options:HostedModeConfigInput):HostedModeConfig=>parseAdmittedNumbers(HostedModeConfigSchema,options);
