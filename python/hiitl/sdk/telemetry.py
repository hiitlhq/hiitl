"""Telemetry collector — SDK-side behavioral aggregation.

Collects pre-aggregated statistics from evaluations and buffers them
for shipping to the hosted service via the sync engine's telemetry channel.

Privacy is enforced structurally at the aggregation layer (telemetry_schema.md §4,
ruled 2026-11-04: no raw value leaves in telemetry at any level; the default sends
counts only):
- record() extracts incremental updates only (counter++, set.add(digest), and at
  `full` a running sum)
- Raw parameter values, target identifiers, and user IDs are never stored: no
  minimum, maximum or frequency table of values is kept
- Parameters are tracked only for the actions named in `parameter_tools` (opt-in
  per tool, §6)
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
from typing import Any, Callable, Iterable, Optional

from hiitl._version import __version__ as _SDK_VERSION
from hiitl.core.redaction import Redaction
from hiitl.core.statistics import percentile

logger = logging.getLogger(__name__)

_SDK_LANGUAGE = "python"
_TELEMETRY_VERSION = "2.0"
_MAX_PARAMS_PER_TOOL = 20


class _NumericStat:
    """A numeric parameter's sightings (O(1) memory per parameter).

    Holds no observed value: no minimum or maximum (each is one value). At `full`
    it keeps a running sum and whether the values differ (by digest of the first),
    so the mean it sends is never a mean of one value, which is that value.
    A value the store does not record as given contributes its count, and the
    stat holds no sum or digest from then on in its window (row 216).
    """

    __slots__ = ("count", "sum", "first_digest", "varied")

    def __init__(self, keep_mean: bool) -> None:
        self.count = 0
        self.sum: Optional[float] = 0.0 if keep_mean else None
        self.first_digest: Optional[int] = None
        self.varied = False

    def update(self, value: Optional[float], as_given: bool = True) -> None:
        self.count += 1
        if not as_given:
            self.sum, self.first_digest, self.varied = None, None, False
            return
        if self.sum is None or value is None:
            return
        self.sum += value
        digest = hash(("numeric", value))
        if self.first_digest is None:
            self.first_digest = digest
        elif digest != self.first_digest:
            self.varied = True

    def to_dict(self, as_given: bool = True) -> dict:
        out: dict[str, Any] = {"count": self.count}
        if as_given and self.sum is not None and self.varied:
            out["mean"] = round(self.sum / self.count, 3)
        return out


class _CategoricalStat:
    """A categorical parameter's sightings: a count and the digests of its values (never a value)."""

    __slots__ = ("digests", "count")

    def __init__(self) -> None:
        self.digests: set[int] = set()
        self.count = 0

    def update(self, digest: int) -> None:
        self.digests.add(digest)
        self.count += 1

    @property
    def distinct_count(self) -> int:
        return len(self.digests)


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


from hiitl.sdk.admission import admit_configuration
from hiitl.core.numeric_domain import validate_numeric_domain, admitted_numbers
from hiitl.core.types import Envelope, Decision
from hiitl.core.input_types import model_shape
from hiitl.core.input_declarations import policy_shape
from hiitl.sdk.numeric_declarations import SHAPES as NUMERIC_DECLARATIONS


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
        parameter_tools: Actions whose parameters are tracked (default: none;
            telemetry_schema.md §6, "opt-in per tool")
        declaration: The store's declaration as the store applies it, the org's
            included (AuditLogger.declaration). It is read where a parameter is
            recorded and where its stats leave, and a parameter the store does not
            record as given sends its count and no mean (row 216)
    """

    def __init__(
        self,
        org_id: str,
        environment: str,
        level: str = "standard",
        buffer_size: int = 60,
        sample_rate: float = 1.0,
        parameter_tools: Iterable[str] = (),
        declaration: Optional[Callable[[], Redaction]] = None,
    ):
        admit_configuration(type(self).__init__, {"buffer_size": buffer_size, "sample_rate": sample_rate})
        self._org_id = org_id
        self._environment = environment
        self._level = level
        self._parameter_tools = frozenset(parameter_tools)
        self._declaration = declaration
        self._keep_mean = level == "full"     # a numeric sum is held, and its mean sent, only at `full`
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

    def _record_admitted(self, envelope, decision):
        """Consume the SDK's own evaluation without treating its output as input."""
        with admitted_numbers():
            return self.record(envelope, decision)

    def record(self, envelope: Any, decision: Any) -> None:
        """Record an evaluation for telemetry aggregation.

        Extracts incremental updates from envelope and decision.
        Never stores raw parameter values, target IDs, or user IDs.
        Numeric admission refusals are raised before aggregation; unrelated telemetry errors are swallowed with a warning.

        Args:
            envelope: Evaluated Envelope object
            decision: Resulting Decision object
        """
        validate_numeric_domain(envelope, ('envelope',), shape=model_shape(Envelope))
        validate_numeric_domain(decision, ('decision',), shape=policy_shape(Decision, Envelope))
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

        # Parameter sightings: top-level only, only for a tracked action, only if
        # sampling. A categorical value is reduced to its digest here; a number is
        # kept only at `full`, for the running sum.
        param_updates: list[tuple[str, str, Any, bool]] = []
        if sample_details and action in self._parameter_tools:
            parameters = getattr(envelope, "parameters", None) or {}
            as_given = self._as_given(action)
            for key, value in parameters.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    given = as_given(key)
                    param_updates.append((key, "numeric", float(value) if self._keep_mean and given else None, given))
                elif isinstance(value, (str, bool)):
                    param_updates.append((key, "categorical", hash(("categorical", value)), True))

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

                for key, ptype, value, given in param_updates:
                    if ptype == "numeric":
                        ns = ts.numeric_params.get(key)
                        if ns is None:
                            if ts._param_count >= _MAX_PARAMS_PER_TOOL:
                                continue
                            ns = _NumericStat(keep_mean=self._keep_mean)
                            ts.numeric_params[key] = ns
                            ts._param_count += 1
                        ns.update(value, given)
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

    def _as_given(self, action: str) -> Callable[[str], bool]:
        """Whether the store records an action's parameter as given, by its declaration as it applies it now."""
        if self._declaration is None:
            return lambda key: True
        declaration = self._declaration()
        return lambda key: declaration.records_as_given(f"parameters.{key}", action)

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
            validate_numeric_domain(record, shape=NUMERIC_DECLARATIONS['telemetry'])

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
        is_minimal = self._level == "minimal"

        record: dict[str, Any] = {
            "telemetry_version": _TELEMETRY_VERSION,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "org_id": self._org_id,
            "environment": self._environment,
            "sdk_version": _SDK_VERSION,
            "sdk_language": _SDK_LANGUAGE,
            "tool_summaries": self._build_tool_summaries(is_minimal),
        }

        agent_summaries = self._build_agent_summaries(is_minimal)
        if agent_summaries:
            record["agent_summaries"] = agent_summaries

        record["system_metrics"] = self._build_system_metrics()

        return record

    def _build_tool_summaries(self, is_minimal: bool) -> list[dict]:
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
                    summary["latency"] = {
                        "p50": round(percentile(sorted_latencies, 0.50), 3),
                        "p95": round(percentile(sorted_latencies, 0.95), 3),
                        "p99": round(percentile(sorted_latencies, 0.99), 3),
                        "min": round(sorted_latencies[0], 3),
                        "max": round(sorted_latencies[-1], 3),
                        "mean": round(statistics.mean(sorted_latencies), 3),
                    }

                # Operation counts
                if ts.operation_counts:
                    summary["operations"] = dict(ts.operation_counts)

                # Parameter stats (exclude params seen < 3 times)
                param_stats = []
                as_given = self._as_given(action)
                for key, ns in ts.numeric_params.items():
                    if ns.count >= 3:
                        param_stats.append({
                            "parameter_path": key,
                            "stat_type": "numeric",
                            "numeric_stats": ns.to_dict(as_given(key)),
                        })
                for key, cs in ts.categorical_params.items():
                    if cs.count >= 3:
                        param_stats.append({
                            "parameter_path": key,
                            "stat_type": "categorical",
                            "categorical_stats": {
                                "distinct_count": cs.distinct_count,
                            },
                        })

                if param_stats:
                    summary["parameter_stats"] = param_stats

                # Target cardinality (count only, never target content)
                summary["target_cardinality"] = len(ts.target_hashes)

                # Reason code counts
                if ts.reason_code_counts:
                    summary["reason_code_counts"] = dict(ts.reason_code_counts)

            summaries.append(summary)

        return summaries

    def _build_agent_summaries(self, is_minimal: bool) -> list[dict]:
        """Build agent_summaries array with redaction applied (§3.2: counts always, distinct_users Standard+)."""
        summaries = []

        for agent_id, ag in self._agent_stats.items():
            summary: dict[str, Any] = {
                "agent_id": agent_id,
                "action_count": ag.action_count,
                "tools_used": sorted(ag.tools_used),
                "decision_counts": dict(ag.decision_counts),
            }
            if not is_minimal:
                summary["distinct_users"] = len(ag.user_id_hashes)
            summaries.append(summary)

        return summaries

    def _build_system_metrics(self) -> dict:
        """Build system_metrics object: what the collector itself counts (§3.3)."""
        return {
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "total_evaluations": self._total_evaluations,
            "error_counts": {
                "evaluation_errors": self._error_counts["evaluation_errors"],
                "telemetry_errors": self._error_counts["telemetry_errors"],
            },
        }
