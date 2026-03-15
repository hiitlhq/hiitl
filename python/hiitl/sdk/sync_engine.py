"""Sync engine — background synchronization orchestrator.

The sync engine runs as a daemon thread, managing independent sync channels:
- Audit upload (local → server, 30s interval)
- Policy download (server → local, 5m interval)
- Route download (server → local, 5m interval)
- Kill switch polling (server → local, 30s interval)

Core invariant: evaluation is NEVER blocked by sync. All sync operations
run in a background thread. The evaluator reads from in-memory cache.

Lifecycle:
    engine = SyncEngine(config, cache, audit_logger, ...)
    engine.start()       # spawns daemon thread
    ...                  # evaluator works independently
    engine.stop()        # signals stop, flushes audit, joins thread
"""

import hashlib
import json
import logging
import threading
import time
from typing import Optional

from hiitl.sdk.circuit_breaker import CircuitBreaker
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import SyncError
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import SyncClient

logger = logging.getLogger(__name__)


class SyncEngine:
    """Background sync engine orchestrator.

    Manages a single daemon thread that runs all sync channels on
    independent schedules. Each channel has its own circuit breaker.

    Args:
        sync_config: Sync configuration (intervals, thresholds, etc.)
        sync_cache: Shared cache instance (also used by evaluator)
        audit_logger: AuditLogger instance for reading unsynced records
        api_key: Bearer token for server auth
        org_id: Organization ID
        environment: Environment (dev/stage/prod)
    """

    def __init__(
        self,
        sync_config: SyncConfig,
        sync_cache: SyncCache,
        audit_logger,  # AuditLogger — avoid circular import
        api_key: str,
        org_id: str,
        environment: str,
        telemetry_collector=None,  # TelemetryCollector — None when telemetry is off
    ):
        self._config = sync_config
        self._cache = sync_cache
        self._audit_logger = audit_logger
        self._telemetry_collector = telemetry_collector
        self._org_id = org_id
        self._environment = environment

        # Sync client for HTTP communication
        self._client = SyncClient(
            server_url=sync_config.server_url,
            api_key=api_key,
            org_id=org_id,
            environment=environment,
            timeout=sync_config.sync_timeout,
            max_retries=sync_config.sync_max_retries,
        )

        # Per-channel circuit breakers
        cb_threshold = sync_config.circuit_breaker_threshold
        cb_reset = sync_config.circuit_breaker_reset
        self._breakers = {
            "audit": CircuitBreaker("audit", cb_threshold, cb_reset),
            "policy": CircuitBreaker("policy", cb_threshold, cb_reset),
            "routes": CircuitBreaker("routes", cb_threshold, cb_reset),
            "kill_switches": CircuitBreaker("kill_switches", cb_threshold, cb_reset),
        }
        if telemetry_collector is not None:
            self._breakers["telemetry"] = CircuitBreaker("telemetry", cb_threshold, cb_reset)

        # Sync state
        self._audit_sequence = 0
        self._last_telemetry_sent = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self) -> None:
        """Start the sync engine daemon thread.

        Non-blocking — returns immediately. The background thread
        fires all pull channels immediately on first run.
        """
        if self._started:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="hiitl-sync-engine",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        logger.info("Sync engine started (server=%s)", self._config.server_url)

    def stop(self, flush_timeout: float = 5.0) -> None:
        """Stop the sync engine and flush pending audit records.

        Args:
            flush_timeout: Max seconds to wait for final audit flush (default: 5)
        """
        if not self._started:
            return

        logger.info("Stopping sync engine...")
        self._stop_event.set()

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=flush_timeout + 2.0)

        # Best-effort final audit flush
        try:
            self._sync_audit()
        except Exception as e:
            logger.warning("Final audit flush failed: %s", e)

        # Best-effort final telemetry flush
        if self._telemetry_collector is not None:
            try:
                self._sync_telemetry()
            except Exception as e:
                logger.warning("Final telemetry flush failed: %s", e)

        # Clean up
        try:
            self._client.close()
        except Exception:
            pass

        self._started = False
        logger.info("Sync engine stopped")

    def initial_sync(self, timeout: float = 10.0) -> bool:
        """Perform initial sync (blocking, for cold start).

        Attempts to download policies, routes, and kill switches before
        returning. Used during SDK initialization when no disk cache exists.

        Args:
            timeout: Max seconds to wait for initial sync

        Returns:
            True if at least policies were downloaded, False on timeout/failure
        """
        deadline = time.monotonic() + timeout
        policies_ok = False

        # Try policy download first (most critical)
        try:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                policies_ok = self._sync_policies()
        except Exception as e:
            logger.warning("Initial policy sync failed: %s", e)

        # Try routes and kill switches (best effort within remaining time)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                self._sync_routes()
            except Exception as e:
                logger.warning("Initial route sync failed: %s", e)

        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                self._sync_kill_switches()
            except Exception as e:
                logger.warning("Initial kill switch sync failed: %s", e)

        if policies_ok:
            logger.info("Initial sync completed: policies downloaded")
        else:
            logger.warning(
                "Initial sync: no policies downloaded within %.1fs timeout. "
                "Using local fallback.",
                timeout,
            )

        return policies_ok

    def status(self) -> dict:
        """Return sync engine health status."""
        result = {
            "running": self._started,
            "server_url": self._config.server_url,
            "cache": self._cache.status(),
            "circuit_breakers": {
                name: breaker.status()
                for name, breaker in self._breakers.items()
            },
            "audit_sequence": self._audit_sequence,
        }
        if self._telemetry_collector is not None:
            result["telemetry"] = self._telemetry_collector.status()
        return result

    # ── Main sync loop ───────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main sync loop — runs in daemon thread.

        Each channel runs on its own schedule. On first iteration,
        all pull channels fire immediately.
        """
        # Track last-run timestamps (0 = fire immediately)
        last_audit = 0.0
        last_policy = 0.0
        last_routes = 0.0
        last_kill_switches = 0.0
        last_telemetry = 0.0

        while not self._stop_event.is_set():
            now = time.monotonic()

            # Audit upload
            if now - last_audit >= self._config.audit_sync_interval:
                self._safe_sync("audit", self._sync_audit)
                last_audit = time.monotonic()

            # Policy download
            if now - last_policy >= self._config.policy_sync_interval:
                self._safe_sync("policy", self._sync_policies)
                last_policy = time.monotonic()

            # Route download
            if now - last_routes >= self._config.route_sync_interval:
                self._safe_sync("routes", self._sync_routes)
                last_routes = time.monotonic()

            # Kill switch polling
            if now - last_kill_switches >= self._config.kill_switch_poll_interval:
                self._safe_sync("kill_switches", self._sync_kill_switches)
                last_kill_switches = time.monotonic()

            # Telemetry upload (only if collector exists)
            if self._telemetry_collector is not None:
                if now - last_telemetry >= self._config.telemetry_sync_interval:
                    self._safe_sync("telemetry", self._sync_telemetry)
                    last_telemetry = time.monotonic()

            # Sleep in short increments for responsive shutdown
            self._stop_event.wait(timeout=1.0)

    def _safe_sync(self, channel: str, fn) -> None:
        """Execute a sync function with circuit breaker protection."""
        breaker = self._breakers[channel]

        if not breaker.allow_request():
            return  # Circuit is open

        try:
            fn()
            breaker.record_success()
        except SyncError as e:
            breaker.record_failure()
            logger.warning("Sync [%s] failed: %s", channel, e)
        except Exception as e:
            breaker.record_failure()
            logger.error("Sync [%s] unexpected error: %s", channel, e)

    # ── Channel implementations ──────────────────────────────────

    def _sync_audit(self) -> None:
        """Upload unsynced audit records in batches."""
        while True:
            records = self._audit_logger.get_unsynced(
                limit=self._config.audit_batch_size
            )
            if not records:
                break

            self._audit_sequence += 1
            result = self._client.upload_audit(records, self._audit_sequence)

            # Mark successfully accepted records as synced
            synced_ids = []
            error_ids = {e.get("event_id") for e in result.errors}

            for record in records:
                event_id = record["event_id"]
                if event_id not in error_ids:
                    synced_ids.append(event_id)

            if synced_ids:
                self._audit_logger.mark_synced(synced_ids)

            logger.debug(
                "Audit sync: accepted=%d, duplicates=%d, errors=%d",
                result.accepted,
                result.duplicates,
                len(result.errors),
            )

            # If there were errors, stop draining and retry next interval
            if result.errors:
                for err in result.errors:
                    logger.warning(
                        "Audit record %s rejected: [%s] %s",
                        err.get("event_id", "?"),
                        err.get("code", "?"),
                        err.get("message", "?"),
                    )
                break

            # If we got a full batch, drain immediately (no interval wait)
            if len(records) < self._config.audit_batch_size:
                break

            # Check for shutdown between drain batches
            if self._stop_event.is_set():
                break

    def _sync_policies(self) -> bool:
        """Download policies from server, update cache.

        Returns:
            True if policies were downloaded (new or updated), False if unchanged
        """
        etag = self._cache.get_policies_etag()
        result = self._client.download_policies(etag=etag)

        if result is None:
            # 304 Not Modified
            logger.debug("Policy sync: not modified (etag=%s)", etag)
            return False

        # Verify content hashes
        for policy in result.policies:
            expected_hash = policy.get("content_hash")
            if expected_hash:
                content = policy.get("content", {})
                actual_hash = hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                if actual_hash != expected_hash:
                    logger.error(
                        "POLICY_INTEGRITY_VIOLATION: policy '%s' content hash "
                        "mismatch (expected=%s, got=%s). Rejecting download.",
                        policy.get("name", "?"),
                        expected_hash,
                        actual_hash,
                    )
                    raise SyncError(
                        "policy",
                        f"Policy integrity violation for '{policy.get('name', '?')}': "
                        f"content hash mismatch",
                    )

        # Update cache atomically
        self._cache.update_policies(
            {"policies": result.policies, "version": result.version},
            etag=result.etag,
        )

        logger.info(
            "Policy sync: downloaded %d policies (version=%s)",
            len(result.policies),
            result.version,
        )
        return True

    def _sync_routes(self) -> bool:
        """Download routes from server, update cache.

        Returns:
            True if routes were downloaded, False if unchanged
        """
        etag = self._cache.get_routes_etag()
        result = self._client.download_routes(etag=etag)

        if result is None:
            logger.debug("Route sync: not modified (etag=%s)", etag)
            return False

        self._cache.update_routes(result.routes, etag=result.etag)

        logger.info("Route sync: downloaded %d routes", len(result.routes))
        return True

    def _sync_kill_switches(self) -> None:
        """Poll kill switches from server, update cache."""
        result = self._client.poll_kill_switches()

        self._cache.update_kill_switches(result.kill_switches)

        logger.debug(
            "Kill switch sync: %d active switches (server_time=%s)",
            len(result.kill_switches),
            result.server_time,
        )

    def _sync_telemetry(self) -> None:
        """Flush current telemetry window and upload pending records.

        Heartbeat: if no records are pending and > 10 minutes since last
        send, flush an empty window to confirm the SDK is alive (spec §7.4).
        """
        collector = self._telemetry_collector
        now = time.monotonic()

        # Flush current window
        collector.flush()

        # Check for heartbeat (empty window every 10 min)
        pending = collector.get_pending()
        if not pending and (now - self._last_telemetry_sent) >= 600:
            # Flush again to produce an empty-window heartbeat
            collector.flush()
            pending = collector.get_pending()

        if not pending:
            return

        # Upload pending records
        result = self._client.upload_telemetry(pending)
        collector.mark_sent(result.accepted)
        self._last_telemetry_sent = time.monotonic()

        logger.debug(
            "Telemetry sync: uploaded %d records",
            result.accepted,
        )
