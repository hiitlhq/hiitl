"""Row 175 (HTL-22): `trace_id` from the active OpenTelemetry span; `correlation_id` an `evaluate()` option.

Trevor's ruling on HTL-20: "`trace_id` from the active OpenTelemetry span when its API can be imported (never a
dependency); `correlation_id` an `evaluate()` option. By 'OpenTelemetry compatibility'", event_format.md's "designed
with **OpenTelemetry compatibility** in mind"; envelope_schema.json names both "Auto-propagated from execution context".
Design: the HTL-22 test design, row 175, behaviors 1-3. The TypeScript side is
typescript/packages/sdk/tests/unit/row175.test.ts, with the same ids.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import sys

import pytest

from hiitl import HIITL
from hiitl.sdk import trace_context

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"  # W3C Trace Context's example trace id
SPAN_ID = "b7ad6b7169203331"
CORRELATION_ID = "req_row175_checkout_42"
SERVER_URL = "https://ecp.example.com"
ALLOW = {"decision": "ALLOW", "allowed": True, "reason_codes": ["DEFAULT_ALLOW"], "policy_version": "v1.0.0",
         "timing": {"total_ms": 1.0}, "envelope_hash": "a" * 64}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """Each cell sets the variables it reads; none comes from the shell that runs the suite."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _span():
    """The W3C example span made active, through the API's own use_span."""
    from opentelemetry import trace

    return trace.use_span(trace.NonRecordingSpan(trace.SpanContext(
        trace_id=int(TRACE_ID, 16), span_id=int(SPAN_ID, 16), is_remote=False, trace_flags=trace.TraceFlags(1))))


def _span_where_installed():
    """The example span where the API is installed; where it is not, no span."""
    try:
        return _span()
    except ImportError:
        return contextlib.nullcontext()


def _recorded(client: HIITL, **options) -> dict:
    """The envelope the local audit record holds for one evaluate() call."""
    decision = client.evaluate("send_receipt", parameters={"order": "ord_42"}, **options)
    return json.loads(client._audit_logger.query_by_action_id(decision.action_id)["envelope"])


def test_inside_a_span_the_envelope_carries_its_trace_id(tmp_path):
    """Behavior 1: inside an active span the record carries the span's trace id; outside one, and inside a span from
    the API's no-op tracer (the API with no SDK), it carries none."""
    trace = pytest.importorskip("opentelemetry.trace", reason="needs the OpenTelemetry API (opentelemetry-api)")
    client = HIITL(audit_db_path=str(tmp_path / "audit.db"))
    try:
        with _span():
            inside = _recorded(client)
        outside = _recorded(client)
        with trace.get_tracer("row175").start_as_current_span("no-sdk"):
            no_op = _recorded(client)
    finally:
        client.close()

    assert inside.get("trace_id") == TRACE_ID
    assert "trace_id" not in outside, outside.get("trace_id")
    assert "trace_id" not in no_op, no_op.get("trace_id")


def test_without_the_api_nothing_is_set(tmp_path, monkeypatch):
    """Behavior 2: with the API's import refused, the client builds, evaluates and records, with no trace id. Where
    the API is installed, the call runs inside an active span, which the refused SDK does not read."""
    span = _span_where_installed()
    try:
        with monkeypatch.context() as m:
            m.setitem(sys.modules, "opentelemetry", None)
            m.setitem(sys.modules, "opentelemetry.trace", None)
            importlib.reload(trace_context)
            client = HIITL(audit_db_path=str(tmp_path / "audit.db"))
            try:
                with span:
                    recorded = _recorded(client)
            except Exception as e:  # nothing breaks
                raise AssertionError(f"evaluate() failed without the API: {e!r}") from e
            finally:
                client.close()
    finally:
        importlib.reload(trace_context)

    assert recorded["action"] == "send_receipt"
    assert "trace_id" not in recorded, recorded.get("trace_id")


def test_a_given_correlation_id_reaches_the_record(tmp_path, httpx_mock):
    """Behavior 3: local mode records the caller's correlation_id; hosted mode sends it in the envelope the service
    records (the request body is the envelope)."""
    client = HIITL(audit_db_path=str(tmp_path / "audit.db"))
    try:
        assert _recorded(client, correlation_id=CORRELATION_ID).get("correlation_id") == CORRELATION_ID
    finally:
        client.close()

    httpx_mock.add_response(url=f"{SERVER_URL}/v1/evaluate", method="POST", json=ALLOW, status_code=200)
    with HIITL(api_key="sk_test_row175", server_url=SERVER_URL, evaluation="remote",
               signature_key="test-signing-secret-0123456789abcdef", audit_db_path=str(tmp_path / "hosted.db")) as hosted:
        hosted.evaluate("send_receipt", parameters={"order": "ord_42"}, correlation_id=CORRELATION_ID)

    assert json.loads(httpx_mock.get_request().content).get("correlation_id") == CORRELATION_ID
