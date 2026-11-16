"""Actual JSON/YAML loaders preserve source-required migration names."""
import json

import pytest
import yaml

from hiitl.core.tests.test_migration_diagnostics import policy, route, rule
from hiitl.sdk.exceptions import PolicyLoadError, RouteLoadError
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.sdk.route_loader import RouteLoader


@pytest.mark.parametrize("extension", ["json", "yaml"])
@pytest.mark.parametrize("artifact", ["route", "policy"])
def test_file_loader_preserves_existing_migration_guidance(extension, artifact, tmp_path):
    if artifact == "route":
        control = route({"actions": ["pay"]})
        changed = route({"tools": ["pay"]})
        names = ("filters.tools", "filters.actions")
        error = RouteLoadError
    else:
        control = policy(rule(tests=[{"envelope": {"action": "pay"}, "expect": "ALLOW"}]))
        changed = policy(rule(tests=[{"envelope": {"tool_name": "pay"}, "expect": "ALLOW"}]))
        names = ("tool_name", "action")
        error = PolicyLoadError
    def load(value, directory):
        directory.mkdir()
        path = directory / f'{value["name"]}.{extension}'
        path.write_text(json.dumps(value) if extension == "json" else yaml.safe_dump(value))
        return (RouteLoader(str(directory)).get(value["name"]) if artifact == "route"
                else PolicyLoader(str(path)).load())
    assert load(control, tmp_path / "control").name == control["name"]
    with pytest.raises(error) as caught:
        load(changed, tmp_path / "changed")
    assert all(name in str(caught.value) for name in names)
    assert "renamed" in str(caught.value)
