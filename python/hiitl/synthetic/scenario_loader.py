"""Load and validate scenario JSON files from synthetic/scenarios/."""

import json
from pathlib import Path
from typing import List, Optional

from .types import Scenario


class ScenarioLoadError(Exception):
    """Failed to load or validate a scenario file."""


class ScenarioLoader:
    """Loads scenarios from the synthetic/scenarios/ directory.

    Args:
        scenarios_dir: Path to directory containing scenario JSON files.
                       Defaults to <project_root>/synthetic/scenarios/
    """

    def __init__(self, scenarios_dir: Optional[str] = None):
        if scenarios_dir:
            self.scenarios_dir = Path(scenarios_dir)
        else:
            # Default: project_root/synthetic/scenarios/
            # Navigate from python/hiitl/synthetic/ up to project root
            self.scenarios_dir = (
                Path(__file__).parent.parent.parent.parent / "synthetic" / "scenarios"
            )

    def load(self, scenario_name: str) -> Scenario:
        """Load a single scenario by name (filename without .json).

        Args:
            scenario_name: Scenario name (e.g., "high-value-payment-approval")

        Returns:
            Validated Scenario object

        Raises:
            ScenarioLoadError: If file not found or validation fails
        """
        filepath = self.scenarios_dir / f"{scenario_name}.json"
        if not filepath.exists():
            available = self.list_available()
            available_str = ", ".join(available) if available else "(none found)"
            raise ScenarioLoadError(
                f"Scenario '{scenario_name}' not found at {filepath}\n\n"
                f"Available scenarios: {available_str}\n"
                f"Scenarios directory: {self.scenarios_dir}"
            )

        try:
            data = json.loads(filepath.read_text())
        except json.JSONDecodeError as e:
            raise ScenarioLoadError(
                f"Invalid JSON in scenario '{scenario_name}': {e}"
            ) from e

        try:
            return Scenario(**data)
        except Exception as e:
            raise ScenarioLoadError(
                f"Scenario '{scenario_name}' validation failed: {e}"
            ) from e

    def load_all(self) -> List[Scenario]:
        """Load all scenarios from the directory.

        Returns:
            List of validated Scenario objects (skips invalid files with warning)
        """
        scenarios = []
        for name in self.list_available():
            try:
                scenarios.append(self.load(name))
            except ScenarioLoadError:
                # Skip invalid scenarios in batch mode
                pass
        return scenarios

    def list_available(self) -> List[str]:
        """List available scenario names (filenames without .json extension).

        Returns:
            Sorted list of scenario names
        """
        if not self.scenarios_dir.exists():
            return []
        return sorted(
            p.stem for p in self.scenarios_dir.glob("*.json")
        )
