"""HTTP client for sync engine communication with /v1/sync/* endpoints.

Handles authenticated requests to the hosted service for:
- POST /v1/sync/audit      — batch audit upload
- POST /v1/sync/telemetry  — telemetry record upload
- GET  /v1/sync/policies   — policy download (conditional)
- GET  /v1/sync/routes     — route download (conditional)
- GET  /v1/sync/kill-switches — kill switch polling

Uses the same patterns as http_client.py (httpx, retry with backoff)
but operates in the background sync context rather than the hot path.
"""

import gzip
import json
import logging
import random
import time
from dataclasses import dataclass, field

import httpx

from hiitl.sdk.exceptions import SyncError

logger = logging.getLogger(__name__)

# Retryable HTTP status codes
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# SDK version for headers
_SDK_VERSION = "0.1.0"


@dataclass
class AuditUploadResult:
    """Result of a batch audit upload."""
    accepted: int = 0
    duplicates: int = 0
    errors: list = field(default_factory=list)


@dataclass
class PolicyDownloadResult:
    """Result of a policy download."""
    policies: list = field(default_factory=list)
    version: str = ""
    etag: str = ""


@dataclass
class RouteDownloadResult:
    """Result of a route download."""
    routes: list = field(default_factory=list)
    etag: str = ""


@dataclass
class KillSwitchResult:
    """Result of a kill switch poll."""
    kill_switches: list = field(default_factory=list)
    server_time: str = ""


@dataclass
class TelemetryUploadResult:
    """Result of a telemetry upload."""
    accepted: int = 0


class SyncClient:
    """HTTP client for /v1/sync/* endpoints.

    Args:
        server_url: ECP server base URL
        api_key: Bearer token for authentication
        org_id: Organization ID
        environment: Environment (dev/stage/prod)
        timeout: Request timeout in seconds (default: 10.0)
        max_retries: Max retry attempts (default: 3)
    """

    def __init__(
        self,
        server_url: str,
        api_key: str,
        org_id: str,
        environment: str,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        self._server_url = server_url.rstrip("/")
        self._org_id = org_id
        self._environment = environment
        self._max_retries = max_retries

        self._client = httpx.Client(
            base_url=self._server_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip",
                "X-HIITL-Org-Id": org_id,
                "X-HIITL-Environment": environment,
                "X-HIITL-SDK-Version": _SDK_VERSION,
                "X-HIITL-SDK-Language": "python",
            },
        )

    def upload_audit(
        self,
        records: list[dict],
        sync_sequence: int,
    ) -> AuditUploadResult:
        """Upload a batch of audit records.

        Args:
            records: List of audit record dicts (max 100)
            sync_sequence: Monotonically increasing batch sequence number

        Returns:
            AuditUploadResult with accepted/duplicate/error counts

        Raises:
            SyncError: On unrecoverable failure
        """
        payload = {
            "records": records,
            "sdk_version": _SDK_VERSION,
            "sync_sequence": sync_sequence,
        }

        body = json.dumps(payload).encode()

        # Compress if > 1KB
        headers = {}
        if len(body) > 1024:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
            headers["Content-Type"] = "application/json"

        response = self._send_with_retry(
            "POST",
            "/v1/sync/audit",
            content=body,
            extra_headers=headers,
        )

        if response.status_code == 200:
            data = response.json()
            return AuditUploadResult(
                accepted=data.get("accepted", 0),
                duplicates=data.get("duplicates", 0),
                errors=data.get("errors", []),
            )

        raise SyncError(
            "audit",
            f"Audit upload failed with status {response.status_code}: "
            f"{_extract_error(response)}",
        )

    def download_policies(
        self,
        etag: str | None = None,
    ) -> PolicyDownloadResult | None:
        """Download active policies from server.

        Args:
            etag: ETag from previous download for conditional request

        Returns:
            PolicyDownloadResult with policies, or None if 304 Not Modified

        Raises:
            SyncError: On unrecoverable failure
        """
        headers = {}
        if etag:
            headers["If-None-Match"] = f'"{etag}"'

        response = self._send_with_retry(
            "GET",
            "/v1/sync/policies",
            extra_headers=headers,
        )

        if response.status_code == 304:
            return None  # Not modified

        if response.status_code == 200:
            data = response.json()
            return PolicyDownloadResult(
                policies=data.get("policies", []),
                version=data.get("version", ""),
                etag=data.get("etag", ""),
            )

        raise SyncError(
            "policy",
            f"Policy download failed with status {response.status_code}: "
            f"{_extract_error(response)}",
        )

    def download_routes(
        self,
        etag: str | None = None,
    ) -> RouteDownloadResult | None:
        """Download active route configurations from server.

        Args:
            etag: ETag from previous download for conditional request

        Returns:
            RouteDownloadResult with routes, or None if 304 Not Modified

        Raises:
            SyncError: On unrecoverable failure
        """
        headers = {}
        if etag:
            headers["If-None-Match"] = f'"{etag}"'

        response = self._send_with_retry(
            "GET",
            "/v1/sync/routes",
            extra_headers=headers,
        )

        if response.status_code == 304:
            return None

        if response.status_code == 200:
            data = response.json()
            return RouteDownloadResult(
                routes=data.get("routes", []),
                etag=data.get("etag", ""),
            )

        raise SyncError(
            "routes",
            f"Route download failed with status {response.status_code}: "
            f"{_extract_error(response)}",
        )

    def poll_kill_switches(self) -> KillSwitchResult:
        """Poll for active kill switch state.

        Returns:
            KillSwitchResult with current kill switches

        Raises:
            SyncError: On unrecoverable failure
        """
        response = self._send_with_retry("GET", "/v1/sync/kill-switches")

        if response.status_code == 200:
            data = response.json()
            return KillSwitchResult(
                kill_switches=data.get("kill_switches", []),
                server_time=data.get("server_time", ""),
            )

        raise SyncError(
            "kill_switches",
            f"Kill switch poll failed with status {response.status_code}: "
            f"{_extract_error(response)}",
        )

    def upload_telemetry(
        self,
        records: list[dict],
    ) -> TelemetryUploadResult:
        """Upload telemetry records.

        Args:
            records: List of telemetry record dicts (one per window)

        Returns:
            TelemetryUploadResult with accepted count

        Raises:
            SyncError: On unrecoverable failure
        """
        payload = {
            "records": records,
            "sdk_version": _SDK_VERSION,
        }

        body = json.dumps(payload).encode()

        # Compress if > 1KB
        headers = {}
        if len(body) > 1024:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
            headers["Content-Type"] = "application/json"

        response = self._send_with_retry(
            "POST",
            "/v1/sync/telemetry",
            content=body,
            extra_headers=headers,
        )

        if response.status_code == 200:
            data = response.json()
            return TelemetryUploadResult(
                accepted=data.get("accepted", len(records)),
            )

        raise SyncError(
            "telemetry",
            f"Telemetry upload failed with status {response.status_code}: "
            f"{_extract_error(response)}",
        )

    def _send_with_retry(
        self,
        method: str,
        path: str,
        content: bytes | None = None,
        extra_headers: dict | None = None,
    ) -> httpx.Response:
        """Send request with exponential backoff + jitter on transient failures.

        Backoff per spec: 1s → 2s → 4s → 8s → 60s max
        Jitter: delay * (0.5 + random() * 1.0)
        """
        last_error: Exception | None = None
        headers = dict(extra_headers) if extra_headers else {}

        for attempt in range(self._max_retries + 1):
            try:
                request = self._client.build_request(
                    method,
                    path,
                    content=content,
                    headers=headers,
                )
                response = self._client.send(request)

                # Success or non-retryable error
                if response.status_code not in _RETRYABLE_STATUS_CODES:
                    return response

                # Retryable — wait and retry
                if attempt < self._max_retries:
                    delay = _backoff_with_jitter(attempt)
                    logger.warning(
                        "Sync request %s %s returned %d, retrying in %.1fs "
                        "(attempt %d/%d)",
                        method, path, response.status_code,
                        delay, attempt + 1, self._max_retries,
                    )
                    time.sleep(delay)
                    continue

                return response

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = _backoff_with_jitter(attempt)
                    logger.warning(
                        "Sync request %s %s timed out, retrying in %.1fs "
                        "(attempt %d/%d)",
                        method, path, delay,
                        attempt + 1, self._max_retries,
                    )
                    time.sleep(delay)
                    continue

            except httpx.HTTPError as e:
                raise SyncError(
                    "transport",
                    f"HTTP error during sync {method} {path}: {e}",
                    cause=e,
                ) from e

        # All retries exhausted
        raise SyncError(
            "transport",
            f"Sync request {method} {path} failed after "
            f"{self._max_retries + 1} attempts: {last_error}",
            cause=last_error,
        )

    def close(self) -> None:
        """Close the HTTP client and release connections."""
        self._client.close()


def _backoff_with_jitter(attempt: int) -> float:
    """Exponential backoff with jitter per sync engine spec.

    Base delays: 1s, 2s, 4s, 8s, capped at 60s
    Jitter: delay * (0.5 + random() * 1.0)
    """
    base = min(1.0 * (2 ** attempt), 60.0)
    return base * (0.5 + random.random())


def _extract_error(response: httpx.Response) -> str:
    """Extract error message from response body."""
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("detail", data)
            if isinstance(detail, dict):
                return detail.get("message", str(detail))
            return str(detail)
        return str(data)
    except Exception:
        return response.text[:200] if response.text else "No response body"
