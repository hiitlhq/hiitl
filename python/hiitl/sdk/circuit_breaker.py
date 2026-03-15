"""Per-channel circuit breaker for sync engine resilience.

Implements a standard circuit breaker pattern to prevent repeated failures
from overwhelming the sync engine or server.

States:
    CLOSED (normal) → requests flow normally
    OPEN (tripped)  → requests are blocked after N consecutive failures
    HALF_OPEN       → after reset timeout, one probe request is allowed

State transitions:
    CLOSED  → OPEN       when failure_count >= threshold
    OPEN    → HALF_OPEN  when reset_timeout has elapsed
    HALF_OPEN → CLOSED   on success
    HALF_OPEN → OPEN     on failure

Thread safety: All state mutations are protected by a threading.Lock.
"""

import logging
import threading
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-channel circuit breaker.

    Each sync channel (audit, policy, routes, kill switches) gets its own
    CircuitBreaker instance so failures in one channel don't affect others.

    Args:
        name: Channel name for logging (e.g., "audit", "policy")
        failure_threshold: Consecutive failures before opening (default: 5)
        reset_timeout: Seconds in OPEN state before probing (default: 60)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state (evaluates OPEN → HALF_OPEN transition)."""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time >= self.reset_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "Sync circuit breaker [%s] → HALF_OPEN (probing after %.0fs)",
                    self.name,
                    self.reset_timeout,
                )
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through the circuit.

        Returns:
            True if the request should proceed, False if blocked.
        """
        current = self.state  # triggers OPEN → HALF_OPEN check
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return True  # allow one probe
        # OPEN — blocked
        return False

    def record_success(self) -> None:
        """Record a successful request. Resets failure count and closes circuit."""
        with self._lock:
            previous = self._state
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            if previous != CircuitState.CLOSED:
                logger.info(
                    "Sync circuit breaker [%s] → CLOSED (recovered from %s)",
                    self.name,
                    previous.value,
                )

    def record_failure(self) -> None:
        """Record a failed request. Opens circuit after threshold failures."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — back to OPEN
                self._state = CircuitState.OPEN
                logger.warning(
                    "Sync circuit breaker [%s] → OPEN (probe failed, "
                    "will retry in %.0fs)",
                    self.name,
                    self.reset_timeout,
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.error(
                    "Sync circuit breaker [%s] → OPEN after %d consecutive "
                    "failures. Sync paused for %.0fs.",
                    self.name,
                    self._failure_count,
                    self.reset_timeout,
                )

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED. Used during shutdown/restart."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0

    def status(self) -> dict:
        """Return circuit breaker status for health reporting."""
        with self._lock:
            return {
                "channel": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "reset_timeout": self.reset_timeout,
            }
