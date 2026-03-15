"""SDK configuration using Pydantic Settings.

Configuration can be provided via:
1. Constructor arguments (highest priority)
2. Environment variables (HIITL_* prefix)
3. Default values (lowest priority)

Local mode example (no api_key):
    >>> config = LocalModeConfig(
    ...     environment="dev",
    ...     agent_id="payment-agent",
    ...     org_id="org_mycompany12345678",
    ...     policy_path="./policy.yaml"
    ... )

Hosted mode example (api_key + server_url + evaluation="remote"):
    >>> config = HostedModeConfig(
    ...     environment="dev",
    ...     agent_id="payment-agent",
    ...     org_id="org_mycompany12345678",
    ...     api_key="sk_live_abc123...",
    ...     server_url="https://ecp.hiitl.com"
    ... )

Environment variables:
    HIITL_ENVIRONMENT: dev, stage, or prod
    HIITL_AGENT_ID: Agent identifier
    HIITL_ORG_ID: Organization ID (must match pattern)
    HIITL_POLICY_PATH: Path to policy file (local/hybrid mode)
    HIITL_API_KEY: API key (hybrid/hosted mode)
    HIITL_SERVER_URL: Server URL (hosted mode, requires evaluation="remote")
    HIITL_AUDIT_DB_PATH: Path to SQLite database (default: ./hiitl_audit.db)
    HIITL_ENABLE_RATE_LIMITING: Enable rate limiting (default: true)
    HIITL_SIGNATURE_KEY: HMAC signature key (optional)
    HIITL_TIMEOUT: HTTP timeout in seconds (hosted mode, default: 5.0)
    HIITL_MAX_RETRIES: Max retry attempts (hosted mode, default: 3)

    Sync configuration (HIITL_SYNC_* prefix):
    HIITL_SYNC_CACHE_DIR: Disk cache location (default: ~/.hiitl/cache/)
    HIITL_SYNC_AUDIT_INTERVAL: Audit upload interval in seconds (default: 30)
    HIITL_SYNC_POLICY_INTERVAL: Policy refresh interval in seconds (default: 300)
    HIITL_SYNC_ROUTE_INTERVAL: Route refresh interval in seconds (default: 300)
    HIITL_SYNC_KS_INTERVAL: Kill switch poll interval in seconds (default: 30)
    HIITL_SYNC_AUDIT_BATCH: Max records per audit upload (default: 100)
    HIITL_SYNC_MAX_BUFFER: Max audit records in memory buffer (default: 10000)
    HIITL_SYNC_INIT_TIMEOUT: Cold start sync timeout in seconds (default: 10)
    HIITL_SYNC_CB_THRESHOLD: Circuit breaker failure threshold (default: 5)
    HIITL_SYNC_CB_RESET: Circuit breaker reset timeout in seconds (default: 60)
    HIITL_SYNC_MAX_STALE: Max cache stale age in seconds (default: 86400)
    HIITL_SYNC_TELEMETRY_SYNC_INTERVAL: Telemetry upload interval in seconds (default: 60)
    HIITL_SYNC_TELEMETRY_LEVEL: Telemetry redaction level (default: standard)
    HIITL_SYNC_TELEMETRY_BUFFER_SIZE: Max buffered telemetry records (default: 60)
    HIITL_SYNC_TELEMETRY_SAMPLE_RATE: Sampling rate for detailed stats (default: 1.0)
"""

import re
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hiitl.core.types import Environment


def _validate_org_id(v: str) -> str:
    """Validate org_id matches the required pattern."""
    pattern = r"^org_[a-z0-9]{18,}$"
    if not re.match(pattern, v):
        raise ValueError(
            f"Invalid org_id '{v}'. Must match pattern 'org_[a-z0-9]{{18,}}'. "
            f"Example: 'org_mycompany123456789'"
        )
    return v


class LocalModeConfig(BaseSettings):
    """Configuration for HIITL SDK in local/hybrid mode.

    Used for both pure local mode (no api_key) and hybrid mode (api_key
    present, local evaluation with future sync support).

    Attributes:
        environment: Execution environment (dev, stage, or prod)
        agent_id: Agent identifier (arbitrary string)
        org_id: Organization ID (must match pattern org_[a-z0-9]{18,})
        mode: Policy evaluation mode (OBSERVE_ALL or RESPECT_POLICY)
        policy_path: Path to policy file (JSON or YAML), optional for zero-config
        audit_db_path: Path to SQLite audit database
        enable_rate_limiting: Whether to enforce rate limits
        routes_path: Path to routes directory (optional)
        signature_key: HMAC-SHA256 key for envelope signing (optional)
        api_key: API key (stored for future sync engine, optional)
    """

    environment: Environment = Field(..., description="Execution environment: dev, stage, or prod")
    agent_id: str = Field(..., description="Agent identifier")
    org_id: str = Field(..., description="Organization ID")
    mode: str = Field(default="OBSERVE_ALL", description="Policy mode: OBSERVE_ALL or RESPECT_POLICY")
    policy_path: Optional[str] = Field(default=None, description="Path to policy file (JSON or YAML)")
    audit_db_path: str = Field(default="./hiitl_audit.db")
    enable_rate_limiting: bool = Field(default=True)
    routes_path: Optional[str] = Field(default=None)
    signature_key: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None, description="API key for future sync engine")

    model_config = SettingsConfigDict(env_prefix="HIITL_", case_sensitive=False)

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        return _validate_org_id(v)


class HostedModeConfig(BaseSettings):
    """Configuration for HIITL SDK in hosted mode.

    In hosted mode, the SDK calls the ECP server's /v1/evaluate endpoint
    instead of evaluating locally. Audit, rate limiting, and policy
    management are all server-side.

    Attributes:
        environment: Execution environment (dev, stage, or prod)
        agent_id: Agent identifier (arbitrary string)
        org_id: Organization ID (must match pattern org_[a-z0-9]{18,})
        api_key: API key for server authentication (Bearer token)
        server_url: ECP server URL (e.g., "https://ecp.hiitl.com")
        timeout: HTTP request timeout in seconds (default: 5.0)
        max_retries: Max retry attempts on transient failures (default: 3)
        signature_key: HMAC-SHA256 key for envelope signing (optional)
    """

    environment: Environment = Field(..., description="Execution environment: dev, stage, or prod")
    agent_id: str = Field(..., description="Agent identifier")
    org_id: str = Field(..., description="Organization ID")
    api_key: str = Field(..., description="API key for server authentication")
    server_url: str = Field(..., description="ECP server URL")
    timeout: float = Field(default=5.0, description="HTTP timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts", ge=0, le=10)
    signature_key: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(env_prefix="HIITL_", case_sensitive=False)

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        return _validate_org_id(v)

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                f"Invalid server_url '{v}'. Must start with 'http://' or 'https://'. "
                f"Example: 'https://ecp.hiitl.com'"
            )
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError(
                "API key is too short. Provide a valid API key from your ECP dashboard."
            )
        return v


class SyncConfig(BaseSettings):
    """Configuration for sync engine.

    Controls sync intervals, buffer sizes, cache location, and circuit
    breaker behavior. All parameters have sensible defaults per the
    sync engine spec.

    Attributes:
        server_url: ECP server URL for sync target
        cache_dir: Disk cache directory (default: ~/.hiitl/cache/)
        audit_sync_interval: Seconds between audit uploads (default: 30)
        policy_sync_interval: Seconds between policy refreshes (default: 300)
        route_sync_interval: Seconds between route refreshes (default: 300)
        kill_switch_poll_interval: Seconds between kill switch polls (default: 30)
        audit_batch_size: Max records per audit upload batch (default: 100)
        max_buffer_records: Max audit records in memory buffer (default: 10000)
        sync_init_timeout: Cold start sync timeout in seconds (default: 10)
        circuit_breaker_threshold: Consecutive failures before circuit opens (default: 5)
        circuit_breaker_reset: Seconds before half-open probe (default: 60)
        max_cache_stale_age: Seconds before CACHE_STALE warning (default: 86400)
        sync_timeout: HTTP timeout for sync requests in seconds (default: 10.0)
        sync_max_retries: Max retry attempts for sync requests (default: 3)
        telemetry_sync_interval: Seconds between telemetry uploads (default: 60)
        telemetry_level: Redaction level: full/standard/minimal/off (default: standard)
        telemetry_buffer_size: Max buffered telemetry records (default: 60)
        telemetry_sample_rate: Fraction of evaluations to sample for detailed stats (default: 1.0)
    """

    server_url: str = Field(
        default="https://api.hiitl.com",
        description="ECP server URL for sync target",
    )
    cache_dir: str = Field(
        default="~/.hiitl/cache/",
        description="Disk cache directory",
    )
    audit_sync_interval: int = Field(default=30, ge=5, le=3600)
    policy_sync_interval: int = Field(default=300, ge=30, le=86400)
    route_sync_interval: int = Field(default=300, ge=30, le=86400)
    kill_switch_poll_interval: int = Field(default=30, ge=5, le=3600)
    audit_batch_size: int = Field(default=100, ge=1, le=1000)
    max_buffer_records: int = Field(default=10000, ge=100, le=1000000)
    sync_init_timeout: int = Field(default=10, ge=1, le=120)
    circuit_breaker_threshold: int = Field(default=5, ge=1, le=100)
    circuit_breaker_reset: int = Field(default=60, ge=5, le=3600)
    max_cache_stale_age: int = Field(default=86400, ge=60, le=604800)
    sync_timeout: float = Field(default=10.0, ge=1.0, le=60.0)
    sync_max_retries: int = Field(default=3, ge=0, le=10)
    telemetry_sync_interval: int = Field(default=60, ge=5, le=3600)
    telemetry_level: str = Field(default="standard")
    telemetry_buffer_size: int = Field(default=60, ge=10, le=1000)
    telemetry_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(env_prefix="HIITL_SYNC_", case_sensitive=False)

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                f"Invalid server_url '{v}'. Must start with 'http://' or 'https://'. "
                f"Example: 'https://api.hiitl.com'"
            )
        return v

    @field_validator("telemetry_level")
    @classmethod
    def validate_telemetry_level(cls, v: str) -> str:
        valid = ("full", "standard", "minimal", "off")
        if v not in valid:
            raise ValueError(
                f"Invalid telemetry_level '{v}'. Must be one of: {', '.join(valid)}. "
                f"Use 'standard' for balanced privacy/utility, 'off' to disable telemetry."
            )
        return v
