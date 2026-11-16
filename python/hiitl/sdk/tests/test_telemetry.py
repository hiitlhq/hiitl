"""Tests for telemetry collector pipeline.

Covers: collection, aggregation, privacy boundaries, redaction levels,
buffering, record format, sampling, and sync integration.
"""

import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hiitl._version import __version__
from hiitl.sdk.telemetry import _MAX_PARAMS_PER_TOOL, TelemetryCollector


# ── Test helpers ───────────────────────────────────────────────

def _make_envelope(
    action="send_email",
    operation="execute",
    agent_id="test-agent",
    user_id=None,
    parameters=None,
    target=None,
):
    """Create a minimal envelope-like object for telemetry testing."""
    return SimpleNamespace(
        action=action,
        operation=operation,
        agent_id=agent_id,
        user_id=user_id,
        parameters=parameters or {},
        target=target or {},
    )


def _make_decision(
    decision="ALLOW",
    reason_codes=None,
    evaluation_ms=0.5,
    error=None,
):
    """Create a minimal decision-like object for telemetry testing."""
    timing = SimpleNamespace(evaluation_ms=evaluation_ms)
    return SimpleNamespace(
        decision=decision,
        reason_codes=reason_codes or ["default_allow"],
        timing=timing,
        error=error,
    )


def _make_collector(**kwargs):
    """Create a TelemetryCollector with test defaults."""
    defaults = {
        "org_id": "org_test1234567890ab",
        "environment": "dev",
        "level": "full",
        "buffer_size": 60,
        "sample_rate": 1.0,
        "parameter_tools": ("send_email",),   # the helper envelope's action; tracking is opt-in per tool (§6)
    }
    defaults.update(kwargs)
    return TelemetryCollector(**defaults)


# ============================================================================
# Collection tests
# ============================================================================


class TestTelemetryCollection:
    """Test basic telemetry collection and aggregation."""

    def test_single_action_recorded(self):
        """Single evaluation produces correct tool summary."""
        collector = _make_collector()
        collector.record(
            _make_envelope(action="process_payment"),
            _make_decision(decision="ALLOW", evaluation_ms=0.5),
        )
        record = collector.flush()

        assert record is not None
        assert len(record["tool_summaries"]) == 1

        ts = record["tool_summaries"][0]
        assert ts["action"] == "process_payment"
        assert ts["action_count"] == 1
        assert ts["decision_counts"]["ALLOW"] == 1
        assert ts["error_count"] == 0

    def test_multiple_actions_aggregate_separately(self):
        """Different actions produce separate tool summaries."""
        collector = _make_collector()
        collector.record(
            _make_envelope(action="send_email"),
            _make_decision(decision="ALLOW"),
        )
        collector.record(
            _make_envelope(action="process_payment"),
            _make_decision(decision="BLOCK"),
        )
        collector.record(
            _make_envelope(action="send_email"),
            _make_decision(decision="ALLOW"),
        )
        record = collector.flush()

        assert len(record["tool_summaries"]) == 2
        by_action = {ts["action"]: ts for ts in record["tool_summaries"]}

        assert by_action["send_email"]["action_count"] == 2
        assert by_action["send_email"]["decision_counts"]["ALLOW"] == 2
        assert by_action["process_payment"]["action_count"] == 1
        assert by_action["process_payment"]["decision_counts"]["BLOCK"] == 1

    def test_agent_aggregation(self):
        """Per-agent aggregation tracks tools used and decision distribution."""
        collector = _make_collector()
        collector.record(
            _make_envelope(agent_id="agent-a", action="send_email"),
            _make_decision(decision="ALLOW"),
        )
        collector.record(
            _make_envelope(agent_id="agent-a", action="process_payment"),
            _make_decision(decision="BLOCK"),
        )
        collector.record(
            _make_envelope(agent_id="agent-b", action="send_email"),
            _make_decision(decision="ALLOW"),
        )
        record = collector.flush()

        assert "agent_summaries" in record
        by_agent = {ag["agent_id"]: ag for ag in record["agent_summaries"]}

        assert by_agent["agent-a"]["action_count"] == 2
        assert set(by_agent["agent-a"]["tools_used"]) == {"send_email", "process_payment"}
        assert by_agent["agent-b"]["action_count"] == 1

    @pytest.mark.parametrize("latencies,expected", [
        ([0.1, 0.2, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0],
         {"p50": 1.25, "p95": 4.55, "p99": 4.91, "min": 0.1, "max": 5.0, "mean": 1.76}),
        ([9.0, 1.0, 4.0],
         {"p50": 4.0, "p95": 8.5, "p99": 8.9, "min": 1.0, "max": 9.0, "mean": 4.667}),
        ([2.3456],
         {"p50": 2.346, "p95": 2.346, "p99": 2.346, "min": 2.346, "max": 2.346, "mean": 2.346}),
        ([8.0, 2.0, 2.0, 8.0],
         {"p50": 5.0, "p95": 8.0, "p99": 8.0, "min": 2.0, "max": 8.0, "mean": 5.0}),
    ], ids=["even", "odd-unsorted", "singleton-rounded", "duplicates"])
    def test_latency_percentiles(self, latencies, expected):
        """Telemetry §6: interpolate at (n-1)*p, retaining duplicates, then round to three decimals."""
        collector = _make_collector()
        for lat in latencies:
            collector.record(
                _make_envelope(action="test_tool"),
                _make_decision(evaluation_ms=lat),
            )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        assert ts["latency"] == expected

    def test_system_metrics_present(self, monkeypatch):
        """System metrics include uptime and total evaluations."""
        clock = iter([100.0, 112.5])
        monkeypatch.setattr("hiitl.sdk.telemetry.time", SimpleNamespace(monotonic=lambda: next(clock)))
        collector = _make_collector()
        collector.record(
            _make_envelope(),
            _make_decision(),
        )
        record = collector.flush()

        assert "system_metrics" in record
        sm = record["system_metrics"]
        assert sm["total_evaluations"] == 1
        assert sm["uptime_seconds"] == 12.5

    def test_reason_code_counts(self):
        """Reason codes aggregated correctly."""
        collector = _make_collector()
        collector.record(
            _make_envelope(),
            _make_decision(reason_codes=["default_allow"]),
        )
        collector.record(
            _make_envelope(),
            _make_decision(reason_codes=["amount_threshold_exceeded"]),
        )
        collector.record(
            _make_envelope(),
            _make_decision(reason_codes=["default_allow"]),
        )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        assert ts["reason_code_counts"]["default_allow"] == 2
        assert ts["reason_code_counts"]["amount_threshold_exceeded"] == 1


# ============================================================================
# Parameter discovery tests
# ============================================================================


class TestParameterDiscovery:
    """Test automatic parameter discovery and aggregation."""

    def test_numeric_parameter_stats(self):
        """Numeric parameters produce a count, and at `full` a mean; never a min or max (row 142)."""
        collector = _make_collector()
        for amount in [10.0, 50.0, 100.0, 200.0]:
            collector.record(
                _make_envelope(parameters={"amount": amount}),
                _make_decision(),
            )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        param_stats = {p["parameter_path"]: p for p in ts["parameter_stats"]}
        assert "amount" in param_stats
        ns = param_stats["amount"]["numeric_stats"]
        assert ns == {"count": 4, "mean": 90.0}

    def test_categorical_parameter_stats(self):
        """Categorical parameters produce distinct_count."""
        collector = _make_collector()
        for currency in ["usd", "eur", "gbp", "usd", "usd"]:
            collector.record(
                _make_envelope(parameters={"currency": currency}),
                _make_decision(),
            )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        param_stats = {p["parameter_path"]: p for p in ts["parameter_stats"]}
        assert "currency" in param_stats
        cs = param_stats["currency"]["categorical_stats"]
        assert cs["distinct_count"] == 3

    def test_parameters_per_tool_stop_at_the_cap(self):
        """Only the first parameters up to the per-tool cap are tracked."""
        collector = _make_collector()
        # Record more distinct parameters than the cap, each 3+ times to pass noise filter
        names = [f"param_{i}" for i in range(_MAX_PARAMS_PER_TOOL + 5)]
        for i, name in enumerate(names):
            for _ in range(3):
                collector.record(
                    _make_envelope(parameters={name: i * 1.0}),
                    _make_decision(),
                )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        assert [p["parameter_path"] for p in ts["parameter_stats"]] == names[:_MAX_PARAMS_PER_TOOL]

    def test_params_seen_fewer_than_3_times_excluded(self):
        """Parameters seen < 3 times are excluded from output."""
        collector = _make_collector()
        # "amount" seen 4 times, "rare_param" seen 2 times
        for amount in (100.0, 120.0, 140.0, 160.0):
            collector.record(
                _make_envelope(parameters={"amount": amount}),
                _make_decision(),
            )
        for _ in range(2):
            collector.record(
                _make_envelope(parameters={"rare_param": 1.0}),
                _make_decision(),
            )
        record = collector.flush()

        ts = record["tool_summaries"][0]
        param_names = [p["parameter_path"] for p in ts.get("parameter_stats", [])]
        assert "amount" in param_names
        assert "rare_param" not in param_names


# ============================================================================
# Privacy boundary tests
# ============================================================================


class TestPrivacyBoundaries:
    """Test that privacy boundaries are structurally enforced."""

    def test_no_raw_parameter_values_at_standard_level(self):
        """At standard redaction, raw categorical values never appear."""
        collector = _make_collector(level="standard")
        for _ in range(5):
            collector.record(
                _make_envelope(parameters={
                    "amount": 42.50,
                    "currency": "usd",
                    "secret": "super_secret_value",
                }),
                _make_decision(),
            )
        record = collector.flush()
        record_str = json.dumps(record)

        # At standard level, top_values is excluded — raw categorical values must not appear
        assert "super_secret_value" not in record_str
        assert "usd" not in record_str

        # No numeric value either: no min, max or (at standard) mean — counts only (row 142)
        assert "42.5" not in record_str
        ts = record["tool_summaries"][0]
        cat_params = [p for p in ts.get("parameter_stats", []) if p["stat_type"] == "categorical"]
        assert {p["parameter_path"]: p["categorical_stats"] for p in cat_params} == {
            "currency": {"distinct_count": 1}, "secret": {"distinct_count": 1},
        }

    def test_target_cardinality_is_count_only(self):
        """Target cardinality is a count, never actual target content."""
        collector = _make_collector()
        collector.record(
            _make_envelope(target={"account_id": "acct_secret_123"}),
            _make_decision(),
        )
        collector.record(
            _make_envelope(target={"account_id": "acct_secret_456"}),
            _make_decision(),
        )
        record = collector.flush()
        record_str = json.dumps(record)

        ts = record["tool_summaries"][0]
        assert ts["target_cardinality"] == 2
        assert "acct_secret_123" not in record_str
        assert "acct_secret_456" not in record_str

    def test_distinct_users_is_count_only(self):
        """distinct_users is a count, never user IDs."""
        collector = _make_collector()
        collector.record(
            _make_envelope(user_id="user_alice@example.com"),
            _make_decision(),
        )
        collector.record(
            _make_envelope(user_id="user_bob@example.com"),
            _make_decision(),
        )
        collector.record(
            _make_envelope(user_id="user_alice@example.com"),
            _make_decision(),
        )
        record = collector.flush()
        record_str = json.dumps(record)

        ag = record["agent_summaries"][0]
        assert ag["distinct_users"] == 2
        assert "alice" not in record_str
        assert "bob" not in record_str

    def test_envelope_decision_not_retained(self):
        """Collector does not retain references to envelope or decision objects."""
        collector = _make_collector()
        envelope = _make_envelope()
        decision = _make_decision()

        collector.record(envelope, decision)

        # The collector's internal state should not hold the original objects
        for ts in collector._tool_stats.values():
            # Only primitive types in the stats
            assert not hasattr(ts, 'envelope')
            assert not hasattr(ts, 'decision')


# ============================================================================
# Redaction level tests
# ============================================================================


class TestRedactionLevels:
    """Test telemetry redaction at different levels."""

    def _record_data(self, collector):
        """Record enough data to populate all fields."""
        for i in range(5):
            collector.record(
                _make_envelope(
                    parameters={"amount": float(i * 10), "currency": "usd"},
                    target={"id": f"target_{i}"},
                    user_id=f"user_{i}",
                ),
                _make_decision(
                    decision="ALLOW" if i < 4 else "BLOCK",
                    reason_codes=["default_allow"] if i < 4 else ["blocked"],
                ),
            )

    def test_minimal_redaction(self):
        """Minimal level: only action, counts, decisions, errors, system metrics."""
        collector = _make_collector(level="minimal")
        self._record_data(collector)
        record = collector.flush()

        ts = record["tool_summaries"][0]
        assert "action" in ts
        assert "action_count" in ts
        assert "decision_counts" in ts
        assert "error_count" in ts

        # These should NOT be present at minimal
        assert "latency" not in ts
        assert "operations" not in ts
        assert "parameter_stats" not in ts
        assert "target_cardinality" not in ts
        assert "reason_code_counts" not in ts

        # Agent counts are sent at every level; distinct_users is Standard+ (§3.2)
        (agent,) = record["agent_summaries"]
        assert "distinct_users" not in agent
        assert agent["action_count"] == 5

        # System metrics always present
        assert "system_metrics" in record

    def test_standard_redaction(self):
        """Standard level: includes latency, params (no top_values), target_cardinality."""
        collector = _make_collector(level="standard")
        self._record_data(collector)
        record = collector.flush()

        ts = record["tool_summaries"][0]
        assert "latency" in ts
        assert "target_cardinality" in ts
        assert "reason_code_counts" in ts

        # Check parameter stats exclude top_values
        if "parameter_stats" in ts:
            for ps in ts["parameter_stats"]:
                if ps["stat_type"] == "categorical":
                    assert "top_values" not in ps["categorical_stats"]

    def test_full_redaction(self):
        """Full level: adds a numeric mean; no categorical value at any level (row 142)."""
        collector = _make_collector(level="full")
        self._record_data(collector)
        record = collector.flush()

        stats = {ps["parameter_path"]: ps for ps in record["tool_summaries"][0]["parameter_stats"]}
        assert stats["amount"]["numeric_stats"] == {"count": 5, "mean": 20.0}
        assert stats["currency"]["categorical_stats"] == {"distinct_count": 1}
        assert "usd" not in json.dumps(record)

    def test_off_level(self):
        """Off level: record() is no-op, flush() returns None."""
        collector = _make_collector(level="off")
        collector.record(
            _make_envelope(),
            _make_decision(),
        )
        record = collector.flush()

        assert record is None
        assert collector._total_evaluations == 0


# ============================================================================
# Buffer tests
# ============================================================================


class TestTelemetryBuffer:
    """Test telemetry record buffering."""

    def test_records_accumulate_in_buffer(self):
        """flush() adds records to buffer."""
        collector = _make_collector()
        collector.record(_make_envelope(), _make_decision())
        collector.flush()
        collector.record(_make_envelope(), _make_decision())
        collector.flush()

        pending = collector.get_pending()
        assert len(pending) == 2

    def test_buffer_overflow_drops_oldest(self):
        """Buffer overflow drops oldest records."""
        collector = _make_collector(buffer_size=3)
        for i in range(5):
            collector.record(_make_envelope(), _make_decision())
            collector.flush()

        pending = collector.get_pending()
        assert len(pending) == 3  # only last 3 kept

    def test_get_pending_returns_copy(self):
        """get_pending() returns a list copy."""
        collector = _make_collector()
        collector.record(_make_envelope(), _make_decision())
        collector.flush()

        pending1 = collector.get_pending()
        pending2 = collector.get_pending()
        assert pending1 == pending2
        assert pending1 is not pending2

    def test_mark_sent_removes_from_front(self):
        """mark_sent() removes sent records from front of buffer."""
        collector = _make_collector()
        for _ in range(3):
            collector.record(_make_envelope(), _make_decision())
            collector.flush()

        collector.mark_sent(2)
        pending = collector.get_pending()
        assert len(pending) == 1

    def test_buffer_overflow_warning(self, caplog):
        """TELEMETRY_BUFFER_FULL warning logged on first overflow."""
        collector = _make_collector(buffer_size=2)
        for _ in range(3):
            collector.record(_make_envelope(), _make_decision())
            with caplog.at_level(logging.WARNING):
                collector.flush()

        assert "TELEMETRY_BUFFER_FULL" in caplog.text


# ============================================================================
# Integration / format tests
# ============================================================================


class TestTelemetryRecordFormat:
    """Test that telemetry records match the spec schema."""

    def test_required_fields_present(self):
        """Telemetry record has all required fields per telemetry_schema.md §2."""
        collector = _make_collector()
        collector.record(_make_envelope(), _make_decision())
        record = collector.flush()

        required_fields = [
            "telemetry_version", "window_start", "window_end",
            "org_id", "environment", "sdk_version", "sdk_language",
            "tool_summaries",
        ]
        for field in required_fields:
            assert field in record, f"Missing required field: {field}"

        assert record["telemetry_version"] == "2.0"
        assert record["sdk_language"] == "python"
        assert record["sdk_version"] == __version__

    def test_empty_window_produces_valid_record(self):
        """Empty window (no evaluations) produces valid record."""
        collector = _make_collector()
        record = collector.flush()

        assert record is not None
        assert record["tool_summaries"] == []
        assert record["system_metrics"]["total_evaluations"] == 0

    def test_window_reset_after_flush(self):
        """After flush(), new evaluations go into fresh window."""
        collector = _make_collector()
        collector.record(_make_envelope(action="action_a"), _make_decision())
        record1 = collector.flush()

        collector.record(_make_envelope(action="action_b"), _make_decision())
        record2 = collector.flush()

        actions1 = {ts["action"] for ts in record1["tool_summaries"]}
        actions2 = {ts["action"] for ts in record2["tool_summaries"]}

        assert actions1 == {"action_a"}
        assert actions2 == {"action_b"}

    def test_sampling_records_all_counts(self):
        """With sample_rate=0.5, action counts are always accurate."""
        collector = _make_collector(sample_rate=0.5)
        for _ in range(100):
            collector.record(_make_envelope(), _make_decision())
        record = collector.flush()

        ts = record["tool_summaries"][0]
        # Counts are always recorded regardless of sampling
        assert ts["action_count"] == 100
        assert ts["decision_counts"]["ALLOW"] == 100

    def test_status_method(self):
        """status() returns correct buffer and evaluation info."""
        collector = _make_collector()
        collector.record(_make_envelope(), _make_decision())
        collector.flush()

        status = collector.status()
        assert status["level"] == "full"
        assert status["buffer_depth"] == 1
        assert status["buffer_capacity"] == 60
        assert status["total_evaluations"] == 1
        assert status["sample_rate"] == 1.0


# ============================================================================
# Sync integration tests
# ============================================================================


class TestSyncIntegration:
    """Test integration with sync engine patterns."""

    def test_sync_engine_with_collector(self):
        """SyncEngine accepts telemetry_collector parameter."""
        from hiitl.sdk.config import SyncConfig

        config = SyncConfig()
        collector = _make_collector()

        # Verify SyncEngine constructor accepts telemetry_collector
        # (can't fully instantiate without mock deps, but can verify the param)
        from hiitl.sdk.sync_engine import SyncEngine
        import inspect
        sig = inspect.signature(SyncEngine.__init__)
        assert "telemetry_collector" in sig.parameters

    def test_sync_engine_without_collector(self):
        """SyncEngine works without telemetry collector (telemetry off)."""
        from hiitl.sdk.sync_engine import SyncEngine
        import inspect
        sig = inspect.signature(SyncEngine.__init__)
        param = sig.parameters["telemetry_collector"]
        assert param.default is None

    def test_config_validates_telemetry_level(self):
        """The client's settings reject invalid telemetry_level values (row 172: a top-level setting)."""
        from hiitl.sdk.config import ClientSettings

        with pytest.raises(Exception):
            ClientSettings(telemetry_level="invalid_level")

    def test_config_accepts_valid_telemetry_levels(self):
        """The client's settings accept all valid telemetry_level values."""
        from hiitl.sdk.config import ClientSettings

        for level in ("full", "standard", "minimal", "off"):
            config = ClientSettings(telemetry_level=level)
            assert config.telemetry_level == level

    def test_config_telemetry_defaults(self):
        """SyncConfig and the client's settings have correct telemetry defaults."""
        from hiitl.sdk.config import ClientSettings, SyncConfig

        config = SyncConfig()
        assert config.telemetry_sync_interval == 60
        assert ClientSettings().telemetry_level == "standard"
        assert config.telemetry_buffer_size == 60
        assert config.telemetry_sample_rate == 1.0
