"""Telemetry collector — SDK-side behavioral aggregation.

Collects pre-aggregated statistics from evaluations and buffers them
for shipping to the hosted service via the sync engine's telemetry channel.

Privacy is enforced structurally at the aggregation layer:
- record() extracts incremental updates only (counter++, min/max, set.add(hash))
- Raw parameter values, target identifiers, and user IDs are never stored
- The collector never retains references to Envelope or Decision objects

Key properties:
- Thread-safe: Lock for record() and flush(), lock-free reads for status()
- Microsecond overhead per evaluation (dict lookups + counter increments)
- Configurable redaction levels (full/standard/minimal/off)
- Best-effort buffering (telemetry loss acceptable, unlike audit)
"""

import hashlib
import json
import logging
import random
import statistics
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SDK_VERSION = "0.1.0"
_SDK_LANGUAGE = "python"
_TELEMETRY_VERSION = "1.0"
_MAX_PARAMS_PER_TOOL = 20


class _NumericStat:
    """Running numeric statistics (O(1) memory per parameter)."""

    __slots__ = ("min", "max", "sum", "count")

    def __init__(self) -> None:
        self.min = float("inf")
        self.max = float("-inf")
        self.sum = 0.0
        self.count = 0

    def update(self, value: float) -> None:
        if value < self.min:
            self.min = value
        if value > self.max:
            self.max = value
        self.sum += value
        self.count += 1

    def to_dict(self) -> dict:
        return {
            "min": round(self.min, 3),
            "max": round(self.max, 3),
            "mean": round(self.sum / self.count, 3) if self.count else 0.0,
            "count": self.count,
        }


class _CategoricalStat:
    """Categorical parameter statistics (distinct count + optional top values)."""

    __slots__ = ("values", "freq")

    def __init__(self) -> None:
        self.values: set[str] = set()
        self.freq: Counter = Counter()

    def update(self, value: str) -> None:
        self.values.add(value)
        self.freq[value] += 1

    @property
    def distinct_count(self) -> int:
        return len(self.values)

    def top_values(self, n: int = 10) -> list[dict]:
        return [
            {"value": v, "count": c}
            for v, c in self.freq.most_common(n)
        ]


class _ToolStats:
    """Per-action aggregation state for one window."""

    __slots__ = (
        "action_count", "decision_counts", "latency_values",
        "operation_counts", "numeric_params", "categorical_params",
        "target_hashes", "error_count", "reason_code_counts",
        "_param_count",
    )

    def __init__(self) -> None:
        self.action_count = 0
        self.decision_counts: Counter = Counter()
        self.latency_values: list[float] = []
        self.operation_counts: Counter = Counter()
        self.numeric_params: dict[str, _NumericStat] = {}
        self.categorical_params: dict[str, _CategoricalStat] = {}
        self.target_hashes: set[int] = set()
        self.error_count = 0
        self.reason_code_counts: Counter = Counter()
        self._param_count = 0


class _AgentStats:
    """Per-agent aggregation state for one window."""

    __slots__ = (
        "action_count", "tools_used", "decision_counts", "user_id_hashes",
    )

    def __init__(self) -> None:
        self.action_count = 0
        self.tools_used: set[str] = set()
        self.decision_counts: Counter = Counter()
        self.user_id_hashes: set[int] = set()


class TelemetryCollector:
    """SDK-side telemetry aggregator.

    Collects behavioral statistics from evaluations and produces
    pre-aggregated telemetry records for shipping via the sync engine.

    Args:
        org_id: Organization ID for telemetry records
        environment: Environment (dev/stage/prod)
        level: Redaction level (full/standard/minimal/off)
        buffer_size: Max buffered telemetry records (default: 60)
        sample_rate: Fraction of evaluations to sample for detailed stats (default: 1.0)
    """

    def __init__(
        self,
        org_id: str,
        environment: str,
        level: str = "standard",
        buffer_size: int = 60,
        sample_rate: float = 1.0,
    ):
        self._org_id = org_id
        self._environment = environment
        self._level = level
        self._buffer_size = buffer_size
        self._sample_rate = sample_rate
        self._lock = threading.Lock()

        # Per-window state
        self._tool_stats: dict[str, _ToolStats] = {}
        self._agent_stats: dict[str, _AgentStats] = {}
        self._window_start = datetime.now(timezone.utc)
        self._window_eval_count = 0

        # Cumulative state (survives flush)
        self._total_evaluations = 0
        self._start_time = time.monotonic()
        self._error_counts: Counter = Counter()

        # Buffer
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._buffer_overflow_warned = False

    def record(self, envelope: Any, decision: Any) -> None:
        """Record an evaluation for telemetry aggregation.

        Extracts incremental updates from envelope and decision.
        Never stores raw parameter values, target IDs, or user IDs.
        Never raises — telemetry errors are swallowed with a warning.

        Args:
            envelope: Evaluated Envelope object
            decision: Resulting Decision object
        """
        if self._level == "off":
            return

        try:
            self._record_inner(envelope, decision)
        except Exception as e:
            logger.debug("Telemetry record failed (non-critical): %s", e)
            self._error_counts["telemetry_errors"] += 1

    def _record_inner(self, envelope: Any, decision: Any) -> None:
        """Internal record implementation (called under try/except)."""
        # Extract values before acquiring lock (minimize lock hold time)
        action = str(getattr(envelope, "action", "unknown"))
        operation = str(getattr(envelope, "operation", "execute"))
        agent_id = getattr(envelope, "agent_id", None)
        user_id = getattr(envelope, "user_id", None)
        decision_type = str(getattr(decision, "decision", "UNKNOWN"))
        reason_codes = getattr(decision, "reason_codes", []) or []
        has_error = getattr(decision, "error", None) is not None

        # Timing
        timing = getattr(decision, "timing", None)
        evaluation_ms = getattr(timing, "evaluation_ms", None) if timing else None

        # Determine if we sample detailed stats for this evaluation
        sample_details = self._sample_rate >= 1.0 or random.random() < self._sample_rate

        # Extract parameter stats (only top-level, only if sampling)
        param_updates: list[tuple[str, str, Any]] = []
        if sample_details:
            parameters = getattr(envelope, "parameters", None) or {}
            for key, value in parameters.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    param_updates.append((key, "numeric", float(value)))
                elif isinstance(value, str):
                    param_updates.append((key, "categorical", value))
                elif isinstance(value, bool):
                    param_updates.append((key, "categorical", str(value)))

        # Target hash (never store raw target)
        target_hash: int | None = None
        if sample_details:
            target = getattr(envelope, "target", None)
            if target:
                target_hash = hash(json.dumps(target, sort_keys=True))

        # User ID hash (never store raw user ID)
        user_id_hash: int | None = None
        if user_id:
            user_id_hash = hash(user_id)

        # --- Acquire lock, update state ---
        with self._lock:
            self._window_eval_count += 1
            self._total_evaluations += 1

            # Tool stats (always record counts; sample details)
            ts = self._tool_stats.get(action)
            if ts is None:
                ts = _ToolStats()
                self._tool_stats[action] = ts

            ts.action_count += 1
            ts.decision_counts[decision_type] += 1

            if has_error:
                ts.error_count += 1
                self._error_counts["evaluation_errors"] += 1

            for code in reason_codes:
                ts.reason_code_counts[code] += 1

            if sample_details:
                if evaluation_ms is not None:
                    ts.latency_values.append(evaluation_ms)

                ts.operation_counts[operation] += 1

                if target_hash is not None:
                    ts.target_hashes.add(target_hash)

                for key, ptype, value in param_updates:
                    if ptype == "numeric":
                        ns = ts.numeric_params.get(key)
                        if ns is None:
                            if ts._param_count >= _MAX_PARAMS_PER_TOOL:
                                continue
                            ns = _NumericStat()
                            ts.numeric_params[key] = ns
                            ts._param_count += 1
                        ns.update(value)
                    elif ptype == "categorical":
                        cs = ts.categorical_params.get(key)
                        if cs is None:
                            if ts._param_count >= _MAX_PARAMS_PER_TOOL:
                                continue
                            cs = _CategoricalStat()
                            ts.categorical_params[key] = cs
                            ts._param_count += 1
                        cs.update(value)

            # Agent stats
            if agent_id:
                ag = self._agent_stats.get(agent_id)
                if ag is None:
                    ag = _AgentStats()
                    self._agent_stats[agent_id] = ag

                ag.action_count += 1
                ag.tools_used.add(action)
                ag.decision_counts[decision_type] += 1

                if user_id_hash is not None:
                    ag.user_id_hashes.add(user_id_hash)

    def flush(self) -> dict | None:
        """Finalize current window and produce a telemetry record.

        Applies redaction level, resets window state, and adds the
        record to the internal buffer.

        Returns:
            Telemetry record dict, or None if level is "off"
        """
        if self._level == "off":
            return None

        with self._lock:
            window_end = datetime.now(timezone.utc)
            record = self._build_record(self._window_start, window_end)

            # Reset window
            self._tool_stats = {}
            self._agent_stats = {}
            self._window_start = window_end
            self._window_eval_count = 0

        # Add to buffer (outside lock)
        prev_len = len(self._buffer)
        self._buffer.append(record)
        if len(self._buffer) == prev_len and prev_len == self._buffer_size:
            if not self._buffer_overflow_warned:
                logger.warning(
                    "TELEMETRY_BUFFER_FULL: Telemetry buffer is full (%d records). "
                    "Oldest records are being dropped. Sync may be failing.",
                    self._buffer_size,
                )
                self._buffer_overflow_warned = True

        return record

    def get_pending(self) -> list[dict]:
        """Return buffered telemetry records for sync engine upload."""
        return list(self._buffer)

    def mark_sent(self, count: int) -> None:
        """Remove sent records from the front of the buffer."""
        for _ in range(min(count, len(self._buffer))):
            self._buffer.popleft()
        if not self._buffer:
            self._buffer_overflow_warned = False

    def status(self) -> dict:
        """Return telemetry collector status for health reporting."""
        return {
            "level": self._level,
            "buffer_depth": len(self._buffer),
            "buffer_capacity": self._buffer_size,
            "window_eval_count": self._window_eval_count,
            "total_evaluations": self._total_evaluations,
            "sample_rate": self._sample_rate,
        }

    # ── Record building ──────────────────────────────────────────

    def _build_record(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> dict:
        """Build a telemetry record dict from current window state.

        Must be called with lock held. Applies redaction level.
        """
        level = self._level
        is_minimal = level == "minimal"
        is_full = level == "full"

        record: dict[str, Any] = {
            "telemetry_version": _TELEMETRY_VERSION,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "org_id": self._org_id,
            "environment": self._environment,
            "sdk_version": _SDK_VERSION,
            "sdk_language": _SDK_LANGUAGE,
            "tool_summaries": self._build_tool_summaries(is_minimal, is_full),
        }

        if not is_minimal:
            agent_summaries = self._build_agent_summaries(is_full)
            if agent_summaries:
                record["agent_summaries"] = agent_summaries

        record["system_metrics"] = self._build_system_metrics()

        return record

    def _build_tool_summaries(self, is_minimal: bool, is_full: bool) -> list[dict]:
        """Build tool_summaries array with redaction applied."""
        summaries = []

        for action, ts in self._tool_stats.items():
            summary: dict[str, Any] = {
                "action": action,
                "action_count": ts.action_count,
                "decision_counts": dict(ts.decision_counts),
                "error_count": ts.error_count,
            }

            if not is_minimal:
                # Latency stats
                if ts.latency_values:
                    sorted_latencies = sorted(ts.latency_values)
                    n = len(sorted_latencies)
                    summary["latency"] = {
                        "p50": round(sorted_latencies[int(n * 0.50)], 3),
                        "p95": round(sorted_latencies[min(int(n * 0.95), n - 1)], 3),
                        "p99": round(sorted_latencies[min(int(n * 0.99), n - 1)], 3),
                        "min": round(sorted_latencies[0], 3),
                        "max": round(sorted_latencies[-1], 3),
                        "mean": round(statistics.mean(sorted_latencies), 3),
                    }

                # Operation counts
                if ts.operation_counts:
                    summary["operations"] = dict(ts.operation_counts)

                # Parameter stats (exclude params seen < 3 times)
                param_stats = []
                for key, ns in ts.numeric_params.items():
                    if ns.count >= 3:
                        param_stats.append({
                            "parameter_path": key,
                            "stat_type": "numeric",
                            "numeric_stats": ns.to_dict(),
                        })
                for key, cs in ts.categorical_params.items():
                    if cs.distinct_count >= 3 or sum(cs.freq.values()) >= 3:
                        stat: dict[str, Any] = {
                            "parameter_path": key,
                            "stat_type": "categorical",
                            "categorical_stats": {
                                "distinct_count": cs.distinct_count,
                            },
                        }
                        if is_full:
                            stat["categorical_stats"]["top_values"] = cs.top_values(10)
                        param_stats.append(stat)

                if param_stats:
                    summary["parameter_stats"] = param_stats

                # Target cardinality (count only, never target content)
                summary["target_cardinality"] = len(ts.target_hashes)

                # Reason code counts
                if ts.reason_code_counts:
                    summary["reason_code_counts"] = dict(ts.reason_code_counts)

            summaries.append(summary)

        return summaries

    def _build_agent_summaries(self, is_full: bool) -> list[dict]:
        """Build agent_summaries array with redaction applied."""
        summaries = []

        for agent_id, ag in self._agent_stats.items():
            summary: dict[str, Any] = {
                "agent_id": agent_id,
                "action_count": ag.action_count,
                "tools_used": sorted(ag.tools_used),
                "decision_counts": dict(ag.decision_counts),
                "distinct_users": len(ag.user_id_hashes),
            }
            summaries.append(summary)

        return summaries

    def _build_system_metrics(self) -> dict:
        """Build system_metrics object."""
        return {
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "total_evaluations": self._total_evaluations,
            "error_counts": dict(self._error_counts),
        }
