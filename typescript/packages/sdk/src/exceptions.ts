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
  constructor(message: string) {
    super(message);
    this.name = 'PolicyLoadError';
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
 * - Invalid org_id format (must match pattern org_[a-z0-9]{18,})
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
