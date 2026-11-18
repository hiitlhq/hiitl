"""Cold-start behavior + cache_status decision field tests (TICKET-116).

Covers:
- `cold_start_behavior` constructor parameter validation
- Behavior on initial-sync failure for each of the three modes:
    fail-closed / warn-and-observe / observe-silent
- `cache_status` field stamped on every Decision returned by hybrid SDK
- Warm-start path leaves cache_status='from_disk'
- Background sync flips cache_status to 'synced'
- Pure local mode leaves cache_status None

Approach: patch `SyncEngine` so we don't make real HTTP calls. `initial_sync`
return value controls the cold-start outcome.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hiitl import HIITL
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import ColdStartError, ConfigurationError


# ---------------------------------------------------------------------------
# cold_start_behavior validation
# ---------------------------------------------------------------------------


def test_invalid_cold_start_behavior_raises_config_error(tmp_path):
    with pytest.raises(ConfigurationError, match="cold_start_behavior"):
        HIITL(
            cold_start_behavior="bogus-value",
            agent_id="test",
            audit_db_path=str(tmp_path / "audit.db"),
        )


def test_cold_start_behavior_unused_in_local_mode(tmp_path):
    """Local mode (no api_key) doesn't use cold-start at all — param accepted."""
    h = HIITL(
        cold_start_behavior="fail-closed",  # would fail if applied — won't be
        agent_id="test",
        audit_db_path=str(tmp_path / "audit.db"),
    )
    # No crash, no api_key → pure local mode
    assert h._mode == "local"


# ---------------------------------------------------------------------------
# Cold start outcomes per behavior
# ---------------------------------------------------------------------------


def _patch_sync_engine(initial_sync_returns: bool):
    """Helper: returns a context manager patching SyncEngine.

    SyncEngine is imported inside `_init_hybrid` (lazy import), so we patch
    at its definition site rather than `hiitl.sdk.client.SyncEngine`.
    """
    mock_engine = MagicMock()
    mock_engine.initial_sync.return_value = initial_sync_returns
    mock_engine.start = MagicMock()
    mock_engine.stop = MagicMock()
    return patch(
        "hiitl.sdk.sync_engine.SyncEngine",
        return_value=mock_engine,
    )


def test_cold_start_fail_closed_raises_when_sync_fails(tmp_path):
    """fail-closed: cold-start sync fails → ColdStartError from constructor."""
    config = SyncConfig(sync_init_timeout=7.0)
    with _patch_sync_engine(initial_sync_returns=False):
        with pytest.raises(ColdStartError) as exc_info:
            HIITL(
                api_key="sk_test_abc",
                cold_start_behavior="fail-closed",
                sync_config=config,
                audit_db_path=str(tmp_path / "audit.db"),
                cache_dir=str(tmp_path / "cache_nonexistent"),
            )
        # Error message references the timeout + server URL for debugging
        assert exc_info.value.timeout_seconds == config.sync_init_timeout
        assert "fail-closed" in str(exc_info.value)


def test_cold_start_warn_and_observe_continues_on_sync_failure(tmp_path, caplog):
    """warn-and-observe (default): sync fails → constructor succeeds, WARNING logged."""
    import logging
    caplog.set_level(logging.WARNING, logger="hiitl.sdk.client")
    with _patch_sync_engine(initial_sync_returns=False):
        h = HIITL(
            api_key="sk_test_abc",
            cold_start_behavior="warn-and-observe",
            audit_db_path=str(tmp_path / "audit.db"),
            cache_dir=str(tmp_path / "cache_nonexistent"),
        )
    assert h._mode == "hybrid"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("OBSERVE_ALL" in r.message for r in warning_records), (
        "Expected a WARNING mentioning OBSERVE_ALL fallback"
    )


def test_cold_start_observe_silent_logs_info_only(tmp_path, caplog):
    """observe-silent: sync fails → INFO log, no WARNING."""
    import logging
    caplog.set_level(logging.INFO, logger="hiitl.sdk.client")
    with _patch_sync_engine(initial_sync_returns=False):
        HIITL(
            api_key="sk_test_abc",
            cold_start_behavior="observe-silent",
            audit_db_path=str(tmp_path / "audit.db"),
            cache_dir=str(tmp_path / "cache_nonexistent"),
        )
    # Warn-and-observe message text should appear at INFO level, not WARNING
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("OBSERVE_ALL" in r.message for r in warnings), (
        "observe-silent should not WARN — found a warning record"
    )


def test_cold_start_warn_and_observe_is_the_default(tmp_path):
    """Constructor with no cold_start_behavior arg uses 'warn-and-observe'."""
    h = HIITL(audit_db_path=str(tmp_path / "audit.db"))  # local mode is fine
    assert h._cold_start_behavior == "warn-and-observe"


# ---------------------------------------------------------------------------
# cache_status on Decision
# ---------------------------------------------------------------------------


def test_local_mode_decision_has_no_cache_status(tmp_path):
    """Pure local mode: Decision.cache_status is None (not applicable)."""
    h = HIITL(audit_db_path=str(tmp_path / "audit.db"))
    decision = h.evaluate("test_action")
    assert decision.cache_status is None


def test_hybrid_cold_start_decision_has_empty_cache_status(tmp_path):
    """Cold start with sync failure (warn-and-observe): cache_status='empty'."""
    with _patch_sync_engine(initial_sync_returns=False):
        h = HIITL(
            api_key="sk_test_abc",
            audit_db_path=str(tmp_path / "audit.db"),
            cache_dir=str(tmp_path / "cache_nonexistent"),
        )
    decision = h.evaluate("test_action")
    assert decision.cache_status == "empty"


def test_hybrid_synced_after_update_policies_flips_cache_status(tmp_path):
    """When SyncCache.update_policies is called, subsequent decisions report 'synced'."""
    with _patch_sync_engine(initial_sync_returns=False):
        h = HIITL(
            api_key="sk_test_abc",
            audit_db_path=str(tmp_path / "audit.db"),
            cache_dir=str(tmp_path / "cache_synced"),
        )
    # Pre-sync: empty
    pre_decision = h.evaluate("test_action")
    assert pre_decision.cache_status == "empty"
    # Simulate a successful background sync writing policies into the cache
    h._sync_cache.update_policies({"policies": []}, etag="e1")
    post_decision = h.evaluate("test_action")
    assert post_decision.cache_status == "synced"


def test_hybrid_warm_start_decision_has_from_disk_cache_status(tmp_path, monkeypatch):
    """Warm start (load_from_disk returns True) → cache_status='from_disk'."""
    # Force SyncCache.load_from_disk to return True without writing a real file.
    from hiitl.sdk.sync_cache import SyncCache

    real_init = SyncCache.__init__

    def patched_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        # Pretend disk had policies — populate in-memory state without
        # touching _synced_this_process.
        self._policies = {"policies": []}

    monkeypatch.setattr(SyncCache, "__init__", patched_init)
    # And short-circuit load_from_disk to advertise the warm cache
    monkeypatch.setattr(SyncCache, "load_from_disk", lambda self: True)

    with _patch_sync_engine(initial_sync_returns=True):
        h = HIITL(
            api_key="sk_test_abc",
            audit_db_path=str(tmp_path / "audit.db"),
            cache_dir=str(tmp_path / "cache_warm"),
        )
    decision = h.evaluate("test_action")
    assert decision.cache_status == "from_disk"
