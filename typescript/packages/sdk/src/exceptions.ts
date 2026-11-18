/**
 * HIITL SDK exceptions - structured error hierarchy for helpful error messages.
 *
 * All SDK errors inherit from HIITLError base class, allowing for
 * catch-all error handling with `catch (e) { if (e instanceof HIITLError) {...} }`.
 *
 * Design:
 * - Helpful error messages pointing to documentation
 * - Proper TypeScript Error extension with stack traces
 * - Specialized error types for different failure modes
 *
 * @example
 * ```typescript
 * try {
 *   hiitl.evaluate(...);
 * } catch (e) {
 *   if (e instanceof PolicyLoadError) {
 *     console.error('Policy file issue:', e.message);
 *   } else if (e instanceof HIITLError) {
 *     console.error('HIITL error:', e.message);
 *   }
 * }
 * ```
 */

/**
 * Base error class for all HIITL SDK errors.
 *
 * All SDK-specific errors inherit from this class, allowing for
 * unified error handling at the top level.
 */
export class HIITLError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'HIITLError';
    // Maintain proper stack trace for where our error was thrown
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
  }
}

/**
 * Policy loading errors - file not found, invalid syntax, schema validation, etc.
 *
 * This error is thrown when policy files cannot be loaded or parsed.
 *
 * Common causes:
 * - File not found at specified path
 * - Invalid JSON or YAML syntax
 * - Policy doesn't match schema (see docs/specs/policy_format.md)
 * - File permissions issue
 */
export class PolicyLoadError extends HIITLError {
  /**
   * On the evaluate path it is not thrown to the caller: an envelope exists, so the failure is the decision
   * POLICY_ERROR with `reason` as its cause and this message logged (decision_response.md "Error Handling"; HTL-22
   * row 159). `reason` is the Error Handling cause: POLICY_NOT_FOUND, POLICY_LOAD_FAILED or POLICY_VALIDATION_ERROR.
   */
  readonly reason: string;

  constructor(message: string, reason: string = 'POLICY_VALIDATION_ERROR') {
    super(message);
    this.name = 'PolicyLoadError';
    this.reason = reason;
  }
}

/**
 * Audit logging errors - database initialization, write failures, etc.
 *
 * This error is thrown when audit log operations fail.
 *
 * Common causes:
 * - Cannot create/access SQLite database file
 * - Disk full
 * - Database corrupted
 * - Permissions issue
 */
export class AuditLogError extends HIITLError {
  constructor(message: string) {
    super(message);
    this.name = 'AuditLogError';
  }
}

/**
 * Configuration errors - invalid config values, missing required fields, etc.
 *
 * This error is thrown when SDK configuration is invalid.
 *
 * Common causes:
 * - Missing required config fields (environment, agent_id, org_id, policy_path)
 * - Invalid org_id format (must match the envelope's org_id pattern, ORG_ID_PATTERN)
 * - Invalid environment value (must be dev/stage/prod)
 * - Invalid mode (only 'local' supported)
 */
export class ConfigurationError extends HIITLError {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigurationError';
  }
}

/**
 * Envelope validation errors - envelope doesn't match schema.
 *
 * This error is thrown when envelope validation fails during evaluate().
 *
 * Includes detailed validation errors from Zod for debugging.
 */
/**
 * Route config loading errors - file not found, invalid syntax, validation, etc.
 *
 * This error is thrown when route configuration files cannot be loaded or parsed.
 *
 * Common causes:
 * - Invalid JSON or YAML syntax in config file
 * - Missing required fields (name, version, escalation_context, etc.)
 * - Config name doesn't match filename
 * - Missing surface_fields or available_responses
 *
 * See docs/specs/routes.md for the config format.
 */
export class RouteLoadError extends HIITLError {
  constructor(message: string) {
    super(message);
    this.name = 'RouteLoadError';
  }
}

export class EnvelopeValidationError extends HIITLError {
  /**
   * Detailed validation errors from Zod, formatted as "field: message"
   */
  public readonly validation_errors: string[];

  constructor(message: string, validation_errors: string[] = []) {
    super(message);
    this.name = 'EnvelopeValidationError';
    this.validation_errors = validation_errors;
  }
}

/**
 * ECP server returned an error response.
 *
 * Thrown when the hosted server returns a non-2xx response.
 * Includes HTTP status code, machine-readable error code, and human-readable message.
 */
export class ServerError extends HIITLError {
  public readonly status_code: number;
  public readonly error_code: string;
  public readonly server_message: string;

  constructor(status_code: number, error_code: string, server_message: string) {
    super(
      `ECP server error (${status_code}): [${error_code}] ${server_message}`
    );
    this.name = 'ServerError';
    this.status_code = status_code;
    this.error_code = error_code;
    this.server_message = server_message;
  }
}

/**
 * A result `recordResult` does not record on the action's lifecycle (event_format.md "The lifecycle"; HTL-22 row
 * 150). `reason` is why, the code the hosted service answers too: RESULT_INVALID, ACTION_NOT_FOUND,
 * RESULT_ON_UNALLOWED_DECISION or RESULT_ALREADY_RECORDED. Mirrors exceptions.py.
 */
export class LifecycleError extends HIITLError {
  public readonly reason: string;

  constructor(reason: string, message: string) {
    super(`[${reason}] ${message}`);
    this.name = 'LifecycleError';
    this.reason = reason;
  }
}

/**
 * Sync engine encountered an error.
 *
 * Raised internally by the sync engine for recoverable sync failures.
 * These errors are logged but never bubble up to evaluate() — sync
 * failures degrade gracefully (cached data continues to be used).
 *
 * Mirrors `python/hiitl/sdk/exceptions.py:SyncError` exactly.
 */
export class SyncError extends HIITLError {
  public readonly channel: string;
  public readonly cause_error?: Error;

  constructor(channel: string, message: string, cause?: Error) {
    super(`Sync error [${channel}]: ${message}`);
    this.name = 'SyncError';
    this.channel = channel;
    this.cause_error = cause;
  }
}

/**
 * Failed to connect to ECP server.
 *
 * Thrown when the SDK cannot reach the server due to network issues,
 * DNS failures, timeouts, or connection refusals.
 */
export class NetworkError extends HIITLError {
  public readonly server_url: string;
  public readonly cause_error: Error;

  constructor(server_url: string, cause: Error) {
    super(
      `Cannot reach ECP server at '${server_url}': ${cause.message}\n\n` +
        'Troubleshooting:\n' +
        '  1. Verify server_url is correct\n' +
        '  2. Check network connectivity\n' +
        '  3. Confirm the server is running\n' +
        '  4. Check for firewall or proxy issues'
    );
    this.name = 'NetworkError';
    this.server_url = server_url;
    this.cause_error = cause;
  }
}

/**
 * Raised when the initial sync at SDK startup fails AND
 * cold_start_behavior is 'fail-closed' (TICKET-121 / TICKET-116).
 *
 * Thrown from `evaluate()` (NOT the constructor) on the first call
 * after the initial sync has resolved as a failure. Why on evaluate
 * and not the constructor: JavaScript constructors cannot be async,
 * so we can't block on initialSync from `new HIITL(...)`. Instead,
 * fail-closed is enforced at the first evaluate() — the safety net
 * a developer can't accidentally bypass.
 *
 * The other cold_start_behavior values ('warn-and-observe' (default),
 * 'observe-silent') never throw this — they continue in OBSERVE_ALL
 * with `cache_status='empty'` on every Decision until background sync
 * succeeds.
 */
export class ColdStartError extends HIITLError {
  public readonly server_url: string;
  public readonly timeout_seconds: number;

  constructor(server_url: string, timeout_seconds: number) {
    super(
      `Cold-start sync failed: could not reach ${server_url} within ` +
        `${timeout_seconds}s and no disk cache was available. ` +
        "cold_start_behavior='fail-closed' was set, so evaluate() " +
        'refused to run against an empty policy set. ' +
        "Switch to cold_start_behavior='warn-and-observe' to allow " +
        'the SDK to operate in OBSERVE_ALL until background sync succeeds.'
    );
    this.name = 'ColdStartError';
    this.server_url = server_url;
    this.timeout_seconds = timeout_seconds;
  }
}
