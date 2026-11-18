"""HTL-41 uses real JSON/YAML files and the customer-facing route loader."""
import copy
import json

import pytest
import yaml

from hiitl.core.tests.route_null_support import corpus, replace_with_null, assert_named_path
from hiitl.sdk.exceptions import RouteLoadError
from hiitl.sdk.route_loader import RouteLoader

CASES = corpus()['cases']
UNTYPED = corpus()['untyped_controls']


def load(value, name, directory, extension):
    directory.mkdir()
    text = json.dumps(value) if extension == 'json' else yaml.safe_dump(value)
    (directory / f'{name}.{extension}').write_text(text)
    return RouteLoader(str(directory)).get(name)


@pytest.fixture(autouse=True)
def fixture_credential(monkeypatch):
    monkeypatch.setenv('HTL39_ROUTE_FIXTURE', 'local-route-fixture')
    monkeypatch.setenv('HTL41_ROUTE_FIXTURE', 'local-route-fixture')


@pytest.mark.parametrize('extension', ['json', 'yaml'])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_loader_obeys_each_typed_null_case(case, extension, tmp_path):
    name = case['control']['name']
    control = load(case['control'], name, tmp_path / 'control', extension)
    assert control.name == name
    value = replace_with_null(case['control'], case['path'])
    assert value == case['input']
    if case['expected_accept']:
        assert load(value, name, tmp_path / 'null', extension).name == name
    else:
        with pytest.raises(RouteLoadError) as caught:
            load(value, name, tmp_path / 'null', extension)
        assert_named_path(caught.value, case['path'])


@pytest.mark.parametrize('extension', ['json', 'yaml'])
@pytest.mark.parametrize('case', UNTYPED, ids=lambda case: case['id'])
def test_loader_keeps_free_form_null_values(case, extension, tmp_path):
    route = load(case['input'], case['input']['name'], tmp_path / 'route', extension)
    dumped = route.model_dump(mode='json', exclude_unset=True)
    for key, value in case['input'].items():
        assert dumped[key] == value


@pytest.mark.parametrize('extension', ['json', 'yaml'])
@pytest.mark.parametrize('field,bad,path', [
    ('author', 7, ['metadata', 'author']),
    ('created_at', False, ['metadata', 'created_at']),
    ('tags', {}, ['metadata', 'tags']),
    ('tags', [3], ['metadata', 'tags', 0]),
])
def test_loader_refuses_declared_wrong_metadata_types(extension, tmp_path, field, bad, path):
    # CC PR19 (a), then HTL-43 d82fe0f5: this explicitly replaces the null-only scope.
    control = copy.deepcopy(CASES[0]['control'])
    metadata = {'author': 'author', 'created_at': '2026-11-14T00:00:00Z', 'tags': ['input'],
                'extra': {'null': None}}
    control['metadata'] = metadata
    assert load(control, control['name'], tmp_path / 'control', extension).metadata == metadata
    control['metadata'] = {**metadata, field: bad}
    with pytest.raises(RouteLoadError) as caught:
        load(control, control['name'], tmp_path / 'changed', extension)
    assert_named_path(caught.value, path)
