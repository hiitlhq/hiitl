"""HIITL SDK Client - Main developer-facing API.

Single entry point: evaluate(). Deployment mode auto-detected from
constructor arguments:

- **api_key present**: Hybrid mode (default) — local evaluation with
  background sync to hosted service. Microsecond latency, server-managed
  policies synced in background.
- **No api_key**: Pure local mode — file-based policies, SQLite audit,
  no network. For development, CI/CD, air-gapped environments.
- **api_key + evaluation="remote"**: Pure hosted mode (opt-in) — HTTP
  call to server for every evaluation. Higher latency but zero local state.

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
    ...     server_url="https://ecp.hiitl.com",
    ...     evaluation="remote",
    ... )
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from hiitl.core.types import (
    CostEstimate,
    Decision,
    DecisionType,
    Envelope,
    Operation,
    PolicySet,
    Sensitivity,
)
from hiitl.sdk.config import HostedModeConfig, LocalModeConfig, SyncConfig
from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    PolicyLoadError,
)

logger = logging.getLogger(__name__)


class HIITL:
    """HIITL client for policy evaluation.

    Deployment mode is auto-detected from constructor arguments:

    - **api_key present**: Hybrid (default) — local eval + background sync
    - **No api_key**: Pure local — file-based policies, no network
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
        agent_id: str = "default",
        environment: str = "dev",
        org_id: str = "org_devlocal0000000000",
        # Policy mode
        mode: str = "OBSERVE_ALL",
        # Local/hybrid parameters
        policy_path: Optional[str] = None,
        audit_db_path: str = "./hiitl_audit.db",
        enable_rate_limiting: bool = True,
        routes_path: Optional[str] = None,
        signature_key: Optional[str] = None,
        # Hosted/hybrid parameters
        api_key: Optional[str] = None,
        server_url: Optional[str] = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        # Evaluation mode control
        evaluation: str = "local",
        # Sync configuration overrides
        cache_dir: Optional[str] = None,
        sync_config: Optional[SyncConfig] = None,
    ):
        """Initialize HIITL client.

        All parameters are keyword-only with sensible defaults.
        ``HIITL()`` with no arguments works in local OBSERVE mode.

        Args:
            agent_id: Agent identifier (default: "default")
            environment: Execution environment — dev, stage, or prod (default: "dev")
            org_id: Organization ID (default: dev-local placeholder)
            mode: Policy mode — "OBSERVE_ALL" or "RESPECT_POLICY" (default: "OBSERVE_ALL")

            Local evaluation:
                policy_path: Path to policy file (JSON or YAML). Optional in
                    OBSERVE_ALL mode (uses empty policy set). In hybrid mode,
                    used as fallback when server cache is unavailable.
                audit_db_path: Path to SQLite audit database (default: ./hiitl_audit.db)
                enable_rate_limiting: Whether to enforce rate limits (default: True)
                routes_path: Path to route config files directory (optional)
                signature_key: HMAC-SHA256 key for envelope signing (optional)

            Server connection:
                api_key: API key for server auth (Bearer token). When present,
                    enables hybrid mode (local eval + background sync).
                server_url: ECP server URL. In hybrid mode, defaults to
                    https://api.hiitl.com. Required for hosted mode.
                timeout: HTTP timeout in seconds (default: 5.0)
                max_retries: Max retry attempts on transient failures (default: 3)

            Evaluation mode:
                evaluation: Where evaluation happens — "local" (default) or
                    "remote" (opt-in hosted mode, requires api_key + server_url).

            Sync:
                cache_dir: Override disk cache directory (default: ~/.hiitl/cache/)
                sync_config: Full SyncConfig override (advanced)

        Raises:
            ConfigurationError: If configuration is invalid
            PolicyLoadError: If policy file cannot be loaded (local/hybrid)
            AuditLogError: If audit database cannot be initialized (local/hybrid)
        """
        self._hosted_client = None
        self._sync_engine = None
        self._sync_cache = None
        self._telemetry_collector = None
        self._api_key = api_key
        self._eval_mode = mode

        # Mode detection per hybrid architecture:
        # api_key + evaluation="remote" → hosted (explicit opt-in)
        # api_key present → hybrid (default architecture)
        # no api_key → local
        if api_key and evaluation == "remote":
            self._mode = "hosted"
        elif api_key:
            self._mode = "hybrid"
        else:
            self._mode = "local"

        if self._mode == "hosted":
            if not server_url:
                raise ConfigurationError(
                    "server_url is required for hosted evaluation (evaluation='remote').\n\n"
                    "Provide your ECP server URL:\n"
                    "  HIITL(api_key='...', server_url='https://ecp.hiitl.com', evaluation='remote')\n\n"
                    "Or use the default hybrid mode (recommended) — local eval + sync:\n"
                    "  HIITL(api_key='...')"
                )
            self._init_hosted(
                environment=environment,
                agent_id=agent_id,
                org_id=org_id,
                api_key=api_key,
                server_url=server_url,
                timeout=timeout,
                max_retries=max_retries,
                signature_key=signature_key,
            )
        elif self._mode == "hybrid":
            self._init_hybrid(
                environment=environment,
                agent_id=agent_id,
                org_id=org_id,
                mode=mode,
                policy_path=policy_path,
                audit_db_path=audit_db_path,
                enable_rate_limiting=enable_rate_limiting,
                routes_path=routes_path,
                signature_key=signature_key,
                api_key=api_key,
                server_url=server_url,
                cache_dir=cache_dir,
                sync_config=sync_config,
            )
        else:
            # Pure local mode
            if policy_path is None and mode != "OBSERVE_ALL":
                raise ConfigurationError(
                    "policy_path is required for RESPECT_POLICY mode.\n\n"
                    "Provide a policy file:\n"
                    "  HIITL(policy_path='./policy.yaml', mode='RESPECT_POLICY')\n\n"
                    "Or use OBSERVE_ALL mode (default) which works without a policy file:\n"
                    "  HIITL()\n\n"
                    "Or use hybrid mode with an API key (policies sync from server):\n"
                    "  HIITL(api_key='sk_live_...')"
                )
            self._init_local(
                environment=environment,
                agent_id=agent_id,
                org_id=org_id,
                mode=mode,
                policy_path=policy_path,
                audit_db_path=audit_db_path,
                enable_rate_limiting=enable_rate_limiting,
                routes_path=routes_path,
                signature_key=signature_key,
            )

    def _init_local(
        self,
        environment: str,
        agent_id: str,
        org_id: str,
        mode: str,
        policy_path: Optional[str],
        audit_db_path: str,
        enable_rate_limiting: bool,
        routes_path: Optional[str],
        signature_key: Optional[str],
    ):
        """Initialize pure local mode components."""
        from hiitl.core import PolicyEvaluator
        from hiitl.sdk.audit import AuditLogger
        from hiitl.sdk.route_loader import RouteLoader
        from hiitl.sdk.policy_loader import PolicyLoader
        from hiitl.sdk.rate_limiter import RateLimiter

        try:
            self.config = LocalModeConfig(
                environment=environment,
                agent_id=agent_id,
                policy_path=policy_path,
                org_id=org_id,
                mode=mode,
                audit_db_path=audit_db_path,
                enable_rate_limiting=enable_rate_limiting,
                routes_path=routes_path,
                signature_key=signature_key,
            )
        except Exception as e:
            raise ConfigurationError(
                f"Invalid HIITL configuration: {e}\n\n"
                "Check that all required parameters are provided and valid."
            ) from e

        try:
            if policy_path is not None:
                self._policy_loader = PolicyLoader(self.config.policy_path)
            else:
                self._policy_loader = None
                self._empty_policy = PolicySet(
                    version="0.0.0",
                    name="__zero_config__",
                    rules=[],
                )

            self._evaluator = PolicyEvaluator()
            self._audit_logger = AuditLogger(self.config.audit_db_path)
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
        environment: str,
        agent_id: str,
        org_id: str,
        mode: str,
        policy_path: Optional[str],
        audit_db_path: str,
        enable_rate_limiting: bool,
        routes_path: Optional[str],
        signature_key: Optional[str],
        api_key: str,
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

        # Build sync config
        if sync_config is None:
            sync_kwargs = {}
            if server_url:
                sync_kwargs["server_url"] = server_url
            if cache_dir:
                sync_kwargs["cache_dir"] = cache_dir
            sync_config = SyncConfig(**sync_kwargs)

        # Build local config (api_key stored for sync engine)
        try:
            self.config = LocalModeConfig(
                environment=environment,
                agent_id=agent_id,
                policy_path=policy_path,
                org_id=org_id,
                mode=mode,
                audit_db_path=audit_db_path,
                enable_rate_limiting=enable_rate_limiting,
                routes_path=routes_path,
                signature_key=signature_key,
                api_key=api_key,
            )
        except Exception as e:
            raise ConfigurationError(
                f"Invalid HIITL configuration: {e}\n\n"
                "Check that all required parameters are provided and valid."
            ) from e

        try:
            # Initialize local evaluator components
            self._evaluator = PolicyEvaluator()
            self._audit_logger = AuditLogger(self.config.audit_db_path)
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
            if sync_config.telemetry_level != "off":
                from hiitl.sdk.telemetry import TelemetryCollector
                self._telemetry_collector = TelemetryCollector(
                    org_id=org_id,
                    environment=environment,
                    level=sync_config.telemetry_level,
                    buffer_size=sync_config.telemetry_buffer_size,
                    sample_rate=sync_config.telemetry_sample_rate,
                )

            # Warm start: load cached data from disk
            has_cache = self._sync_cache.load_from_disk()

            # Policy source resolution:
            # Server cache > disk cache > local policy file > empty (OBSERVE_ALL)
            self._policy_loader = None
            self._empty_policy = PolicySet(
                version="0.0.0",
                name="__zero_config__",
                rules=[],
            )

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
                        "Using local policy file as fallback: %s", policy_path
                    )
                    self._policy_loader = PolicyLoader(policy_path)
                elif not initial_ok:
                    logger.info(
                        "No cached policies and sync unavailable. "
                        "Running in OBSERVE_ALL mode until first sync."
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
            raise ConfigurationError(
                f"Failed to initialize hybrid mode: {e}"
            ) from e

    def _init_hosted(
        self,
        environment: str,
        agent_id: str,
        org_id: str,
        api_key: str,
        server_url: str,
        timeout: float,
        max_retries: int,
        signature_key: Optional[str],
    ):
        """Initialize hosted mode components."""
        from hiitl.sdk.http_client import HostedClient

        try:
            self.config = HostedModeConfig(
                environment=environment,
                agent_id=agent_id,
                org_id=org_id,
                api_key=api_key,
                server_url=server_url,
                timeout=timeout,
                max_retries=max_retries,
                signature_key=signature_key,
            )
        except Exception as e:
            raise ConfigurationError(
                f"Invalid HIITL configuration: {e}\n\n"
                "Check that all required parameters are provided and valid.\n"
                "Required for hosted evaluation: environment, agent_id, org_id, api_key, server_url"
            ) from e

        self._hosted_client = HostedClient(self.config)

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
        idempotency_key: Optional[str] = None,
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
            idempotency_key: Idempotency key (optional, auto-generated)

        Returns:
            Decision with .allowed, .ok, .blocked, .needs_approval, .observed properties.

        Raises:
            EnvelopeValidationError: If envelope validation fails
            PolicyLoadError: If policy cannot be loaded (local mode)
            AuditLogError: If audit log write fails (local/hybrid mode)
            ServerError: If server returns an error (hosted mode)
            NetworkError: If server is unreachable (hosted mode)
        """
        if self._mode == "hosted":
            return self._evaluate_hosted(
                action=action,
                operation=operation,
                target=target if target is not None else {},
                parameters=parameters if parameters is not None else {},
                user_id=user_id,
                session_id=session_id,
                reason=reason,
                sensitivity=sensitivity,
                cost_estimate=cost_estimate,
            )
        else:
            # Both local and hybrid use _evaluate_local
            return self._evaluate_local(
                action=action,
                operation=operation,
                target=target if target is not None else {},
                parameters=parameters if parameters is not None else {},
                user_id=user_id,
                session_id=session_id,
                agent_id=agent_id,
                confidence=confidence,
                reason=reason,
                sensitivity=sensitivity,
                cost_estimate=cost_estimate,
                idempotency_key=idempotency_key,
            )

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
    ) -> Decision:
        """Evaluate via hosted ECP server."""
        return self._hosted_client.evaluate(
            action=action,
            operation=operation,
            target=target,
            parameters=parameters,
            user_id=user_id,
            session_id=session_id,
            reason=reason,
            sensitivity=sensitivity,
            cost_estimate=cost_estimate,
        )

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
        idempotency_key: Optional[str] = None,
    ) -> Decision:
        """Evaluate via local embedded evaluator.

        Used by both local and hybrid modes. In hybrid mode, policies
        come from SyncCache first, then PolicyLoader fallback.
        """
        from hiitl.sdk.route_loader import resolve_escalation_context

        effective_agent_id = agent_id if agent_id is not None else self.config.agent_id

        # 1. Build envelope
        try:
            envelope = self._build_envelope(
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
                idempotency_key=idempotency_key,
            )
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

        # 2. Load policy
        # Priority: sync cache > policy loader > empty policy (OBSERVE_ALL)
        policy = self._resolve_policy()

        # 3. Evaluate policy with mode
        try:
            decision = self._evaluator.evaluate(
                envelope, policy, mode=self._eval_mode
            )
        except Exception as e:
            raise RuntimeError(
                f"Policy evaluation failed: {e}\n\n"
                "This is an unexpected error. Please report this issue."
            ) from e

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

        # 5. Apply rate limiting (if enabled)
        if self._rate_limiter:
            try:
                rate_config = policy.metadata if hasattr(policy, 'metadata') else None
                rate_limited = self._rate_limiter.check_and_increment(
                    envelope, decision, rate_config
                )
                if rate_limited:
                    decision = rate_limited
            except Exception as e:
                logger.warning(
                    "Rate limit check failed: %s. "
                    "Action will proceed without rate limiting.",
                    e,
                )

        # 6. Write to audit log
        try:
            self._audit_logger.write(envelope, decision)
        except AuditLogError:
            raise
        except Exception as e:
            raise AuditLogError(f"Failed to write audit record: {e}") from e

        # 7. Record telemetry (fire-and-forget, never blocks)
        if self._telemetry_collector is not None:
            try:
                self._telemetry_collector.record(envelope, decision)
            except Exception:
                pass  # Telemetry errors are non-critical

        return decision

    def _resolve_policy(self) -> PolicySet:
        """Resolve policy from the appropriate source.

        Priority order (hybrid mode):
            1. Sync cache (server-managed policies)
            2. Local policy loader (file-based fallback)
            3. Empty policy set (OBSERVE_ALL)
        """
        # In hybrid mode, check sync cache first
        if self._mode == "hybrid" and self._sync_cache:
            cached = self._sync_cache.get_policies()
            if cached and isinstance(cached, dict):
                policies = cached.get("policies", [])
                if policies:
                    # Use the first active policy from cache
                    for p in policies:
                        if p.get("active", True):
                            content = p.get("content", {})
                            try:
                                return PolicySet(**content)
                            except Exception as e:
                                logger.warning(
                                    "Failed to parse cached policy '%s': %s. "
                                    "Trying next source.",
                                    p.get("name", "?"),
                                    e,
                                )

        # Fall back to policy loader (file-based)
        if hasattr(self, '_policy_loader') and self._policy_loader is not None:
            try:
                return self._policy_loader.load()
            except PolicyLoadError:
                raise
            except Exception as e:
                raise PolicyLoadError(f"Failed to load policy: {e}") from e

        # Final fallback: empty policy (OBSERVE_ALL)
        return self._empty_policy

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
        idempotency_key: Optional[str] = None,
    ) -> Envelope:
        """Build envelope from provided fields and auto-generated values."""
        action_id = f"act_{uuid4().hex[:20]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        if idempotency_key is None:
            idempotency_key = f"idem_{uuid4().hex}"

        if isinstance(operation, str):
            operation_enum = Operation(operation)
        else:
            operation_enum = operation

        if self.config.signature_key:
            content = f"{action_id}:{timestamp}:{self.config.org_id}:{action}:{operation_enum.value}"
            signature = hmac.new(
                self.config.signature_key.encode(),
                content.encode(),
                hashlib.sha256
            ).hexdigest()
        else:
            signature = "0" * 64

        envelope = Envelope(
            schema_version="v1.0",
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
            signature=signature,
            user_id=user_id,
            session_id=session_id,
            confidence=confidence,
            reason=reason,
            sensitivity=sensitivity,
            cost_estimate=cost_estimate,
        )

        return envelope

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
