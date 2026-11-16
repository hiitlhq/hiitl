"""HTL-41: each schema-derived typed occurrence has a real model refusal/control."""
import copy

import pytest
from pydantic import ValidationError

from hiitl.core.route_types import Route
from hiitl.core.tests.route_null_support import corpus, replace_with_null, assert_named_path

CASES = corpus()['cases']
UNTYPED = corpus()['untyped_controls']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_route_model_obeys_each_typed_null_case(case):
    Route.model_validate(case['control'])
    value = replace_with_null(case['control'], case['path'])
    assert value == case['input']
    if case['expected_accept']:
        Route.model_validate(value)
    else:
        with pytest.raises(ValidationError) as caught:
            Route.model_validate(value)
        assert_named_path(caught.value, case['path'])


@pytest.mark.parametrize('case', UNTYPED, ids=lambda case: case['id'])
def test_route_model_keeps_free_form_null_values(case):
    route = Route.model_validate(case['input'])
    # Preserve the complete authored payload, including null-valued map/array children.
    dumped = route.model_dump(mode='json', exclude_unset=True)
    for key, value in case['input'].items():
        assert dumped[key] == value


@pytest.mark.parametrize('field,bad,path', [
    ('author', 7, ['metadata', 'author']),
    ('created_at', False, ['metadata', 'created_at']),
    ('tags', {}, ['metadata', 'tags']),
    ('tags', [3], ['metadata', 'tags', 0]),
])
def test_declared_non_null_metadata_types_are_refused(field, bad, path):
    # CC PR19 (a), then HTL-43 d82fe0f5: the old acceptance was scoped to HTL-41 only.
    control = copy.deepcopy(CASES[0]['control'])
    metadata = {'author': 'author', 'created_at': '2026-11-14T00:00:00Z', 'tags': ['input'],
                'extra': {'null': None}}
    control['metadata'] = metadata
    assert Route.model_validate(control).metadata == metadata
    control['metadata'] = {**metadata, field: bad}
    with pytest.raises(ValidationError) as caught:
        Route.model_validate(control)
    assert_named_path(caught.value, path)


def test_existing_route_instance_and_nested_model_omissions_remain_valid():
    from hiitl.core.route_types import RouteScope
    control = copy.deepcopy(CASES[0]['control'])
    scope = RouteScope(org_id='org_0123456789abcdef')
    control['scope'] = scope
    route = Route.model_validate(control)
    before = route.model_dump(mode='python')
    fields = set(route.model_fields_set)
    assert Route.model_validate(route) is route
    assert route.model_dump(mode='python') == before
    assert route.model_fields_set == fields
    assert route.scope.model_fields_set == {'org_id'}
    assert scope.model_fields_set == {'org_id'}


def test_explicit_null_inside_a_supplied_nested_model_is_still_refused():
    from hiitl.core.route_types import RouteScope
    control = copy.deepcopy(CASES[0]['control'])
    control['scope'] = RouteScope(org_id='org_0123456789abcdef', environment=None)
    with pytest.raises(ValidationError) as caught:
        Route.model_validate(control)
    assert_named_path(caught.value, ['scope', 'environment'])
