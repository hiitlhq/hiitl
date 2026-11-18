"""The active OpenTelemetry trace, read for the envelope's `trace_id`.

envelope_schema.json: `trace_id` is "Auto-propagated from execution context". The SDK reads the active span's trace id
through the OpenTelemetry API when the application has installed it (`opentelemetry-api`); the API is never a
dependency of this package. It is resolved once, at import. Without it, or outside a span, there is no trace id.
"""

from __future__ import annotations

from typing import Optional

try:
    from opentelemetry import trace as _trace
except ImportError:  # the API is not installed: there is no span to read
    _trace = None


def active_trace_id() -> Optional[str]:
    """The active span's trace id as W3C Trace Context writes it (32 lowercase hex), or None.

    Only a valid span context counts: outside a span, or in a span from the API's no-op tracer (the API installed with
    no SDK), the context carries the all-zero id, which names no trace.
    """
    if _trace is None:
        return None
    context = _trace.get_current_span().get_span_context()
    return _trace.format_trace_id(context.trace_id) if context.is_valid else None
