/**
 * HIITL SDK Client - Main developer-facing API.
 *
 * Single entry point: evaluate(). Mode is auto-detected from constructor arguments:
 * - **No api_key**: Local evaluation with embedded evaluator
 * - **api_key + server_url**: Hosted evaluation via ECP server
 * - **api_key only**: Hybrid (local eval, sync in a future release)
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
 * @example Hosted (api_key + server_url)
 * ```typescript
 * const hiitl = new HIITL({
 *   environment: 'prod',
 *   agent_id: 'payment-agent',
 *   org_id: 'org_mycompany123456789',
 *   api_key: 'your-api-key',
 *   server_url: 'https://api.hiitl.com',
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
import { PolicyEvaluator, EnvelopeSchema, DecisionType } from '@hiitl/core';
import type {
  Envelope,
  Decision,
  Operation,
  PolicySet,
  Sensitivity,
} from '@hiitl/core';
import { createConfig, createHostedConfig } from './config.js';
import type {
  LocalModeConfig,
  LocalModeConfigInput,
  HostedModeConfig,
  HostedModeConfigInput,
  HIITLConfigInput,
} from './config.js';

type HIITLMode = 'local' | 'hosted' | 'hybrid';
import { PolicyLoader } from './policy-loader.js';
import { RouteLoader, resolveEscalationContext } from './route-loader.js';
import { AuditLogger } from './audit.js';
import { RateLimiter } from './rate-limiter.js';
import { HostedClient } from './http-client.js';
import {
  ConfigurationError,
  EnvelopeValidationError,
  PolicyLoadError,
  AuditLogError,
} from './exceptions.js';

/**
 * Cost estimate for an action.
 */
export interface CostEstimate {
  tokens?: number;
  usd_cents?: number;
}

/**
 * Options for evaluate() method.
 *
 * Only `action` is required. Everything else has sensible defaults.
 */
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
  /** Idempotency key (auto-generated if omitted). */
  idempotency_key?: string;
}

/**
 * HIITL client for policy evaluation.
 *
 * Mode is auto-detected from constructor arguments:
 * - No api_key → local (embedded evaluation)
 * - api_key + server_url → hosted (ECP server)
 * - api_key only → hybrid (local eval, sync in future)
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
  private rateLimiter?: RateLimiter;
  private routeLoader?: RouteLoader;
  private _zeroConfigPolicy?: PolicySet;

  // Hosted mode components (only initialized in hosted mode)
  public readonly hostedConfig?: HostedModeConfig;
  private hostedClient?: HostedClient;

  /**
   * Initialize HIITL client.
   *
   * Mode is auto-detected:
   * - No api_key → local
   * - api_key + server_url → hosted
   * - api_key only → hybrid (local eval, sync in future)
   * - sync: false forces local even with api_key
   *
   * Zero-config: `new HIITL()` works with OBSERVE_ALL defaults.
   *
   * @param options - Configuration options (all optional for zero-config)
   * @throws {ConfigurationError} If configuration is invalid
   * @throws {PolicyLoadError} If policy file cannot be loaded (local/hybrid)
   * @throws {AuditLogError} If audit database cannot be initialized (local/hybrid)
   */
  constructor(options: HIITLConfigInput = {}) {
    const sync = options.sync ?? true;
    this._evalMode = options.mode ?? 'OBSERVE_ALL';

    // Auto-detect mode from arguments
    if (options.api_key && options.server_url) {
      this._mode = 'hosted';
    } else if (options.api_key && sync) {
      this._mode = 'hybrid';
    } else {
      this._mode = 'local';
    }

    if (this._mode === 'hosted') {
      this._initHosted(options as HostedModeConfigInput);
    } else {
      // Both local and hybrid use local evaluation
      if (!options.policy_path && this._evalMode === 'RESPECT_POLICY') {
        throw new ConfigurationError(
          'policy_path is required when mode is RESPECT_POLICY.\n\n' +
            'Either provide a policy file:\n' +
            "  new HIITL({ policy_path: './policy.yaml', mode: 'RESPECT_POLICY' })\n\n" +
            'Or use OBSERVE_ALL mode (default) for zero-config:\n' +
            '  new HIITL()'
        );
      }

      if (this._mode === 'hybrid' && !options.policy_path) {
        throw new ConfigurationError(
          'policy_path is required for hybrid mode (local evaluation with api_key).\n\n' +
            'Policy sync will be available in a future release. Until then, provide a local policy:\n' +
            "  new HIITL({ api_key: '...', policy_path: './policy.yaml', ... })\n\n" +
            'Or add server_url for hosted evaluation:\n' +
            "  new HIITL({ api_key: '...', server_url: 'https://ecp.hiitl.com', ... })"
        );
      }

      if (this._mode === 'hybrid') {
        console.info(
          'Hybrid mode: local evaluation active. ' +
            'Policy sync will be available in a future release.'
        );
      }

      this._initLocal(options as LocalModeConfigInput);
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
      (this as any).config = createConfig(options);
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
      this.auditLogger = new AuditLogger(this.config!.audit_db_path);
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

  private _initHosted(options: HostedModeConfigInput): void {
    try {
      (this as any).hostedConfig = createHostedConfig(options);
    } catch (e: any) {
      throw new ConfigurationError(
        `Invalid HIITL configuration: ${e.message}\n\n` +
          'Required for hosted evaluation: environment, agent_id, org_id, api_key, server_url'
      );
    }

    this.hostedClient = new HostedClient(this.hostedConfig!);
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
   * @param options - Evaluation options (only action required)
   * @returns Decision (or Promise<Decision> in hosted mode)
   */
  evaluate(options: EvaluateOptions): Decision | Promise<Decision> {
    if (this._mode === 'hosted') {
      return this._evaluateHosted(options);
    }
    return this._evaluateLocal(options);
  }

  private _evaluateLocal(options: EvaluateOptions): Decision {
    // Resolve agent_id: per-call override > init default
    const agentId = options.agent_id ?? this.config!.agent_id;

    // 1. Build envelope
    let envelope: Envelope;
    try {
      envelope = this._buildEnvelope(options, agentId);
    } catch (e: any) {
      if (e.name === 'ZodError') {
        const errors = e.errors?.map(
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

    // 2. Load policy (cached) or use zero-config empty policy
    let policy: PolicySet;
    if (this.policyLoader) {
      try {
        policy = this.policyLoader.load();
      } catch (e: any) {
        if (e instanceof PolicyLoadError) {
          throw e;
        }
        throw new PolicyLoadError(`Failed to load policy: ${e.message}`);
      }
    } else {
      // Zero-config: empty policy set
      if (!this._zeroConfigPolicy) {
        this._zeroConfigPolicy = {
          version: '0.0.0',
          name: '__zero_config__',
          rules: [],
        } as PolicySet;
      }
      policy = this._zeroConfigPolicy;
    }

    // 3. Evaluate policy with mode
    let decision: Decision;
    try {
      decision = this.evaluator!.evaluate(envelope, policy, this._evalMode);
    } catch (e: any) {
      throw new Error(
        `Policy evaluation failed: ${e.message}\n\n` +
          'This is an unexpected error. Please report this issue.'
      );
    }

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

    // 5. Apply rate limiting (if enabled)
    if (this.rateLimiter) {
      try {
        const rateConfig = (policy as any).metadata;
        const rateLimited = this.rateLimiter.checkAndIncrement(
          envelope,
          decision,
          rateConfig
        );
        if (rateLimited) {
          decision = rateLimited;
        }
      } catch {
        // Rate limiting failures are non-fatal
      }
    }

    // 6. Write to audit log
    try {
      this.auditLogger!.write(envelope, decision);
    } catch (e: any) {
      if (e instanceof AuditLogError) {
        throw e;
      }
      throw new AuditLogError(`Failed to write audit record: ${e.message}`);
    }

    // 7. Return decision
    return decision;
  }

  private async _evaluateHosted(options: EvaluateOptions): Promise<Decision> {
    return this.hostedClient!.evaluate({
      action: options.action,
      operation: typeof options.operation === 'string' ? options.operation : (options.operation ?? 'execute'),
      target: options.target ?? {},
      parameters: options.parameters ?? {},
      agent_id: options.agent_id,
      user_id: options.user_id,
      session_id: options.session_id,
      confidence: options.confidence,
      reason: options.reason,
      sensitivity: options.sensitivity,
      cost_estimate: options.cost_estimate,
      idempotency_key: options.idempotency_key,
    });
  }

  /**
   * Build envelope from provided fields and auto-generated values.
   * @private
   */
  private _buildEnvelope(options: EvaluateOptions, agentId: string): Envelope {
    const actionId = `act_${crypto.randomUUID().replace(/-/g, '').slice(0, 20)}`;
    const timestamp = new Date().toISOString();
    const idempotencyKey =
      options.idempotency_key ?? `idem_${crypto.randomUUID().replace(/-/g, '')}`;
    const operation = (options.operation ?? 'execute') as Operation;
    const signature = this._computeSignature(
      actionId,
      timestamp,
      options.action,
      operation
    );

    const envelopeData = {
      schema_version: 'v1.0',
      org_id: this.config!.org_id,
      environment: this.config!.environment,
      agent_id: agentId,
      action_id: actionId,
      timestamp,
      action: options.action,
      operation,
      parameters: options.parameters ?? {},
      target: options.target ?? {},
      idempotency_key: idempotencyKey,
      signature,
      user_id: options.user_id,
      session_id: options.session_id,
      confidence: options.confidence,
      reason: options.reason,
      sensitivity: options.sensitivity,
      cost_estimate: options.cost_estimate,
    };

    return EnvelopeSchema.parse(envelopeData);
  }

  /**
   * Compute HMAC-SHA256 signature for envelope.
   * @private
   */
  private _computeSignature(
    actionId: string,
    timestamp: string,
    action: string,
    operation: Operation
  ): string {
    if (!this.config?.signature_key) {
      return '0'.repeat(64);
    }

    const content = `${actionId}:${timestamp}:${this.config.org_id}:${action}:${operation}`;
    return crypto
      .createHmac('sha256', this.config.signature_key)
      .update(content)
      .digest('hex');
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
   * Close all resources.
   *
   * In local mode, closes the audit logger database.
   * In hosted mode, this is a no-op (no persistent connections).
   */
  close(): void {
    if (this.auditLogger) {
      this.auditLogger.close();
    }
  }
}
