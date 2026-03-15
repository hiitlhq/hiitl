"""Policy loader - loads policies from JSON or YAML files.

Per docs/specs/policy_format.md:
- JSON is the primary format (native format for evaluator)
- YAML is a convenience layer for human-friendly editing
- Both formats are converted to PolicySet objects for validation

Design:
- Format detection by file extension (.json, .yaml, .yml)
- Fallback: try JSON first (faster), then YAML
- mtime-based caching to avoid re-parsing unchanged files
- Helpful error messages pointing to policy_format.md

Example:
    >>> loader = PolicyLoader("./policy.yaml")
    >>> policy = loader.load()
    >>> # On next call, returns cached if file unchanged
    >>> policy = loader.load()  # Fast cache hit
"""

import json
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from hiitl.core.types import PolicySet
from hiitl.sdk.exceptions import PolicyLoadError


class PolicyLoader:
    """Loads and caches policy files from JSON or YAML.

    This loader supports both JSON (primary format) and YAML (convenience layer).
    Policies are parsed into PolicySet objects and validated with Pydantic.

    The loader maintains an mtime-based cache to avoid re-parsing unchanged files.
    This is critical for performance in high-throughput scenarios.

    Attributes:
        policy_path: Path to policy file (JSON or YAML)
        _cached_policy: Cached PolicySet (None if not loaded or invalidated)
        _cached_mtime: File modification time when cached (None if not cached)
    """

    def __init__(self, policy_path: str):
        """Initialize policy loader.

        Args:
            policy_path: Path to policy file (JSON or YAML format)
        """
        self.policy_path = Path(policy_path)
        self._cached_policy: Optional[PolicySet] = None
        self._cached_mtime: Optional[float] = None

    def load(self) -> PolicySet:
        """Load policy from JSON or YAML file with mtime-based caching.

        This method:
        1. Checks file modification time
        2. Returns cached policy if file unchanged
        3. Otherwise, parses file (JSON or YAML)
        4. Validates with Pydantic PolicySet schema
        5. Caches result for next call

        Format detection:
        - .json extension → parse as JSON
        - .yaml or .yml extension → parse as YAML, convert to JSON
        - No extension → try JSON first (faster), fallback to YAML

        Returns:
            PolicySet object (validated)

        Raises:
            PolicyLoadError: If file not found, invalid syntax, or validation fails
        """
        # Check if file exists
        if not self.policy_path.exists():
            raise PolicyLoadError(
                f"Policy file not found: {self.policy_path}\n\n"
                "Make sure the path is correct and the file exists.\n"
                "See docs/specs/policy_format.md for policy file format."
            )

        # Get current file modification time
        try:
            current_mtime = self.policy_path.stat().st_mtime
        except OSError as e:
            raise PolicyLoadError(
                f"Cannot access policy file {self.policy_path}: {e}"
            ) from e

        # Return cached policy if file unchanged
        if self._cached_policy and self._cached_mtime == current_mtime:
            return self._cached_policy

        # Parse file to Python dict
        policy_dict = self._parse_file()

        # Handle optional "policy_set" wrapper
        # Some policy files wrap the policy in {"policy_set": {...}}
        if isinstance(policy_dict, dict) and "policy_set" in policy_dict:
            policy_dict = policy_dict["policy_set"]

        # Validate with Pydantic PolicySet schema
        try:
            policy = PolicySet(**policy_dict)
        except ValidationError as e:
            raise PolicyLoadError(
                f"Invalid policy format in {self.policy_path}:\n\n{e}\n\n"
                "The policy file doesn't match the required schema.\n"
                "Check docs/specs/policy_format.md for the correct format.\n\n"
                "Note: JSON is the primary format; YAML is a convenience layer.\n"
                "Both formats must produce valid PolicySet objects."
            ) from e
        except Exception as e:
            raise PolicyLoadError(
                f"Unexpected error parsing policy {self.policy_path}: {e}\n\n"
                "Check that the file contains valid JSON or YAML."
            ) from e

        # Cache for next call
        self._cached_policy = policy
        self._cached_mtime = current_mtime

        return policy

    def _parse_file(self) -> dict:
        """Parse policy file to Python dict (JSON or YAML).

        Format detection:
        1. Check file extension (.json, .yaml, .yml)
        2. Parse accordingly
        3. If no extension or unknown, try JSON first (faster), then YAML

        Returns:
            Python dict from JSON or YAML

        Raises:
            PolicyLoadError: If file cannot be parsed as JSON or YAML
        """
        suffix = self.policy_path.suffix.lower()

        try:
            with open(self.policy_path, 'r', encoding='utf-8') as f:
                # JSON format (primary)
                if suffix == '.json':
                    try:
                        return json.load(f)
                    except json.JSONDecodeError as e:
                        raise PolicyLoadError(
                            f"Invalid JSON in {self.policy_path}:\n{e}\n\n"
                            "The file has .json extension but contains invalid JSON.\n"
                            "Check for syntax errors (missing commas, quotes, brackets)."
                        ) from e

                # YAML format (convenience layer)
                elif suffix in ('.yaml', '.yml'):
                    try:
                        policy_dict = yaml.safe_load(f)
                        if not isinstance(policy_dict, dict):
                            raise PolicyLoadError(
                                f"Invalid YAML in {self.policy_path}: "
                                "YAML file must contain a mapping/dict, "
                                f"but got {type(policy_dict).__name__}"
                            )
                        return policy_dict
                    except yaml.YAMLError as e:
                        raise PolicyLoadError(
                            f"Invalid YAML in {self.policy_path}:\n{e}\n\n"
                            "The file has .yaml/.yml extension but contains invalid YAML.\n"
                            "Check for syntax errors (indentation, colons, dashes)."
                        ) from e

                # Unknown or no extension: try JSON first, fallback to YAML
                else:
                    content = f.read()

                    # Try JSON first (faster, native format)
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        pass  # Not JSON, try YAML

                    # Try YAML as fallback
                    try:
                        policy_dict = yaml.safe_load(content)
                        if not isinstance(policy_dict, dict):
                            raise PolicyLoadError(
                                f"Invalid policy file {self.policy_path}: "
                                "File must contain JSON object or YAML mapping, "
                                f"but got {type(policy_dict).__name__}"
                            )
                        return policy_dict
                    except yaml.YAMLError as e:
                        raise PolicyLoadError(
                            f"Cannot parse {self.policy_path} as JSON or YAML:\n{e}\n\n"
                            "The file is neither valid JSON nor valid YAML.\n"
                            "Ensure the file is properly formatted."
                        ) from e

        except OSError as e:
            raise PolicyLoadError(
                f"Cannot read policy file {self.policy_path}: {e}"
            ) from e

    def invalidate_cache(self):
        """Invalidate cached policy, forcing reload on next load() call.

        This is useful for testing or when you know the file has changed
        but the mtime might not have been updated (e.g., same-second edits).
        """
        self._cached_policy = None
        self._cached_mtime = None
