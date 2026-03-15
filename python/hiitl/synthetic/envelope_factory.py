"""Generate valid Envelope objects from agent persona distributions.

Supports three distribution types from persona definitions:
- "distribution": statistical distributions (exponential, normal, uniform)
- "categorical": weighted random choice from a set of values
- "pattern": string templates with {random_id} substitution

All generation is deterministic when a seed is provided.
"""

import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hiitl.core.types import Envelope

from .agent_loader import AgentPersona


class EnvelopeFactory:
    """Generates valid Envelope objects from agent persona specs.

    Separates data collection (this class) from analysis (grading strategy).
    The factory produces envelopes; what happens to them is the caller's concern.

    Args:
        agent: AgentPersona with behavior_profile
        org_id: Organization ID (must match pattern ^org_[a-zA-Z0-9]{16,}$)
        environment: "dev", "stage", or "prod"
        seed: Optional random seed for deterministic generation
    """

    def __init__(
        self,
        agent: AgentPersona,
        org_id: str = "org_synthetictest00001",
        environment: str = "dev",
        seed: Optional[int] = None,
    ):
        self._agent = agent
        self._org_id = org_id
        self._environment = environment
        self._rng = random.Random(seed)

    def generate_one(self, tool: Optional[str] = None) -> Envelope:
        """Generate a single valid envelope.

        If tool is not specified, picks one according to action_frequency weights.
        """
        if tool is None:
            tool = self._pick_tool()

        params = self._generate_parameters(tool)
        target = self._generate_target(tool)
        action_id = self._generate_action_id()
        sensitivity = self._agent.sensitivity_flags.get(tool)

        return Envelope(
            schema_version="v1.0",
            org_id=self._org_id,
            environment=self._environment,
            agent_id=self._agent.agent_id,
            action_id=action_id,
            idempotency_key=f"idem_{self._generate_hex(32)}",
            action=tool,
            operation="execute",
            target=target,
            parameters=params,
            timestamp=datetime.now(timezone.utc),
            signature="0" * 64,
            sensitivity=sensitivity if sensitivity else None,
        )

    def generate_batch(self, count: int) -> List[Envelope]:
        """Generate a batch of envelopes with realistic tool distribution."""
        return [self.generate_one() for _ in range(count)]

    def _pick_tool(self) -> str:
        """Pick a tool according to action_frequency weights."""
        tools = list(self._agent.action_frequency.keys())
        weights = list(self._agent.action_frequency.values())
        return self._rng.choices(tools, weights=weights, k=1)[0]

    def _generate_parameters(self, tool: str) -> Dict[str, Any]:
        """Generate parameters for a tool according to parameter_distributions."""
        distributions = self._agent.parameter_distributions.get(tool, {})
        params: Dict[str, Any] = {}

        for param_name, spec in distributions.items():
            params[param_name] = self._sample(spec)

        return params

    def _generate_target(self, tool: str) -> Dict[str, Any]:
        """Generate a target dict from parameter distributions.

        Looks for account_id or similar pattern fields in distributions.
        """
        distributions = self._agent.parameter_distributions.get(tool, {})

        # Extract target-like fields (account_id, resource_id, etc.)
        target: Dict[str, Any] = {}
        for param_name, spec in distributions.items():
            if param_name.endswith("_id") or param_name == "target":
                target[param_name] = self._sample(spec)

        # If no target fields found, generate a default
        if not target:
            target = {"resource_id": f"res_{self._generate_hex(16)}"}

        return target

    def _sample(self, spec: Dict[str, Any]) -> Any:
        """Sample a value from a distribution spec."""
        dist_type = spec.get("type", "")

        if dist_type == "distribution":
            return self._sample_distribution(spec)
        elif dist_type == "categorical":
            return self._sample_categorical(spec)
        elif dist_type == "pattern":
            return self._sample_pattern(spec)
        else:
            # Unknown type, return spec as-is if it's a simple value
            return spec.get("value", spec)

    def _sample_distribution(self, spec: Dict[str, Any]) -> float:
        """Sample from a statistical distribution."""
        dist = spec.get("distribution", "exponential")
        mean = spec.get("mean", 100)
        min_val = spec.get("min", 0)
        max_val = spec.get("max", float("inf"))

        if dist == "exponential":
            value = self._rng.expovariate(1.0 / mean)
        elif dist == "normal":
            stddev = spec.get("stddev", mean * 0.2)
            value = self._rng.gauss(mean, stddev)
        elif dist == "uniform":
            value = self._rng.uniform(min_val, max_val)
        else:
            value = self._rng.expovariate(1.0 / mean)

        # Clamp to [min, max] and round
        return round(max(min_val, min(max_val, value)), 2)

    def _sample_categorical(self, spec: Dict[str, Any]) -> Any:
        """Pick a value using weighted probabilities."""
        values = spec["values"]
        probabilities = spec.get("probabilities")
        return self._rng.choices(values, weights=probabilities, k=1)[0]

    def _sample_pattern(self, spec: Dict[str, Any]) -> str:
        """Generate a string from a pattern template."""
        pattern = spec["pattern"]
        random_id = self._generate_hex(16)
        return pattern.replace("{random_id}", random_id)

    def _generate_action_id(self) -> str:
        """Generate action_id matching pattern ^act_[a-zA-Z0-9]{20,}$."""
        # Generate 24 hex chars (all alphanumeric, satisfies the pattern)
        return f"act_{self._generate_hex(24)}"

    def _generate_hex(self, length: int) -> str:
        """Generate a random hex string of specified length."""
        # randbytes available in Python 3.9+
        num_bytes = (length + 1) // 2
        return self._rng.randbytes(num_bytes).hex()[:length]
