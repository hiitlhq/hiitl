"""The customer file loaders retain source-derived refusals and named paths."""
import json

import pytest
import yaml

from hiitl.core.tests.input_contract_support import cases
from hiitl.core.tests.route_null_support import assert_named_path
from hiitl.sdk.exceptions import PolicyLoadError, RouteLoadError
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.sdk.route_loader import RouteLoader


def load(case, value, directory, extension):
    directory.mkdir()
    name = case['control']['name']
    path = directory / f'{name}.{extension}'
    path.write_text(json.dumps(value) if extension == 'json' else yaml.safe_dump(value))
    if case['format'] == 'policy':
        return PolicyLoader(str(path)).load()
    return RouteLoader(str(directory)).get(name)


@pytest.fixture(autouse=True)
def fixture_credential(monkeypatch):
    monkeypatch.setenv('HTL39_ROUTE_FIXTURE', 'local-route-fixture')
    monkeypatch.setenv('HTL41_ROUTE_FIXTURE', 'local-route-fixture')


@pytest.mark.parametrize('extension', ['json', 'yaml'])
@pytest.mark.parametrize('case', cases('policy', 'routes'), ids=lambda case: case['id'])
def test_file_loader_obeys_each_source_contract(case, extension, tmp_path):
    load(case, case['control'], tmp_path / 'control', extension)
    if case['expected_accept']:
        load(case, case['input'], tmp_path / 'changed', extension)
    else:
        with pytest.raises((PolicyLoadError, RouteLoadError)) as caught:
            load(case, case['input'], tmp_path / 'changed', extension)
        assert_named_path(caught.value, case['path'])

