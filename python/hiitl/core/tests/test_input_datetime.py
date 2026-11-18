"""Declared open-object date-times use the existing shared RFC 3339 reader."""
import copy
import pytest
from pydantic import ValidationError
from hiitl.core.types import PolicySet
from hiitl.core.route_types import Route
from hiitl.core.tests.input_contract_support import cases
from hiitl.core.tests.route_null_support import assert_named_path


@pytest.mark.parametrize('format,path,subtype', [
    ('policy', ['metadata', 'created_at'], None),
    ('policy', ['metadata', 'updated_at'], None),
    ('routes', ['metadata', 'created_at'], None),
    ('policy', ['rules', 0, 'remediation', 'details', 'reset_at'], 'rate_limit'),
    ('policy', ['rules', 0, 'remediation', 'details', 'next_allowed_at'], 'temporal'),
])
@pytest.mark.parametrize('invalid', ['not-a-date', '2026-02-30T12:00:00Z'])
def test_declared_datetime_child_uses_shared_reader(format, path, subtype, invalid):
    model = PolicySet if format == 'policy' else Route
    source = copy.deepcopy(cases(format)[0]['control'])
    if subtype:
        source['rules'][0]['remediation'] = {
            'type': subtype, 'message': 'Wait', 'suggestion': 'Retry', 'details': {}}
    else:
        source['metadata'] = {}
    target = source
    for part in path[:-1]:
        target = target[part]
    written = '2026-11-14T12:00:00+05:30'
    target[path[-1]] = written
    control = model.model_validate(source).model_dump(mode='json', exclude_unset=True)
    actual = control
    for part in path:
        actual = actual[part]
    assert actual == written
    target[path[-1]] = invalid
    caught = None
    try:
        model.model_validate(source)
    except ValidationError as error:
        caught = error
    assert caught is not None
    assert_named_path(caught, path)


def test_custom_details_and_plain_current_time_keep_strings():
    for subtype, details in [('custom', {'reset_at': 'not-a-date', 'next_allowed_at': 'also-data'}),
                             ('temporal', {'current_time': 'display as written'})]:
        source = copy.deepcopy(cases('policy')[0]['control'])
        source['rules'][0]['remediation'] = {
            'type': subtype, 'message': 'Read', 'suggestion': 'Keep', 'details': details}
        assert PolicySet.model_validate(source).rules[0].remediation.details == details
