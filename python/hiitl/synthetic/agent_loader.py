"""Load agent persona JSON files from synthetic/agents/."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class AgentLoadError(Exception):
    """Failed to load or validate an agent persona file."""


class AgentPersona:
    """Loaded agent persona with behavior profile access."""

    def __init__(self, data: Dict[str, Any]):
        self.agent_id: str = data["agent_id"]
        self.name: str = data["name"]
        self.description: str = data.get("description", "")
        self.behavior_profile: Dict[str, Any] = data["behavior_profile"]
        self.sensitivity_flags: Dict[str, List[str]] = data.get("sensitivity_flags", {})
        self.expected_policy_interactions: Dict[str, Any] = data.get(
            "expected_policy_interactions", {}
        )
        self._raw = data

    @property
    def tools(self) -> List[str]:
        """List of tools this agent uses."""
        return self.behavior_profile["tools"]

    @property
    def action_frequency(self) -> Dict[str, float]:
        """Tool → probability weight mapping."""
        return self.behavior_profile["action_frequency"]

    @property
    def parameter_distributions(self) -> Dict[str, Dict[str, Any]]:
        """Tool → parameter distribution specs."""
        return self.behavior_profile.get("parameter_distributions", {})

    @property
    def rate(self) -> str:
        """Target action rate (e.g., '100 actions/hour')."""
        return self.behavior_profile.get("rate", "unknown")


class AgentLoader:
    """Loads agent personas from synthetic/agents/ directory.

    Args:
        agents_dir: Path to directory containing agent persona JSON files.
                    Defaults to <project_root>/synthetic/agents/
    """

    def __init__(self, agents_dir: Optional[str] = None):
        if agents_dir:
            self.agents_dir = Path(agents_dir)
        else:
            # Default: project_root/synthetic/agents/
            self.agents_dir = (
                Path(__file__).parent.parent.parent.parent / "synthetic" / "agents"
            )

    def load(self, agent_id: str) -> AgentPersona:
        """Load agent persona by agent_id (filename without .json).

        Args:
            agent_id: Agent identifier (e.g., "payment-agent")

        Returns:
            AgentPersona object

        Raises:
            AgentLoadError: If file not found or invalid
        """
        filepath = self.agents_dir / f"{agent_id}.json"
        if not filepath.exists():
            available = self.list_available()
            available_str = ", ".join(available) if available else "(none found)"
            raise AgentLoadError(
                f"Agent persona '{agent_id}' not found at {filepath}\n\n"
                f"Available agents: {available_str}\n"
                f"Agents directory: {self.agents_dir}"
            )

        try:
            data = json.loads(filepath.read_text())
        except json.JSONDecodeError as e:
            raise AgentLoadError(
                f"Invalid JSON in agent '{agent_id}': {e}"
            ) from e

        try:
            return AgentPersona(data)
        except KeyError as e:
            raise AgentLoadError(
                f"Agent persona '{agent_id}' missing required field: {e}"
            ) from e

    def load_all(self) -> Dict[str, AgentPersona]:
        """Load all agent personas. Returns dict keyed by agent_id."""
        agents = {}
        for name in self.list_available():
            try:
                agent = self.load(name)
                agents[agent.agent_id] = agent
            except AgentLoadError:
                pass
        return agents

    def list_available(self) -> List[str]:
        """List available agent persona names."""
        if not self.agents_dir.exists():
            return []
        return sorted(p.stem for p in self.agents_dir.glob("*.json"))
