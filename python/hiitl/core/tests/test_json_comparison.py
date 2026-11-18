"""policy_format.md JSON-value comparison, all six operator consumers."""
import pytest
from hiitl.core import PolicyEvaluator
from hiitl.core.tests.json_comparison_support import DATA,inputs,outcome

@pytest.mark.parametrize('row',DATA['cases'],ids=lambda row:row['id'])
def test_declared_comparison_answer(row):
    policy,envelope=inputs(row)
    assert outcome(PolicyEvaluator().evaluate(envelope,policy))==row['expected']

@pytest.mark.parametrize('operator',DATA['operators'])
@pytest.mark.parametrize('missing',[False,True],ids=['explicit-null','absent'])
def test_comparison_preserves_field_gate(operator,missing):
    row={'operator':operator,'left':None,'right':[None] if operator in ('in','not_in') else None}
    policy,envelope=inputs(row)
    if missing:del envelope['parameters']['probe']
    assert outcome(PolicyEvaluator().evaluate(envelope,policy))=={'decision':'BLOCK','allowed':False,'reason_codes':['NO_MATCHING_RULE']}

@pytest.mark.parametrize('left,right,same',[
    ({'__proto__':{'constructor':[None,True,0.1]}},{'__proto__':{'constructor':[None,True,0.1]}},True),
    ({'__proto__':1},{},False),({'constructor':1},{'toString':1},False),
    ([1,2],[2,1],False),([1],[1,1],False),(1,1.0,True),('A','a',False),
    ({'a':[None,{'x':True}]},{'a':[None,{'x':1}]},False),
])
def test_recursive_values_and_own_keys(left,right,same):
    policy,envelope=inputs({'operator':'equals','left':left,'right':right})
    assert PolicyEvaluator().evaluate(envelope,policy).allowed is same
    # The same comparison receives a field reference after the existing path read.
    envelope['parameters']['other']=right
    policy['rules'][0]['conditions']['value']={'$field':'parameters.other'}
    assert PolicyEvaluator().evaluate(envelope,policy).allowed is same

MODEL_OBJECTS = [
    ('cost_estimate', {'tokens': 1}, {'tokens': 1}, True),
    ('cost_estimate', {'tokens': 1}, {'tokens': 2}, False),
    ('cost_estimate', {}, {}, True),
    ('principal', {'sub': 'user', 'verified_by': 'sdk_verifier'}, {'verified_by': 'sdk_verifier', 'sub': 'user'}, True),
    ('principal', {'sub': 'user', 'verified_by': 'sdk_verifier'}, {'sub': 'other', 'verified_by': 'sdk_verifier'}, False),
]


@pytest.mark.parametrize('field,left,right,same', MODEL_OBJECTS)
def test_declared_model_objects_compare_supplied_members(field,left,right,same):
    policy,envelope=inputs({'operator':'equals','left':left,'right':right})
    envelope[field]=left
    policy['rules'][0]['conditions']['field']=field
    assert PolicyEvaluator().evaluate(envelope,policy).allowed is same

from datetime import datetime, timezone, timedelta


@pytest.mark.parametrize('operator', DATA['operators'])
def test_native_envelope_dates_compare_their_existing_json_text(operator):
    left = datetime(2026,11,14,1,tzinfo=timezone.utc)
    right = datetime(2026,11,14,2,tzinfo=timezone(timedelta(hours=1)))
    # The same native inputs now enter through their declared envelope fields;
    # different existing JSON spellings remain different, even at one instant.
    from hiitl.core import Envelope
    from hiitl.core.tests.date_text_support import ORIGINAL
    import copy
    raw = copy.deepcopy(ORIGINAL[0]['envelope'])
    raw['timestamp'] = left; raw['principal']['verified_at'] = right
    envelope = Envelope.model_validate(raw)
    left, right = envelope.timestamp, envelope.principal.verified_at
    left_value = [left] if operator in ('contains','not_contains') else left
    right_value = [right] if operator in ('in','not_in') else right
    expected = operator in ('not_equals','not_contains','not_in')
    assert PolicyEvaluator()._evaluate_operator(left_value,operator,right_value) is expected


@pytest.mark.parametrize('operator',['in','not_in'])
@pytest.mark.parametrize('left,right,contained',[
    ('ab','abc',True),(['ab'],'abc',True),('absent','abc',False),
    ('key',{'key':1},True),(['key'],{'key':1},True),('absent',{'key':1},False),
])
def test_nonarray_rhs_is_a_declared_operand_failure(operator,left,right,contained):
    from hiitl.core.operator_kinds import OperatorKindError
    with pytest.raises(OperatorKindError, match=operator):
        PolicyEvaluator()._evaluate_operator(left,operator,right)


@pytest.mark.parametrize('operator',['in','not_in'])
@pytest.mark.parametrize('right',[None,True,1])
def test_noniterable_rhs_is_a_declared_operand_failure(operator,right):
    from hiitl.core.operator_kinds import OperatorKindError
    with pytest.raises(OperatorKindError, match=operator):
        PolicyEvaluator()._evaluate_operator('probe',operator,right)
