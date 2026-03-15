"""HIITL - Human Intelligence in the Loop.

Deterministic control point for software that can act.

This package provides policy-based access control for AI agents and
autonomous systems. It enables developers to define and enforce policies
that govern what actions agents can take.

Zero-config (observe everything):
    >>> from hiitl import HIITL
    >>> hiitl = HIITL()
    >>> decision = hiitl.evaluate("send_email")
    >>> if decision.allowed:
    ...     send_email()

With policy enforcement:
    >>> hiitl = HIITL(
    ...     agent_id="payment-agent",
    ...     policy_path="./policy.yaml",
    ...     mode="RESPECT_POLICY",
    ... )
    >>> decision = hiitl.evaluate(
    ...     "process_payment",
    ...     parameters={"amount": 500, "currency": "USD"},
    ... )
    >>> if decision.allowed:
    ...     process_payment()
"""

__version__ = "0.1.0"

# Import main SDK class
from hiitl.sdk.client import HIITL

# Import common exceptions
from hiitl.sdk.exceptions import (
    AuditLogError,
    ConfigurationError,
    EnvelopeValidationError,
    HIITLError,
    NetworkError,
    PolicyLoadError,
    ServerError,
)

# Export public API
__all__ = [
    "HIITL",
    "HIITLError",
    "PolicyLoadError",
    "AuditLogError",
    "ConfigurationError",
    "EnvelopeValidationError",
    "ServerError",
    "NetworkError",
    "__version__",
]
