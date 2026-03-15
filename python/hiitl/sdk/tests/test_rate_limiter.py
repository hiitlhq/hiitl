"""Tests for RateLimiter."""

import time
from datetime import datetime, timedelta, timezone
from threading import Thread

import pytest

from hiitl.core.types import Decision, DecisionType, Envelope, Timing
from hiitl.sdk.rate_limiter import RateLimiter


class TestRateLimiterBasics:
    """Test basic rate limiting functionality."""

    @pytest.fixture
    def sample_envelope(self):
        """Create sample envelope."""
        return Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

    @pytest.fixture
    def allow_decision(self):
        """Create ALLOW decision."""
        return Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

    @pytest.fixture
    def block_decision(self):
        """Create BLOCK decision."""
        return Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.BLOCK,
            allowed=False,
            reason_codes=["BLOCKED"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

    def test_no_rate_limit_if_no_config(self, sample_envelope, allow_decision):
        """No rate limiting if rate_config is None."""
        limiter = RateLimiter()
        result = limiter.check_and_increment(sample_envelope, allow_decision, None)

        assert result is None  # Not rate limited

    def test_no_rate_limit_if_empty_config(self, sample_envelope, allow_decision):
        """No rate limiting if rate_config has no rate_limits."""
        limiter = RateLimiter()
        result = limiter.check_and_increment(
            sample_envelope, allow_decision, {"other": "config"}
        )

        assert result is None  # Not rate limited

    def test_no_rate_limit_for_block_decision(self, sample_envelope, block_decision):
        """BLOCK decisions should not be rate limited."""
        limiter = RateLimiter()
        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 0, "window_seconds": 60}  # Zero limit
            ]
        }

        result = limiter.check_and_increment(sample_envelope, block_decision, rate_config)

        assert result is None  # Not rate limited (BLOCK decisions exempt)

    def test_allows_under_limit(self, sample_envelope, allow_decision):
        """Should allow actions under the rate limit."""
        limiter = RateLimiter()
        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 3, "window_seconds": 60}
            ]
        }

        # First 3 should be allowed
        for i in range(3):
            result = limiter.check_and_increment(sample_envelope, allow_decision, rate_config)
            assert result is None  # Not rate limited

    def test_blocks_over_limit(self, sample_envelope, allow_decision):
        """Should block actions over the rate limit."""
        limiter = RateLimiter()
        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 3, "window_seconds": 60}
            ]
        }

        # First 3 allowed
        for i in range(3):
            result = limiter.check_and_increment(sample_envelope, allow_decision, rate_config)
            assert result is None

        # 4th should be rate limited
        result = limiter.check_and_increment(sample_envelope, allow_decision, rate_config)
        assert result is not None
        assert result.decision == DecisionType.RATE_LIMIT
        assert result.allowed is False
        assert "RATE_LIMIT_EXCEEDED" in result.reason_codes

    def test_rate_limit_decision_includes_metadata(self, sample_envelope, allow_decision):
        """Rate limit decision should include RateLimit metadata."""
        limiter = RateLimiter()
        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 2, "window_seconds": 60}
            ]
        }

        # Use up limit
        for i in range(2):
            limiter.check_and_increment(sample_envelope, allow_decision, rate_config)

        # Next should be rate limited
        result = limiter.check_and_increment(sample_envelope, allow_decision, rate_config)

        assert result.rate_limit is not None
        assert result.rate_limit.current == 2
        assert result.rate_limit.limit == 2
        assert result.rate_limit.reset_at is not None  # ISO 8601 timestamp


class TestRateLimiterSlidingWindow:
    """Test sliding window algorithm."""

    def test_old_events_are_cleaned_up(self):
        """Old events outside window should be removed."""
        limiter = RateLimiter()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 2, "window_seconds": 1}  # 1 second window
            ]
        }

        # Use up limit
        limiter.check_and_increment(envelope, decision, rate_config)
        limiter.check_and_increment(envelope, decision, rate_config)

        # Check we're at limit
        stats = limiter.get_counter_stats("org_test000000000000")
        assert stats['current'] == 2

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again (old events cleaned up)
        result = limiter.check_and_increment(envelope, decision, rate_config)
        assert result is None  # Not rate limited

        # Counter should have 1 event (old ones removed)
        stats = limiter.get_counter_stats("org_test000000000000")
        assert stats['current'] == 1


class TestRateLimiterScopes:
    """Test different rate limit scopes."""

    def test_org_scope(self):
        """Org scope should share limits across all requests for same org."""
        limiter = RateLimiter()

        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 2, "window_seconds": 60}
            ]
        }

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        # Two different tools, same org
        envelope1 = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="tool_a",
            operation="execute",
            parameters={},
            idempotency_key="idem_test1",
            target={},
            signature="0" * 64,
        )

        envelope2 = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000001",
            timestamp="2026-02-15T10:00:00Z",
            action="tool_b",
            operation="execute",
            parameters={},
            idempotency_key="idem_test2",
            target={},
            signature="0" * 64,
        )

        # First request (tool_a) - allowed
        result = limiter.check_and_increment(envelope1, decision, rate_config)
        assert result is None

        # Second request (tool_b, different tool but same org) - allowed
        result = limiter.check_and_increment(envelope2, decision, rate_config)
        assert result is None

        # Third request - should be rate limited (org scope shares limit)
        result = limiter.check_and_increment(envelope1, decision, rate_config)
        assert result is not None
        assert result.decision == DecisionType.RATE_LIMIT

    def test_tool_scope(self):
        """Tool scope should have separate limits per tool."""
        limiter = RateLimiter()

        rate_config = {
            "rate_limits": [
                {"scope": "tool", "limit": 2, "window_seconds": 60}
            ]
        }

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        envelope_a = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="tool_a",
            operation="execute",
            parameters={},
            idempotency_key="idem_test1",
            target={},
            signature="0" * 64,
        )

        envelope_b = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000001",
            timestamp="2026-02-15T10:00:00Z",
            action="tool_b",
            operation="execute",
            parameters={},
            idempotency_key="idem_test2",
            target={},
            signature="0" * 64,
        )

        # Use up limit for tool_a
        limiter.check_and_increment(envelope_a, decision, rate_config)
        limiter.check_and_increment(envelope_a, decision, rate_config)

        # tool_a should be rate limited
        result = limiter.check_and_increment(envelope_a, decision, rate_config)
        assert result is not None

        # tool_b should still be allowed (separate counter)
        result = limiter.check_and_increment(envelope_b, decision, rate_config)
        assert result is None


class TestRateLimiterThreadSafety:
    """Test thread safety of rate limiter."""

    def test_concurrent_increments_are_thread_safe(self):
        """Concurrent increments should be thread-safe."""
        limiter = RateLimiter()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 100, "window_seconds": 60}
            ]
        }

        results = []

        def increment():
            result = limiter.check_and_increment(envelope, decision, rate_config)
            results.append(result)

        # Spawn 50 threads
        threads = [Thread(target=increment) for _ in range(50)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All should succeed (under limit of 100)
        assert all(result is None for result in results)

        # Counter should have exactly 50 events
        stats = limiter.get_counter_stats("org_test000000000000")
        assert stats['current'] == 50


class TestRateLimiterUtilities:
    """Test utility methods."""

    def test_get_counter_stats(self):
        """get_counter_stats() should return current stats."""
        limiter = RateLimiter()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 10, "window_seconds": 60}
            ]
        }

        # Add 3 events
        for _ in range(3):
            limiter.check_and_increment(envelope, decision, rate_config)

        stats = limiter.get_counter_stats("org_test000000000000")

        assert stats is not None
        assert stats['current'] == 3
        assert stats['limit'] == 10
        assert stats['window_seconds'] == 60

    def test_get_counter_stats_returns_none_for_unknown_key(self):
        """get_counter_stats() should return None for unknown scope key."""
        limiter = RateLimiter()

        stats = limiter.get_counter_stats("unknown_key")

        assert stats is None

    def test_reset_clears_all_counters(self):
        """reset() should clear all counters."""
        limiter = RateLimiter()

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        rate_config = {
            "rate_limits": [
                {"scope": "org", "limit": 10, "window_seconds": 60}
            ]
        }

        # Add events
        limiter.check_and_increment(envelope, decision, rate_config)

        # Reset
        limiter.reset()

        # Stats should be None (counter removed)
        stats = limiter.get_counter_stats("org_test000000000000")
        assert stats is None
