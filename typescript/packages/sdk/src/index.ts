/**
 * @hiitl/sdk - TypeScript SDK for hiitl policy evaluation.
 *
 * This package provides a TypeScript SDK for hiitl policy evaluation. It
 * supports local mode with embedded evaluation, hybrid mode (embedded
 * evaluation with background sync), and hosted mode via the ECP server.
 *
 * `evaluate()` returns a Decision in local mode and a Promise in hybrid and
 * hosted mode; `await` every call.
 *
 * @example Zero-config (OBSERVE_ALL mode)
 * ```typescript
 * import { HIITL } from '@hiitl/sdk';
 *
 * const hiitl = new HIITL();
 * const decision = await hiitl.evaluate({ action: 'send_email' });
 * if (decision.allowed) {
 *   sendEmail();
 * }
 * ```
 *
 * @example With policy (RESPECT_POLICY mode)
 * ```typescript
 * const hiitl = new HIITL({
 *   policy_path: './policy.yaml',
 *   mode: 'RESPECT_POLICY',
 * });
 *
 * const decision = await hiitl.evaluate({
 *   action: 'payment_transfer',
 *   parameters: { amount: 500, currency: 'USD' },
 * });
 *
 * if (decision.allowed) {
 *   processPayment();
 * }
 * ```
 *
 * @packageDocumentation
 */

// =============================================================================
// Main API
// =============================================================================

/**
 * HIITL client for policy evaluation.
 *
 * This is the primary interface for using HIITL. It orchestrates policy loading,
 * evaluation, rate limiting, and audit logging.
 *
 * @see {@link HIITL} for usage details
 */
export { HIITL } from './client.js';

// =============================================================================
// Configuration
// =============================================================================

/**
 * Configuration types for HIITL client.
 *
 * @see {@link LocalModeConfig} for the local mode validated configuration
 * @see {@link HostedModeConfig} for the hosted mode validated configuration
 * @see {@link HIITLConfigInput} for the union constructor input type
 */
export type {
  LocalModeConfig,
  LocalModeConfigInput,
  HostedModeConfig,
  HostedModeConfigInput,
  HIITLConfigInput,
  TelemetryLevel,
} from './config.js';

/**
 * Create configuration from input options and environment variables.
 *
 * @see {@link createConfig} for local mode configuration
 * @see {@link createHostedConfig} for hosted mode configuration
 */
export { createConfig, createHostedConfig } from './config.js';

// =============================================================================
// Exceptions
// =============================================================================

/**
 * Error types thrown by HIITL SDK.
 *
 * All SDK errors inherit from {@link HIITLError} base class.
 *
 * @see {@link ConfigurationError} for configuration validation errors
 * @see {@link PolicyLoadError} for policy file loading errors
 * @see {@link AuditLogError} for audit database errors
 * @see {@link EnvelopeValidationError} for envelope validation errors
 */
export {
  HIITLError,
  ConfigurationError,
  PolicyLoadError,
  RouteLoadError,
  AuditLogError,
  EnvelopeValidationError,
  ServerError,
  NetworkError,
  SyncError,
  ColdStartError,
  LifecycleError,
} from './exceptions.js';

// =============================================================================
// Core Types (Re-exported for convenience)
// =============================================================================

/**
 * Core types from @hiitl/core, re-exported for convenience.
 *
 * These types are used when calling {@link HIITL.evaluate} and handling
 * {@link Decision} responses.
 *
 * @see https://github.com/hiitlhq/hiitl for full type documentation
 */
export type {
  // Envelope types
  Envelope,
  Operation,
  Sensitivity,
  // Decision types
  Decision,
  DecisionType,
  StagedObservation,
  // Policy types
  PolicySet,
  Rule,
  Condition,
} from '@hiitl/core';

export { PolicyEvaluator } from '@hiitl/core';

// SDK-specific types
export type { CostEstimate } from './client.js';

// =============================================================================
// Advanced Components (for power users)
// =============================================================================

/**
 * Advanced components for power users who need fine-grained control.
 *
 * Most users should use {@link HIITL} instead of these directly.
 */
export { PolicyLoader } from './policy-loader.js';
export { RouteLoader, resolveEscalationContext } from './route-loader.js';
export type { EscalationContext } from './route-loader.js';
export { AuditLogger } from './audit.js';
export { RateLimiter } from './rate-limiter.js';
export { HostedClient } from './http-client.js';

// =============================================================================
// Hybrid Mode Sync Engine (Block 5c-5e)
// =============================================================================

/**
 * Background sync engine for hybrid mode. Orchestrates audit upload +
 * policy / route / kill-switch download against the hosted backend
 * while evaluate() continues to run locally at zero-network-cost
 * latency. Mirrors the Python SDK's hybrid architecture exactly.
 *
 * Most users won't construct these directly — they're surfaced for
 * advanced scenarios (custom audit stores, alternate transport,
 * test instrumentation).
 *
 * @see https://github.com/hiitlhq/hiitl/blob/main/docs/specs/sync_engine_spec.md
 */
export { SyncEngine } from './sync-engine.js';
export type {
  SyncConfig,
  SyncEngineOptions,
  AuditDrainSink,
  TelemetryCollectorSink,
} from './sync-engine.js';

export { SyncCache } from './sync-cache.js';
export type { SyncCacheOptions, SyncCacheStatus } from './sync-cache.js';

export { SyncClient, backoffWithJitter } from './sync-client.js';
export type {
  SyncClientOptions,
  AuditUploadResult,
  PolicyDownloadResult,
  RouteDownloadResult,
  KillSwitchResult,
  TelemetryUploadResult,
} from './sync-client.js';

export { CircuitBreaker, CircuitState } from './circuit-breaker.js';
export type { CircuitBreakerStatus } from './circuit-breaker.js';

export type { Logger } from './logger.js';
export { consoleLogger } from './logger.js';
