"""HTL-41 null-only traversal, independent of the generated route corpus."""
import copy

import pytest
from pydantic import BaseModel


def guard(value, shape):
    from hiitl.core.route_nulls import forbidden_nulls
    return forbidden_nulls(value, shape)


@pytest.mark.parametrize('value,shape,expected', [
    (None, {'allows_null': False}, [()]),
    (None, {'allows_null': True}, []),
    (None, {}, []),
    ({'written': None}, {'properties': {'written': {'allows_null': False}}}, [('written',)]),
    ({'written': None}, {'properties': {'written': {'allows_null': True}}}, []),
    ([None, 'ok', None], {'items': {'allows_null': False}}, [(0,), (2,)]),
    ([None], {'items': {'allows_null': True}}, []),
    ({'one': None, 'two': 'ok', 'three': None},
     {'additionalProperties': {'allows_null': False}}, [('one',), ('three',)]),
    ({'one': None}, {'additionalProperties': {'allows_null': True}}, []),
    ({'declared': None, 'other': None}, {'properties': {'declared': {'allows_null': True}},
                                      'additionalProperties': {'allows_null': False}}, [('other',)]),
    ({'declared': None, 'other': None}, {'properties': {'declared': {'allows_null': False}},
                                      'additionalProperties': {'allows_null': True}}, [('declared',)]),
    ({'rows': [{'labels': {'first': None, 'last': None}}, {'labels': {'last': None}}], 'tail': None},
     {'properties': {'rows': {'items': {'properties': {'labels': {'additionalProperties': {'allows_null': False}}}}},
                     'tail': {'allows_null': False}}},
     [('rows', 0, 'labels', 'first'), ('rows', 0, 'labels', 'last'), ('rows', 1, 'labels', 'last'), ('tail',)]),
])
def test_null_guard_returns_every_precise_instance_path(value, shape, expected):
    original = copy.deepcopy(value)
    assert guard(value, shape) == expected
    assert value == original


@pytest.mark.parametrize('value', [{}, [], 'wrong object type', 0, False])
def test_null_guard_preserves_omission_and_non_null_validation_responsibility(value):
    shape = {'allows_null': False, 'properties': {'missing': {'allows_null': False}},
             'items': {'allows_null': False}, 'additionalProperties': {'allows_null': False}}
    original = copy.deepcopy(value)
    assert guard(value, shape) == []
    assert value == original


@pytest.mark.parametrize('value', [None, {'arbitrary': None, 'nested': [None, {'child': None}]}, [None]])
def test_null_guard_does_not_type_untyped_data(value):
    original = copy.deepcopy(value)
    assert guard(value, {}) == []
    assert value == original


def test_null_guard_preserves_nested_pydantic_field_presence():
    class Child(BaseModel):
        optional: str | None = None

    class Parent(BaseModel):
        child: Child | None = None

    shape = {'properties': {'child': {'allows_null': False,
                                     'properties': {'optional': {'allows_null': False}}}}}
    omitted = Parent()
    present_parent = Parent(child=Child())
    explicit_child_null = Parent(child=None)
    explicit_leaf_null = Parent(child=Child(optional=None))
    assert guard(omitted, shape) == []
    assert guard(present_parent, shape) == []
    assert guard(explicit_child_null, shape) == [('child',)]
    assert guard(explicit_leaf_null, shape) == [('child', 'optional')]
    assert omitted.model_fields_set == set()
    assert present_parent.child.model_fields_set == set()
    assert explicit_leaf_null.child.model_fields_set == {'optional'}


def test_null_guard_reads_models_inside_containers_without_inventing_defaults():
    class Item(BaseModel):
        value: str | None = None

    values = [Item(), Item(value=None), Item(value='kept')]
    shape = {'items': {'properties': {'value': {'allows_null': False}}}}
    assert guard(values, shape) == [(1, 'value')]
    assert [item.model_fields_set for item in values] == [set(), {'value'}, {'value'}]
