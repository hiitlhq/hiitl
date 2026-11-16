"""Gap 272: exact defaults from every source member, with valid containing shapes."""
import copy
import pytest
from pydantic import ValidationError
from hiitl.core.route_types import Route
from hiitl.core.tests.route_defaults_support import (
    ROUTE_SCHEMA, WITNESSES, all_cases, apply_defaults, defaults, omission_cases,
)

@pytest.mark.parametrize('case', all_cases(), ids=lambda c:c['id'])
def test_schema_default_and_explicit_route_values(case):
    route = Route.model_validate(case['input'])
    # Route wire shape: Pydantic represents absent optional members internally as None.
    assert route.model_dump(mode='json', exclude_none=True) == case['expected']

def test_every_default_has_an_omission_witness():
    assert {case['declaration'] for case in omission_cases()} == {d['address'] for d in defaults(ROUTE_SCHEMA)}

@pytest.mark.parametrize('value', [False, 0, '', [], {}])
def test_reader_discovers_new_referenced_array_default(value):
    schema = {'properties':{'items':{'type':'array','items':{'$ref':'#/$defs/item'}}},
              '$defs':{'item':{'properties':{'added':{'default':value}}}}}
    cases = omission_cases(schema, [{'id':'new','input':{'items':[{}]}}])
    assert cases == [{'id':'items.*.added@new:items.0', 'path':['items',0,'added'],
                      'declaration':'#/$defs/item/properties/added', 'input':{'items':[{}]},
                      'expected':{'items':[{'added':value}]}}]
    assert apply_defaults(schema, {}) == {}

def test_reader_refuses_unwitnessed_and_unread_defaults():
    with pytest.raises(ValueError, match='no omission witness for parent.child'):
        omission_cases({'properties':{'parent':{'properties':{'child':{'default':False}}}}}, [{'id':'absent','input':{}}])
    with pytest.raises(ValueError, match='unread default declaration #/allOf/0/properties/child'):
        defaults({'allOf':[{'properties':{'child':{'default':0}}}]})

@pytest.mark.parametrize('witness', WITNESSES, ids=lambda w:w['id'])
def test_defaults_do_not_waive_root_required_members(witness):
    for key in ROUTE_SCHEMA['required']:
        value = copy.deepcopy(witness['input'])
        value.pop(key)
        with pytest.raises(ValidationError):
            Route.model_validate(value)


def test_reader_audits_external_target_but_not_unreferenced_members():
    schema = {'properties':{'referenced':{'$ref':'external.json#/$defs/target'}}}
    external = {'$defs':{'target':{'allOf':[{'default':'new'}]}, 'unrelated':{'default':'not referenced'}}}
    with pytest.raises(ValueError, match='unread default declaration external.json#/.defs/target/allOf/0'):
        defaults(schema, lambda name: external)
    external['$defs']['target'] = {'properties':{'written':{'default':False}}}
    assert defaults(schema, lambda name: external) == [
        {'path':['referenced','written'], 'value':False, 'address':'external.json#/$defs/target/properties/written'}]


def test_reader_follows_reference_aliases_in_the_owning_document():
    external = {'$defs':{'alias':{'$ref':'#/$defs/target'}, 'target':{'properties':{'value':{'default':False}}}}}
    schema = {'properties':{'item':{'$ref':'external.json#/$defs/alias'}}}
    assert defaults(schema, lambda name: external) == [
        {'path':['item','value'], 'value':False, 'address':'external.json#/$defs/target/properties/value'}]
    local = {**external, 'properties':{'item':{'$ref':'#/$defs/alias'}}}
    assert apply_defaults(local, {'item':{}}) == {'item':{'value':False}}
    local['$defs']['target'] = {'default':False}
    assert apply_defaults(local, {}) == {'item':False}


def test_reader_names_reference_cycles():
    schema = {'$defs':{'loop':{'$ref':'#/$defs/loop'}},'properties':{'item':{'$ref':'#/$defs/loop'}}}
    with pytest.raises(ValueError, match='recursive schema at #/.defs/loop'):
        defaults(schema)
    with pytest.raises(ValueError, match='recursive schema at #/.defs/loop'):
        apply_defaults(schema, {'item':{}})
