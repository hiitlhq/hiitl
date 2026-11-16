/**
 * HIITL SDK Client - Main developer-facing API.
 *
 * Single entry point: evaluate(). Mode is auto-detected from constructor arguments:
 * - **No api_key**, or **sync: false**: Local evaluation with embedded evaluator
 * - **api_key** (the default architecture): Hybrid — local evaluation + background sync
 * - **api_key + evaluation: 'remote'**: Hosted evaluation via ECP server (explicit opt-in)
 *
 * Every option left unset is read from its HIITL_* environment variable, then falls to its
 * default (`ENV_SETTINGS` in config.ts lists them).
 *
 * @example Zero-config (OBSERVE_ALL mode)
 * ```typescript
 * const hiitl = new HIITL();
 *
 * const decision = hiitl.evaluate({ action: 'send_email' });
 * if (decision.allowed) {
 *   sendEmail(...);
 * }
 * ```
 *
 * @example Local with policy (RESPECT_POLICY mode)
 * ```typescript
 * const hiitl = new HIITL({
 *   environment: 'dev',
 *   agent_id: 'payment-agent',
 *   policy_path: './policy.yaml',
 *   org_id: 'org_mycompany123456789',
 *   mode: 'RESPECT_POLICY',
 * });
 *
 * const decision = hiitl.evaluate({
 *   action: 'payment_transfer',
 *   parameters: { amount: 500, currency: 'USD' },
 * });
 * ```
 *
 * @example Hosted (api_key + server_url + evaluation: 'remote')
 * ```typescript
 * const hiitl = new HIITL({
 *   environment: 'prod',
 *   agent_id: 'payment-agent',
 *   org_id: 'org_mycompany123456789',
 *   api_key: 'your-api-key',
 *   server_url: 'https://api.hiitl.com',
 *   signature_key: '...', // the API key's signing secret, shown when the key was created
 *   evaluation: 'remote',
 *   mode: 'RESPECT_POLICY',
 * });
 *
 * const decision = await hiitl.evaluate({
 *   action: 'payment_transfer',
 *   parameters: { amount: 500, currency: 'USD' },
 * });
 * ```
 */

import crypto from 'node:crypto';
import { z } from 'zod';
import {
  PolicyEvaluator,
  OperatorKindError,
  EnvelopeSchema,
  ENVELOPE_SCHEMA_VERSION,
  PolicySetSchema,
  DecisionType,
  Operation,
  routing,
  observe,
  limiterFailed,
  envelopeHash,
  envelopeSignature,
  envelopeVerifies,
  Redaction,
  assertNumericDomain,
  assertSchemaNumbers,
  ResultNumberSchema,
  parseAdmittedNumbers,
  copySuppliedInput,
  NumericDomainError,
} from '@hiitl/core';
import type {
  CostEstimate,
  Envelope,
  Decision,
  PolicySet,
  Sensitivity,
  Principal,
} from '@hiitl/core';
import { ERROR_MESSAGES, auditWriteFailed, errorBlock, errorDecision } from '@hiitl/core';
import { LIFECYCLE_MESSAGES, executionResult, recordedResult, resultRefusal, unreadReview } from '@hiitl/core';
import {
  DEFAULT_SERVER_URL, _createResolvedConfig, _createResolvedHostedConfig, resolveSettings, serverUrlRefusal, LocalModeConfigSchema,
  TELEMETRY_LEVELS,
} from './config.js';
import type {
  LocalModeConfig,
  LocalModeConfigInput,
  HostedModeConfig,
  HostedModeConfigInput,
  HIITLConfigInput,
  PrincipalVerifier,
} from './config.js';

type HIITLMode = 'local' | 'hosted' | 'hybrid';
type ColdStartBehavior = 'warn-and-observe' | 'fail-closed' | 'observe-silent';

import { PolicyLoader } from './policy-loader.js';
import { RouteLoader, resolveEscalationContext } from './route-loader.js';
import { AuditLogger } from './audit.js';
import { RateLimiter } from './rate-limiter.js';
import { HostedClient } from './http-client.js';
import type { CircuitBreakerStatus } from './circuit-breaker.js';
import { SyncCache } from './sync-cache.js';
import { SyncEngine } from './sync-engine.js';
import { activeTraceId } from './trace-context.js';
import {
  ConfigurationError,
  EnvelopeValidationError,
  PolicyLoadError,
  AuditLogError,
  ColdStartError,
  LifecycleError,
} from './exceptions.js';

const VALID_COLD_START_BEHAVIORS: ReadonlySet<ColdStartBehavior> = new Set([
  'warn-and-observe',
  'fail-closed',
  'observe-silent',
]);
const DEFAULT_SYNC_INIT_TIMEOUT_SEC = 10;
const VALID_EVALUATIONS: ReadonlySet<string> = new Set(['local', 'remote']);

/** What an empty policy set does under each evaluation mode (the cold-start message names the one in force). */
const EMPTY_POLICY_OUTCOME = {
  OBSERVE_ALL: 'running in OBSERVE_ALL: every action is observed and allowed',
  RESPECT_POLICY: 'running in RESPECT_POLICY with no policy loaded: every action is blocked (NO_MATCHING_RULE)',
} as const;

/**
 * The envelope's operation, or EnvelopeValidationError naming the valid ones
 * (Principle 11; HTL-20, row 145). Every mode reads it here, so the text is
 * the same in local, hybrid and hosted.
 */
function checkOperation(value: Operation | string | undefined): Operation {
  const operation = value ?? 'execute';
  const valid: string[] = Object.values(Operation);
  if (!valid.includes(operation)) {
    const message =
      `operation '${operation}' is not a valid operation. Use one of: ${valid.join(', ')} ` +
      "(the default is 'execute').";
    throw new EnvelopeValidationError(message, [`operation: ${message}`]);
  }
  return operation as Operation;
}

/** Cost estimate for an action: the envelope's own (envelope_schema.json v1.4 `cost_estimate`). */
export type { CostEstimate };

/**
 * Options for evaluate() method.
 *
 * Only `action` is required. Everything else has sensible defaults.
 */
/** What `status()` returns. */
export interface HIITLStatus {
  mode: 'local' | 'hybrid' | 'hosted';
  environment?: string;
  org_id?: string;
  sync?: Record<string, unknown>;
  policy_version?: string | null;
  cache_age_seconds?: number | null;
  server_url?: string;
  circuit_breakers?: { hosted: CircuitBreakerStatus };
}

export interface EvaluateOptions {
  /** Action name (e.g., "process_payment", "send_email"). */
  action: string;
  /** Operation type (default: "execute"). */
  operation?: Operation | string;
  /** Target resource (default: {}). */
  target?: Record<string, unknown>;
  /** Parameters for the action (default: {}). */
  parameters?: Record<string, unknown>;
  /** User identifier. */
  user_id?: string;
  /** Session identifier. */
  session_id?: string;
  /** Agent ID override for this call (overrides init default). */
  agent_id?: string;
  /** Agent confidence 0-1. */
  confidence?: number;
  /** Reasoning for action. */
  reason?: string;
  /** Sensitivity labels. */
  sensitivity?: Sensitivity[];
  /** Cost estimate. */
  cost_estimate?: CostEstimate;
  /**
   * Permission scopes this call requests (envelope_schema.json `requested_scopes`):
   * free strings the caller supplies, distinct from the verified principal's scopes.
   */
  requested_scopes?: string[];
  /** Idempotency key (auto-generated if omitted). */
  idempotency_key?: string;
  /**
   * A token for the configured principal_verifier (T-130 A7). The envelope's
   * verified `principal` is set from what the verifier returns.
   */
  principal_token?: string;
  /**
   * Your own id tying this action to others, e.g. a request id; recorded in the envelope as given. `trace_id` is not
   * an option: the SDK sets it from the active OpenTelemetry span when `@opentelemetry/api` is installed.
   */
  correlation_id?: string;
}

// The token is a native-call argument, not a member of the recorded envelope.
// This declaration is diagnostic only; it does not parse or project the call.
const EvaluateNumbers=EnvelopeSchema.extend({
  principal_token: z.string().optional() satisfies z.ZodType<EvaluateOptions['principal_token']>,
});

/**
 * HIITL client for policy evaluation.
 *
 * Mode is auto-detected from constructor arguments:
 * - No api_key, or sync: false → local (embedded evaluation)
 * - api_key → hybrid (local evaluation + background sync)
 * - api_key + evaluation: 'remote' → hosted (ECP server; needs server_url)
 *
 * Zero-config: `new HIITL()` works with defaults (OBSERVE_ALL mode).
 */
export class HIITL {
  /** Decision types that trigger route config resolution. */
  private static readonly ESCALATION_TYPES = new Set<string>([
    DecisionType.REQUIRE_APPROVAL,
    DecisionType.PAUSE,
    DecisionType.ESCALATE,
  ]);

  private readonly _mode: HIITLMode;
  private readonly _evalMode: 'OBSERVE_ALL' | 'RESPECT_POLICY';

  // Local mode components (only initialized in local mode)
  public readonly config?: LocalModeConfig;
  private policyLoader?: PolicyLoader;
  private evaluator?: PolicyEvaluator;
  private auditLogger?: AuditLogger;
  private readonly _redaction: Redaction;
  private rateLimiter?: RateLimiter;
  private routeLoader?: RouteLoader;
  private _zeroConfigPolicy?: PolicySet;

  // Hosted mode components (only initialized in hosted mode)
  public readonly hostedConfig?: HostedModeConfig;
  private hostedClient?: HostedClient;
  private _principalVerifier?: PrincipalVerifier;
  private _routeFetch: typeof fetch = (...a) => globalThis.fetch(...a);

  // Hybrid mode components (only initialized in hybrid mode — TICKET-121)
  private syncCache?: SyncCache;
  private syncEngine?: SyncEngine;
  private readonly _coldStartBehavior: ColdStartBehavior;
  private readonly _serverUrl?: string;
  private readonly _syncInitTimeoutSec: number;
  /**
   * Resolves to `true` if the cold-start sync populated the cache,
   * `false` if it timed out or failed. Constructed in `_initHybrid`
   * and awaited by `evaluate()` in fail-closed mode before deciding
   * whether to throw `ColdStartError`. Stays a no-op in non-hybrid
   * modes — `evaluate()` only awaits it when it needs to.
   */
  private _initialSyncPromise: Promise<boolean> = Promise.resolve(false);
  /** True once the initial-sync resolution has been observed at least once. */
  private _initialSyncResolved = false;

  /**
   * Initialize HIITL client.
   *
   * Mode is auto-detected:
   * - No api_key → local
   * - api_key → hybrid (a server_url sets the sync target)
   * - api_key + evaluation: 'remote' → hosted (the explicit opt-in; needs server_url)
   * - sync: false forces local even with api_key
   *
   * Each option left unset is read from its HIITL_* environment variable
   * (`ENV_SETTINGS` in config.ts), then falls to its default.
   *
   * Zero-config: `new HIITL()` works with OBSERVE_ALL defaults.
   *
   * @param options - Configuration options (all optional for zero-config)
   * @throws {ConfigurationError} If configuration is invalid
   * @throws {PolicyLoadError} If policy file cannot be loaded (local/hybrid)
   * @throws {AuditLogError} If audit database cannot be initialized (local/hybrid)
   */
  constructor(input: HIITLConfigInput = {}) {
    let options: HIITLConfigInput;
    try {
      options = resolveSettings(input);
    } catch (e: any) {
      if (e instanceof ConfigurationError) throw e;
      throw new ConfigurationError(`Invalid HIITL configuration: ${e.message}`);
    }
    const sync = options.sync ?? true;
    this._principalVerifier = options.principal_verifier;
    if (options.route_fetch) this._routeFetch = options.route_fetch;
    this._evalMode = options.mode ?? 'OBSERVE_ALL';

    // TICKET-121: validate cold_start_behavior up front so a typo
    // fails the constructor instead of being silently ignored at
    // sync-failure time. Default mirrors Python: warn-and-observe.
    const coldStartBehavior =
      options.cold_start_behavior ?? 'warn-and-observe';
    if (!VALID_COLD_START_BEHAVIORS.has(coldStartBehavior)) {
      throw new ConfigurationError(
        `cold_start_behavior='${coldStartBehavior}' is invalid. ` +
          `Must be one of: ${[...VALID_COLD_START_BEHAVIORS].sort().join(', ')}.`
      );
    }
    this._coldStartBehavior = coldStartBehavior;
    const evaluation = options.evaluation ?? 'local';
    if (!VALID_EVALUATIONS.has(evaluation)) {
      throw new ConfigurationError(
        `evaluation='${evaluation}' is invalid. Must be one of: ${[...VALID_EVALUATIONS].sort().join(', ')}. ` +
          "'remote' is the explicit opt-in to hosted evaluation."
      );
    }
    // telemetry_schema.md section 5's levels. No collector ships here, so no level sends anything; a value outside
    // them is refused as in the Python SDK (row 172).
    const telemetryLevel = options.telemetry_level ?? 'standard';
    if (!(TELEMETRY_LEVELS as readonly string[]).includes(telemetryLevel)) {
      throw new ConfigurationError(
        `telemetry_level='${telemetryLevel}' is invalid. ` +
          `Must be one of: ${TELEMETRY_LEVELS.map((level) => `'${level}'`).join(', ')}. ` +
          "'standard' sends counts and no parameter value; 'off' sends no telemetry."
      );
    }
    // the URL the API key and the records go to, in every mode that sends (sync_engine.md section 8; row 140)
    const serverRefusal = options.server_url === undefined ? null : serverUrlRefusal(options.server_url);
    if (serverRefusal) throw new ConfigurationError(serverRefusal);
    this._serverUrl = options.server_url;
    this._syncInitTimeoutSec =
      options.sync_init_timeout ?? DEFAULT_SYNC_INIT_TIMEOUT_SEC;

    // Mode detection, the deployment modes page's table (docs-site/concepts/deployment-modes.mdx; client.py does the same):
    // api_key + evaluation 'remote' → hosted (explicit opt-in)
    // api_key present, sync on → hybrid (default architecture)
    // no api_key, or sync: false → local
    if (options.api_key && evaluation === 'remote') {
      this._mode = 'hosted';
    } else if (options.api_key && sync) {
      this._mode = 'hybrid';
    } else {
      this._mode = 'local';
    }

    // What the local store records (event_format.md §Redaction, row 139); in hosted mode, the records the client
    // holds when the service could not take them (Stop B (i)).
    try {
      this._redaction = Redaction.declared(options.redact_fields, options.recorded_parameters);
    } catch (e: any) {
      throw new ConfigurationError(e.message);
    }

    if (this._mode === 'hosted') {
      if (!options.server_url) {
        throw new ConfigurationError(
          "server_url is required for hosted evaluation (evaluation: 'remote').\n\n" +
            'Provide your ECP server URL:\n' +
            "  new HIITL({ api_key: '...', server_url: 'https://api.hiitl.com', evaluation: 'remote' })\n\n" +
            'Or use the default hybrid mode (recommended) — local eval + sync:\n' +
            "  new HIITL({ api_key: '...' })"
        );
      }
      this._initHosted(options as HostedModeConfigInput);
    } else {
      // Pure-local mode requires policy_path under RESPECT_POLICY (no
      // sync cache to provide one). Hybrid mode accepts no policy_path
      // because the sync engine populates the cache — policy_path
      // becomes an optional file-based fallback.
      if (
        this._mode === 'local' &&
        !options.policy_path &&
        this._evalMode === 'RESPECT_POLICY'
      ) {
        throw new ConfigurationError(
          'policy_path is required when mode is RESPECT_POLICY in pure-local mode.\n\n' +
            'Either provide a policy file:\n' +
            "  new HIITL({ policy_path: './policy.yaml', mode: 'RESPECT_POLICY' })\n\n" +
            'Or use OBSERVE_ALL mode (default) for zero-config:\n' +
            '  new HIITL()\n\n' +
            'Or use hybrid mode (policies sync from server):\n' +
            "  new HIITL({ api_key: 'sk_...' })"
        );
      }

      // Local-mode components are needed by both local AND hybrid modes
      // (hybrid = local evaluator + sync engine + sync cache layered on top).
      this._initLocal(options as LocalModeConfigInput);

      if (this._mode === 'hybrid') {
        this._initHybrid(options);
      }
    }
    this._warnOnCodeLevelOverride();
  }

  /**
   * Warn when the code-level OBSERVE_ALL override is in force in prod (ecp_evaluate_spec.md, Resolved
   * Design Decision 1: "If a code-level override is active in a production environment, the SDK logs a
   * warning"). Hosted mode evaluates on the server, which applies its own mode. Mirrors client.py.
   * @private
   */
  private _warnOnCodeLevelOverride(): void {
    if (this._mode !== 'hosted' && this.config?.environment === 'prod' && this._evalMode === 'OBSERVE_ALL') {
      console.warn(
        'HIITL is running in OBSERVE_ALL in the prod environment: every action is allowed, ' +
          "whatever the policy says. Production uses RESPECT_POLICY, with each rule's " +
          "lifecycle_stage set in the policy: new HIITL({ mode: 'RESPECT_POLICY' }) or HIITL_MODE=RESPECT_POLICY."
      );
    }
  }

  /** Current mode: 'local', 'hosted', or 'hybrid'. */
  get mode(): HIITLMode {
    return this._mode;
  }

  /** Current evaluation mode: 'OBSERVE_ALL' or 'RESPECT_POLICY'. */
  get evalMode(): 'OBSERVE_ALL' | 'RESPECT_POLICY' {
    return this._evalMode;
  }

  private _initLocal(options: LocalModeConfigInput): void {
    try {
      (this as any).config = _createResolvedConfig(options);
    } catch (e: any) {
      throw new ConfigurationError(
        `Invalid HIITL configuration: ${e.message}\n\n` +
          'Check that all required parameters are provided and valid.'
      );
    }

    try {
      if (this.config!.policy_path) {
        this.policyLoader = new PolicyLoader(this.config!.policy_path);
        this.policyLoader.load();
      }
      this.evaluator = new PolicyEvaluator();
      // In hybrid mode each write redacts the org's declared fields, as last pulled, with the SDK's own (row 163(a))
      this.auditLogger = new AuditLogger(
        this.config!.audit_db_path,
        this._redaction,
        this._mode === 'hybrid' ? () => this.syncCache?.getRedactionFields() ?? [] : undefined
      );
      this.rateLimiter = this.config!.enable_rate_limiting
        ? new RateLimiter()
        : undefined;
      this.routeLoader = this.config!.routes_path
        ? new RouteLoader(this.config!.routes_path)
        : undefined;
    } catch (e: any) {
      if (e instanceof PolicyLoadError || e instanceof AuditLogError) {
        throw e;
      }
      throw new ConfigurationError(
        `Failed to initialize HIITL components: ${e.message}`
      );
    }
  }

  /**
   * Initialize hybrid mode — local evaluation + background sync engine.
   *
   * Mirrors Python's `_init_hybrid` (TICKET-116) within JS constraints:
   * the constructor cannot block on `initialSync` because JS constructors
   * cannot be async. Instead:
   *   1. Create the SyncCache and synchronously kick off `loadFromDisk`
   *      (an async operation; its result feeds the cold-start branch).
   *   2. Create the SyncEngine.
   *   3. Fire `initialSync` in the background, store the resulting promise
   *      on `_initialSyncPromise`. Log the outcome per cold_start_behavior.
   *   4. Start the engine's background tick loop.
   *
   * Cold-start enforcement (fail-closed) happens at the first `evaluate()`
   * call instead of the constructor — see `_awaitInitialSyncIfFailClosed`.
   *
   * @private
   */
  private _initHybrid(options: HIITLConfigInput): void {
    const { max_cache_stale_age, ...engineSettings } = options.sync_config ?? {};
    try {
      this.syncCache = new SyncCache({
        cache_dir: options.cache_dir,
        org_id: this.config!.org_id,
        environment: this.config!.environment,
        max_stale_age: max_cache_stale_age,
      });

      this.syncEngine = new SyncEngine({
        sync_config: {
          ...engineSettings,
          server_url: this._serverUrl ?? DEFAULT_SERVER_URL,
        },
        sync_cache: this.syncCache,
        audit_logger: this.auditLogger! as unknown as any,
        api_key: options.api_key!,
        org_id: this.config!.org_id,
        environment: this.config!.environment,
      });
    } catch (e: any) {
      throw new ConfigurationError(
        `Failed to initialize hybrid mode: ${e.message ?? e}`
      );
    }

    // Background cold-start sequence: load from disk → if cold, initial
    // sync → start background ticks. Captured into `_initialSyncPromise`
    // so evaluate() can await it in fail-closed mode.
    this._initialSyncPromise = this._coldStartSequence(
      this.syncCache,
      this.syncEngine,
      this._syncInitTimeoutSec
    );
  }

  /**
   * Full cold-start sequence for hybrid mode. Runs async without blocking
   * the constructor. Resolves to `true` if the cache was populated by
   * either disk-load or a successful initial sync.
   *
   * Cold-start failure with a local policy file: evaluation uses the file until
   * background sync succeeds (INFO log), as client.py does. Without one, handling
   * depends on `_coldStartBehavior`:
   *   - fail-closed: error path — `evaluate()` will throw on next call
   *   - warn-and-observe (default): WARNING log, continue with the empty policy set
   *   - observe-silent: INFO log, continue with the empty policy set
   *
   * @private
   */
  private async _coldStartSequence(
    cache: SyncCache,
    engine: SyncEngine,
    timeoutSec: number
  ): Promise<boolean> {
    const hadDiskCache = await cache.loadFromDisk();

    let initialOk = hadDiskCache;
    if (!hadDiskCache) {
      try {
        initialOk = await engine.initialSync(timeoutSec);
      } catch (e: any) {
        initialOk = false;
      }
      const target = this._serverUrl ?? DEFAULT_SERVER_URL;
      if (!initialOk && this.policyLoader) {
        console.info(
          `Cold-start sync to ${target} did not complete within ${timeoutSec.toFixed(1)}s. Using the local ` +
            `policy file as fallback, in ${this._evalMode}, until background sync succeeds: ${this.config!.policy_path}`
        );
      } else if (!initialOk) {
        const msg =
          `Cold-start sync to ${target} ` +
          `did not complete within ${timeoutSec.toFixed(1)}s. No disk ` +
          `cache and no local policy fallback — ${EMPTY_POLICY_OUTCOME[this._evalMode]} ` +
          `until background sync succeeds. Every Decision will carry ` +
          `cache_status='empty' until then. ` +
          `Set cold_start_behavior='fail-closed' to refuse evaluation ` +
          `instead.`;
        if (this._coldStartBehavior === 'warn-and-observe') {
          console.warn(msg);
        } else if (this._coldStartBehavior === 'observe-silent') {
          console.info(msg);
        }
        // fail-closed: no log here — the ColdStartError thrown at
        // evaluate-time carries the user-facing message.
      }
    }

    // Start background ticks regardless of cold-start outcome. The engine
    // keeps retrying; a later tick may succeed and flip cacheStatus to
    // 'synced'.
    try {
      engine.start();
    } catch (e: any) {
      // If start() throws (very rare — config or already-started),
      // we don't have a great recovery path; surface as a warning so
      // the operator can see it. evaluate() continues to function.
      console.warn(
        `Hybrid sync engine failed to start: ${e.message ?? e}. ` +
          'Local evaluation continues; sync is offline.'
      );
    }

    this._initialSyncResolved = true;
    return initialOk;
  }

  /**
   * Await the cold-start sync iff fail-closed and we haven't yet observed
   * a successful sync. After this returns, callers know the cache is
   * either populated (continue) or empty (throw ColdStartError).
   *
   * No-op for warn-and-observe + observe-silent — those modes continue
   * with whatever the current cacheStatus is.
   *
   * @private
   */
  private async _enforceFailClosedIfNeeded(): Promise<void> {
    if (this._coldStartBehavior !== 'fail-closed') return;
    if (!this.syncCache) return; // Should not happen in hybrid mode, defensive
    if (this.policyLoader) return; // the local policy file is the fallback: the policy set is not empty
    const status = this.syncCache.cacheStatus();
    if (status === 'synced' || status === 'from_disk') return;

    // status === 'empty' — wait for the initial-sync promise to resolve
    // and re-check. If still empty after the wait, throw.
    await this._initialSyncPromise;
    if (this.syncCache.cacheStatus() === 'empty') {
      throw new ColdStartError(
        this._serverUrl ?? DEFAULT_SERVER_URL,
        this._syncInitTimeoutSec
      );
    }
  }

  private _initHosted(options: HostedModeConfigInput): void {
    // the defaults local and hybrid take (LocalModeConfigSchema's), so the same options configure every mode
    const { environment, agent_id, org_id } = _createResolvedConfig({});
    try {
      (this as any).hostedConfig = _createResolvedHostedConfig({ environment, agent_id, org_id, ...options });
    } catch (e: any) {
      throw new ConfigurationError(
        `Invalid HIITL configuration: ${e.message}\n\n` +
          'Required for hosted evaluation: environment, agent_id, org_id, api_key, server_url'
      );
    }

    if (!this.hostedConfig!.signature_key) {
      throw new ConfigurationError(
        "Hosted evaluation needs signature_key: the service refuses an envelope that is not signed with the API " +
          "key's signing secret (403 SIGNATURE_INVALID). The secret is shown once, beside the key, when the key is " +
          "created (the API keys page; the create response's signing_secret). Pass " +
          'new HIITL({ ..., signature_key: <signing secret> }) or set HIITL_SIGNATURE_KEY.'
      );
    }
    this.hostedClient = HostedClient._fromAdmitted(this.hostedConfig!, this._redaction);
  }

  /**
   * SDK health: the mode, and in hybrid mode the sync state, the policy version and the cache's age; in hosted mode
   * the server and its circuit breaker, as the sync engine names its own (decision_response.md "Where the error is
   * answered", row 198). Mirrors client.py `status()`.
   */
  status(): HIITLStatus {
    const config = this.config ?? this.hostedConfig;
    const result: HIITLStatus = { mode: this._mode, environment: config?.environment, org_id: config?.org_id };
    if (this._mode === 'hybrid' && this.syncEngine) {
      result.sync = this.syncEngine.status();
      const cached = this.syncCache?.getPolicies();
      result.policy_version = cached ? ((cached.version as string | undefined) ?? null) : null;
      result.cache_age_seconds = cached ? Math.round(this.syncCache!.getPoliciesAgeSeconds() * 10) / 10 : null;
    } else if (this._mode === 'hosted') {
      result.server_url = this.hostedConfig!.server_url;
      result.circuit_breakers = { hosted: this.hostedClient!.breaker.status() };
    }
    return result;
  }

  /**
   * Evaluate an action against policy and return decision.
   *
   * Only `action` is required. Everything else has sensible defaults.
   *
   * In local mode, evaluation is synchronous and returns a Decision directly.
   * In hosted mode, evaluation is async and returns a Promise<Decision>.
   *
   * For consistent usage across modes, always await the result:
   * ```typescript
   * const decision = await hiitl.evaluate({ action: 'send_email' });
   * ```
   *
   * An error is a decision (decision_response.md "Error Handling"): in hosted mode an unreachable service is
   * CONTROL_PLANE_UNAVAILABLE with `allowed` false, never a thrown NetworkError; once the envelope exists, a failure
   * no step answers is BLOCK with AUDIT_READ_FAILED (the dedup read) or EVALUATION_FAILED (row 193).
   *
   * @param options - Evaluation options (only action required)
   * @returns Decision (or Promise<Decision> in hosted mode)
   */
  evaluate(options: EvaluateOptions): Decision | Promise<Decision> {
    const started=performance.now(); // the call's clock: its admission is counted in its timing (HTL-43 gap 303)
    options=copySuppliedInput(options);
    try {assertSchemaNumbers(options,EvaluateNumbers);} catch(error) {
      if(!(error instanceof NumericDomainError))throw error;
      throw new EnvelopeValidationError(error.message,[`${error.path.join('.')}: ${error.message}`]);
    }
    if (this._mode === 'hosted') {
      // the hosted service verifies the token with the org's configured verifier
      return this._evaluateHosted(options);
    }
    if (this._mode === 'hybrid') {
      // Hybrid mode is async-flavored — we may need to await the
      // cold-start sync in fail-closed mode before evaluating. Always
      // return a Promise so callers don't have to discriminate.
      return this._evaluateHybrid(options, started);
    }
    return this._evaluateLocal(options, started);
  }

  /**
   * Hybrid-mode evaluate wrapper. Awaits the cold-start sync iff
   * fail-closed, then delegates to the local evaluator (which reads
   * policies from the sync cache).
   *
   * @private
   */
  private async _evaluateHybrid(options: EvaluateOptions, started: number): Promise<Decision> {
    await this._enforceFailClosedIfNeeded();
    return this._evaluateLocal(options, started);
  }

  private _evaluateLocal(options: EvaluateOptions, started: number): Decision | Promise<Decision> {
    // Resolve agent_id: per-call override > init default
    const agentId = options.agent_id ?? this.config!.agent_id;

    // 1. Build envelope
    const envelope = this._builtEnvelope(options, agentId, this._verifiedPrincipal(options.principal_token));

    // Once the envelope exists, a failure no step below answers is BLOCK, fail-closed, recorded (row 193: "Never
    // return generic 500 errors without a decision response body"; Principle 7). Every step after a record is
    // written answers its own failure, so no envelope is recorded twice. Mirrors client.py `_evaluate_local`.
    // A caller's key is held in the audit store from the dedup read to the record's write (HTL-29 row 160).
    let decided: Decision | Promise<Decision>;
    try {
      const step = (): Decision | Promise<Decision> => this._decided(envelope, options.idempotency_key, started);
      decided =
        options.idempotency_key === undefined
          ? step()
          : this.auditLogger!.underKey(envelope.org_id, envelope.environment, options.idempotency_key, step);
    } catch (e: any) {
      return this._failedUnexpectedly(envelope, e);
    }
    return decided instanceof Promise ? decided.catch((e) => this._failedUnexpectedly(envelope, e)) : decided;
  }

  /**
   * The decision of a kill switch the tick's part binds, or null (sync_engine.md 2.4; HTL-29 row 240). The part is read
   * in the client's mode, and its decision stands where the evaluator names one of its switches as the binding rule:
   * KILL_SWITCH (observed: OBSERVE with would_be KILL_SWITCH), or under `fail_closed` the BLOCK of a switch the call
   * cannot read (condition 2, ruled 2026-11-10). What a switch stops is its rule, in the version the tick names.
   * Mirrors client.py `_switched`.
   * @private
   */
  private _switched(envelope: Envelope, part: PolicySet, ingestedMs: number): Decision | null {
    const decision = this.evaluator!._evaluateAdmittedEnvelope(envelope, part, this._evalMode, undefined, ingestedMs);
    return decision.matched_rules?.length ? decision : null;
  }

  /** A failure no step answered, logged with its cause and answered BLOCK / EVALUATION_FAILED (row 193). @private */
  private _failedUnexpectedly(envelope: Envelope, e: any): Decision {
    console.error(`Evaluation failed unexpectedly (fail-closed): ${e?.stack ?? e?.message ?? String(e)}`);
    return this._refused(envelope, 'BLOCK', 'EVALUATION_FAILED');
  }

  /**
   * Steps 1b to 8 of the local evaluation, for the envelope built: the decision, recorded. `started` is where the call's
   * clock started; a caller that enters here starts it here. @private
   */
  private _decided(envelope: Envelope, idempotencyKey: string | undefined, started: number = performance.now()): Decision | Promise<Decision> {
    // 1b. Verify before evaluating, with the same key (the security architecture §1.3: "The evaluator verifies
    // before processing"; row 134). Without a key there is nothing to verify against: the envelope carries zeros.
    // An envelope that does not verify is refused and recorded (§1.3: "action rejected with `SIGNATURE_INVALID`,
    // audit record written"; HTL-22 row 159).
    const key = this.config!.signature_key;
    if (key && !envelopeVerifies(key, envelope as unknown as Record<string, unknown>)) {
      console.warn(`Envelope ${envelope.action_id} does not verify under signature_key: refused (SIGNATURE_INVALID).`);
      return this._refused(envelope, 'SIGNATURE_INVALID', 'ENVELOPE_SIGNATURE_VERIFICATION_FAILED');
    }
    // The call's ingest, from its evaluate() through the signature check (decision_response.md Timing Metadata:
    // "validate envelope, check signature"). Each evaluation below counts from there (HTL-43 gap 303).
    const ingestedMs = performance.now() - started;

    // 1c. A repeated key. The caller's idempotency_key that this store already recorded, for an envelope within the
    // dedup window of this one's timestamp, returns that record's decision and writes no record (the security
    // architecture §1.3: "A replayed envelope produces a dedup hit, not a re-evaluation"; row 143). A key the SDK
    // generated is new by construction. A store that cannot be read for it is BLOCK, never a fresh evaluation
    // (row 193: "the same for a failed dedup read").
    if (idempotencyKey !== undefined) {
      let first: Decision | null;
      try {
        first = this.auditLogger!.firstDecisionUnderKey(
          envelope.org_id,
          envelope.environment,
          idempotencyKey,
          envelope.timestamp,
          this.config!.dedup_window_seconds
        );
      } catch (e: any) {
        console.error(
          `The first decision under the idempotency_key could not be read (fail-closed): ${e?.message ?? String(e)}`
        );
        return this._refused(envelope, 'BLOCK', 'AUDIT_READ_FAILED');
      }
      if (first) return first;
    }

    // 2. A kill-switch tick no pull has followed: the set it names decides first, and a switch that binds there stands
    // under the tick's version (sync_engine.md 2.4; HTL-29 row 240, ruled 2026-11-09). Elsewhere the version below
    // decides, as before. Mirrors client.py `_decided`.
    const part = this.syncCache ? this.syncCache.tickPart() : null;
    if (part) {
      let switched: Decision | null;
      try {
        switched = this._switched(envelope, part, ingestedMs);
      } catch (e: any) {
        return this._evaluationFailed(envelope, e);
      }
      if (switched) return this._afterEvaluate(envelope, switched);
    }

    // 2b. Load policy. Priority (hybrid mode):
    //      1. Sync cache (server-managed policies)
    //      2. Local policy loader (file-based fallback)
    //      3. Empty policy set (OBSERVE_ALL)
    // In pure-local mode the sync cache is undefined and we skip step 1.
    let policy: PolicySet | undefined;

    if (this.syncCache) {
      // Read through the model where it was received (R-0872): a policy it refused was rejected there, naming the
      // field, and the next source decides (sync_engine.md §6 precedence; Numeric domain). Mirrors client.py
      // _resolve_policy.
      policy = this.syncCache.getPolicySet() ?? undefined;
    }

    // A policy that cannot be had is POLICY_ERROR, its cause the loader's reason (Error Handling: "Policy file not
    // found, invalid policy syntax"); the loader's text is logged.
    if (!policy && this.policyLoader) {
      try {
        policy = this.policyLoader.load();
      } catch (e: any) {
        console.error(`Policy could not be loaded (fail-closed): ${e?.message ?? String(e)}`);
        return this._refused(envelope, 'POLICY_ERROR', e instanceof PolicyLoadError ? e.reason : 'POLICY_LOAD_FAILED');
      }
    }

    if (!policy) {
      // Zero-config: an empty policy set, scoped to the configured org and environment (policy_format.md's Policy Set
      // Fields; HTL-22 row 165)
      if (!this._zeroConfigPolicy) {
        this._zeroConfigPolicy = PolicySetSchema.parse({
          name: '__zero_config__',
          version: 'v0.0.0',
          description: 'Zero-config: no rules, so every action is observed',
          scope: { org_id: this.config!.org_id, environment: this.config!.environment },
          rules: [],
        }) as PolicySet;
      }
      policy = this._zeroConfigPolicy;
    }

    // 3. Evaluate policy with mode; 3b reads the route it asks. An evaluator, or a route the loader refuses (row 140),
    // that throws is POLICY_ERROR, never an exception past here. Mirrors client.py `_evaluate_local`.
    const routeOf = (name: string) => (this.routeLoader ? (this.routeLoader.get(name) as any) : null);
    let decision: Decision;
    let asks: boolean;
    try {
      decision = this.evaluator!._evaluateAdmittedEnvelope(envelope, policy, this._evalMode, undefined, ingestedMs);
      asks = Boolean(this.routeLoader && routing.toAsk(decision, routeOf, new Set()));
    } catch (e: any) {
      return this._evaluationFailed(envelope, e);
    }

    // 3b. A ROUTE asking a sync route: ask it, and evaluate again with its answer (policy_format.md 2.7; TICKET-046).
    // Only this path is asynchronous; every other decision returns synchronously as before.
    if (asks) {
      const settled = policy;
      return routing
        .evaluateWithRoutes(
          (enrichment) => this.evaluator!._evaluateAdmittedEnvelope(envelope, settled, this._evalMode, enrichment, ingestedMs),
          routeOf,
          (route, payload) => this._askRoute(route, payload),
          envelope as Record<string, any>,
          decision
        )
        .then(
          (d) => this._afterEvaluate(envelope, d),
          (e) => this._evaluationFailed(envelope, e)
        );
    }
    return this._afterEvaluate(envelope, decision);
  }

  /**
   * The error decision for an envelope that could not be evaluated, recorded like any other (decision_response.md
   * "Error Handling": "Even error decisions produce audit records"). Its message is the authored one for its cause;
   * the cause itself was logged where it was caught. A record that cannot be written is logged too: the refusal
   * stands, and it allows nothing. `BLOCK` is a failure no error decision names (row 193). Mirrors client.py
   * `_refused`.
   * @private
   */
  private _refused(envelope: Envelope, decision: DecisionType, reason: string, authoredMessage?: string): Decision {
    const options = { envelopeHash: envelopeHash(envelope as unknown as Record<string, unknown>) };
    const refused = decision === 'BLOCK'
      ? errorBlock(envelope.action_id, reason, options)
      : errorDecision(envelope.action_id, decision, reason, authoredMessage ?? ERROR_MESSAGES[reason], options);
    try {
      this.auditLogger!._writeAdmitted(envelope, refused);
    } catch (e: any) {
      console.error(`The refusal's audit record could not be written: ${e?.message ?? String(e)}`);
    }
    return this._stamped(refused);
  }

  /**
   * The decision with the sync cache's status, read after its record is written: a status that cannot be read is
   * logged and left unset, so the decision stands as recorded (row 193). Mirrors client.py `_stamped`.
   * @private
   */
  private _stamped(decision: Decision): Decision {
    if (this.syncCache) {
      try {
        decision.cache_status = this.syncCache.cacheStatus();
      } catch (e: any) {
        console.warn(`The sync cache's status could not be read: ${e?.message ?? String(e)}`);
      }
    }
    return decision;
  }

  /** An evaluation that threw, logged with its cause and answered POLICY_ERROR. @private */
  private _evaluationFailed(envelope: Envelope, e: any): Decision {
    console.error(`Policy evaluation failed (fail-closed): ${e?.stack ?? e?.message ?? String(e)}`);
    return this._refused(envelope, 'POLICY_ERROR', 'POLICY_EVALUATION_FAILED',
      e instanceof OperatorKindError ? e.message : undefined);
  }

  /**
   * POST the route's context to its endpoint and return the JSON answer (routes.md "A sync route's answer re-enters
   * evaluation"). No answer — a transport error, the SLA timeout, a non-2xx status, a body that is not JSON — rejects
   * with RouteUnanswered, and the route's SLA decides (fail closed unless fail_open). Mirrors client.py `_ask_route`.
   * @private
   */
  private async _askRoute(route: routing.RouteConfig, payload: Record<string, unknown>): Promise<unknown> {
    const headers = { 'content-type': 'application/json', ...routing.authHeaders(route) };   // its own reason
    let res: Response;
    try {
      res = await this._routeFetch(String(route.endpoint ?? ''), {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(routing.timeoutSeconds(route) * 1000),
        redirect: 'manual',     // a redirect is the route's answer, not a hop (sync_engine.md section 8)
      });
    } catch (e: any) {
      throw new routing.RouteUnanswered(`${e?.name ?? 'Error'}: ${e?.message ?? String(e)}`);
    }
    if (!res.ok) throw new routing.RouteUnanswered(`the route answered ${res.status}`);
    try {
      return await res.json();
    } catch {
      throw new routing.RouteUnanswered('the answer is not JSON');
    }
  }

  /** Steps 4–8 of a local evaluation, on the decision evaluation settled on. @private */
  private _afterEvaluate(envelope: Envelope, decision: Decision): Decision {
    // 4. Resolve route config for escalation decisions
    if (
      HIITL.ESCALATION_TYPES.has(decision.decision) &&
      decision.route_ref &&
      this.routeLoader
    ) {
      try {
        const routeConfig = this.routeLoader.get(decision.route_ref);
        if (routeConfig) {
          decision.escalation_context = resolveEscalationContext(routeConfig);
        }
      } catch {
        // Route config resolution is non-fatal
      }
    }

    // 5. Apply rate limiting (if enabled): the windowed RATE_LIMIT rules the evaluator listed (T47: one
    // representation, the rule's). A limiter that fails never lets the call through (safe by default), and under
    // OBSERVE_ALL a refusal is observed — observe never blocks (policy_format.md "Rate-limit rules").
    if (this.rateLimiter) {
      let limited: Decision | null;
      try {
        limited = this.rateLimiter.checkAndIncrement(envelope, decision);
      } catch (e: any) {
        console.error(`Rate limiting unavailable: ${e?.message ?? String(e)}. Action blocked (fail-closed).`);
        limited = limiterFailed(decision);
      }
      if (limited) {
        decision = this._evalMode === 'OBSERVE_ALL' ? observe(limited) : limited;
      }
    }

    // 6. Write to audit log. The decision carries the SHA-256 of the evaluated envelope's signed form, in every
    // mode (Security Tier 1; decision_response.md envelope_hash). A record that cannot be written blocks the action
    // ("Audit write failures in fail-closed mode must block the action", Infrastructure spec 3; HTL-22 row 159).
    decision.envelope_hash = envelopeHash(envelope as unknown as Record<string, unknown>);
    try {
      this.auditLogger!._writeAdmitted(envelope, decision);
    } catch (e: any) {
      console.error(`Audit write failed (fail-closed): ${e?.message ?? String(e)}`);
      return auditWriteFailed(decision);
    }

    // 7. Stamp cache_status (TICKET-121). Hybrid mode reads from the
    // sync cache; pure local mode leaves this null (file-loaded policies
    // are static, not sync-cache state). Hosted mode also leaves it null
    // — the server is authoritative, the SDK has no cache to describe.
    return this._stamped(decision);
  }

  /**
   * Evaluate via the hosted ECP server. The SDK builds and signs the envelope as in local mode and sends it whole
   * (the evaluate implementation guide 1.1: "The request body is the envelope"; row 134). The principal is not
   * in it: the token rides in `X-Hiitl-Principal-Token` and the server verifies it (T-130 §A7).
   * @private
   */
  private async _evaluateHosted(options: EvaluateOptions): Promise<Decision> {
    const envelope = this._builtEnvelope(options, options.agent_id ?? this.hostedConfig!.agent_id, undefined);
    return this.hostedClient!._evaluateAdmitted(envelope, options.principal_token);
  }

  /**
   * The verified principal for a token (T-130 A7): set only from what the
   * configured verifier returns. A token the verifier rejects yields no
   * principal — the envelope carries none and an identity gate blocks — and
   * the rejection is logged.
   * @private
   */
  private _verifiedPrincipal(token: string | undefined): Principal | undefined {
    if (token === undefined) return undefined;
    if (!this._principalVerifier) {
      throw new ConfigurationError(
        'principal_token was passed but no principal_verifier is configured. Configure ' +
          'new HIITL({ principal_verifier: fn }): fn(token) checks the token (signature, issuer, audience, ' +
          'expiry) and returns its claims { sub, scope or scopes, iss, aud }, throwing on an invalid token.'
      );
    }
    try {
      const c = this._principalVerifier(token);
      assertNumericDomain(c);
      const scopes = c.scopes ?? (typeof c.scope === 'string' ? c.scope.split(/\s+/).filter(Boolean) : undefined);
      return {
        sub: c.sub,
        ...(scopes ? { scopes } : {}),
        ...(c.iss ? { iss: c.iss } : {}),
        ...(c.aud ? { aud: c.aud } : {}),
        verified_by: 'sdk_verifier',
        verified_at: new Date().toISOString(),
      };
    } catch (e) {
      console.warn(`principal token failed verification (${(e as Error).message}): evaluated with no verified principal`);
      return undefined;
    }
  }

  /**
   * _buildEnvelope, its validation failure thrown as the SDK's EnvelopeValidationError.
   * @private
   */
  private _builtEnvelope(options: EvaluateOptions, agentId: string, principal: Principal | undefined): Envelope {
    try {
      return this._buildEnvelope(options, agentId, principal);
    } catch (e: any) {
      if (e.name === 'ZodError') {
        const errors = e.issues?.map(
          (err: any) => `${err.path.join('.')}: ${err.message}`
        ) || [];
        throw new EnvelopeValidationError(
          `Envelope validation failed: ${e.message}\n\n` +
            'Check that all provided fields are valid.\n' +
            'See docs/specs/envelope_schema.json for the full schema.',
          errors
        );
      }
      throw e;
    }
  }

  /**
   * Build envelope from provided fields and auto-generated values, signed with signature_key over the one signed form
   * (@hiitl/core envelopeSignedForm) of the envelope as recorded (row 127). With no key the signature is zeros.
   * `trace_id` is the active OpenTelemetry span's ("Auto-propagated from execution context"; row 175);
   * `correlation_id` is the caller's.
   * @private
   */
  private _buildEnvelope(options: EvaluateOptions, agentId: string, principal: Principal | undefined): Envelope {
    const actionId = `act_${crypto.randomUUID().replace(/-/g, '').slice(0, 20)}`;
    const timestamp = new Date().toISOString();
    const idempotencyKey =
      options.idempotency_key ?? `idem_${crypto.randomUUID().replace(/-/g, '')}`;
    const operation = checkOperation(options.operation);
    const settings = (this.config ?? this.hostedConfig)!;

    const envelopeData = {
      schema_version: ENVELOPE_SCHEMA_VERSION,
      org_id: settings.org_id,
      environment: settings.environment,
      agent_id: agentId,
      action_id: actionId,
      timestamp,
      action: options.action,
      operation,
      parameters: options.parameters ?? {},
      target: options.target ?? {},
      idempotency_key: idempotencyKey,
      signature: '0'.repeat(64),
      user_id: options.user_id,
      session_id: options.session_id,
      confidence: options.confidence,
      reason: options.reason,
      sensitivity: options.sensitivity,
      cost_estimate: options.cost_estimate,
      requested_scopes: options.requested_scopes,
      principal,
      correlation_id: options.correlation_id,
      trace_id: activeTraceId(),
    };

    const envelope = parseAdmittedNumbers(EnvelopeSchema,envelopeData);
    if (settings.signature_key) {
      envelope.signature = envelopeSignature(settings.signature_key, envelope as unknown as Record<string, unknown>);
    }
    return envelope;
  }

  /**
   * Query audit log records (local mode only).
   *
   * @throws {Error} If called in hosted mode
   */
  queryAudit(options: {
    org_id?: string;
    action_id?: string;
    decision_type?: string;
    limit?: number;
    offset?: number;
  }): any[] {
    if (this._mode === 'hosted') {
      throw new Error('queryAudit is not available in hosted mode. Use the server API directly.');
    }

    const org_id = options.org_id ?? this.config!.org_id;

    if (options.action_id) {
      return this.auditLogger!.queryByActionId(options.action_id);
    }

    if (options.decision_type) {
      return this.auditLogger!.queryByDecisionType(
        options.decision_type,
        { limit: options.limit, offset: options.offset }
      );
    }

    return this.auditLogger!.queryByOrgId(org_id, {
      limit: options.limit,
      offset: options.offset,
    });
  }

  /**
   * Record what happened when the caller executed an action evaluate() allowed: the lifecycle's result
   * (Principle 4, Intent → Attempt → Result; event_format.md "The lifecycle"). Mirrors client.py `record_result`.
   *
   * @param action_id - The action_id of the decision evaluate() returned
   * @param status - succeeded, failed or canceled
   * @param options.error - What failed, when status is failed
   * @param options.duration_ms - How long the execution took
   * @returns The record carrying the result. The same result again returns the record that already holds it.
   * @throws {LifecycleError} The result is not recorded, with its reason: RESULT_INVALID, ACTION_NOT_FOUND,
   *   RESULT_ON_UNALLOWED_DECISION (an action that was not allowed never executed) or RESULT_ALREADY_RECORDED (a
   *   different result is recorded)
   *   In hosted mode, a result the service could not take is held in the local store and pushed before the next call;
   *   the return is then `{action_id, execution_result, held: true}`, and a warning is logged (row 200).
   * @throws {AuditLogError} The store could not write the result record (in hosted mode, could not hold it)
   */
  async recordResult(
    action_id: string,
    status: string,
    options: { error?: string; duration_ms?: number } = {}
  ): Promise<Record<string, unknown>> {
    try{assertSchemaNumbers({action_id,status,...options},ResultNumberSchema.extend({action_id:EnvelopeSchema.shape.action_id}));}catch(error){
      if(!(error instanceof NumericDomainError))throw error;
      throw new LifecycleError('RESULT_INVALID',error.message);
    }
    let result;
    try {
      result = executionResult(status, options.error, options.duration_ms);
    } catch {
      throw new LifecycleError('RESULT_INVALID', LIFECYCLE_MESSAGES.RESULT_INVALID);
    }
    if (this._mode === 'hosted') return this.hostedClient!.recordResult(action_id, result);
    const lifecycle = this.auditLogger!.lifecycle(this.config!.org_id, this.config!.environment, action_id);
    // The action's decision: its latest record that carries no result (event_format.md "The lifecycle"). The store
    // holds no review case, so it passes the decision's review as unread, and the service, which holds the case, reads
    // it at sync ingest (row 217, event_format.md "A result whose writer holds no case")
    const decided = lifecycle.filter((r) => !('execution_result' in r)).pop();
    const review = decided ? unreadReview(decided.decision as any) : null;
    const refusal = resultRefusal(lifecycle as any, result, review);
    if (refusal) throw new LifecycleError(refusal, LIFECYCLE_MESSAGES[refusal]);
    const first = recordedResult(lifecycle as any, result);
    if (first) return first;
    // The result record, its hash over the decision record's terms, the result and the review it was read under
    // (row 191, ruled 2026-11-06; row 217)
    return this.auditLogger!.writeResult(decided!, result as unknown as Record<string, unknown>, review);
  }

  /**
   * Close all resources: the audit store, and in hosted mode the local store the client opened.
   */
  close(): void {
    if (this.auditLogger) {
      this.auditLogger.close();
    }
    this.hostedClient?.close();
  }
}
