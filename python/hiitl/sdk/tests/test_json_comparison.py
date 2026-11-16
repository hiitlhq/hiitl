"""Both real policy-file loaders retain the source comparison answers."""
import json
import pytest
import yaml
from hiitl.core import PolicyEvaluator
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.core.tests.json_comparison_support import DATA,inputs,outcome

@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('row',DATA['cases'],ids=lambda row:row['id'])
def test_file_comparison_answer(row,wire,tmp_path):
    policy,envelope=inputs(row)
    path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    loaded=PolicyLoader(path).load()
    assert outcome(PolicyEvaluator().evaluate(envelope,loaded))==row['expected']

from hiitl.core.tests.test_json_comparison import MODEL_OBJECTS


@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('field,left,right,same', MODEL_OBJECTS)
def test_file_model_objects_compare_supplied_members(field,left,right,same,wire,tmp_path):
    policy,envelope=inputs({'operator':'equals','left':left,'right':right})
    envelope[field]=left
    policy['rules'][0]['conditions']['field']=field
    path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    loaded=PolicyLoader(path).load()
    assert PolicyEvaluator().evaluate(envelope,loaded).allowed is same


@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('operator,expected',[('equals',False),('not_equals',True)])
def test_datetime_field_reference_compares_supplied_text(wire,operator,expected,tmp_path):
    policy,envelope=inputs({'operator':operator,'left':None,'right':{'$field':'principal.verified_at'}})
    envelope['timestamp']='2026-11-14T01:00:00Z'
    envelope['principal']={'sub':'user','verified_by':'sdk_verifier','verified_at':'2026-11-14T02:00:00+01:00'}
    policy['rules'][0]['conditions']['field']='timestamp'
    path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    assert PolicyEvaluator().evaluate(envelope,PolicyLoader(path).load()).allowed is expected


@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('operator,expected',[('in',True),('not_in',False)])
def test_nonarray_reference_fails_with_its_operator_and_both_fields(wire,operator,expected,tmp_path):
    policy,envelope=inputs({'operator':operator,'left':'ab','right':{'$field':'parameters.set'}})
    envelope['parameters']['set']='abc'
    path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    from hiitl.core.operator_kinds import OperatorKindError
    with pytest.raises(OperatorKindError, match=operator+'.*parameters.probe.*parameters.set'):
        PolicyEvaluator().evaluate(envelope,PolicyLoader(path).load())
