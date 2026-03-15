"""Route loader - loads and validates route configuration files.

Per docs/specs/routes.md:
- Routes define how ECP communicates with external systems
- In local mode, stored as YAML/JSON files on disk
- Referenced by name from policy rules via route field
- Resolved by SDK after evaluation to populate escalation_context

Design:
- Directory-based loading (all configs in a directory)
- Format detection by file extension (.json, .yaml, .yml)
- mtime-based caching (per-file) to avoid re-parsing
- Lookup by config name (file stem must match config name)
- Pydantic Route model validation at load time
- Helpful error messages pointing to routes.md

Example:
    >>> loader = RouteLoader("./routes/")
    >>> route = loader.get("finance-review")
    >>> route.sla.timeout
    '4h'
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from hiitl.core.route_types import Route
from hiitl.sdk.exceptions import RouteLoadError

logger = logging.getLogger(__name__)


class RouteLoader:
    """Loads and caches route configuration files from a directory.

    Routes are the third core artifact alongside envelopes and policies.
    They define how external communication works when a policy produces an
    escalation decision (REQUIRE_APPROVAL, PAUSE, ESCALATE) or when
    events need to be shipped to external systems.

    The loader scans a directory for YAML/JSON files, validates them
    against the Route Pydantic model, and provides lookup by config name.
    Files are cached with mtime-based invalidation.

    Attributes:
        configs_path: Path to routes directory
        _cache: Dict mapping config name to (mtime, Route) tuples
    """

    def __init__(self, configs_path: str):
        """Initialize route loader.

        Args:
            configs_path: Path to directory containing route config files
        """
        self.configs_path = Path(configs_path)
        self._cache: Dict[str, tuple[float, Route]] = {}

    def get(self, config_name: str) -> Optional[Route]:
        """Get a route config by name.

        Looks for a file matching the config name in the configs directory.
        Supports .yaml, .yml, and .json extensions.

        Args:
            config_name: Route config name (e.g., "finance-review")

        Returns:
            Validated Route model, or None if not found

        Raises:
            RouteLoadError: If config file exists but is malformed or invalid
        """
        if not self.configs_path.exists():
            logger.warning(
                "Routes directory not found: %s. "
                "Escalation decisions will not include escalation_context.",
                self.configs_path,
            )
            return None

        # Try each supported extension
        for ext in (".yaml", ".yml", ".json"):
            config_file = self.configs_path / f"{config_name}{ext}"
            if config_file.exists():
                return self._load_file(config_file, config_name)

        logger.warning(
            "Route config '%s' not found in %s. "
            "The decision will still be returned but without escalation_context. "
            "Create a file named '%s.yaml' (or .json) in the routes directory. "
            "See docs/specs/routes.md for the schema.",
            config_name,
            self.configs_path,
            config_name,
        )
        return None

    def _load_file(self, file_path: Path, config_name: str) -> Route:
        """Load, validate, and cache a single route config file.

        Uses mtime-based caching to avoid re-parsing unchanged files.
        Validates against the Route Pydantic model for strict type checking.

        Args:
            file_path: Path to the config file
            config_name: Expected config name

        Returns:
            Validated Route model

        Raises:
            RouteLoadError: If file is malformed, invalid, or fails validation
        """
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError as e:
            raise RouteLoadError(
                f"Cannot access route config file {file_path}: {e}"
            ) from e

        # Return cached if unchanged
        if config_name in self._cache:
            cached_mtime, cached_route = self._cache[config_name]
            if cached_mtime == current_mtime:
                return cached_route

        # Parse file
        raw_config = self._parse_file(file_path)

        # Validate with Pydantic Route model
        try:
            route = Route.model_validate(raw_config)
        except ValidationError as e:
            raise RouteLoadError(
                f"Route config validation failed for {file_path}:\n{e}\n\n"
                "See docs/specs/routes.md for the full schema."
            ) from e

        # Verify name matches filename
        if route.name != config_name:
            raise RouteLoadError(
                f"Route config name mismatch in {file_path}: "
                f"file contains name '{route.name}' but expected '{config_name}' "
                f"(based on filename).\n\n"
                f"The 'name' field in the route config must match the filename (without extension).\n"
                f"See docs/specs/routes.md for naming conventions."
            )

        # Cache and return
        self._cache[config_name] = (current_mtime, route)
        return route

    def _parse_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse a route config file (JSON or YAML).

        Args:
            file_path: Path to the config file

        Returns:
            Parsed dict

        Raises:
            RouteLoadError: If file cannot be parsed
        """
        suffix = file_path.suffix.lower()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                if suffix == ".json":
                    try:
                        return json.load(f)
                    except json.JSONDecodeError as e:
                        raise RouteLoadError(
                            f"Invalid JSON in route config {file_path}:\n{e}\n\n"
                            "Check for syntax errors (missing commas, quotes, brackets).\n"
                            "See docs/specs/routes.md for the schema."
                        ) from e

                elif suffix in (".yaml", ".yml"):
                    try:
                        config = yaml.safe_load(f)
                        if not isinstance(config, dict):
                            raise RouteLoadError(
                                f"Invalid YAML in route config {file_path}: "
                                f"expected a mapping/dict, got {type(config).__name__}.\n"
                                "See docs/specs/routes.md for the schema."
                            )
                        return config
                    except yaml.YAMLError as e:
                        raise RouteLoadError(
                            f"Invalid YAML in route config {file_path}:\n{e}\n\n"
                            "Check for syntax errors (indentation, colons, dashes).\n"
                            "See docs/specs/routes.md for the schema."
                        ) from e

                else:
                    raise RouteLoadError(
                        f"Unsupported file extension '{suffix}' for route config {file_path}.\n"
                        "Supported formats: .json, .yaml, .yml"
                    )

        except OSError as e:
            raise RouteLoadError(
                f"Cannot read route config file {file_path}: {e}"
            ) from e

    def invalidate_cache(self) -> None:
        """Invalidate all cached configs, forcing reload on next get() call."""
        self._cache.clear()


def resolve_escalation_context(route: Route) -> Dict[str, Any]:
    """Resolve a Route into an escalation_context dict for the decision.

    Extracts the key fields from the typed Route model and returns a
    flattened escalation_context suitable for the Decision object.

    The output includes:
    - timeout: SLA timeout duration (e.g., "4h")
    - timeout_action: What happens on timeout
    - decision_options: What the reviewer can do
    - endpoint: Where the escalation goes
    - protocol: Transport protocol
    - fields: What envelope fields the reviewer sees
    - severity: Risk severity (if specified)
    - summary: Risk summary (if specified)
    - escalation_ladder: Multi-level escalation config (if present)
    - token_field: Correlation token field name (if present)

    Args:
        route: Validated Route model

    Returns:
        Flattened escalation_context dict for the Decision
    """
    context: Dict[str, Any] = {
        "endpoint": route.endpoint,
        "protocol": route.protocol,
    }

    # SLA fields
    if route.sla:
        context["timeout"] = route.sla.timeout
        context["timeout_action"] = route.sla.timeout_action

    # Response schema
    if route.response_schema:
        context["decision_options"] = list(route.response_schema.decision_options)

    # Context fields
    if route.context and route.context.fields:
        context["fields"] = [
            {
                "field_path": f.field_path,
                "label": f.label,
                "format": f.format,
            }
            for f in route.context.fields
        ]

    # Risk framing
    if route.context and route.context.risk_framing:
        rf = route.context.risk_framing
        if rf.severity:
            context["severity"] = rf.severity
        if rf.summary:
            context["summary"] = rf.summary

    # Escalation ladder
    if route.escalation_ladder and route.escalation_ladder.levels:
        context["escalation_ladder"] = {
            "levels": [
                {"level": lv.level, "route": lv.route, "after": lv.after}
                for lv in route.escalation_ladder.levels
            ],
            "max_escalation_depth": route.escalation_ladder.max_escalation_depth,
            "final_timeout_action": route.escalation_ladder.final_timeout_action,
        }

    # Correlation
    if route.correlation:
        context["token_field"] = route.correlation.token_field

    return context
