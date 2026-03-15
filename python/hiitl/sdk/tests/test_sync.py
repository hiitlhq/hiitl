"""Tests for sync engine components.

Covers:
- CircuitBreaker: state transitions, thread safety, recovery
- SyncCache: atomic writes, disk persistence, warm start, stale detection
- SyncClient: HTTP requests, retry, error handling
- SyncEngine: lifecycle, channel scheduling, non-blocking guarantee
- Audit sync: batch retrieval, mark synced
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

from hiitl.sdk.circuit_breaker import CircuitBreaker, CircuitState
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import (
    SyncClient,
    AuditUploadResult,
    PolicyDownloadResult,
    RouteDownloadResult,
    KillSwitchResult,
)
from hiitl.sdk.sync_engine import SyncEngine
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import SyncError


# ── CircuitBreaker Tests ──────────────────────────────────────────


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_allow_request_when_closed(self):
        cb = CircuitBreaker("test")
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_blocks_requests_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_allows_one_request_in_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.allow_request() is True

    def test_closes_on_success_from_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        _ = cb.state  # Trigger HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        _ = cb.state  # Trigger HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Still closed — success reset the count
        assert cb.state == CircuitState.CLOSED

    def test_reset_forces_closed(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_status_returns_dict(self):
        cb = CircuitBreaker("audit", failure_threshold=5, reset_timeout=60.0)
        cb.record_failure()
        status = cb.status()
        assert status["channel"] == "audit"
        assert status["state"] == "closed"
        assert status["failure_count"] == 1
        assert status["failure_threshold"] == 5
        assert status["reset_timeout"] == 60.0


class TestCircuitBreakerThreadSafety:
    """Test circuit breaker under concurrent access."""

    def test_concurrent_failures(self):
        cb = CircuitBreaker("test", failure_threshold=10)
        errors = []

        def fail_n_times(n):
            try:
                for _ in range(n):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fail_n_times, args=(5,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb.state == CircuitState.OPEN


# ── SyncCache Tests ───────────────────────────────────────────────


class TestSyncCacheDiskPersistence:
    """Test SyncCache disk read/write operations."""

    def test_write_and_read_policies(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        policy_data = {"policies": [{"name": "test"}], "version": "v1"}

        cache.update_policies(policy_data, etag="abc123")

        assert cache.get_policies() == policy_data
        assert cache.get_policies_etag() == "abc123"

        # Verify disk persistence
        policy_file = tmp_path / "org_test" / "dev" / "policies.json"
        assert policy_file.exists()
        disk_data = json.loads(policy_file.read_text())
        assert disk_data == policy_data

    def test_write_and_read_routes(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        routes = [{"name": "approval-webhook", "type": "webhook"}]

        cache.update_routes(routes, etag="route_etag")

        assert cache.get_routes() == routes
        assert cache.get_routes_etag() == "route_etag"

    def test_write_and_read_kill_switches(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        switches = [{"action": "process_payment", "active": True}]

        cache.update_kill_switches(switches)

        assert cache.get_kill_switches() == switches

    def test_warm_start_loads_from_disk(self, tmp_path):
        # First instance writes data
        cache1 = SyncCache(str(tmp_path), "org_test", "dev")
        cache1.update_policies({"policies": [{"name": "p1"}], "version": "v1"}, etag="e1")
        cache1.update_routes([{"name": "r1"}], etag="e2")
        cache1.update_kill_switches([{"action": "blocked_action"}])

        # Second instance loads from disk
        cache2 = SyncCache(str(tmp_path), "org_test", "dev")
        loaded = cache2.load_from_disk()

        assert loaded is True
        assert cache2.get_policies() == {"policies": [{"name": "p1"}], "version": "v1"}
        assert cache2.get_policies_etag() == "e1"
        assert cache2.get_routes() == [{"name": "r1"}]
        assert cache2.get_routes_etag() == "e2"
        assert cache2.get_kill_switches() == [{"action": "blocked_action"}]

    def test_cold_start_returns_false(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        loaded = cache.load_from_disk()
        assert loaded is False
        assert cache.get_policies() is None
        assert cache.get_routes() is None
        assert cache.get_kill_switches() is None


class TestSyncCacheAgeTracking:
    """Test cache freshness/age tracking."""

    def test_policies_age_infinite_when_never_set(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        assert cache.get_policies_age_seconds() == float("inf")

    def test_policies_age_resets_on_update(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"policies": []}, etag="e1")
        assert cache.get_policies_age_seconds() < 1.0

    def test_routes_age_infinite_when_never_set(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        assert cache.get_routes_age_seconds() == float("inf")

    def test_kill_switches_age_infinite_when_never_set(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        assert cache.get_kill_switches_age_seconds() == float("inf")


class TestSyncCacheStatus:
    """Test cache status reporting."""

    def test_status_empty_cache(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        status = cache.status()
        assert status["policies"]["cached"] is False
        assert status["routes"]["cached"] is False
        assert status["kill_switches"]["cached"] is False

    def test_status_with_data(self, tmp_path):
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"policies": []}, etag="e1")
        status = cache.status()
        assert status["policies"]["cached"] is True
        assert status["policies"]["etag"] == "e1"
        assert status["policies"]["age_seconds"] < 1.0


class TestSyncCacheOrgIsolation:
    """Test that caches are scoped by org_id and environment."""

    def test_different_orgs_have_separate_caches(self, tmp_path):
        cache_a = SyncCache(str(tmp_path), "org_aaa", "dev")
        cache_b = SyncCache(str(tmp_path), "org_bbb", "dev")

        cache_a.update_policies({"policies": [{"name": "a_policy"}]})
        cache_b.update_policies({"policies": [{"name": "b_policy"}]})

        assert cache_a.get_policies()["policies"][0]["name"] == "a_policy"
        assert cache_b.get_policies()["policies"][0]["name"] == "b_policy"

    def test_different_envs_have_separate_caches(self, tmp_path):
        cache_dev = SyncCache(str(tmp_path), "org_test", "dev")
        cache_prod = SyncCache(str(tmp_path), "org_test", "prod")

        cache_dev.update_policies({"env": "dev"})
        cache_prod.update_policies({"env": "prod"})

        assert cache_dev.get_policies()["env"] == "dev"
        assert cache_prod.get_policies()["env"] == "prod"


# ── SyncCache SRE Hardening Tests ────────────────────────────────


class TestSyncCacheDiskDivergence:
    """Test disk/memory divergence tracking."""

    def test_memory_updates_on_disk_failure(self, tmp_path):
        """Memory should be updated even when disk write fails."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"version": "v1"})  # Create dir first

        # Make cache dir read-only to force disk write failure
        cache_dir = tmp_path / "org_test" / "dev"
        cache_dir.chmod(0o444)
        try:
            cache.update_policies({"version": "v2"}, etag="e2")
            # Memory should have the new data
            assert cache.get_policies() == {"version": "v2"}
            assert cache.get_policies_etag() == "e2"
            # Disk divergence should be tracked
            assert cache.status()["disk_synced"] is False
        finally:
            cache_dir.chmod(0o755)

    def test_disk_diverged_clears_on_success(self, tmp_path):
        """Successful write should clear disk divergence flag."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache._disk_diverged = True

        cache.update_policies({"version": "v1"})
        assert cache.status()["disk_synced"] is True

    def test_status_reports_disk_synced(self, tmp_path):
        """status() should include disk_synced field."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        status = cache.status()
        assert "disk_synced" in status
        assert status["disk_synced"] is True


class TestSyncCacheWarmStartAge:
    """Test that warm start preserves actual file age."""

    def test_warm_start_age_reflects_file_age(self, tmp_path):
        """Loaded cache age should reflect actual file age, not zero."""
        cache1 = SyncCache(str(tmp_path), "org_test", "dev")
        cache1.update_policies({"version": "v1"}, etag="e1")

        # Backdate the file mtime by 120 seconds
        policy_file = tmp_path / "org_test" / "dev" / "policies.json"
        import os as _os
        old_mtime = _os.path.getmtime(str(policy_file)) - 120
        _os.utime(str(policy_file), (old_mtime, old_mtime))

        # Load in new instance
        cache2 = SyncCache(str(tmp_path), "org_test", "dev")
        cache2.load_from_disk()

        age = cache2.get_policies_age_seconds()
        # Age should be approximately 120 seconds (with some tolerance)
        assert age >= 100.0, f"Expected age >= 100s, got {age:.1f}s"
        assert age < 200.0, f"Expected age < 200s, got {age:.1f}s"

    def test_fresh_update_age_near_zero(self, tmp_path):
        """Freshly updated cache should have age near zero."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"version": "v1"})
        assert cache.get_policies_age_seconds() < 1.0


class TestSyncCacheMaxStale:
    """Test max-stale enforcement with CACHE_STALE warnings."""

    def test_stale_cache_emits_warning(self, tmp_path, caplog):
        """CACHE_STALE warning should be emitted when data exceeds max stale age."""
        cache = SyncCache(str(tmp_path), "org_test", "dev", max_stale_age=1.0)
        cache.update_policies({"version": "v1"})

        import time as _time
        _time.sleep(1.2)

        with caplog.at_level(logging.WARNING):
            cache.get_policies()

        assert any("CACHE_STALE" in r.message for r in caplog.records)

    def test_stale_warning_only_once(self, tmp_path, caplog):
        """CACHE_STALE warning should only be emitted once per channel."""
        cache = SyncCache(str(tmp_path), "org_test", "dev", max_stale_age=1.0)
        cache.update_policies({"version": "v1"})

        import time as _time
        _time.sleep(1.2)

        with caplog.at_level(logging.WARNING):
            cache.get_policies()
            cache.get_policies()
            cache.get_policies()

        stale_count = sum(1 for r in caplog.records if "CACHE_STALE" in r.message)
        assert stale_count == 1

    def test_stale_warning_resets_on_update(self, tmp_path, caplog):
        """Update should clear stale warning, allowing re-emission if stale again."""
        cache = SyncCache(str(tmp_path), "org_test", "dev", max_stale_age=1.0)
        cache.update_policies({"version": "v1"})

        import time as _time
        _time.sleep(1.2)

        with caplog.at_level(logging.WARNING):
            cache.get_policies()  # Triggers warning
        assert any("CACHE_STALE" in r.message for r in caplog.records)

        # Update should clear the warning flag
        caplog.clear()
        cache.update_policies({"version": "v2"})
        _time.sleep(1.2)

        with caplog.at_level(logging.WARNING):
            cache.get_policies()  # Should trigger warning again

        assert any("CACHE_STALE" in r.message for r in caplog.records)

    def test_fresh_cache_no_warning(self, tmp_path, caplog):
        """No warning for freshly updated data."""
        cache = SyncCache(str(tmp_path), "org_test", "dev", max_stale_age=86400.0)
        cache.update_policies({"version": "v1"})

        with caplog.at_level(logging.WARNING):
            cache.get_policies()

        assert not any("CACHE_STALE" in r.message for r in caplog.records)


class TestSyncCacheIntegrity:
    """Test SHA-256 integrity verification on cached files."""

    def test_integrity_check_passes_for_valid_data(self, tmp_path):
        """Valid data with matching hash should load successfully."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        data = {"version": "v1", "policies": [{"name": "test"}]}
        cache.update_policies(data)

        # Verify hash file was created
        hash_file = tmp_path / "org_test" / "dev" / "policies.json.sha256"
        assert hash_file.exists()

        # Load in new instance
        cache2 = SyncCache(str(tmp_path), "org_test", "dev")
        loaded = cache2.load_from_disk()
        assert loaded is True
        assert cache2.get_policies() == data

    def test_integrity_check_rejects_corrupted_data(self, tmp_path, caplog):
        """Corrupted data should be rejected with CACHE_INTEGRITY_VIOLATION."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"version": "v1"})

        # Corrupt the data file
        policy_file = tmp_path / "org_test" / "dev" / "policies.json"
        policy_file.write_text('{"version":"CORRUPTED"}')

        cache2 = SyncCache(str(tmp_path), "org_test", "dev")
        with caplog.at_level(logging.ERROR):
            loaded = cache2.load_from_disk()

        assert cache2.get_policies() is None
        assert any("CACHE_INTEGRITY_VIOLATION" in r.message for r in caplog.records)

    def test_integrity_graceful_without_hash_file(self, tmp_path):
        """Data should load if hash file doesn't exist (backward compat)."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache.update_policies({"version": "v1"})

        # Delete the hash file
        hash_file = tmp_path / "org_test" / "dev" / "policies.json.sha256"
        hash_file.unlink()

        cache2 = SyncCache(str(tmp_path), "org_test", "dev")
        loaded = cache2.load_from_disk()
        assert loaded is True
        assert cache2.get_policies() == {"version": "v1"}


class TestSyncCacheOrphanCleanup:
    """Test orphaned .tmp file cleanup."""

    def test_cleanup_removes_old_tmp_files(self, tmp_path):
        """Old .tmp files should be removed during startup."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache_dir = tmp_path / "org_test" / "dev"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create old .tmp file (backdate mtime)
        tmp_file = cache_dir / "orphaned.tmp"
        tmp_file.write_text("stale data")
        import os as _os
        old_mtime = _os.path.getmtime(str(tmp_file)) - 600
        _os.utime(str(tmp_file), (old_mtime, old_mtime))

        removed = cache._cleanup_orphans()
        assert removed == 1
        assert not tmp_file.exists()

    def test_cleanup_preserves_recent_tmp_files(self, tmp_path):
        """Recent .tmp files should not be removed (could be in-progress write)."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache_dir = tmp_path / "org_test" / "dev"
        cache_dir.mkdir(parents=True, exist_ok=True)

        tmp_file = cache_dir / "recent.tmp"
        tmp_file.write_text("in progress")

        removed = cache._cleanup_orphans()
        assert removed == 0
        assert tmp_file.exists()

    def test_cleanup_handles_missing_dir(self, tmp_path):
        """Cleanup should not crash on missing directory."""
        cache = SyncCache(str(tmp_path), "org_nonexistent", "dev")
        removed = cache._cleanup_orphans()
        assert removed == 0


class TestSyncCacheEnsureDir:
    """Test that _ensure_dir caches the result."""

    def test_ensure_dir_creates_directory(self, tmp_path):
        """First call should create the directory."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache._ensure_dir()
        assert (tmp_path / "org_test" / "dev").exists()
        assert cache._dir_created is True

    def test_ensure_dir_is_idempotent(self, tmp_path):
        """Multiple calls should succeed without error."""
        cache = SyncCache(str(tmp_path), "org_test", "dev")
        cache._ensure_dir()
        cache._ensure_dir()
        cache._ensure_dir()
        assert cache._dir_created is True


# ── SyncClient Tests ──────────────────────────────────────────────


class TestSyncClientHeaders:
    """Test that SyncClient sets correct headers."""

    def test_client_sets_auth_headers(self):
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )
        headers = client._client.headers
        assert headers["Authorization"] == "Bearer sk_test_123"
        assert headers["X-HIITL-Org-Id"] == "org_testorg1234567890"
        assert headers["X-HIITL-Environment"] == "dev"
        assert "X-HIITL-SDK-Version" in headers
        assert headers["X-HIITL-SDK-Language"] == "python"
        client.close()


class TestSyncClientRetry:
    """Test retry behavior with backoff."""

    def test_retries_on_503(self):
        """Verify client retries on 503 status codes."""
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
            max_retries=1,
        )

        call_count = 0
        original_send = client._client.send

        def mock_send(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, request=request, content=b'{"error": "unavailable"}')

        client._client.send = mock_send

        # Should retry once then return the 503 response
        response = client._send_with_retry("GET", "/v1/sync/policies")
        assert response.status_code == 503
        assert call_count == 2  # initial + 1 retry
        client.close()

    def test_no_retry_on_400(self):
        """Client should NOT retry on 400 (not in retryable set)."""
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
            max_retries=3,
        )

        call_count = 0

        def mock_send(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, request=request, content=b'{"error": "bad request"}')

        client._client.send = mock_send

        response = client._send_with_retry("GET", "/v1/sync/policies")
        assert response.status_code == 400
        assert call_count == 1  # no retry
        client.close()

    def test_raises_sync_error_on_http_error(self):
        """Non-retryable HTTP errors raise SyncError."""
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )

        def mock_send(request):
            raise httpx.ConnectError("Connection refused")

        client._client.send = mock_send

        with pytest.raises(SyncError) as exc_info:
            client._send_with_retry("GET", "/v1/sync/policies")

        assert exc_info.value.channel == "transport"
        client.close()


class TestSyncClientAuditUpload:
    """Test audit upload method."""

    def test_upload_audit_success(self):
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )

        def mock_send(request):
            return httpx.Response(
                200,
                request=request,
                json={"accepted": 5, "duplicates": 1, "errors": []},
            )

        client._client.send = mock_send

        result = client.upload_audit([{"event_id": "e1"}], sync_sequence=1)
        assert isinstance(result, AuditUploadResult)
        assert result.accepted == 5
        assert result.duplicates == 1
        assert result.errors == []
        client.close()

    def test_upload_audit_failure_raises(self):
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )

        def mock_send(request):
            return httpx.Response(
                422,
                request=request,
                json={"detail": {"message": "Invalid records"}},
            )

        client._client.send = mock_send

        with pytest.raises(SyncError) as exc_info:
            client.upload_audit([{"bad": "data"}], sync_sequence=1)
        assert "422" in str(exc_info.value)
        client.close()


class TestSyncClientPolicyDownload:
    """Test policy download method."""

    def test_download_policies_success(self):
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )

        def mock_send(request):
            return httpx.Response(
                200,
                request=request,
                json={
                    "policies": [{"name": "p1", "content": {}}],
                    "version": "v1.0",
                    "etag": "etag_abc",
                },
            )

        client._client.send = mock_send

        result = client.download_policies()
        assert isinstance(result, PolicyDownloadResult)
        assert len(result.policies) == 1
        assert result.version == "v1.0"
        assert result.etag == "etag_abc"
        client.close()

    def test_download_policies_304_returns_none(self):
        client = SyncClient(
            server_url="https://api.hiitl.com",
            api_key="sk_test_123",
            org_id="org_testorg1234567890",
            environment="dev",
        )

        def mock_send(request):
            return httpx.Response(304, request=request)

        client._client.send = mock_send

        result = client.download_policies(etag="existing_etag")
        assert result is None
        client.close()


# ── SyncEngine Tests ──────────────────────────────────────────────


class TestSyncEngineLifecycle:
    """Test sync engine start/stop lifecycle."""

    def _make_engine(self, tmp_path):
        """Create a SyncEngine with mocked components."""
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
            audit_sync_interval=30,
            policy_sync_interval=300,
            route_sync_interval=300,
            kill_switch_poll_interval=30,
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()
        audit_logger.get_unsynced.return_value = []

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )
        return engine, cache, audit_logger

    def test_start_and_stop(self, tmp_path):
        engine, _, _ = self._make_engine(tmp_path)

        # Mock the sync client to avoid real HTTP
        engine._client = MagicMock()
        engine._client.close = MagicMock()

        engine.start()
        assert engine._started is True
        assert engine._thread is not None
        assert engine._thread.is_alive()

        engine.stop()
        assert engine._started is False

    def test_start_is_idempotent(self, tmp_path):
        engine, _, _ = self._make_engine(tmp_path)
        engine._client = MagicMock()
        engine._client.close = MagicMock()

        engine.start()
        thread1 = engine._thread
        engine.start()  # Second call should be no-op
        assert engine._thread is thread1

        engine.stop()

    def test_stop_when_not_started_is_noop(self, tmp_path):
        engine, _, _ = self._make_engine(tmp_path)
        engine._client = MagicMock()
        engine._client.close = MagicMock()
        engine.stop()  # Should not raise

    def test_status_when_running(self, tmp_path):
        engine, _, _ = self._make_engine(tmp_path)
        engine._client = MagicMock()
        engine._client.close = MagicMock()

        engine.start()
        status = engine.status()

        assert status["running"] is True
        assert "cache" in status
        assert "circuit_breakers" in status
        assert len(status["circuit_breakers"]) == 4

        engine.stop()

    def test_status_when_stopped(self, tmp_path):
        engine, _, _ = self._make_engine(tmp_path)
        status = engine.status()
        assert status["running"] is False


class TestSyncEngineInitialSync:
    """Test initial sync (blocking, for cold start)."""

    def test_initial_sync_success(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()
        audit_logger.get_unsynced.return_value = []

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        # Mock client to return policies
        engine._client = MagicMock()
        engine._client.download_policies.return_value = PolicyDownloadResult(
            policies=[{"name": "test_policy", "content": {}, "active": True}],
            version="v1",
            etag="e1",
        )
        engine._client.download_routes.return_value = RouteDownloadResult(
            routes=[],
            etag="e2",
        )
        engine._client.poll_kill_switches.return_value = KillSwitchResult(
            kill_switches=[],
            server_time="2024-01-01T00:00:00Z",
        )

        result = engine.initial_sync(timeout=5.0)

        assert result is True
        assert cache.get_policies() is not None
        engine._client.close()

    def test_initial_sync_failure_returns_false(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        # Mock client to fail
        engine._client = MagicMock()
        engine._client.download_policies.side_effect = SyncError("policy", "Connection refused")
        engine._client.download_routes.side_effect = SyncError("routes", "Connection refused")
        engine._client.poll_kill_switches.side_effect = SyncError("kill_switches", "Connection refused")

        result = engine.initial_sync(timeout=2.0)
        assert result is False
        engine._client.close()


class TestSyncEngineCircuitBreaker:
    """Test circuit breaker integration with sync engine."""

    def test_circuit_breaker_blocks_after_failures(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
            circuit_breaker_threshold=2,
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()
        audit_logger.get_unsynced.return_value = []

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        # Mock client to fail
        engine._client = MagicMock()
        engine._client.download_policies.side_effect = SyncError("policy", "fail")

        # Fail twice to trip the breaker
        engine._safe_sync("policy", engine._sync_policies)
        engine._safe_sync("policy", engine._sync_policies)

        # Circuit should be open now
        assert engine._breakers["policy"].state == CircuitState.OPEN

        # Reset call count to verify no more calls are made
        engine._client.download_policies.reset_mock()
        engine._safe_sync("policy", engine._sync_policies)

        # Should not have been called — circuit is open
        engine._client.download_policies.assert_not_called()
        engine._client.close()


class TestSyncEngineAuditSync:
    """Test audit upload channel."""

    def test_audit_sync_uploads_and_marks_synced(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()
        audit_logger.get_unsynced.side_effect = [
            [
                {"event_id": "evt_1", "envelope": {}, "decision": {}},
                {"event_id": "evt_2", "envelope": {}, "decision": {}},
            ],
            [],  # Second call returns empty (drain complete)
        ]

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        engine._client = MagicMock()
        engine._client.upload_audit.return_value = AuditUploadResult(
            accepted=2, duplicates=0, errors=[]
        )

        engine._sync_audit()

        # Should have called upload
        engine._client.upload_audit.assert_called_once()

        # Should have marked both as synced
        audit_logger.mark_synced.assert_called_once_with(["evt_1", "evt_2"])
        engine._client.close()

    def test_audit_sync_handles_partial_errors(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()
        audit_logger.get_unsynced.return_value = [
            {"event_id": "evt_1", "envelope": {}, "decision": {}},
            {"event_id": "evt_2", "envelope": {}, "decision": {}},
        ]

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        engine._client = MagicMock()
        engine._client.upload_audit.return_value = AuditUploadResult(
            accepted=1,
            duplicates=0,
            errors=[{"event_id": "evt_2", "code": "INVALID", "message": "bad data"}],
        )

        engine._sync_audit()

        # Should only mark the successful one as synced
        audit_logger.mark_synced.assert_called_once_with(["evt_1"])
        engine._client.close()


class TestSyncEnginePolicyIntegrity:
    """Test policy content hash verification."""

    def test_policy_integrity_verification_passes(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        # Create a policy with a valid content hash
        import hashlib
        content = {"version": "1.0", "name": "test", "rules": []}
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        engine._client = MagicMock()
        engine._client.download_policies.return_value = PolicyDownloadResult(
            policies=[{
                "name": "test",
                "content": content,
                "content_hash": content_hash,
                "active": True,
            }],
            version="v1",
            etag="e1",
        )

        result = engine._sync_policies()
        assert result is True
        assert cache.get_policies() is not None
        engine._client.close()

    def test_policy_integrity_violation_raises(self, tmp_path):
        config = SyncConfig(
            server_url="https://api.hiitl.com",
            cache_dir=str(tmp_path / "cache"),
        )
        cache = SyncCache(str(tmp_path / "cache"), "org_test", "dev")
        audit_logger = MagicMock()

        engine = SyncEngine(
            sync_config=config,
            sync_cache=cache,
            audit_logger=audit_logger,
            api_key="sk_test_123",
            org_id="org_test",
            environment="dev",
        )

        engine._client = MagicMock()
        engine._client.download_policies.return_value = PolicyDownloadResult(
            policies=[{
                "name": "test",
                "content": {"version": "1.0"},
                "content_hash": "wrong_hash_value_here",
                "active": True,
            }],
            version="v1",
            etag="e1",
        )

        with pytest.raises(SyncError) as exc_info:
            engine._sync_policies()

        assert "integrity" in str(exc_info.value).lower()
        # Cache should NOT be updated
        assert cache.get_policies() is None
        engine._client.close()


# ── Audit Sync Tracking Tests ─────────────────────────────────────


class TestAuditSyncTracking:
    """Test the audit logger's sync tracking features."""

    def test_get_unsynced_returns_new_records(self, tmp_path):
        from hiitl.sdk.audit import AuditLogger

        db_path = str(tmp_path / "test_audit.db")
        logger = AuditLogger(db_path)

        # Write some records
        envelope = {
            "org_id": "org_test",
            "environment": "dev",
            "action_id": "act_12345678901234567890",
            "action": "test_action",
        }
        decision = {
            "decision": "ALLOW",
            "policy_version": "v1",
        }

        event_id = logger.write(envelope, decision)

        # Should be unsynced
        unsynced = logger.get_unsynced()
        assert len(unsynced) == 1
        assert unsynced[0]["event_id"] == event_id

    def test_mark_synced_removes_from_unsynced(self, tmp_path):
        from hiitl.sdk.audit import AuditLogger

        db_path = str(tmp_path / "test_audit.db")
        logger = AuditLogger(db_path)

        envelope = {
            "org_id": "org_test",
            "environment": "dev",
            "action_id": "act_12345678901234567890",
            "action": "test_action",
        }
        decision = {"decision": "ALLOW", "policy_version": "v1"}

        eid1 = logger.write(envelope, decision)
        eid2 = logger.write(envelope, decision)

        # Mark first as synced
        count = logger.mark_synced([eid1])
        assert count == 1

        # Only second should be unsynced
        unsynced = logger.get_unsynced()
        assert len(unsynced) == 1
        assert unsynced[0]["event_id"] == eid2

    def test_count_unsynced(self, tmp_path):
        from hiitl.sdk.audit import AuditLogger

        db_path = str(tmp_path / "test_audit.db")
        logger = AuditLogger(db_path)

        envelope = {
            "org_id": "org_test",
            "environment": "dev",
            "action_id": "act_12345678901234567890",
            "action": "test_action",
        }
        decision = {"decision": "ALLOW", "policy_version": "v1"}

        logger.write(envelope, decision)
        logger.write(envelope, decision)
        logger.write(envelope, decision)

        assert logger.count_unsynced() == 3

    def test_get_unsynced_ordered_by_timestamp_asc(self, tmp_path):
        from hiitl.sdk.audit import AuditLogger

        db_path = str(tmp_path / "test_audit.db")
        logger = AuditLogger(db_path)

        envelope = {
            "org_id": "org_test",
            "environment": "dev",
            "action_id": "act_12345678901234567890",
            "action": "test_action",
        }
        decision = {"decision": "ALLOW", "policy_version": "v1"}

        eid1 = logger.write(envelope, decision)
        eid2 = logger.write(envelope, decision)
        eid3 = logger.write(envelope, decision)

        unsynced = logger.get_unsynced()
        event_ids = [r["event_id"] for r in unsynced]
        # Should be in chronological order (oldest first)
        assert event_ids == [eid1, eid2, eid3]

    def test_mark_synced_empty_list_is_noop(self, tmp_path):
        from hiitl.sdk.audit import AuditLogger

        db_path = str(tmp_path / "test_audit.db")
        logger = AuditLogger(db_path)

        count = logger.mark_synced([])
        assert count == 0


# ── SyncConfig Tests ──────────────────────────────────────────────


class TestSyncConfig:
    """Test SyncConfig validation and defaults."""

    def test_default_values(self):
        config = SyncConfig()
        assert config.server_url == "https://api.hiitl.com"
        assert config.audit_sync_interval == 30
        assert config.policy_sync_interval == 300
        assert config.route_sync_interval == 300
        assert config.kill_switch_poll_interval == 30
        assert config.audit_batch_size == 100
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_reset == 60.0

    def test_custom_values(self):
        config = SyncConfig(
            server_url="https://custom.hiitl.com",
            audit_sync_interval=10,
            circuit_breaker_threshold=3,
        )
        assert config.server_url == "https://custom.hiitl.com"
        assert config.audit_sync_interval == 10
        assert config.circuit_breaker_threshold == 3

    def test_cache_dir_default(self):
        config = SyncConfig()
        assert config.cache_dir == "~/.hiitl/cache/"


# ── SyncError Tests ───────────────────────────────────────────────


class TestSyncError:
    """Test SyncError exception structure."""

    def test_sync_error_has_channel(self):
        err = SyncError("audit", "Upload failed")
        assert err.channel == "audit"
        assert "audit" in str(err)
        assert "Upload failed" in str(err)

    def test_sync_error_with_cause(self):
        cause = ConnectionError("refused")
        err = SyncError("policy", "Download failed", cause=cause)
        assert err.cause is cause

    def test_sync_error_inherits_from_hiitl_error(self):
        from hiitl.sdk.exceptions import HIITLError
        err = SyncError("test", "test message")
        assert isinstance(err, HIITLError)
