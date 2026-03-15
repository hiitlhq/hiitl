"""Tests for synthetic envelope generation."""

import pytest

from hiitl.core.types import Envelope
from hiitl.synthetic.agent_loader import AgentPersona
from hiitl.synthetic.envelope_factory import EnvelopeFactory


def _make_agent() -> AgentPersona:
    """Create a minimal agent persona for testing."""
    return AgentPersona({
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "Agent for testing",
        "behavior_profile": {
            "tools": ["tool_a", "tool_b"],
            "action_frequency": {"tool_a": 0.7, "tool_b": 0.3},
            "parameter_distributions": {
                "tool_a": {
                    "amount": {
                        "type": "distribution",
                        "distribution": "exponential",
                        "mean": 100,
                        "min": 10,
                        "max": 500,
                    },
                    "currency": {
                        "type": "categorical",
                        "values": ["usd", "eur"],
                        "probabilities": [0.8, 0.2],
                    },
                },
                "tool_b": {
                    "target_id": {
                        "type": "pattern",
                        "pattern": "tgt_{random_id}",
                    },
                },
            },
        },
        "sensitivity_flags": {
            "tool_a": ["money"],
        },
    })


class TestEnvelopeFactory:
    """Tests for EnvelopeFactory."""

    def test_generate_one_valid_envelope(self):
        """Generated envelope must pass Pydantic validation."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        env = factory.generate_one()
        assert isinstance(env, Envelope)

    def test_deterministic_with_seed(self):
        """Same seed produces identical envelopes."""
        factory1 = EnvelopeFactory(_make_agent(), seed=42)
        factory2 = EnvelopeFactory(_make_agent(), seed=42)

        env1 = factory1.generate_one()
        env2 = factory2.generate_one()

        assert env1.action == env2.action
        assert env1.parameters == env2.parameters
        assert env1.action_id == env2.action_id

    def test_different_seeds_different_output(self):
        """Different seeds produce different envelopes."""
        factory1 = EnvelopeFactory(_make_agent(), seed=1)
        factory2 = EnvelopeFactory(_make_agent(), seed=2)

        env1 = factory1.generate_one()
        env2 = factory2.generate_one()

        # At least action_id should differ
        assert env1.action_id != env2.action_id

    def test_generate_batch(self):
        """Batch generation produces the requested count."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        batch = factory.generate_batch(20)
        assert len(batch) == 20
        assert all(isinstance(e, Envelope) for e in batch)

    def test_tool_distribution(self):
        """Over many samples, tool distribution matches weights."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        batch = factory.generate_batch(1000)
        tool_a_count = sum(1 for e in batch if e.action == "tool_a")
        # 70% expected, allow 60-80% range
        assert 600 <= tool_a_count <= 800

    def test_exponential_distribution_clamping(self):
        """Exponential distribution values are clamped to [min, max]."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        batch = factory.generate_batch(100)
        for env in batch:
            if env.action == "tool_a":
                amount = env.parameters.get("amount")
                if amount is not None:
                    assert 10 <= amount <= 500

    def test_categorical_distribution(self):
        """Categorical values come from the defined set."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        batch = factory.generate_batch(50)
        for env in batch:
            if env.action == "tool_a":
                currency = env.parameters.get("currency")
                if currency is not None:
                    assert currency in ("usd", "eur")

    def test_pattern_distribution(self):
        """Pattern values match the template."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        env = factory.generate_one(tool="tool_b")
        target_id = env.parameters.get("target_id")
        assert target_id is not None
        assert target_id.startswith("tgt_")

    def test_action_id_pattern(self):
        """Action ID matches required pattern."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        env = factory.generate_one()
        assert env.action_id.startswith("act_")
        assert len(env.action_id) >= 24  # act_ + 20+ chars

    def test_sensitivity_from_persona(self):
        """Sensitivity flags come from the agent persona."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        env = factory.generate_one(tool="tool_a")
        assert env.sensitivity == ["money"]

    def test_specific_tool(self):
        """Specifying a tool overrides random selection."""
        factory = EnvelopeFactory(_make_agent(), seed=42)
        env = factory.generate_one(tool="tool_b")
        assert env.action == "tool_b"
