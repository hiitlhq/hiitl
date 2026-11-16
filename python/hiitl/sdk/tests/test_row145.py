"""Row 145 (HTL-20): an error says what happened and what to do (Principle 11), the same way on every path.

- An invalid `operation` raises EnvelopeValidationError naming the valid operations, in local and hosted mode alike,
  before anything is sent.
- The cold-start message names the mode the client keeps: under RESPECT_POLICY an empty policy set blocks every call,
  and the message says so.
- The hosted client and the sync client read the service's one error shape (docs-site/api/overview.mdx "Error
  format"): `{"detail": {"error", "message", "details"}}`, a 422's list of field problems, or a message string.
  A retryable status's last answer is read the same way.
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hiitl import HIITL
from hiitl.core.types import Operation
from hiitl.sdk.exceptions import EnvelopeValidationError, ServerError
from hiitl.sdk.sync_client import _extract_error

SERVER = "https://ecp.example"


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hosted() -> HIITL:
    return HIITL(api_key="sk_test_1234567890abcdef", server_url=SERVER, evaluation="remote", max_retries=0,
                 signature_key="s" * 32)


def _operation_error(client: HIITL) -> str:
    with pytest.raises(EnvelopeValidationError) as e:
        client.evaluate("refund", operation="refund_everything")
    return str(e.value)


def test_an_invalid_operation_names_the_valid_ones_in_every_mode_before_anything_is_sent(tmp_path, httpx_mock):
    local = _operation_error(HIITL(audit_db_path=str(tmp_path / "a.db")))
    hosted = _operation_error(_hosted())
    assert local == hosted, "one text, whichever mode the client is in"
    assert all(o.value in local for o in Operation) and "'execute'" in local
    assert httpx_mock.get_requests() == [], "the hosted client raised before it sent the call"


@pytest.mark.parametrize("mode, outcome", [
    ("OBSERVE_ALL", "every action is observed and allowed"),
    ("RESPECT_POLICY", "every action is blocked (NO_MATCHING_RULE)"),
])
def test_the_cold_start_message_names_the_mode_the_client_keeps(mode, outcome, tmp_path, caplog):
    engine = MagicMock()
    engine.initial_sync.return_value = False
    caplog.set_level(logging.WARNING, logger="hiitl.sdk.client")
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine):
        h = HIITL(api_key="sk_test_1234567890abcdef", mode=mode, cache_dir=str(tmp_path / "c"),
                  audit_db_path=str(tmp_path / "a.db"))
    cold = [r.getMessage() for r in caplog.records if "Cold-start sync" in r.getMessage()]
    assert len(cold) == 1 and f"running in {mode}" in cold[0] and outcome in cold[0], cold
    d = h.evaluate("refund")
    assert d.allowed is (mode == "OBSERVE_ALL"), "the decision is the one the message names"


@pytest.mark.parametrize("status, body, code, message", [
    (404, {"detail": {"error": "POLICY_NOT_FOUND", "message": "No active policy in this environment."}},
     "POLICY_NOT_FOUND", "No active policy in this environment."),
    (500, {"detail": {"error": "INTERNAL_ERROR", "message": "Retry.", "details": {"request_id": "req_1"}}},
     "INTERNAL_ERROR", "Retry."),
    (422, {"detail": [{"loc": ["body", "action"], "msg": "Field required", "type": "missing"}]},
     "VALIDATION_ERROR", "body.action: Field required"),
    (403, {"detail": "Insufficient permissions"}, "UNKNOWN_ERROR", "Insufficient permissions"),
    (400, {"detail": {"error": {"code": "NESTED"}, "message": 7}}, "UNKNOWN_ERROR", "Server returned HTTP 400"),
    (503, {"detail": {"error": "UNAVAILABLE", "message": "Try again shortly."}}, "UNAVAILABLE", "Try again shortly."),
], ids=["object", "5xx-with-request-id", "422-list", "string", "not-the-shape", "retryable-last-answer"])
def test_the_hosted_client_reads_each_error_shape(status, body, code, message, httpx_mock):
    httpx_mock.add_response(url=f"{SERVER}/v1/evaluate", method="POST", json=body, status_code=status)
    with pytest.raises(ServerError) as e:
        _hosted().evaluate("refund")
    assert (e.value.status_code, e.value.error_code, e.value.server_message) == (status, code, message)


@pytest.mark.parametrize("body, message", [
    ({"detail": {"error": "INSERT_FAILED", "message": "The audit record was not stored."}},
     "The audit record was not stored."),
    ({"detail": [{"loc": ["body", "records", 0], "msg": "Field required"}]}, "body.records.0: Field required"),
    ({"detail": "Not authenticated"}, "Not authenticated"),
    ({"detail": {"error": "X"}}, '{"error":"X"}'),
], ids=["object", "422-list", "string", "no-message"])
def test_the_sync_client_reads_the_same_shapes(body, message):
    assert _extract_error(httpx.Response(400, content=json.dumps(body).encode())) == message
