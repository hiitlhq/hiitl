/**
 * @hiitl/sdk - TypeScript SDK for HIITL policy evaluation.
 *
 * This package provides a TypeScript SDK for HIITL (Human-in-the-Loop) policy
 * evaluation. It supports local/edge mode with embedded evaluation, and hosted
 * mode via the ECP server.
 *
 * @example Zero-config (OBSERVE_ALL mode)
 * ```typescript
 * import { HIITL } from '@hiitl/sdk';
 *
 * const hiitl = new HIITL();
 * const decision = hiitl.evaluate({ action: 'send_email' });
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
 * const decision = hiitl.evaluate({
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
export type { RateLimitConfig } from './rate-limiter.js';
export { HostedClient } from './http-client.js';
