"""HIITL SDK - Python implementation.

This module provides the Python SDK for HIITL (Human-In-The-Loop) policy
evaluation. Mode is auto-detected from constructor arguments:

- **api_key present**: Hybrid (default) — local eval + background sync
- **No api_key**: Pure local — file-based policies, no network
- **api_key + evaluation="remote"**: Hosted — server-side eval (opt-in)

Main components:
- HIITL: Main client class for policy evaluation
- PolicyLoader: Loads and caches policy files (JSON/YAML)
- AuditLogger: SQLite-based audit logging
- RateLimiter: In-memory rate limiting
- SyncConfig: Configuration for background sync engine

Zero-config (observe everything):
    >>> from hiitl import HIITL
    >>> hiitl = HIITL()
    >>> decision = hiitl.evaluate("send_email")
    >>> if decision.allowed:
    ...     send_email()

Hybrid mode (recommended for production):
    >>> hiitl = HIITL(
    ...     agent_id="payment-agent",
    ...     org_id="org_mycompany123456789",
    ...     api_key="sk_live_abc123...",
    ... )
    >>> decision = hiitl.evaluate(
    ...     "process_payment",
    ...     parameters={"amount": 500, "currency": "USD"},
    ... )
    >>> if decision.allowed:
    ...     process_payment()
"""

from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL
from hiitl.sdk.config import LocalModeConfig, SyncConfig
from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    HIITLError,
    PolicyLoadError,
    RouteLoadError,
    SyncError,
)
from hiitl.sdk.route_loader import RouteLoader
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.sdk.rate_limiter import RateLimiter

__all__ = [
    "HIITL",
    "PolicyLoader",
    "RouteLoader",
    "AuditLogger",
    "RateLimiter",
    "LocalModeConfig",
    "SyncConfig",
    "HIITLError",
    "PolicyLoadError",
    "RouteLoadError",
    "AuditLogError",
    "ConfigurationError",
    "EnvelopeValidationError",
    "SyncError",
]
