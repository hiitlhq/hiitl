"""Tests for PolicyLoader."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hiitl.core.types import PolicySet
from hiitl.core.tests.measurements import record_measurement
from hiitl.sdk.exceptions import PolicyLoadError
from hiitl.sdk.policy_loader import PolicyLoader


# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestPolicyLoaderValidFiles:
    """Test PolicyLoader with valid policy files."""

    def test_load_valid_json_policy(self):
        """Loading valid JSON policy should succeed."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")
        policy = loader.load()

        assert isinstance(policy, PolicySet)
        assert policy.version == "v1.0.0"
        assert policy.name == "test_policy"
        assert len(policy.rules) == 1
        assert policy.rules[0].name == "allow_small_amounts"
        assert policy.rules[0].priority == 100

    def test_load_valid_yaml_policy(self):
        """Loading valid YAML policy should succeed."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.yaml")
        policy = loader.load()

        assert isinstance(policy, PolicySet)
        assert policy.version == "v1.0.0"
        assert policy.name == "test_policy_yaml"
        assert len(policy.rules) == 1
        assert policy.rules[0].name == "allow_small_amounts"

    def test_load_wrapped_policy(self):
        """Loading policy with policy_set wrapper should succeed."""
        loader = PolicyLoader(FIXTURES_DIR / "wrapped_policy.json")
        policy = loader.load()

        assert isinstance(policy, PolicySet)
        assert policy.name == "wrapped_test_policy"
        assert len(policy.rules) == 1

    def test_json_and_yaml_produce_equivalent_policies(self):
        """JSON and YAML versions should produce equivalent PolicySet objects."""
        # Both fixtures have same structure, different names
        json_loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")
        yaml_loader = PolicyLoader(FIXTURES_DIR / "valid_policy.yaml")

        json_policy = json_loader.load()
        yaml_policy = yaml_loader.load()

        # Same structure (both have 1 rule with same fields)
        assert len(json_policy.rules) == len(yaml_policy.rules) == 1
        assert json_policy.rules[0].priority == yaml_policy.rules[0].priority
        assert json_policy.rules[0].decision == yaml_policy.rules[0].decision


class TestPolicyLoaderCaching:
    """Test PolicyLoader caching behavior."""

    def test_cache_hit_on_second_load(self):
        """Second load() call should return cached policy if file unchanged."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")

        # First load
        policy1 = loader.load()
        mtime1 = loader._cached_mtime

        # Second load (cache hit)
        policy2 = loader.load()
        mtime2 = loader._cached_mtime

        # Should return same cached object
        assert policy1 is policy2
        assert mtime1 == mtime2

    def test_cache_miss_after_file_modification(self, tmp_path):
        """Cache should be invalidated if file is modified."""
        # Create temporary policy file
        policy_file = tmp_path / "test_policy.json"
        policy_file.write_text('''{
            "version": "v1.0.0",
            "description": "Cache miss after file modification",
            "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"},
            "name": "test_v1",
            "rules": []
        }''')

        loader = PolicyLoader(policy_file)

        # First load
        policy1 = loader.load()
        assert policy1.name == "test_v1"

        # Wait a bit to ensure mtime changes (some filesystems have 1s resolution)
        time.sleep(0.01)

        # Modify file
        policy_file.write_text('''{
            "version": "v1.0.0",
            "description": "Cache miss after file modification",
            "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"},
            "name": "test_v2",
            "rules": []
        }''')

        # Second load (cache miss - file changed)
        policy2 = loader.load()
        assert policy2.name == "test_v2"

        # Different objects
        assert policy1 is not policy2

    def test_invalidate_cache(self):
        """invalidate_cache() should force reload on next load()."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")

        # First load
        policy1 = loader.load()

        # Invalidate cache
        loader.invalidate_cache()
        assert loader._cached_policy is None
        assert loader._cached_mtime is None

        # Second load (forced reload)
        policy2 = loader.load()

        # Different object instances (not cached)
        assert policy1 is not policy2


class TestPolicyLoaderErrors:
    """Test PolicyLoader error handling."""

    def test_missing_file_raises_policy_load_error(self):
        """Loading nonexistent file should raise PolicyLoadError."""
        loader = PolicyLoader("nonexistent_policy.json")

        with pytest.raises(PolicyLoadError) as exc_info:
            loader.load()

        error_msg = str(exc_info.value)
        assert "not found" in error_msg.lower()
        assert "nonexistent_policy.json" in error_msg

    def test_invalid_json_raises_policy_load_error(self):
        """Loading file with invalid JSON should raise PolicyLoadError."""
        loader = PolicyLoader(FIXTURES_DIR / "invalid_json.json")

        with pytest.raises(PolicyLoadError) as exc_info:
            loader.load()

        error_msg = str(exc_info.value)
        assert "invalid json" in error_msg.lower()
        assert "invalid_json.json" in error_msg

    def test_invalid_yaml_raises_policy_load_error(self):
        """Loading file with invalid YAML should raise PolicyLoadError."""
        loader = PolicyLoader(FIXTURES_DIR / "invalid_yaml.yaml")

        with pytest.raises(PolicyLoadError) as exc_info:
            loader.load()

        error_msg = str(exc_info.value)
        assert "invalid yaml" in error_msg.lower() or "yaml" in error_msg.lower()
        assert "invalid_yaml.yaml" in error_msg

    def test_invalid_schema_raises_policy_load_error(self):
        """Loading file with invalid PolicySet schema should raise PolicyLoadError."""
        loader = PolicyLoader(FIXTURES_DIR / "invalid_schema.json")

        with pytest.raises(PolicyLoadError) as exc_info:
            loader.load()

        error_msg = str(exc_info.value)
        assert "invalid policy format" in error_msg.lower()
        assert "policy_format.md" in error_msg  # Should point to docs

    def test_helpful_error_messages(self):
        """Error messages should be helpful and point to documentation."""
        # Missing file
        with pytest.raises(PolicyLoadError) as exc_info:
            PolicyLoader("missing.json").load()
        assert "policy_format.md" in str(exc_info.value)

        # Invalid schema
        with pytest.raises(PolicyLoadError) as exc_info:
            PolicyLoader(FIXTURES_DIR / "invalid_schema.json").load()
        error_msg = str(exc_info.value)
        assert "policy_format.md" in error_msg
        assert "schema" in error_msg.lower()


class TestPolicyLoaderFormatDetection:
    """Test PolicyLoader format detection logic."""

    def test_json_extension_uses_json_parser(self):
        """File with .json extension should be parsed as JSON."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")
        policy = loader.load()

        assert isinstance(policy, PolicySet)
        assert policy.name == "test_policy"

    def test_yaml_extension_uses_yaml_parser(self):
        """File with .yaml extension should be parsed as YAML."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.yaml")
        policy = loader.load()

        assert isinstance(policy, PolicySet)
        assert policy.name == "test_policy_yaml"

    def test_no_extension_tries_json_first(self, tmp_path):
        """File without extension should try JSON first."""
        # Create file without extension containing JSON
        policy_file = tmp_path / "policy"
        policy_file.write_text('''{
            "version": "v1.0.0",
            "description": "No extension tries json first",
            "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"},
            "name": "no_extension_json",
            "rules": []
        }''')

        loader = PolicyLoader(policy_file)
        policy = loader.load()

        assert policy.name == "no_extension_json"

    def test_no_extension_falls_back_to_yaml(self, tmp_path):
        """File without extension should fallback to YAML if JSON fails."""
        # Create file without extension containing YAML
        policy_file = tmp_path / "policy"
        policy_file.write_text('''version: "v1.0.0"
name: no_extension_yaml
description: A YAML set in a file with no extension
scope:
  org_id: org_devlocal0000000000
  environment: dev
rules: []
''')

        loader = PolicyLoader(policy_file)
        policy = loader.load()

        assert policy.name == "no_extension_yaml"


class TestPolicyLoaderPerformance:
    """Test PolicyLoader performance characteristics."""

    def test_unchanged_file_returns_cached_policy_without_parsing_again(self):
        """The unchanged-file cache reuses the loaded policy; this proves cache behavior without a timing proxy."""
        loader = PolicyLoader(FIXTURES_DIR / "valid_policy.json")
        with patch.object(loader, "_parse_file", wraps=loader._parse_file) as parse:
            first = loader.load()
            again = loader.load()
        assert again is first
        parse.assert_called_once_with()

    def test_cache_load_measurements_and_identity(self, tmp_path, record_property):
        """Record cold/cached load durations and assert the cache returns the same object."""
        # Create policy file
        policy_file = tmp_path / "performance_test.json"
        policy_file.write_text('''{
            "version": "v1.0.0",
            "description": "Cache provides performance benefit",
            "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"},
            "name": "performance_test",
            "rules": []
        }''')

        loader = PolicyLoader(policy_file)

        # First load (includes file I/O, parsing, validation)
        start = time.perf_counter()
        policy1 = loader.load()
        first_load_time = time.perf_counter() - start

        # Second load (cache hit - should be much faster)
        start = time.perf_counter()
        policy2 = loader.load()
        cached_load_time = time.perf_counter() - start

        record_measurement(record_property, metric="policy_cold_and_cached_load", unit="seconds",
                           source="hiitl.sdk.policy_loader.PolicyLoader.load",
                           value={"cold": first_load_time, "cached": cached_load_time})

        # Should be same object (cache hit)
        assert policy1 is policy2

    def test_json_and_yaml_load_measurements(self, tmp_path, record_property):
        """Record equivalent JSON/YAML loads without a host-dependent speed ratio."""
        # Create equivalent JSON and YAML files
        json_file = tmp_path / "test.json"
        yaml_file = tmp_path / "test.yaml"

        policy_content = {
            "version": "v1.0.0",
            "description": "Json parsing faster than yaml",
            "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"},
            "name": "performance_comparison",
            "rules": []
        }

        import json
        json_file.write_text(json.dumps(policy_content))

        import yaml
        yaml_file.write_text(yaml.dump(policy_content))

        # Measure JSON parsing (average over multiple runs)
        json_times = []
        for _ in range(10):
            loader = PolicyLoader(json_file)
            loader.invalidate_cache()
            start = time.perf_counter()
            loader.load()
            json_times.append(time.perf_counter() - start)

        # Measure YAML parsing
        yaml_times = []
        for _ in range(10):
            loader = PolicyLoader(yaml_file)
            loader.invalidate_cache()
            start = time.perf_counter()
            loader.load()
            yaml_times.append(time.perf_counter() - start)

        avg_json_time = sum(json_times) / len(json_times)
        avg_yaml_time = sum(yaml_times) / len(yaml_times)

        record_measurement(record_property, metric="policy_json_and_yaml_load", unit="seconds",
                           source="hiitl.sdk.policy_loader.PolicyLoader.load",
                           value={"json_samples": json_times, "yaml_samples": yaml_times,
                                  "json_mean": avg_json_time, "yaml_mean": avg_yaml_time})


def test_lint_runs_on_load_and_logs_findings(tmp_path, caplog):
    """The loader lints the set it loads and logs warning/error findings; the load
    itself is never blocked by a finding."""
    import json as _json
    import logging
    from hiitl.sdk.policy_loader import PolicyLoader
    p = tmp_path / "p.json"
    p.write_text(_json.dumps({"name": "p", "version": "v1.0.0", "description": "Lint runs on load and logs findings", "scope": {"org_id": "org_devlocal0000000000", "environment": "dev"}, "rules": [
        {"name": "rl", "description": "rl", "priority": 1, "decision": "RATE_LIMIT", "reason_code": "RL",
         "conditions": {"field": "action", "operator": "equals", "value": "x"}}]}))
    with caplog.at_level(logging.WARNING, logger="hiitl.sdk.policy_loader"):
        policy = PolicyLoader(str(p)).load()
    assert policy.rules[0].name == "rl"
    assert "RATE_LIMIT_NO_WINDOW" in caplog.text
