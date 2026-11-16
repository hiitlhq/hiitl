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
    ...     server_url="https://api.hiitl.com"
    ... )

Environment variables (``HIITL()`` reads each one its arguments leave unset;
``ClientSettings`` and ``SyncConfig`` below are the readers):
    HIITL_ENVIRONMENT: dev, stage, or prod (default: dev)
    HIITL_AGENT_ID: Agent identifier (default: default)
    HIITL_ORG_ID: Organization ID (must match pattern)
    HIITL_MODE: OBSERVE_ALL or RESPECT_POLICY (default: OBSERVE_ALL)
    HIITL_POLICY_PATH: Path to policy file (local/hybrid mode)
    HIITL_AUDIT_DB_PATH: Path to SQLite database (default: ./hiitl_audit.db)
    HIITL_ENABLE_RATE_LIMITING: Enable rate limiting (default: true)
    HIITL_ROUTES_PATH: Path to the route config directory (optional)
    HIITL_SIGNATURE_KEY: HMAC signature key (optional)
    HIITL_DEDUP_WINDOW_SECONDS: A repeated idempotency_key within it returns the first decision (default: 86400)
    HIITL_API_KEY: API key (hybrid/hosted mode)
    HIITL_SERVER_URL: Server URL (the sync target in hybrid mode; required for hosted mode)
    HIITL_EVALUATION: local or remote; remote is the explicit opt-in to hosted mode (default: local)
    HIITL_SYNC: false keeps a client with an api_key in pure local mode (default: true)
    HIITL_COLD_START_BEHAVIOR: warn-and-observe, fail-closed, or observe-silent (default: warn-and-observe)
    HIITL_TIMEOUT: HTTP timeout in seconds (hosted mode, default: 5.0)
    HIITL_MAX_RETRIES: Max retry attempts (hosted mode, default: 3)
    HIITL_FAIL_MODE: FAIL_CLOSED or FAIL_OPEN, what an outage answers (hosted mode, default: FAIL_CLOSED)

    Telemetry configuration (docs/specs/telemetry_schema.md section 5, one family):
    HIITL_TELEMETRY_LEVEL: full, standard, minimal, or off; off sends no telemetry (hybrid mode, default: standard)
    HIITL_TELEMETRY_INTERVAL: Telemetry upload interval in seconds, 5 to 3600 (default: 60)
    HIITL_TELEMETRY_BUFFER_SIZE: Max buffered telemetry records, 10 to 1000 (default: 60)
    HIITL_TELEMETRY_SAMPLE_RATE: Fraction of evaluations whose details are counted, 0 to 1 (default: 1.0)
    HIITL_TELEMETRY_PARAMETER_TOOLS: JSON list of actions whose parameters telemetry counts (default: [])

    Sync configuration (docs/specs/sync_engine.md section 9):
    HIITL_CACHE_DIR: Disk cache location (default: ~/.hiitl/cache/)
    HIITL_SYNC_AUDIT_INTERVAL: Audit upload interval in seconds (default: 30)
    HIITL_SYNC_POLICY_INTERVAL: Policy refresh interval in seconds (default: 300)
    HIITL_SYNC_ROUTE_INTERVAL: Route refresh interval in seconds (default: 300)
    HIITL_SYNC_KS_INTERVAL: Kill switch poll interval in seconds (default: 30)
    HIITL_SYNC_AUDIT_BATCH: Max records per audit upload (default: 100)
    HIITL_SYNC_MAX_BUFFER: Unsynced audit records before BUFFER_FULL (default: 10000)
    HIITL_SYNC_MAX_BUFFER_BYTES: Unsynced audit bytes before BUFFER_FULL (default: 52428800)
    HIITL_SYNC_INIT_TIMEOUT: Cold start sync timeout in seconds (default: 10)
    HIITL_SYNC_CB_THRESHOLD: Circuit breaker failure threshold (default: 5)
    HIITL_SYNC_CB_RESET: Circuit breaker reset timeout in seconds (default: 60)
    HIITL_SYNC_MAX_STALE: Max cache stale age in seconds (default: 86400)
    HIITL_SYNC_TIMEOUT: HTTP timeout for sync requests in seconds (default: 10.0)
    HIITL_SYNC_MAX_RETRIES: Max retry attempts for sync requests (default: 3)

A set HIITL_SYNC_* or HIITL_TELEMETRY_* variable that no setting reads is refused when ``HIITL()`` is
constructed, naming the names a setting reads, or, for a name an earlier release read, its replacement
(``EARLIER_NAMES``; row 207), by ``hiitl.settings.unread_variables``, which each component calls with its own
families (row 222). A value outside a setting's range is refused naming the range.
"""

import json
import re
from typing import Annotated, Optional, get_args
from functools import lru_cache

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from hiitl.core.numeric_domain import validate_numeric_domain, admitted_numbers, numbers_are_admitted
from hiitl.core.input_types import model_shape, validate_numbers

from hiitl.core.error_decisions import FAIL_MODES
from hiitl.core.transport import https_refusal
from hiitl.core.types import DEDUP_WINDOW_SECONDS, Environment, ORG_ID_PATTERN
from hiitl.settings import read_variables, variable

# What a hybrid client's telemetry sends, docs/specs/telemetry_schema.md section 5's levels; "off" sends nothing
TELEMETRY_LEVELS = ("full", "standard", "minimal", "off")
# The telemetry family: every telemetry setting is read under it (telemetry_schema.md section 5; row 208)
TELEMETRY_FAMILY = "HIITL_TELEMETRY_"


def _validate_org_id(v: str) -> str:
    """Validate org_id against the envelope's own pattern, so the SDK takes every id the service mints."""
    if not re.match(ORG_ID_PATTERN, v):
        raise ValueError(
            f"Invalid org_id '{v}'. Must match the envelope's org_id pattern {ORG_ID_PATTERN!r}. "
            f"Use the org id your API key belongs to, e.g. 'org_mycompany123456789'"
        )
    return v


def _bound(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _named_range(cls, v, handler, info):
    """A value outside its field's range is refused naming the range, read from the field's own bounds
    (decision_response.md, the hosted client's settings, and telemetry_schema.md section 5: "naming the range";
    rows 208, 209). A field with no range, or a value refused for another reason, is left to its own check."""
    try:
        return handler(v)
    except ValidationError as e:
        if not {err["type"] for err in e.errors()} & {"greater_than_equal", "less_than_equal"}:
            raise
        field = cls.model_fields[info.field_name]
        bounds = {type(m).__name__: m for m in field.metadata}
        named = field.validation_alias if isinstance(field.validation_alias, str) else field.description
        raise ValueError(f"{info.field_name} ({named}) must be from {_bound(bounds['Ge'].ge)} to "
                         f"{_bound(bounds['Le'].le)}; got {v!r}") from None


def _validate_server_url(cls, v: str) -> str:
    """The URL the API key and the records go to: an https URL naming a host (sync_engine.md section 8; row 140)."""
    refusal = https_refusal(v, f"server_url ({variable(cls, 'server_url')})")
    if refusal:
        raise ValueError(refusal)
    return v.rstrip("/")


def _validate_fail_mode(v: Optional[str]) -> Optional[str]:
    """The hosted client's fail mode, one of FAIL_MODES (decision_response.md, the hosted settings table; Stop B (ii))."""
    if v is not None and v not in FAIL_MODES:
        raise ValueError(
            f"Invalid fail_mode '{v}'. Must be one of: {', '.join(FAIL_MODES)}. FAIL_CLOSED, the default, answers an "
            "outage with the action not allowed; FAIL_OPEN, opt-in, allows it without evaluation and records the warning."
        )
    return v


class _NumericSettings(BaseSettings):
    @classmethod
    @lru_cache
    def numeric_shape(cls):
        shape = model_shape(cls)
        properties = dict(shape.get('properties', {}))
        for name, field in cls.model_fields.items():
            if isinstance(field.validation_alias, str):
                properties[field.validation_alias] = properties[name]
        return {**shape, 'properties': properties}

    def __init__(self, **values):
        # Native kwargs precede the separate documented environment-text reader.
        for name, field in type(self).model_fields.items():
            kinds = {field.annotation, *get_args(field.annotation)}
            if not kinds.intersection({int, float}) or str in kinds:
                continue
            keys = (name, field.validation_alias) if isinstance(field.validation_alias, str) else (name,)
            for key in keys:
                if key in values and values[key] is not None and type(values[key]) not in (int, float):
                    raise ValueError(f"<root>[{name!r}] must be supplied as a native number; bool and text are not coerced")
        super().__init__(**values)

    @model_validator(mode="wrap")
    @classmethod
    def numeric_input(cls, value, handler):
        if numbers_are_admitted():
            return handler(value)
        shape=cls.numeric_shape()
        validate_numbers(cls.__name__, value, shape=shape)
        # The native numbers have been read. Settings' environment-text reader
        # may produce additional numbers; only those new values need admission.
        with admitted_numbers():
            result=handler(value)
        converted={}
        if isinstance(value,dict):
            for name,field in cls.model_fields.items():
                if not {field.annotation,*get_args(field.annotation)}.intersection({int,float}):
                    continue
                keys=(name,field.validation_alias) if isinstance(field.validation_alias,str)else(name,)
                if any(isinstance(value.get(key),str) for key in keys):
                    converted[name]=getattr(result,name)
        if converted:
            validate_numbers(cls.__name__, converted, shape=shape)
        return result


class LocalModeConfig(_NumericSettings):
    """Configuration for HIITL SDK in local/hybrid mode.

    Used for both pure local mode (no api_key) and hybrid mode (api_key
    present, local evaluation with future sync support).

    Attributes:
        environment: Execution environment (dev, stage, or prod)
        agent_id: Agent identifier (arbitrary string)
        org_id: Organization ID (must match the envelope's org_id pattern, ORG_ID_PATTERN)
        mode: Policy evaluation mode (OBSERVE_ALL or RESPECT_POLICY)
        policy_path: Path to policy file (JSON or YAML), optional for zero-config
        audit_db_path: Path to SQLite audit database
        enable_rate_limiting: Whether to enforce rate limits
        routes_path: Path to routes directory (optional)
        signature_key: HMAC-SHA256 key for envelope signing (optional)
        dedup_window_seconds: A repeated idempotency key within it returns the first decision (row 143)
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
    dedup_window_seconds: int = Field(default=DEDUP_WINDOW_SECONDS)
    api_key: Optional[str] = Field(default=None, description="API key for future sync engine")

    model_config = SettingsConfigDict(env_prefix="HIITL_", case_sensitive=False)

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        return _validate_org_id(v)


class HostedModeConfig(_NumericSettings):
    """Configuration for HIITL SDK in hosted mode.

    In hosted mode, the SDK calls the ECP server's /v1/evaluate endpoint
    instead of evaluating locally. Audit, rate limiting, and policy
    management are all server-side.

    Attributes:
        environment: Execution environment (dev, stage, or prod)
        agent_id: Agent identifier (arbitrary string)
        org_id: Organization ID (must match the envelope's org_id pattern, ORG_ID_PATTERN)
        api_key: API key for server authentication (Bearer token)
        server_url: ECP server URL (e.g., "https://api.hiitl.com")
        timeout: HTTP request timeout in seconds (default: 5.0; 0.1 to 30, row 209)
        max_retries: Max retry attempts on transient failures (default: 3; 0 to 10)
        signature_key: HMAC-SHA256 key for envelope signing (optional)
        fail_mode: What an outage answers: FAIL_CLOSED (default) or FAIL_OPEN, opt-in (Stop B (ii))
        audit_db_path: The local store that holds what the service could not take (Stop B (i), row 200)
    """

    environment: Environment = Field(..., description="Execution environment: dev, stage, or prod")
    agent_id: str = Field(..., description="Agent identifier")
    org_id: str = Field(..., description="Organization ID")
    api_key: str = Field(..., description="API key for server authentication")
    server_url: str = Field(..., description="ECP server URL")
    timeout: float = Field(default=5.0, description="HTTP timeout in seconds", ge=0.1, le=30)
    max_retries: int = Field(default=3, description="Max retry attempts", ge=0, le=10)
    signature_key: Optional[str] = Field(default=None)
    fail_mode: str = Field(default="FAIL_CLOSED")
    audit_db_path: str = Field(default=LocalModeConfig.model_fields["audit_db_path"].default)

    model_config = SettingsConfigDict(env_prefix="HIITL_", case_sensitive=False)

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        return _validate_org_id(v)

    @field_validator("fail_mode")
    @classmethod
    def validate_fail_mode(cls, v: Optional[str]) -> Optional[str]:
        return _validate_fail_mode(v)

    validate_range = field_validator("*", mode="wrap")(classmethod(_named_range))

    validate_server_url = field_validator("server_url")(classmethod(_validate_server_url))

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError(
                "API key is too short. Provide a valid API key from your ECP dashboard."
            )
        return v


class ClientSettings(LocalModeConfig):
    """Every setting ``HIITL()`` takes as a value, resolved by the precedence above.

    ``HIITL()`` passes only the arguments it was given; a setting it leaves
    unset is read from ``HIITL_<NAME>``, then falls to the default here. The
    local and hybrid modes use these settings as their ``LocalModeConfig``;
    hosted mode builds its ``HostedModeConfig`` from them.

    Attributes (beyond LocalModeConfig's):
        server_url: ECP server URL (the hosted target; the hybrid sync target is SyncConfig's)
        timeout: Hosted HTTP timeout in seconds (HostedModeConfig's default when unset)
        max_retries: Hosted retry attempts (HostedModeConfig's default when unset)
        fail_mode: What a hosted outage answers (HostedModeConfig's default, FAIL_CLOSED, when unset)
        evaluation: "local" or "remote"; "remote" is the explicit opt-in to hosted mode
        sync: False keeps a client with an api_key in pure local mode
        cold_start_behavior: warn-and-observe, fail-closed, or observe-silent (hybrid mode)
        telemetry_level: What the hybrid client's telemetry sends: full, standard, minimal, or off, which
            sends nothing (docs/specs/telemetry_schema.md section 5)
    """

    environment: Environment = Field(default=Environment.DEV, description="Execution environment: dev, stage, or prod")
    agent_id: str = Field(default="default", description="Agent identifier")
    org_id: str = Field(default="org_devlocal0000000000", description="Organization ID")
    server_url: Optional[str] = Field(default=None)
    timeout: Optional[float] = Field(default=None)
    max_retries: Optional[int] = Field(default=None)
    fail_mode: Optional[str] = Field(default=None)
    evaluation: str = Field(default="local")
    sync: bool = Field(default=True)
    cold_start_behavior: str = Field(default="warn-and-observe")
    telemetry_level: str = Field(default="standard")

    @classmethod
    @lru_cache
    def numeric_shape(cls):
        # These optional settings become HostedModeConfig's fields when used.
        # Read their remedies from that owner; this adds no new range check.
        from hiitl.core.numeric_domain import numeric_declaration
        shape = super().numeric_shape()
        owned = HostedModeConfig.numeric_shape()
        return {**shape, 'properties': {**shape['properties'], **{
            name: declaration for name, declaration in owned['properties'].items()
            if name in shape['properties'] and numeric_declaration(owned, (name,)) is not None
        }}}

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, v: Optional[str]) -> Optional[str]:
        """Refused when the client is constructed, whatever its mode (sync_engine.md section 8; row 140)."""
        return None if v is None else _validate_server_url(cls, v)

    @field_validator("fail_mode")
    @classmethod
    def validate_fail_mode(cls, v: Optional[str]) -> Optional[str]:
        return _validate_fail_mode(v)

    @field_validator("telemetry_level")
    @classmethod
    def validate_telemetry_level(cls, v: str) -> str:
        if v not in TELEMETRY_LEVELS:
            levels = ", ".join(repr(level) for level in TELEMETRY_LEVELS)
            raise ValueError(
                f"Invalid telemetry_level '{v}'. Must be one of: {levels}. "
                "'standard' sends counts and no parameter value; 'off' sends no telemetry."
            )
        return v


class SyncConfig(_NumericSettings):
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
        max_buffer_records: Unsynced audit records at which BUFFER_FULL is emitted (default: 10000)
        max_buffer_size_bytes: Unsynced audit bytes at which BUFFER_FULL is emitted (default: 50 MB)
        sync_init_timeout: Cold start sync timeout in seconds (default: 10)
        circuit_breaker_threshold: Consecutive failures before circuit opens (default: 5)
        circuit_breaker_reset: Seconds before half-open probe (default: 60)
        max_cache_stale_age: Seconds before CACHE_STALE warning (default: 86400)
        sync_timeout: HTTP timeout for sync requests in seconds (default: 10.0)
        sync_max_retries: Max retry attempts for sync requests (default: 3)
        telemetry_sync_interval: Seconds between telemetry uploads (default: 60)
        telemetry_buffer_size: Max buffered telemetry records (default: 60)
        telemetry_sample_rate: Fraction of evaluations to sample for detailed stats (default: 1.0)
        telemetry_parameter_tools: Actions whose parameters telemetry counts; none by
            default (telemetry_schema.md §6, "opt-in per tool")
    """

    # Each setting's environment variable is the one docs/specs/sync_engine.md section 9 names, and each
    # telemetry setting's the one telemetry_schema.md section 5 names (the alias; row 208)
    server_url: str = Field(
        default="https://api.hiitl.com",
        description="ECP server URL for sync target",
        validation_alias="HIITL_SERVER_URL",
    )
    cache_dir: str = Field(
        default="~/.hiitl/cache/",
        description="Disk cache directory",
        validation_alias="HIITL_CACHE_DIR",
    )
    audit_sync_interval: int = Field(default=30, ge=5, le=3600, validation_alias="HIITL_SYNC_AUDIT_INTERVAL")
    policy_sync_interval: int = Field(default=300, ge=30, le=86400, validation_alias="HIITL_SYNC_POLICY_INTERVAL")
    route_sync_interval: int = Field(default=300, ge=30, le=86400, validation_alias="HIITL_SYNC_ROUTE_INTERVAL")
    kill_switch_poll_interval: int = Field(default=30, ge=5, le=3600, validation_alias="HIITL_SYNC_KS_INTERVAL")
    audit_batch_size: int = Field(default=100, ge=1, le=1000, validation_alias="HIITL_SYNC_AUDIT_BATCH")
    max_buffer_records: int = Field(default=10000, ge=100, le=1000000, validation_alias="HIITL_SYNC_MAX_BUFFER")
    max_buffer_size_bytes: int = Field(
        default=52428800, ge=1048576, le=10737418240, validation_alias="HIITL_SYNC_MAX_BUFFER_BYTES",
    )
    sync_init_timeout: int = Field(default=10, ge=1, le=120, validation_alias="HIITL_SYNC_INIT_TIMEOUT")
    circuit_breaker_threshold: int = Field(default=5, ge=1, le=100, validation_alias="HIITL_SYNC_CB_THRESHOLD")
    circuit_breaker_reset: int = Field(default=60, ge=5, le=3600, validation_alias="HIITL_SYNC_CB_RESET")
    max_cache_stale_age: int = Field(default=86400, ge=60, le=604800, validation_alias="HIITL_SYNC_MAX_STALE")
    sync_timeout: float = Field(default=10.0, ge=1.0, le=60.0, validation_alias="HIITL_SYNC_TIMEOUT")
    sync_max_retries: int = Field(default=3, ge=0, le=10, validation_alias="HIITL_SYNC_MAX_RETRIES")
    telemetry_sync_interval: int = Field(default=60, ge=5, le=3600, validation_alias="HIITL_TELEMETRY_INTERVAL")
    telemetry_buffer_size: int = Field(default=60, ge=10, le=1000, validation_alias="HIITL_TELEMETRY_BUFFER_SIZE")
    telemetry_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0, validation_alias="HIITL_TELEMETRY_SAMPLE_RATE")
    telemetry_parameter_tools: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias="HIITL_TELEMETRY_PARAMETER_TOOLS",
    )

    model_config = SettingsConfigDict(env_prefix="HIITL_SYNC_", case_sensitive=False, populate_by_name=True)

    validate_range = field_validator("*", mode="wrap")(classmethod(_named_range))

    @field_validator("telemetry_parameter_tools", mode="before")
    @classmethod
    def validate_parameter_tools(cls, v):
        """The variable's text is a JSON list of action names (telemetry_schema.md section 5); a given list is taken
        as it is."""
        if not isinstance(v, str):
            return v
        try:
            tools = json.loads(v)
        except ValueError:
            tools = None
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise ValueError(f"telemetry_parameter_tools (HIITL_TELEMETRY_PARAMETER_TOOLS) is a JSON list of action "
                             f"names, e.g. '[\"process_payment\"]'; got {v!r}")
        return tools

    validate_server_url = field_validator("server_url")(classmethod(_validate_server_url))


# Every variable a setting reads, read from the settings models
READ_VARIABLES = read_variables(ClientSettings, SyncConfig)
# The families the SDK's specs give it (sync_engine.md section 9, telemetry_schema.md section 5): a set name in one
# that no setting reads is refused (row 207)
FAMILIES = (SyncConfig.model_config["env_prefix"], TELEMETRY_FAMILY)
# Each telemetry setting's earlier name, the sync prefix and its field's name (as an earlier release read it), and
# the name it is read under now (telemetry_schema.md section 5, "Names earlier releases read")
EARLIER_NAMES = {
    SyncConfig.model_config["env_prefix"] + name.upper(): variable(model, name)
    for model in (ClientSettings, SyncConfig) for name in model.model_fields
    if variable(model, name).startswith(TELEMETRY_FAMILY)
}
