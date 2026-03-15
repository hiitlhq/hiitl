"""SDK exception types.

All exceptions raised by the HIITL SDK inherit from HIITLError.
This allows consumers to catch all SDK exceptions with a single except clause.
"""


class HIITLError(Exception):
    """Base exception for all HIITL SDK errors.

    All SDK exceptions inherit from this class, allowing consumers to catch
    all HIITL-related errors with a single except clause.
    """


class PolicyLoadError(HIITLError):
    """Failed to load or parse policy file.

    Raised when:
    - Policy file not found
    - Policy file has invalid JSON/YAML syntax
    - Policy structure doesn't match PolicySet schema
    - Policy validation fails (e.g., invalid operator, missing fields)

    The error message includes helpful context pointing to the correct schema
    documentation in docs/specs/policy_format.md.
    """


class AuditLogError(HIITLError):
    """Failed to write to audit log.

    Raised when:
    - Cannot create audit database file
    - Cannot write audit record to SQLite
    - Database permissions are insufficient
    - Disk is full or inaccessible
    """


class ConfigurationError(HIITLError):
    """Invalid SDK configuration.

    Raised when:
    - Required configuration parameters are missing
    - Configuration values fail validation (e.g., invalid org_id pattern)
    - Environment value is not valid (must be dev/stage/prod)
    - Mode is not supported
    """


class RouteLoadError(HIITLError):
    """Failed to load or parse route configuration file.

    Raised when:
    - Route config file has invalid JSON/YAML syntax
    - Route config is missing required fields
    - Config name doesn't match filename

    The error message includes helpful context pointing to the correct schema
    documentation in docs/specs/routes.md.
    """


class EnvelopeValidationError(HIITLError):
    """Envelope failed validation.

    Raised when the constructed envelope doesn't match the envelope schema.
    This typically indicates invalid input parameters to evaluate().

    Attributes:
        validation_errors: List of specific validation error messages from Pydantic
    """

    def __init__(self, message: str, validation_errors: list[str]):
        super().__init__(message)
        self.validation_errors = validation_errors


class ServerError(HIITLError):
    """ECP server returned an error response.

    Raised when the hosted server returns a non-2xx response. The error
    message includes the server's error code and message for debugging.

    Attributes:
        status_code: HTTP status code from server
        error_code: Machine-readable error code (e.g., POLICY_NOT_FOUND)
        server_message: Human-readable message from server
    """

    def __init__(self, status_code: int, error_code: str, server_message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.server_message = server_message
        super().__init__(
            f"ECP server error ({status_code}): [{error_code}] {server_message}"
        )


class SyncError(HIITLError):
    """Sync engine encountered an error.

    Raised internally by the sync engine for recoverable sync failures.
    These errors are logged but never bubble up to evaluate() — sync
    failures degrade gracefully (cached data continues to be used).

    Attributes:
        channel: Sync channel that failed (e.g., "audit", "policy")
        cause: Original exception
    """

    def __init__(self, channel: str, message: str, cause: Exception | None = None):
        self.channel = channel
        self.cause = cause
        super().__init__(
            f"Sync error [{channel}]: {message}"
        )


class NetworkError(HIITLError):
    """Failed to connect to ECP server.

    Raised when the SDK cannot reach the server due to network issues,
    DNS failures, timeouts, or connection refusals.

    Check server_url configuration and network connectivity.
    """

    def __init__(self, server_url: str, cause: Exception):
        self.server_url = server_url
        self.cause = cause
        super().__init__(
            f"Cannot reach ECP server at '{server_url}': {cause}\n\n"
            "Troubleshooting:\n"
            "  1. Verify server_url is correct\n"
            "  2. Check network connectivity\n"
            "  3. Confirm the server is running\n"
            "  4. Check for firewall or proxy issues"
        )
