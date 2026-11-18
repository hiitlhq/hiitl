"""Carried-policy discovery separates actual conformance refusals by structure."""
import copy

import pytest

from hiitl.core.tests.test_row165 import _sets


def policy(name):
    return {'name': name, 'version': 'v1.0.0', 'description': 'Carried set',
            'scope': {'org_id': 'org_inputcontract0001', 'environment': 'dev'}, 'rules': []}


def case(accept):
    return {'format': 'policy', 'id': 'case', 'declaration': '#', 'path': [],
            'control': policy('control'), 'input': policy('input'),
            'expected_accept': accept, 'kind': 'wrong_type'}


@pytest.mark.parametrize('accept,expected', [(False, ['control']), (True, ['control', 'input'])])
def test_discovery_keeps_controls_and_positive_inputs(accept, expected):
    assert [value['name'] for _, value in _sets(case(accept), '$')] == expected


@pytest.mark.parametrize('missing', list(case(False)))
def test_incomplete_case_cannot_mask_an_input(missing):
    source = case(False)
    source.pop(missing)
    names = [value['name'] for _, value in _sets(source, '$')]
    assert names == [name for name in ('control', 'input') if name != missing]


def test_unrelated_metadata_flag_is_not_a_refusal_case():
    source = {'metadata': {'expected_accept': False, 'input': policy('still-carried')}}
    assert [value['name'] for _, value in _sets(source, '$')] == ['still-carried']


def test_artifact_members_cannot_be_hidden_by_case_shaped_metadata():
    source = {**copy.deepcopy(case(False)), **policy('artifact')}
    assert [value['name'] for _, value in _sets(source, '$')] == ['artifact', 'control', 'input']
