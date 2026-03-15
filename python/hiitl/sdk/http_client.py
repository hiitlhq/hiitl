"""HTTP client for hosted mode ECP server communication.

Handles:
- POST /v1/evaluate with Bearer token auth
- Retry with exponential backoff on transient failures (5xx, timeouts)
- Response parsing to Decision objects
- Error mapping to SDK exceptions with helpful messages
"""

import hashlib
import hmac as hmac_mod
import json
import logging
import time
from typing import Optional

import httpx

from hiitl.core.types import (
    CostEstimate,
    Decision,
    DecisionType,
    Sensitivity,
    Timing,
)
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import NetworkError, ServerError

logger = logging.getLogger(__name__)

# HTTP status codes that are retryable (transient failures)
_RETRYABLE_STATUS_CODES = {502, 503, 504, 429}


class HostedClient:
    """HTTP client for ECP server hosted mode.

    Manages HTTP communication with the ECP server, including
    authentication, retries, and response parsing.
    """

    def __init__(self, config: HostedModeConfig):
        self._config = config
        self._client = httpx.Client(
            base_url=config.server_url,
            timeout=config.timeout,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )

    def evaluate(
        self,
        action: str,
        operation: str,
        target: dict,
        parameters: dict,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        sensitivity: Optional[list[Sensitivity]] = None,
        cost_estimate: Optional[CostEstimate] = None,
        reason: Optional[str] = None,
        envelope_signature: Optional[str] = None,
    ) -> Decision:
        """Send evaluate request to ECP server and return Decision.

        Builds the request body matching the server's EvaluateRequest schema,
        sends it with retry logic, and parses the response into a Decision.

        Args:
            action: Action name
            operation: Operation type
            target: Target resource
            parameters: Operation parameters
            user_id: User identifier (optional)
            session_id: Session identifier (optional)
            sensitivity: Sensitivity labels (optional)
            cost_estimate: Cost estimate (optional)
            reason: Reasoning for action (optional)
            envelope_signature: HMAC-SHA256 signature (optional)

        Returns:
            Decision object from server response

        Raises:
            ServerError: Server returned an error response
            NetworkError: Cannot reach the server
        """
        # Build request body (EvaluateRequest format)
        body: dict = {
            "action": action,
            "operation": operation,
            "target": target,
            "parameters": parameters,
        }

        if self._config.agent_id:
            body["agent_id"] = self._config.agent_id
        if user_id:
            body["user_id"] = user_id
        if session_id:
            body["session_id"] = session_id
        if sensitivity:
            body["sensitivity"] = [
                s.value if isinstance(s, Sensitivity) else s
                for s in sensitivity
            ]
        if cost_estimate:
            body["cost_estimate"] = (
                cost_estimate.model_dump()
                if hasattr(cost_estimate, "model_dump")
                else cost_estimate
            )
        if reason:
            body["reason"] = reason

        # Compute envelope signature if signing key is configured
        if envelope_signature:
            body["envelope_signature"] = envelope_signature
        elif self._config.signature_key:
            body["envelope_signature"] = self._compute_signature(body)

        # Send with retry
        response = self._send_with_retry(body)

        # Parse response to Decision
        return self._parse_response(response)

    def _compute_signature(self, body: dict) -> str:
        """Compute HMAC-SHA256 signature of request body."""
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hmac_mod.new(
            self._config.signature_key.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _send_with_retry(self, body: dict) -> httpx.Response:
        """Send POST request with exponential backoff retry on transient failures."""
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._client.post("/v1/evaluate", json=body)

                # Success or non-retryable error: return immediately
                if response.status_code < 500 and response.status_code != 429:
                    return response

                # Retryable server error
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < self._config.max_retries:
                        wait = _backoff_delay(attempt)
                        logger.warning(
                            "ECP server returned %d, retrying in %.1fs (attempt %d/%d)",
                            response.status_code,
                            wait,
                            attempt + 1,
                            self._config.max_retries,
                        )
                        time.sleep(wait)
                        continue

                # Non-retryable 5xx or exhausted retries
                return response

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self._config.max_retries:
                    wait = _backoff_delay(attempt)
                    logger.warning(
                        "ECP server request timed out, retrying in %.1fs (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        self._config.max_retries,
                    )
                    time.sleep(wait)
                    continue

            except httpx.ConnectError as e:
                raise NetworkError(self._config.server_url, e) from e

            except httpx.HTTPError as e:
                raise NetworkError(self._config.server_url, e) from e

        # All retries exhausted on timeout
        raise NetworkError(self._config.server_url, last_error)

    def _parse_response(self, response: httpx.Response) -> Decision:
        """Parse HTTP response into a Decision or raise appropriate error."""
        if response.status_code == 200:
            data = response.json()

            # Map server timing format to SDK Timing model
            # Server returns {"total_ms": X, ...} — SDK expects ingest_ms + evaluation_ms
            raw_timing = data.get("timing", {})
            total_ms = raw_timing.get("total_ms", 0.0)
            timing = Timing(
                ingest_ms=raw_timing.get("ingest_ms", 0.0),
                evaluation_ms=raw_timing.get("evaluation_ms", total_ms),
                total_ms=total_ms,
            )

            # Pass all optional fields through — Pydantic validates and
            # coerces types (e.g. error dict → ErrorDetail via model_validator).
            # Use .get() with None default; Pydantic ignores None optionals.
            _OPT_FIELDS = (
                "envelope_hash", "resume_token", "route_ref",
                "escalation_context", "matched_rules", "rate_limit",
                "approval_metadata", "sandbox_metadata", "error",
                "remediation", "would_be", "would_be_reason_codes",
            )
            kwargs = {
                k: data[k] for k in _OPT_FIELDS
                if k in data and data[k] is not None
            }

            return Decision(
                action_id=data.get("action_id", ""),
                decision=DecisionType(data["decision"]),
                allowed=data["allowed"],
                reason_codes=data.get("reason_codes", []),
                policy_version=data.get("policy_version", ""),
                timing=timing,
                **kwargs,
            )

        # Error response — extract structured error info
        error_code = "UNKNOWN_ERROR"
        message = f"Server returned HTTP {response.status_code}"

        try:
            data = response.json()
            # Server wraps errors in {"detail": {...}}
            detail = data.get("detail", data)
            if isinstance(detail, dict):
                error_code = detail.get("error", error_code)
                message = detail.get("message", message)
            elif isinstance(detail, str):
                message = detail
        except Exception:
            message = response.text or message

        raise ServerError(response.status_code, error_code, message)

    def close(self):
        """Close the HTTP client and release connections."""
        self._client.close()


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, capped at 4s."""
    return min(0.5 * (2 ** attempt), 4.0)
