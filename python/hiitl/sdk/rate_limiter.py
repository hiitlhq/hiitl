"""Rate limiter - in-memory rate limiting for local mode.

This module provides thread-safe, in-memory rate limiting using a sliding
window algorithm. It's designed for local/edge mode where rate limits are
enforced within a single process.

Design principles:
- Sliding window: More accurate than fixed windows
- Thread-safe: Uses locks for concurrent access
- Automatic cleanup: Old events are removed automatically
- Scope-based keys: Support for different rate limit scopes

Security tier 1 requirements:
- Rate limiting prevents abuse in local mode
- Configurable limits per policy metadata

Example:
    >>> limiter = RateLimiter()
    >>> rate_limited = limiter.check_and_increment(
    ...     envelope, decision, rate_config
    ... )
    >>> if rate_limited:
    ...     print(f"Rate limited! {rate_limited.reason_codes}")
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

from hiitl.core.types import Decision, DecisionType, Envelope, RateLimit


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
    2. On check: remove events older than window
    3. Compare count to limit
    4. If under limit: add new event and allow
    5. If at/over limit: block and return RateLimit info

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

    def check_and_increment(
        self,
        envelope: Envelope,
        decision: Decision,
        rate_config: Optional[dict] = None
    ) -> Optional[Decision]:
        """Check rate limits and increment counter if allowed.

        This method:
        1. Only checks ALLOW decisions (don't rate limit BLOCK/etc)
        2. Extracts rate limit config from rate_config or policy metadata
        3. Builds scope key from envelope fields
        4. Checks if limit exceeded
        5. Returns modified RATE_LIMIT decision if exceeded, None if OK

        Args:
            envelope: Execution envelope
            decision: Policy decision (only ALLOW is rate-limited)
            rate_config: Optional rate limit configuration dict

        Returns:
            RATE_LIMIT decision if exceeded, None if allowed

        Rate config format:
            {
                "rate_limits": [
                    {
                        "scope": "agent_id",
                        "limit": 100,
                        "window": "hour",
                        "window_seconds": 3600  # alternative to window name
                    }
                ]
            }
        """
        # Only rate limit ALLOW decisions
        if decision.decision != DecisionType.ALLOW:
            return None

        # If no rate config, don't rate limit
        if not rate_config or 'rate_limits' not in rate_config:
            return None

        rate_limits = rate_config.get('rate_limits', [])
        if not rate_limits:
            return None

        # Window name to seconds mapping
        window_name_to_seconds = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }

        # Check each rate limit config (first exceeded wins)
        for config in (rate_limits if isinstance(rate_limits, list) else [rate_limits]):
            result = self._check_single_limit(envelope, decision, config, window_name_to_seconds)
            if result is not None:
                return result

        return None

    def _check_single_limit(
        self,
        envelope: Envelope,
        decision: Decision,
        config: dict,
        window_name_to_seconds: dict
    ) -> Optional[Decision]:
        """Check a single rate limit configuration."""
        scope = config.get('scope', 'org')
        limit = config.get('limit', 1000)
        window = config.get('window', 'hour')
        window_seconds = config.get('window_seconds') or window_name_to_seconds.get(window, 3600)

        # Build scope key from envelope
        scope_key = self._build_scope_key(envelope, scope)

        # Check and increment with lock
        with self._lock:
            # Get or create counter
            if scope_key not in self._counters:
                self._counters[scope_key] = Counter(
                    events=[],
                    limit=limit,
                    window_seconds=window_seconds
                )

            counter = self._counters[scope_key]
            now = datetime.now(timezone.utc)

            # Remove old events (sliding window cleanup)
            cutoff = now - timedelta(seconds=counter.window_seconds)
            counter.events = [
                event for event in counter.events
                if event > cutoff
            ]

            # Check if limit exceeded
            current_count = len(counter.events)

            if current_count >= counter.limit:
                # Rate limit exceeded - return RATE_LIMIT decision
                reset_at = counter.events[0] + timedelta(seconds=counter.window_seconds)

                return Decision(
                    action_id=decision.action_id,
                    decision=DecisionType.RATE_LIMIT,
                    allowed=False,
                    reason_codes=["RATE_LIMIT_EXCEEDED"],
                    policy_version=decision.policy_version,
                    timing=decision.timing,
                    rate_limit=RateLimit(
                        scope=scope,
                        window=window,
                        limit=counter.limit,
                        current=current_count,
                        reset_at=reset_at
                    )
                )

            # Under limit - increment and allow
            counter.events.append(now)
            return None  # No rate limit, allow action

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
