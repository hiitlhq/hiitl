"""HIITL SDK Client - Main developer-facing API.

Single entry point: evaluate(). Deployment mode auto-detected from
constructor arguments:

- **api_key present**: Hybrid mode (default) — local evaluation with
  background sync to hosted service. Microsecond latency, server-managed
  policies synced in background.
- **No api_key**: Pure local mode — file-based policies, SQLite audit,
  no network. For development, CI/CD, air-gapped environments.
- **api_key + evaluation="remote"**: Pure hosted mode (opt-in) — HTTP
  call to server for every evaluation. Higher latency and no local policy
  state; a local audit store holds only what the service could not take.

Example (zero-config local — OBSERVE mode):
    >>> from hiitl import HIITL
    >>> hiitl = HIITL()
    >>> decision = hiitl.evaluate("send_email")
    >>> if decision.allowed:
    ...     send_email()

Example (hybrid — the default with api_key):
    >>> hiitl = HIITL(
    ...     agent_id="payment-agent",
    ...     org_id="org_mycompany123456789",
    ...     api_key="sk_live_abc123...",
    ... )
    >>> decision = hiitl.evaluate(
    ...     "process_payment",
    ...     parameters={"amount": 500, "currency": "USD"},
    ...     target={"account_id": "acct_123"},
    ... )
    >>> if decision.allowed:
    ...     process_payment()

Example (hosted — explicit opt-in):
    >>> hiitl = HIITL(
    ...     agent_id="payment-agent",
    ...     org_id="org_mycompany123456789",
    ...     api_key="sk_live_abc123...",
    ...     server_url="https://api.hiitl.com",
    ...     evaluation="remote",
    ...     signature_key="...",  # the API key's signing secret, shown when the key was created
    ... )

Every value argument left unset is read from its ``HIITL_<NAME>`` environment
variable, then falls to its default (``hiitl.sdk.config`` lists them).
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import ValidationError

from hiitl.core import routing
from hiitl.core.canonical import envelope_hash, envelope_signature, envelope_verifies
from hiitl.core.error_decisions import MESSAGES, audit_write_failed, error_block, error_decision
from hiitl.core.evaluator import observe
from hiitl.core.operator_kinds import OperatorKindError
from hiitl.core.lifecycle import MESSAGES as LIFECYCLE_MESSAGES
from hiitl.core.lifecycle import execution_result, recorded_result, result_refusal, unread_review
from hiitl.core.input_types import supplied
from hiitl.core.numeric_domain import NumericDomainError, validate_numeric_domain, admitted_numbers, copy_supplied_input
from hiitl.core.input_types import model_shape
from hiitl.core.lifecycle import RESULT_NUMBER_SHAPE
from hiitl.sdk.audit import _admitted_envelope_record
from hiitl.sdk.admission import call_numeric_shape
from hiitl.core.rate_limits import limiter_failed
from hiitl.core.redaction import Redaction
from hiitl.core.types import (
    CostEstimate,
    Decision,
    DecisionType,
    ENVELOPE_SCHEMA_VERSION,
    Envelope,
    Environment,
    Operation,
    PolicySet,
    Principal,
    Sensitivity,
)
from hiitl.sdk.audit import envelope_record
from hiitl.sdk.config import EARLIER_NAMES, FAMILIES, READ_VARIABLES, ClientSettings, HostedModeConfig, SyncConfig
from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    LifecycleError,
    PolicyLoadError,
)
from hiitl.sdk.trace_context import active_trace_id
from hiitl.settings import unread_variables

logger = logging.getLogger(__name__)

# What an empty policy set does in each client mode, as the evaluator decides it: OBSERVE_ALL
# observes and allows every action; RESPECT_POLICY finds no matching rule and blocks.
_EMPTY_POLICY_OUTCOME = {
    "OBSERVE_ALL": "running in OBSERVE_ALL: every action is observed and allowed",
    "RESPECT_POLICY": "running in RESPECT_POLICY with no policy loaded: every action is blocked (NO_MATCHING_RULE)",
}


def _zero_config_policy(settings) -> PolicySet:
    """The zero-config set: no rules, scoped to the configured org and environment (policy_format.md's Policy Set
    Fields; HTL-22 row 165)."""
    return PolicySet(name="__zero_config__", version="v0.0.0",
                     description="Zero-config: no rules, so every action is observed",
                     scope={"org_id": settings.org_id, "environment": settings.environment}, rules=[])


def _operation(value: Union[str, Operation]) -> Operation:
    """The envelope's operation, or EnvelopeValidationError naming the valid ones (Principle 11; HTL-20, row 145).
    Every mode reads it here, so the text is the same in local, hybrid and hosted."""
    if isinstance(value, Operation):
        return value
    try:
        return Operation(value)
    except ValueError:
        valid = ", ".join(o.value for o in Operation)
        message = f"operation '{value}' is not a valid operation. Use one of: {valid} (the default is 'execute')."
        raise EnvelopeValidationError(message, validation_errors=[f"operation: {message}"]) from None


class HIITL:
    """HIITL client for policy evaluation.

    Deployment mode is auto-detected from constructor arguments:

    - **api_key present**: Hybrid (default) — local eval + background sync
    - **No api_key**, or **sync=False**: Pure local — file-based policies, no network
    - **api_key + evaluation="remote"**: Hosted — server-side eval (opt-in)

    The hybrid architecture is the default product experience. When you
    provide an api_key, the SDK evaluates locally at microsecond latency
    while syncing policies, audit records, and kill switches with the
    hosted service in the background.

    Zero-config example:
        >>> hiitl = HIITL()
        >>> decision = hiitl.evaluate("send_email")
        >>> print(decision.allowed, decision.observed)

    Hybrid example (recommended for production):
        >>> hiitl = HIITL(
        ...     agent_id="payment-agent",
        ...     environment="prod",
        ...     org_id="org_mycompany123456789",
        ...     api_key="sk_live_abc123...",
        ... )
    """

    # Decision types that trigger escalation (route config resolution)
    ESCALATION_TYPES = {
        DecisionType.REQUIRE_APPROVAL,
        DecisionType.PAUSE,
        DecisionType.ESCALATE,
    }

    def __init__(
        self,
        *,
        # Identity
        agent_id: Optional[str] = None,
        environment: Optional[str] = None,
        org_id: Optional[str] = None,
        # Policy mode
        mode: Optional[str] = None,
        # Local/hybrid parameters
        policy_path: Optional[str] = None,
        audit_db_path: Optional[str] = None,
        enable_rate_limiting: Optional[bool] = None,
        routes_path: Optional[str] = None,
        signature_key: Optional[str] = None,
        dedup_window_seconds: Optional[int] = None,
        # What the local audit store records (event_format.md §Redaction, row 139)
        redact_fields: Optional[List[str]] = None,
        recorded_parameters: Optional[Dict[str, List[str]]] = None,
        # Hosted/hybrid parameters
        api_key: Optional[str] = None,
        server_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        fail_mode: Optional[str] = None,
        # Evaluation mode control
        evaluation: Optional[str] = None,
        sync: Optional[bool] = None,
        # Sync configuration overrides
        cache_dir: Optional[str] = None,
        sync_config: Optional[SyncConfig] = None,
        # Cold-start behavior (TICKET-116)
        cold_start_behavior: Optional[str] = None,
        # What hybrid telemetry sends (telemetry_schema.md §5, row 172)
        telemetry_level: Optional[str] = None,
        # The verified principal (T-130 A7): checks a token passed to evaluate()
        principal_verifier: Optional[Callable[[str], Dict[str, Any]]] = None,
        # The HTTP client a sync route is asked with (TICKET-046); default: one created on first use
        route_client: Optional[Any] = None,
    ):
        """Initialize HIITL client.

        All parameters are keyword-only with sensible defaults.
        ``HIITL()`` with no arguments works in local OBSERVE mode. A value
        argument left unset is read from ``HIITL_<NAME>`` (``HIITL_API_KEY``,
        ``HIITL_POLICY_PATH``, ...), then falls to the default below.

        Args:
            agent_id: Agent identifier (default: "default")
            environment: Execution environment — dev, stage, or prod (default: "dev")
            org_id: Organization ID (default: dev-local placeholder)
            mode: Policy mode — "OBSERVE_ALL" or "RESPECT_POLICY" (default: "OBSERVE_ALL")

            Local evaluation:
                policy_path: Path to policy file (JSON or YAML). Optional in
                    OBSERVE_ALL mode (uses empty policy set). In hybrid mode,
                    used as fallback when server cache is unavailable.
                audit_db_path: Path to SQLite audit database (default: ./hiitl_audit.db). In hosted
                    mode, where the client records an outage and holds what the service could not take
                enable_rate_limiting: Whether to enforce rate limits (default: True)
                routes_path: Path to route config files directory (optional)
                signature_key: HMAC-SHA256 key for envelope signing (optional)
                dedup_window_seconds: A repeated idempotency_key within it returns the first decision and
                    writes no record (default: 24 hours)
                redact_fields: Envelope paths whose values the local audit store
                    records as "[REDACTED]", e.g. ["parameters.account_number"]
                    (event_format.md §Redaction). Evaluation sees the whole
                    envelope. In hosted mode they apply to the records the client
                    holds during an outage; the service's record takes the
                    organisation's redaction_policy.
                recorded_parameters: {action: [parameter names]}. When set,
                    every other parameter is recorded as an HMAC-SHA256 hash of
                    its value, under a key kept beside the audit store (the MCP
                    gateway sets it). In hybrid mode the store also redacts the
                    fields the organisation's redaction_policy declares.

            Server connection:
                api_key: API key for server auth (Bearer token). When present,
                    enables hybrid mode (local eval + background sync).
                server_url: ECP server URL. In hybrid mode, defaults to
                    https://api.hiitl.com. Required for hosted mode.
                timeout: HTTP timeout in seconds, 0.1 to 30 (default: 5.0)
                max_retries: Max retry attempts on transient failures, 0 to 10 (default: 3)
                fail_mode: What a hosted outage answers: "FAIL_CLOSED" (default), the action is
                    not allowed, or "FAIL_OPEN" (opt-in), the action is allowed without being
                    evaluated and the warning recorded

            Evaluation mode:
                evaluation: Where evaluation happens — "local" (default) or
                    "remote" (opt-in hosted mode, requires api_key + server_url).
                sync: With an api_key, False keeps the client in pure local
                    mode: no background sync (default: True).

            Sync:
                cache_dir: Override disk cache directory (default: ~/.hiitl/cache/)
                sync_config: Full SyncConfig override (advanced). An explicit
                    server_url or cache_dir applies on top of it.

            Cold-start (TICKET-116, hybrid mode only):
                cold_start_behavior: How to handle the case where no disk
                    cache exists AND the initial sync to the server times
                    out or fails. One of:
                      - "warn-and-observe" (default): log a WARNING and
                        continue with an empty policy set until background
                        sync succeeds (OBSERVE_ALL allows every action;
                        RESPECT_POLICY blocks every action). Every Decision
                        carries cache_status='empty' until that happens.
                      - "fail-closed": raise ColdStartError from the
                        constructor instead of continuing silently. Use
                        when you must not run un-policied in production.
                      - "observe-silent": current pre-TICKET-116 behavior
                        — log at INFO only. Opt-in; not recommended.

            Telemetry (hybrid mode only; docs/specs/telemetry_schema.md section 5):
                telemetry_level: What the background sync sends as usage
                    telemetry: "full", "standard" (default), "minimal", or
                    "off", which collects and sends nothing.

        Raises:
            ConfigurationError: If configuration is invalid
            ColdStartError: If hybrid cold-start fails and cold_start_behavior='fail-closed'
            PolicyLoadError: If policy file cannot be loaded (local/hybrid)
            AuditLogError: If audit database cannot be initialized (local/hybrid)
        """
        # config.py's precedence: a constructor argument, then HIITL_<NAME>, then the default. The
        # settings model's fields are the value arguments; only the ones given are passed, so
        # ClientSettings reads the rest from the environment.
        args = locals()
        # A set variable of a settings family that no setting reads is refused, never ignored (row 207)
        unread = unread_variables(os.environ, FAMILIES, READ_VARIABLES, EARLIER_NAMES)
        if unread:
            raise ConfigurationError(
                f"{unread}\n\nA HIITL_SYNC_* or HIITL_TELEMETRY_* variable no setting reads is refused "
                "(docs/specs/sync_engine.md section 9; telemetry_schema.md section 5)."
            )
        try:
            settings = ClientSettings(
                **{name: args[name] for name in ClientSettings.model_fields if args[name] is not None}
            )
        except (ValidationError, ValueError) as e:
            raise ConfigurationError(
                f"Invalid HIITL configuration: {e}\n\n"
                "Check that all required parameters are provided and valid."
            ) from e

        self._hosted_client = None
        self._principal_verifier = principal_verifier
        self._route_client = route_client
        self._sync_engine = None
        self._sync_cache = None
        self._telemetry_collector = None
        self._api_key = settings.api_key
        self._eval_mode = settings.mode

        # TICKET-116: validate + stash cold_start_behavior. Validated up
        # front so a typo fails the constructor instead of being
        # ignored at sync-failure time.
        _valid_cold_start = {"warn-and-observe", "fail-closed", "observe-silent"}
        if settings.cold_start_behavior not in _valid_cold_start:
            raise ConfigurationError(
                f"cold_start_behavior='{settings.cold_start_behavior}' is invalid. "
                f"Must be one of: {', '.join(sorted(_valid_cold_start))}."
            )
        self._cold_start_behavior = settings.cold_start_behavior
        _valid_evaluation = {"local", "remote"}
        if settings.evaluation not in _valid_evaluation:
            raise ConfigurationError(
                f"evaluation='{settings.evaluation}' is invalid. Must be one of: {', '.join(sorted(_valid_evaluation))}. "
                "'remote' is the explicit opt-in to hosted evaluation."
            )

        # Mode detection, the deployment modes page's table (docs-site/concepts/deployment-modes.mdx):
        # api_key + evaluation="remote" → hosted (explicit opt-in)
        # api_key present, sync on → hybrid (default architecture)
        # no api_key, or sync=False → local
        if settings.api_key and settings.evaluation == "remote":
            self._mode = "hosted"
        elif settings.api_key and settings.sync:
            self._mode = "hybrid"
        else:
            self._mode = "local"

        # What the local store records (event_format.md §Redaction, row 139); in hosted mode, the records the client
        # holds during an outage (Stop B (i))
        try:
            self._redaction = Redaction.declared(redact_fields, recorded_parameters)
        except ValueError as e:
            raise ConfigurationError(str(e)) from e

        if self._mode == "hosted":
            if not settings.server_url:
                raise ConfigurationError(
                    "server_url is required for hosted evaluation (evaluation='remote').\n\n"
                    "Provide your ECP server URL:\n"
                    "  HIITL(api_key='...', server_url='https://api.hiitl.com', evaluation='remote')\n\n"
                    "Or use the default hybrid mode (recommended) — local eval + sync:\n"
                    "  HIITL(api_key='...')"
                )
            self._init_hosted(settings)
        elif self._mode == "hybrid":
            self._init_hybrid(settings, server_url=server_url, cache_dir=cache_dir, sync_config=sync_config)
        else:
            # Pure local mode
            if settings.policy_path is None and settings.mode != "OBSERVE_ALL":
                raise ConfigurationError(
                    "policy_path is required for RESPECT_POLICY mode.\n\n"
                    "Provide a policy file:\n"
                    "  HIITL(policy_path='./policy.yaml', mode='RESPECT_POLICY')\n\n"
                    "Or use OBSERVE_ALL mode (default) which works without a policy file:\n"
                    "  HIITL()\n\n"
                    "Or use hybrid mode with an API key (policies sync from server):\n"
                    "  HIITL(api_key='sk_live_...')"
                )
            self._init_local(settings)

        self._warn_on_code_level_override()

    def _warn_on_code_level_override(self) -> None:
        """Log a warning when a code-level OBSERVE_ALL runs in production.

        ecp_evaluate_spec.md, Resolved Design Decision 1: "Production uses
        RESPECT_POLICY ... If a code-level override is active in a production
        environment, the SDK logs a warning." Hosted mode evaluates on the
        server, so the client's mode is not applied there.
        """
        if self._mode != "hosted" and self.config.environment == Environment.PROD and self._eval_mode == "OBSERVE_ALL":
            logger.warning(
                "HIITL is running in OBSERVE_ALL in the prod environment: every action is allowed, "
                "whatever the policy says. Production uses RESPECT_POLICY, with each rule's "
                "lifecycle_stage set in the policy: HIITL(mode='RESPECT_POLICY') or HIITL_MODE=RESPECT_POLICY."
            )

    def _init_local(self, settings: ClientSettings):
        """Initialize pure local mode components."""
        from hiitl.core import PolicyEvaluator
        from hiitl.sdk.audit import AuditLogger
        from hiitl.sdk.route_loader import RouteLoader
        from hiitl.sdk.policy_loader import PolicyLoader
        from hiitl.sdk.rate_limiter import RateLimiter

        self.config = settings

        try:
            if settings.policy_path is not None:
                self._policy_loader = PolicyLoader(self.config.policy_path)
            else:
                self._policy_loader = None
                self._empty_policy = _zero_config_policy(settings)

            self._evaluator = PolicyEvaluator()
            self._audit_logger = AuditLogger(self.config.audit_db_path, redaction=self._redaction)
            self._rate_limiter = (
                RateLimiter() if self.config.enable_rate_limiting else None
            )
            self._route_loader = (
                RouteLoader(self.config.routes_path)
                if self.config.routes_path
                else None
            )
        except Exception as e:
            raise ConfigurationError(
                f"Failed to initialize HIITL components: {e}"
            ) from e

    def _init_hybrid(
        self,
        settings: ClientSettings,
        server_url: Optional[str],
        cache_dir: Optional[str],
        sync_config: Optional[SyncConfig],
    ):
        """Initialize hybrid mode — local evaluation + background sync.

        Startup behavior:
        1. Initialize local evaluator (same components as _init_local)
        2. Create SyncCache, load from disk if available (warm start)
        3. If disk cache has policies → use them immediately
        4. If no cache → attempt initial sync (blocking, with timeout)
        5. If no cache and sync fails → fall back to local policy_path
        6. If no cache and no fallback → OBSERVE_ALL until first sync
        7. Start background sync engine (daemon thread)
        """
        from hiitl.core import PolicyEvaluator
        from hiitl.sdk.audit import AuditLogger
        from hiitl.sdk.rate_limiter import RateLimiter
        from hiitl.sdk.policy_loader import PolicyLoader
        from hiitl.sdk.route_loader import RouteLoader
        from hiitl.sdk.sync_cache import SyncCache
        from hiitl.sdk.sync_engine import SyncEngine

        # Build sync config. SyncConfig reads HIITL_SYNC_* (and HIITL_SERVER_URL, HIITL_CACHE_DIR)
        # for what it is not given; an explicit server_url or cache_dir argument applies on top of a
        # given sync_config, as a constructor argument outranks every other source.
        overrides = {name: value for name, value in (("server_url", server_url), ("cache_dir", cache_dir)) if value}
        try:
            if sync_config is not None:
                # A caller can mutate a settings model after constructing it.
                validate_numeric_domain(sync_config, shape=SyncConfig.numeric_shape())
            if sync_config is None:
                sync_config = SyncConfig(**overrides)
            elif overrides:
                sync_config = SyncConfig(**{**sync_config.model_dump(), **overrides})
        except (ValidationError, ValueError) as e:
            raise ConfigurationError(f"Invalid sync configuration: {e}") from e

        self.config = settings
        org_id, environment, api_key, policy_path = (
            settings.org_id, settings.environment, settings.api_key, settings.policy_path,
        )

        try:
            # Initialize local evaluator components
            self._evaluator = PolicyEvaluator()
            # Each write redacts the org's declared fields, as last pulled, with the SDK's own (row 163(a))
            self._audit_logger = AuditLogger(self.config.audit_db_path, redaction=self._redaction,
                                             org_declared=lambda: self._sync_cache.get_redaction_fields())
            self._rate_limiter = (
                RateLimiter() if self.config.enable_rate_limiting else None
            )
            self._route_loader = (
                RouteLoader(self.config.routes_path)
                if self.config.routes_path
                else None
            )

            # Initialize sync cache
            self._sync_cache = SyncCache(
                cache_dir=sync_config.cache_dir,
                org_id=org_id,
                environment=environment,
                max_stale_age=sync_config.max_cache_stale_age,
            )

            # Initialize telemetry collector (if not disabled)
            self._telemetry_collector = None
            if settings.telemetry_level != "off":
                from hiitl.sdk.telemetry import TelemetryCollector
                self._telemetry_collector = TelemetryCollector(
                    org_id=org_id,
                    environment=environment,
                    level=settings.telemetry_level,
                    buffer_size=sync_config.telemetry_buffer_size,
                    sample_rate=sync_config.telemetry_sample_rate,
                    parameter_tools=sync_config.telemetry_parameter_tools,
                    declaration=self._audit_logger.declaration,
                )

            # Warm start: load cached data from disk
            has_cache = self._sync_cache.load_from_disk()

            # Policy source resolution:
            # Server cache > disk cache > local policy file > empty (OBSERVE_ALL)
            self._policy_loader = None
            self._empty_policy = _zero_config_policy(settings)

            if not has_cache:
                # Cold start — attempt initial sync
                self._sync_engine = SyncEngine(
                    sync_config=sync_config,
                    sync_cache=self._sync_cache,
                    audit_logger=self._audit_logger,
                    api_key=api_key,
                    org_id=org_id,
                    environment=environment,
                    telemetry_collector=self._telemetry_collector,
                )

                initial_ok = self._sync_engine.initial_sync(
                    timeout=sync_config.sync_init_timeout
                )

                if not initial_ok and policy_path:
                    # Fall back to local policy file
                    logger.info(
                        "Cold-start sync to %s did not complete within %.1fs. Using the local "
                        "policy file as fallback, in %s, until background sync succeeds: %s",
                        sync_config.server_url,
                        sync_config.sync_init_timeout,
                        self._eval_mode,
                        policy_path,
                    )
                    self._policy_loader = PolicyLoader(policy_path)
                elif not initial_ok:
                    # TICKET-116: cold-start sync failed and no local
                    # fallback. Behavior depends on cold_start_behavior:
                    #   - fail-closed     → raise ColdStartError
                    #   - warn-and-observe → log WARNING, continue
                    #   - observe-silent  → log INFO, continue
                    if self._cold_start_behavior == "fail-closed":
                        from hiitl.sdk.exceptions import ColdStartError
                        raise ColdStartError(
                            server_url=sync_config.server_url,
                            timeout_seconds=sync_config.sync_init_timeout,
                        )
                    msg = (
                        "Cold-start sync to %s did not complete within %.1fs. "
                        "No disk cache and no local policy fallback — %s "
                        "until background sync succeeds. Every Decision will "
                        "carry cache_status='empty' until then. "
                        "Set cold_start_behavior='fail-closed' to abort the "
                        "constructor instead."
                    )
                    log = logger.warning if self._cold_start_behavior == "warn-and-observe" else logger.info
                    log(
                        msg,
                        sync_config.server_url,
                        sync_config.sync_init_timeout,
                        _EMPTY_POLICY_OUTCOME["OBSERVE_ALL" if self._eval_mode == "OBSERVE_ALL" else "RESPECT_POLICY"],
                    )
            else:
                # Warm start — sync engine created normally
                self._sync_engine = SyncEngine(
                    sync_config=sync_config,
                    sync_cache=self._sync_cache,
                    audit_logger=self._audit_logger,
                    api_key=api_key,
                    org_id=org_id,
                    environment=environment,
                    telemetry_collector=self._telemetry_collector,
                )

            # Start background sync
            self._sync_engine.start()
            logger.info("Hybrid mode active: local evaluation + background sync")

        except ConfigurationError:
            raise
        except Exception as e:
            # TICKET-116: ColdStartError is an intentional fail-closed signal,
            # not a setup failure to be wrapped. Let it propagate unchanged.
            from hiitl.sdk.exceptions import ColdStartError
            if isinstance(e, ColdStartError):
                raise
            raise ConfigurationError(
                f"Failed to initialize hybrid mode: {e}"
            ) from e

    def _init_hosted(self, settings: ClientSettings):
        """Initialize hosted mode components."""
        from hiitl.sdk.http_client import HostedClient

        # timeout, max_retries, fail_mode and audit_db_path pass only when set, so HostedModeConfig's defaults stand
        try:
            with admitted_numbers():
                self.config = HostedModeConfig(**settings.model_dump(
                    include=set(HostedModeConfig.model_fields), exclude_none=True,
                ))
        except Exception as e:
            raise ConfigurationError(
                f"Invalid HIITL configuration: {e}\n\n"
                "Check that all required parameters are provided and valid.\n"
                "Required for hosted evaluation: environment, agent_id, org_id, api_key, server_url"
            ) from e

        if not self.config.signature_key:
            raise ConfigurationError(
                "Hosted evaluation needs signature_key: the service refuses an envelope that is not signed with the "
                "API key's signing secret (403 SIGNATURE_INVALID). The secret is shown once, beside the key, when the "
                "key is created (the API keys page; the create response's signing_secret). Pass "
                "HIITL(..., signature_key=<signing secret>) or set HIITL_SIGNATURE_KEY."
            )
        self._hosted_client = HostedClient._from_admitted(self.config, redaction=self._redaction)

    @property
    def mode(self) -> str:
        """Current deployment mode ('local', 'hosted', or 'hybrid')."""
        return self._mode

    def status(self) -> dict:
        """Return SDK health status.

        Useful for monitoring and debugging. Includes mode, sync state,
        cache age, and circuit breaker status.

        Returns:
            Dict with mode, sync status, cache state, and policy version.
        """
        result = {
            "mode": self._mode,
            "environment": self.config.environment if hasattr(self, 'config') else None,
            "org_id": self.config.org_id if hasattr(self, 'config') else None,
        }

        if self._mode == "hybrid" and self._sync_engine:
            result["sync"] = self._sync_engine.status()

            # Policy version from cache
            cached = self._sync_cache.get_policies() if self._sync_cache else None
            if cached and isinstance(cached, dict):
                result["policy_version"] = cached.get("version")
                result["cache_age_seconds"] = round(
                    self._sync_cache.get_policies_age_seconds(), 1
                )
            else:
                result["policy_version"] = None
                result["cache_age_seconds"] = None

        elif self._mode == "hosted":
            result["server_url"] = self.config.server_url
            result["circuit_breakers"] = {"hosted": self._hosted_client.breaker.status()}

        return result

    def evaluate(
        self,
        action: str,
        *,
        parameters: Optional[Dict[str, Any]] = None,
        target: Optional[Dict[str, Any]] = None,
        operation: str = "execute",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        sensitivity: Optional[List[Sensitivity]] = None,
        cost_estimate: Optional[CostEstimate] = None,
        requested_scopes: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        principal_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Decision:
        """Evaluate an action against policy and return a decision.

        Only ``action`` is required. Everything else has sensible defaults.

        In hybrid mode, evaluation always happens locally at microsecond
        latency. Policies come from the sync cache (server-managed),
        with fallback to local policy files or OBSERVE_ALL mode.

        Args:
            action: Action name (e.g., "process_payment", "send_email")
            parameters: Action parameters dict (default: {})
            target: Target resource dict (default: {})
            operation: Operation type (default: "execute")
            user_id: User identifier (optional)
            session_id: Session identifier (optional)
            agent_id: Override the agent_id set at init (optional)
            confidence: Agent confidence score 0-1 (optional)
            reason: Reasoning for action (optional)
            sensitivity: Sensitivity labels (optional)
            cost_estimate: Cost estimate for action (optional)
            requested_scopes: Permission scopes this call requests (optional; envelope_schema.json
                `requested_scopes` — free strings the caller supplies, distinct from the verified principal's scopes)
            idempotency_key: Idempotency key (optional, auto-generated)
            correlation_id: Your own id tying this action to others, e.g. a request id (optional; recorded in the
                envelope as given). `trace_id` is not an option: the SDK sets it from the active OpenTelemetry span
                when the OpenTelemetry API is installed.

        Returns:
            Decision with .allowed, .ok, .blocked, .needs_approval, .observed properties.

        An error is a decision (decision_response.md "Error Handling"): once the envelope exists, a failure is answered
        as one — SIGNATURE_INVALID, POLICY_ERROR, CONTROL_PLANE_UNAVAILABLE (hosted mode, the service unreachable), or
        BLOCK with AUDIT_WRITE_FAILED, AUDIT_READ_FAILED (the dedup read) or EVALUATION_FAILED (any other failure) —
        with ``allowed`` false, the cause in ``reason_codes`` and ``error``, and the caught exception logged, never in
        the message.

        Raises:
            EnvelopeValidationError: If the envelope cannot be built (before one exists)
            ServerError: If the server answers with no decision body (hosted mode)
        """
        started = time.perf_counter()   # the call's clock: its admission is counted in its timing (HTL-43 gap 303)
        fields = copy_supplied_input({key: value for key, value in locals().items() if key not in ('self', 'started')})
        try:
            validate_numeric_domain(fields, shape=call_numeric_shape(HIITL.evaluate, Envelope))
        except NumericDomainError as error:
            raise EnvelopeValidationError(str(error), validation_errors=[str(error)]) from error
        for name in ('target', 'parameters'):
            if fields[name] is None:
                fields[name] = {}
        if self._mode == 'hosted':
            return self._evaluate_hosted(**fields)
        token = fields.pop('principal_token')
        fields['principal'] = self._verified_principal(token)
        return self._evaluate_local(**fields, started=started)

    def _verified_principal(self, token: Optional[str]) -> Optional[Principal]:
        """The verified principal for `token` (T-130 A7; envelope_schema.json `principal`): set only from what the
        configured verifier returns. A token the verifier rejects yields no principal — the envelope then carries none,
        and an identity gate blocks — and the rejection is logged."""
        if token is None:
            return None
        if self._principal_verifier is None:
            raise ConfigurationError(
                "principal_token was passed but no principal_verifier is configured. Configure "
                "HIITL(principal_verifier=fn): fn(token) checks the token (signature, issuer, audience, expiry) and "
                "returns its claims {sub, scope or scopes, iss, aud}, raising on an invalid token."
            )
        try:
            claims = self._principal_verifier(token)
            validate_numeric_domain(supplied(claims))
            optional = {key: claims[key] for key in ("scopes", "iss", "aud") if key in claims}
            if "scopes" not in claims and "scope" in claims:
                if not isinstance(claims["scope"], str):
                    raise ValueError("scope must be a string")
                optional["scopes"] = claims["scope"].split()
            return Principal(sub=claims["sub"], **optional,
                             verified_by="sdk_verifier", verified_at=datetime.now(timezone.utc))
        except Exception as e:  # the verifier's rejection: no principal, recorded in the log
            logger.warning("principal token failed verification (%s): evaluated with no verified principal", e)
            return None

    def _evaluate_hosted(
        self,
        action: str,
        operation: str,
        target: dict,
        parameters: dict,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        reason: Optional[str] = None,
        sensitivity: Optional[List[Sensitivity]] = None,
        cost_estimate: Optional[CostEstimate] = None,
        requested_scopes: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        confidence: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        principal_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Decision:
        """Evaluate via hosted ECP server. The SDK builds and signs the envelope as in local mode and sends it whole
        (the evaluate implementation guide 1.1: "The request body is the envelope"; row 134). The principal is
        not in it: the token rides in `X-Hiitl-Principal-Token` and the server verifies it (T-130 §A7)."""
        envelope = self._built_envelope(
            action=action,
            operation=_operation(operation).value,
            target=target,
            parameters=parameters,
            agent_id=agent_id if agent_id is not None else self.config.agent_id,
            user_id=user_id,
            session_id=session_id,
            confidence=confidence,
            reason=reason,
            sensitivity=sensitivity,
            cost_estimate=cost_estimate,
            requested_scopes=requested_scopes,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        return self._hosted_client._evaluate_admitted(_admitted_envelope_record(envelope), principal_token=principal_token)

    def _evaluate_local(
        self,
        action: str,
        operation: str,
        target: dict,
        parameters: dict,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        sensitivity: Optional[List[Sensitivity]] = None,
        cost_estimate: Optional[CostEstimate] = None,
        requested_scopes: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        principal: Optional[Principal] = None,
        correlation_id: Optional[str] = None,
        started: Optional[float] = None,
    ) -> Decision:
        """Evaluate via local embedded evaluator.

        Used by both local and hybrid modes. In hybrid mode, policies
        come from SyncCache first, then PolicyLoader fallback.
        """
        effective_agent_id = agent_id if agent_id is not None else self.config.agent_id

        # 1. Build envelope
        envelope = self._built_envelope(
            action=action,
            operation=operation,
            target=target,
            parameters=parameters,
            agent_id=effective_agent_id,
            user_id=user_id,
            session_id=session_id,
            confidence=confidence,
            reason=reason,
            sensitivity=sensitivity,
            cost_estimate=cost_estimate,
            requested_scopes=requested_scopes,
            idempotency_key=idempotency_key,
            principal=principal,
            correlation_id=correlation_id,
        )

        # Once the envelope exists, a failure no step below answers is BLOCK, fail-closed, recorded (row 193:
        # "Never return generic 500 errors without a decision response body"; Principle 7). Every step after a record
        # is written answers its own failure, so no envelope is recorded twice.
        record = _admitted_envelope_record(envelope)
        try:
            if idempotency_key is None:
                return self._decided(envelope, record, idempotency_key, started)
            # A caller's key is held in the audit store from the dedup read to the record's write (HTL-29 row 160)
            with self._audit_logger.key_held(record["org_id"], record["environment"], idempotency_key):
                return self._decided(envelope, record, idempotency_key, started)
        except Exception as e:
            logger.exception("Evaluation failed unexpectedly (fail-closed): %s", e)
            return self._refused(envelope, record, "BLOCK", "EVALUATION_FAILED")

    def _decided(self, envelope: Envelope, record: Dict[str, Any], idempotency_key: Optional[str],
                 started: Optional[float] = None) -> Decision:
        """Steps 1b to 8 of the local evaluation, for the envelope built: the decision, recorded. `started` is where the
        call's clock started; a caller that enters here starts it here."""
        from hiitl.core.route_types import resolve_escalation_context
        if started is None:
            started = time.perf_counter()

        # 1b. Verify before evaluating, with the same key (the security architecture §1.3: "The evaluator verifies
        # before processing"; row 134). Without a key there is nothing to verify against: the envelope carries zeros.
        # An envelope that does not verify is refused and recorded (§1.3: "action rejected with `SIGNATURE_INVALID`,
        # audit record written"; HTL-22 row 159).
        if self.config.signature_key and not envelope_verifies(self.config.signature_key, record):
            logger.warning("Envelope %s does not verify under signature_key: refused (SIGNATURE_INVALID).",
                           record["action_id"])
            return self._refused(envelope, record, "SIGNATURE_INVALID", "ENVELOPE_SIGNATURE_VERIFICATION_FAILED")
        # The call's ingest, from its evaluate() through the signature check (decision_response.md Timing Metadata:
        # "validate envelope, check signature"). Each evaluation below counts from there (HTL-43 gap 303).
        ingested_ms = (time.perf_counter() - started) * 1000

        # 1c. A repeated key. The caller's idempotency_key that this store already recorded, for an envelope within the
        # dedup window of this one's timestamp, returns that record's decision and writes no record (the security
        # architecture §1.3: "A replayed envelope produces a dedup hit, not a re-evaluation"; row 143). A key the SDK
        # generated is new by construction. A store that cannot be read for it is BLOCK, never a fresh evaluation
        # (row 193: "the same for a failed dedup read").
        if idempotency_key is not None:
            try:
                first = self._audit_logger.first_decision_under_key(
                    record["org_id"], record["environment"], idempotency_key, record["timestamp"],
                    self.config.dedup_window_seconds)
            except Exception as e:
                logger.exception("The first decision under the idempotency_key could not be read (fail-closed): %s", e)
                return self._refused(envelope, record, "BLOCK", "AUDIT_READ_FAILED")
            if first is not None:
                return Decision.model_validate(first)

        # 2. A kill-switch tick no pull has followed: the set it names decides first, and a switch that binds there
        # stands under the tick's version (sync_engine.md 2.4; HTL-29 row 240, ruled 2026-11-09). Elsewhere the
        # version below decides, as before.
        part = self._sync_cache.tick_part() if self._mode == "hybrid" and self._sync_cache else None
        try:
            decision = self._switched(envelope, part, ingested_ms) if part is not None else None
        except Exception as e:
            logger.exception("Policy evaluation failed (fail-closed): %s", e)
            return self._refused(envelope, record, "POLICY_ERROR", "POLICY_EVALUATION_FAILED",
                                     str(e) if isinstance(e, OperatorKindError) else None)

        if decision is None:
            # 2b. Load policy
            # Priority: sync cache > policy loader > empty policy (OBSERVE_ALL). A policy that cannot be had is
            # POLICY_ERROR, its cause the loader's reason (Error Handling: "Policy file not found, invalid policy
            # syntax").
            try:
                policy = self._resolve_policy()
            except PolicyLoadError as e:
                logger.error("Policy could not be loaded (fail-closed): %s", e)
                return self._refused(envelope, record, "POLICY_ERROR", e.reason)

            # 3. Evaluate policy with mode; 3b. a ROUTE asking a sync route: ask it, and evaluate again with its
            # answer (policy_format.md 2.7; TICKET-046). An evaluator that raises is POLICY_ERROR, never an exception
            # past here.
            try:
                decision = self._evaluator._evaluate_admitted_envelope(
                    envelope, policy, mode=self._eval_mode, ingested_ms=ingested_ms
                )
                if self._route_loader is not None and routing.to_ask(decision, self._route_loader.get, set()):
                    decision = routing.evaluate_with_routes(
                        lambda enrichment: self._evaluator._evaluate_admitted_envelope(envelope, policy, mode=self._eval_mode,
                                                                    enrichment=enrichment, ingested_ms=ingested_ms),
                        self._route_loader.get, self._ask_route, _admitted_envelope_record(envelope), first=decision)
            except Exception as e:
                logger.exception("Policy evaluation failed (fail-closed): %s", e)
                return self._refused(envelope, record, "POLICY_ERROR", "POLICY_EVALUATION_FAILED",
                                     str(e) if isinstance(e, OperatorKindError) else None)

        # 4. Resolve route config for escalation decisions
        if (
            decision.decision in self.ESCALATION_TYPES
            and decision.route_ref
            and self._route_loader
        ):
            try:
                route_config = self._route_loader.get(decision.route_ref)
                if route_config:
                    decision.escalation_context = resolve_escalation_context(route_config)
            except Exception as e:
                logger.warning(
                    "Failed to resolve route config '%s': %s. "
                    "Decision will be returned without escalation_context.",
                    decision.route_ref,
                    e,
                )

        # 5. Apply rate limiting (if enabled): the windowed RATE_LIMIT rules the evaluator listed (T47: one
        # representation, the rule's). A limiter that fails never lets the call through (safe by default), and under
        # OBSERVE_ALL a refusal is observed — observe never blocks (policy_format.md "Rate-limit rules").
        if self._rate_limiter:
            try:
                limited = self._rate_limiter.check_and_increment(envelope, decision)
            except Exception as e:
                logger.error("Rate limiting unavailable: %s. Action blocked (fail-closed).", e)
                limited = limiter_failed(decision)
            if limited:
                decision = observe(limited) if self._eval_mode == "OBSERVE_ALL" else limited

        # 6. Write to audit log. The decision carries the SHA-256 of the evaluated envelope's signed form, in every
        # mode (Security Tier 1; decision_response.md envelope_hash). A record that cannot be written blocks the action
        # ("Audit write failures in fail-closed mode must block the action", Infrastructure spec 3; HTL-22 row 159).
        decision.envelope_hash = envelope_hash(record)
        try:
            self._audit_logger._write_admitted(envelope, decision)
        except Exception as e:
            logger.exception("Audit write failed (fail-closed): %s", e)
            return audit_write_failed(decision)

        # 7. Record telemetry (fire-and-forget, never blocks)
        if self._telemetry_collector is not None:
            try:
                self._telemetry_collector._record_admitted(envelope, decision)
            except Exception:
                pass  # Telemetry errors are non-critical

        # 8. Stamp cache_status (TICKET-116). Hybrid mode reads from the
        # sync cache; pure local mode leaves this None (file-loaded
        # policies are static, not sync-cache state). Hosted mode also
        # leaves it None — the server is authoritative, the SDK doesn't
        # have a cache to describe.
        return self._stamped(decision)

    def _stamped(self, decision: Decision) -> Decision:
        """The decision with the sync cache's status, read after its record is written: a status that cannot be read is
        logged and left unset, so the decision stands as recorded (row 193)."""
        if self._sync_cache is not None:
            try:
                decision.cache_status = self._sync_cache.cache_status()
            except Exception as e:
                logger.warning("The sync cache's status could not be read: %s", e)
        return decision

    def _refused(self, envelope: Envelope, record: Dict[str, Any], decision: str, reason: str,
                 authored_message: Optional[str] = None) -> Decision:
        """The error decision for an envelope that could not be evaluated, recorded like any other (decision_response.md
        "Error Handling": "Even error decisions produce audit records"). Its message is the authored one for its cause;
        the cause itself was logged where it was caught. A record that cannot be written is logged too: the refusal
        stands, and it allows nothing. ``BLOCK`` is a failure no error decision names (row 193)."""
        refused = (error_block(record["action_id"], reason, envelope_hash=envelope_hash(record)) if decision == "BLOCK"
                   else error_decision(record["action_id"], decision, reason, authored_message if authored_message is not None else MESSAGES[reason],
                                       envelope_hash=envelope_hash(record)))
        try:
            self._audit_logger._write_admitted(envelope, refused)
        except Exception as e:
            logger.exception("The refusal's audit record could not be written: %s", e)
        return self._stamped(refused)

    def _ask_route(self, route: Any, payload: Dict[str, Any]) -> Any:
        """POST the route's context to its endpoint and return the JSON answer (routes.md "A sync route's answer
        re-enters evaluation"). No answer — a transport error, a timeout, a non-2xx status, a body that is not JSON —
        raises RouteUnanswered, and the route's SLA decides (fail closed unless fail_open)."""
        import httpx
        client = getattr(self, "_route_client", None)
        if client is None:
            client = self._route_client = httpx.Client()
        try:
            # A client the caller hands the SDK may follow redirects, so the request says it follows none: a redirect is
            # the route's answer, not a hop (sync_engine.md section 8)
            r = client.post(routing.endpoint(route), json=payload, headers=routing.auth_headers(route),
                            timeout=routing.timeout_seconds(route), follow_redirects=False)
        except httpx.HTTPError as e:
            raise routing.RouteUnanswered(f"{type(e).__name__}: {e}") from e
        if not r.is_success:
            raise routing.RouteUnanswered(f"the route answered {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise routing.RouteUnanswered("the answer is not JSON") from e

    def _switched(self, envelope: Envelope, part: PolicySet, ingested_ms: float) -> Optional[Decision]:
        """The decision of a kill switch the tick's part binds, or None (sync_engine.md 2.4; HTL-29 row 240). The part
        is read in the client's mode, and its decision stands where the evaluator names one of its switches as the
        binding rule: KILL_SWITCH (observed: OBSERVE with would_be KILL_SWITCH), or under `fail_closed` the BLOCK of a
        switch the call cannot read (condition 2, ruled 2026-11-10). What a switch stops is its rule, in the version
        the tick names."""
        decision = self._evaluator._evaluate_admitted_envelope(envelope, part, mode=self._eval_mode, ingested_ms=ingested_ms)
        return decision if decision.matched_rules else None

    def _resolve_policy(self) -> PolicySet:
        """Resolve policy from the appropriate source.

        Priority order (hybrid mode):
            1. Sync cache (server-managed policies)
            2. Local policy loader (file-based fallback)
            3. Empty policy set (OBSERVE_ALL)
        """
        # In hybrid mode, check sync cache first
        if self._mode == "hybrid" and self._sync_cache:
            cached = self._sync_cache.get_policy_set()
            if cached is not None:
                return cached

        # Fall back to policy loader (file-based)
        if hasattr(self, '_policy_loader') and self._policy_loader is not None:
            try:
                return self._policy_loader.load()
            except PolicyLoadError:
                raise
            except Exception as e:
                raise PolicyLoadError(f"Failed to load policy: {e}", reason="POLICY_LOAD_FAILED") from e

        # Final fallback: empty policy (OBSERVE_ALL)
        return self._empty_policy

    def _built_envelope(self, **fields: Any) -> Envelope:
        """_build_envelope, its validation failure raised as the SDK's EnvelopeValidationError."""
        try:
            with admitted_numbers():
                return self._build_envelope(**fields)
        except EnvelopeValidationError:
            raise
        except Exception as e:
            if "ValidationError" in type(e).__name__:
                errors = []
                if hasattr(e, 'errors'):
                    errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
                raise EnvelopeValidationError(
                    f"Envelope validation failed: {e}\n\n"
                    "Check that all provided fields are valid.\n"
                    "See docs/specs/envelope_schema.json for the full schema.",
                    validation_errors=errors
                ) from e
            raise

    def _build_envelope(
        self,
        action: str,
        operation: str,
        target: dict,
        parameters: dict,
        agent_id: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        sensitivity: Optional[List[Sensitivity]] = None,
        cost_estimate: Optional[CostEstimate] = None,
        requested_scopes: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        principal: Optional[Principal] = None,
        correlation_id: Optional[str] = None,
    ) -> Envelope:
        """Build envelope from provided fields and auto-generated values, signed with signature_key over the one
        signed form (hiitl.core.canonical.envelope_signed_form) of the envelope as recorded (row 127). With no key
        the signature is zeros. `trace_id` is the active OpenTelemetry span's ("Auto-propagated from execution
        context"; row 175); `correlation_id` is the caller's."""
        action_id = f"act_{uuid4().hex[:20]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        if idempotency_key is None:
            idempotency_key = f"idem_{uuid4().hex}"

        operation_enum = _operation(operation)

        # These are the SDK's own optional arguments, whose declared None means not given.
        # A nested caller value (including null) is data and is never scrubbed here.
        optional = {
            "user_id": user_id, "session_id": session_id, "confidence": confidence,
            "reason": reason, "sensitivity": sensitivity, "cost_estimate": cost_estimate,
            "requested_scopes": requested_scopes, "principal": principal,
            "correlation_id": correlation_id, "trace_id": active_trace_id(),
        }

        envelope = Envelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            org_id=self.config.org_id,
            environment=self.config.environment,
            agent_id=agent_id,
            action_id=action_id,
            timestamp=timestamp,
            action=action,
            operation=operation_enum,
            parameters=parameters,
            target=target,
            idempotency_key=idempotency_key,
            signature="0" * 64,
            **{key: value for key, value in optional.items() if value is not None},
        )
        if self.config.signature_key:
            envelope.signature = envelope_signature(self.config.signature_key, _admitted_envelope_record(envelope))
        return envelope

    def record_result(
        self,
        action_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> dict:
        """Record what happened when the caller executed an action evaluate() allowed: the lifecycle's result
        (Principle 4, Intent → Attempt → Result; event_format.md "The lifecycle").

        Args:
            action_id: The action_id of the decision evaluate() returned
            status: succeeded, failed or canceled
            error: What failed, when status is failed
            duration_ms: How long the execution took

        Returns:
            The record carrying the result. The same result again returns the record that already holds it. In hosted
            mode during an outage, `{action_id, execution_result, held: True}`: the result is held in the local store
            and pushed before the next call (event_format.md "The lifecycle").

        Raises:
            LifecycleError: the result is not recorded, with its reason — RESULT_INVALID, ACTION_NOT_FOUND,
                RESULT_ON_UNALLOWED_DECISION (an action that was not allowed never executed; a held action's result
                is recorded, naming the review the store cannot read) or
                RESULT_ALREADY_RECORDED (a different result is recorded)
            AuditLogError: the store could not write the result record, or hold it during a hosted outage
        """
        try:
            validate_numeric_domain({key: value for key, value in locals().items() if key != 'self'}, shape={**RESULT_NUMBER_SHAPE, 'properties': {**RESULT_NUMBER_SHAPE['properties'], 'action_id': {'type': 'string'}}})
        except NumericDomainError as error:
            raise LifecycleError("RESULT_INVALID", str(error)) from error
        try:
            result = execution_result(status, error, duration_ms)
        except ValueError:
            raise LifecycleError("RESULT_INVALID", LIFECYCLE_MESSAGES["RESULT_INVALID"]) from None
        if self._mode == "hosted":
            return self._hosted_client.record_result(action_id, result)
        environment = getattr(self.config.environment, "value", self.config.environment)
        # The read of the action's records and its result's write are one step in this store (event_format.md "The
        # Lifecycle", "One step")
        with self._audit_logger.action_held(self.config.org_id, environment, action_id):
            lifecycle = self._audit_logger.lifecycle(self.config.org_id, environment, action_id)
            # The action's decision: its latest record that carries no result (event_format.md "The lifecycle"). The
            # store holds no review case, so it passes the decision's review as unread, and the service, which holds
            # the case, reads it at sync ingest (row 217, event_format.md "A result whose writer holds no case")
            decided = next((r for r in reversed(lifecycle) if not r.get("execution_result")), None)
            review = unread_review(decided["decision"]) if decided else None
            refusal = result_refusal(lifecycle, result, review=review)
            if refusal:
                raise LifecycleError(refusal, LIFECYCLE_MESSAGES[refusal])
            first = recorded_result(lifecycle, result)
            if first is not None:
                return first
            # The result record, its hash over the decision record's terms, the result and the review it was read
            # under (Stop A, ruled 2026-11-06; row 217)
            return self._audit_logger.write_result(decided, result, review)

    def close(self):
        """Release resources.

        In hybrid mode: stops sync engine, flushes pending audit records,
        closes HTTP connections.

        Call this when you're done using the client, or use as context manager:

            with HIITL(...) as hiitl:
                decision = hiitl.evaluate(...)
        """
        if self._sync_engine:
            self._sync_engine.stop()
            self._sync_engine = None

        if self._hosted_client:
            self._hosted_client.close()
            self._hosted_client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
