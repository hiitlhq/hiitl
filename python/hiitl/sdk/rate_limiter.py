"""Rate limiter - in-memory rate limiting for local mode.

This module provides thread-safe, in-memory rate limiting using a sliding
window algorithm. It's designed for local/edge mode where rate limits are
enforced within a single process.

Design principles:
- Sliding window: More accurate than fixed windows
- Thread-safe: Uses locks for concurrent access
- Automatic cleanup: Old events are removed automatically
- Scope-based keys: Support for different rate limit scopes

Security Tier 1:
- Rate limiting prevents abuse in local mode
- Limits are the windowed RATE_LIMIT rules the evaluator lists (T47)

Example:
    >>> limiter = RateLimiter()
    >>> rate_limited = limiter.check_and_increment(envelope, decision)
    >>> if rate_limited:
    ...     print(f"Rate limited! {rate_limited.reason_codes}")
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

from hiitl.core.rate_limits import counter_state, limit_exceeded, rule_limit_config, tightest
from hiitl.core.types import Decision, DecisionType, Envelope


@dataclass
class Counter:
    """Sliding window counter for rate limiting.

    Attributes:
        events: List of event timestamps (UTC)
        limit: Maximum number of events allowed in window
        window_seconds: Window duration in seconds
    """
    events: list[datetime]
    limit: int
    window_seconds: int


class RateLimiter:
    """In-memory rate limiter using sliding window algorithm.

    This rate limiter maintains counters for different scopes (e.g., per-org,
    per-user, per-tool) and enforces limits using a sliding time window.

    The sliding window algorithm:
    1. Store timestamps of all events
    2. On check: remove events older than each window
    3. Compare every window's count to its limit, before counting any
    4. If all are under: add the new event to every window and allow
    5. If one is at/over: refuse, counting nothing, and return its counter state

    Thread safety:
    - All counter updates are protected by a lock
    - Safe for concurrent use within a single process

    Attributes:
        _counters: Dict of scope_key -> Counter
        _lock: Thread lock for concurrent access
    """

    def __init__(self):
        """Initialize rate limiter with empty counters."""
        self._counters: dict[str, Counter] = {}
        self._lock = Lock()

    def check_and_increment(self, envelope: Envelope, decision: Decision) -> Optional[Decision]:
        """Read every windowed RATE_LIMIT rule the decision lists, then count the call in all of them or in none
        (policy_format.md "Rate-limit rules"; R-0056: counted "on ALLOW decisions only").

        Only an ALLOW is counted. The rules come from the evaluator (`decision.rate_limit_rules`) — one representation,
        the rule's (T47): a set's `metadata.rate_limits` is compiled to such rules when the set loads, so the limiter
        reads nothing else. A window exceeded: the RATE_LIMIT decision for the first such window in listed order, and
        the call is counted in no window — it did not proceed. None exceeded: the call is counted in every window, the
        ALLOW's `rate_limit` is set to the window with the least headroom left (R-0008), and None is returned.
        """
        if decision.decision != DecisionType.ALLOW or not decision.rate_limit_rules:
            return None
        configs = [rule_limit_config(r) for r in decision.rate_limit_rules]

        with self._lock:
            now = datetime.now(timezone.utc)
            read = []
            for config in configs:
                counter = self._window(envelope, config, now)
                reset_at = (counter.events[0] if counter.events else now) + timedelta(seconds=counter.window_seconds)
                if len(counter.events) >= counter.limit:
                    return limit_exceeded(decision, config["rule"], len(counter.events), reset_at)
                read.append((config["rule"], counter, reset_at))

            for _, counter, _ in read:
                counter.events.append(now)
            decision.rate_limit = tightest([counter_state(rule, len(c.events), reset_at) for rule, c, reset_at in read])
        return None

    def _window(self, envelope: Envelope, config: dict, now: datetime) -> Counter:
        """A rule's window (a config from `rule_limit_config`), counted under `rule:<name>:<scope key>`, its calls
        older than the window dropped. The caller holds the lock."""
        scope_key = config["key_prefix"] + self._build_scope_key(envelope, config["scope"])
        counter = self._counters.setdefault(
            scope_key, Counter(events=[], limit=config["limit"], window_seconds=config["window_seconds"]))
        counter.limit, counter.window_seconds = config["limit"], config["window_seconds"]
        cutoff = now - timedelta(seconds=counter.window_seconds)
        counter.events = [event for event in counter.events if event > cutoff]
        return counter

    def _build_scope_key(self, envelope: Envelope, scope: str) -> str:
        """Build scope key from envelope fields.

        Scope formats:
        - "org": org_id only
        - "agent_id": org_id:agent_id (per-agent limit)
        - "user" / "user_id": org_id:user_id (per-user limit)
        - "tool" / "org:tool": org_id:action (per-tool limit)
        - "user:tool": org_id:user_id:action

        Args:
            envelope: Execution envelope
            scope: Scope string

        Returns:
            Scope key for counter lookup
        """
        org_id = envelope.org_id

        if scope == "org":
            return org_id

        elif scope == "agent_id":
            agent_id = getattr(envelope, 'agent_id', 'unknown') or 'unknown'
            return f"{org_id}:{agent_id}"

        elif scope in ("user", "user_id"):
            user_id = envelope.user_id if hasattr(envelope, 'user_id') and envelope.user_id else "anonymous"
            return f"{org_id}:{user_id}"

        elif scope in ("tool", "org:tool"):
            return f"{org_id}:{envelope.action}"

        elif scope == "user:tool":
            user_id = envelope.user_id if hasattr(envelope, 'user_id') and envelope.user_id else "anonymous"
            return f"{org_id}:{user_id}:{envelope.action}"

        else:
            # Default to org scope
            return org_id

    def get_counter_stats(self, scope_key: str) -> Optional[dict]:
        """Get current stats for a scope key (for debugging/monitoring).

        Args:
            scope_key: Scope key to get stats for

        Returns:
            Dict with current, limit, window_seconds, or None if not found
        """
        with self._lock:
            if scope_key not in self._counters:
                return None

            counter = self._counters[scope_key]
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=counter.window_seconds)

            # Clean old events
            counter.events = [
                event for event in counter.events
                if event > cutoff
            ]

            return {
                "current": len(counter.events),
                "limit": counter.limit,
                "window_seconds": counter.window_seconds,
            }

    def reset(self):
        """Reset all counters (for testing)."""
        with self._lock:
            self._counters.clear()
