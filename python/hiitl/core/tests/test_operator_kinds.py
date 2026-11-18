"""policy_format.md: all operand kinds, literal admission and settled condition trees."""
import pytest
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import PolicySet
from .operator_kind_support import DATA,inputs,evaluated,assert_named

@pytest.mark.parametrize('row',DATA['cases'],ids=lambda r:r['id'])
def test_source_operand_answer(row):
    policy,envelope=inputs(row)
    try:loaded=PolicySet.model_validate(policy)
    except Exception as error:
        assert row['expected']=={'stage':'load'}
        assert_named(error,row)
        return
    actual,error=evaluated(PolicyEvaluator(),envelope,loaded)
    assert actual==row['expected']
    if error:assert_named(error,row)

@pytest.mark.parametrize('logical,settle',[('all_of',False),('any_of',True),('none_of',True)])
@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('nested',[False,True])
@pytest.mark.parametrize('settled',[False,True])
def test_mismatch_is_carried_until_the_tree_is_settled(logical,settle,reverse,nested,settled):
    row={'operator':'greater_than','left':'private-operand-value','right':1,'reference':False}
    policy,envelope=inputs(row);bad=policy['rules'][0]['conditions']
    if nested:bad={'any_of':[bad,{'field':'action','operator':'equals','value':'never-this-action'}]}
    truth=settle if settled else not settle
    good={'field':'action','operator':'equals','value':envelope['action'] if truth else 'never-this-action'}
    children=[bad,good];children.reverse() if reverse else None
    policy['rules'][0]['conditions']={logical:children}
    actual,error=evaluated(PolicyEvaluator(),envelope,policy)
    expected={'stage':'decision','matched':False if logical in ('all_of','none_of') else True} if settled else {'stage':'operand'}
    assert actual==expected
    if error:
        assert_named(error,row)
        assert 'private-operand-value' not in str(error)

@pytest.mark.parametrize('on_missing',['skip','fail_closed'])
@pytest.mark.parametrize('null',[False,True])
def test_missing_and_null_still_use_the_existing_gate(on_missing,null):
    row={'operator':'greater_than','left':None,'right':1,'reference':False}
    policy,envelope=inputs(row);policy['on_missing']=on_missing
    if not null:envelope['parameters'].pop('probe')
    decision=PolicyEvaluator().evaluate(envelope,policy)
    assert (decision.decision,decision.allowed,decision.reason_codes)==('BLOCK',False,['MISSING_FIELD' if on_missing=='fail_closed' else 'NO_MATCHING_RULE'])


def test_conforms_to_sees_declared_model_members_and_child_mismatch_is_false():
    row={'operator':'conforms_to','left':{},'right':{'properties':{'dollars':{'type':'number'}}},'reference':False}
    policy,envelope=inputs(row);policy['rules'][0]['conditions']['field']='cost_estimate'
    envelope['cost_estimate']={'dollars':1}
    assert PolicyEvaluator().evaluate(envelope,policy).allowed is True
    policy['rules'][0]['conditions']['value']['properties']['dollars']['type']='string'
    assert PolicyEvaluator().evaluate(envelope,policy).allowed is False


@pytest.mark.parametrize('row',[row for row in DATA['cases'] if row['expected']=={'stage':'load'} and not row['reference']],ids=lambda r:r['id'])
def test_declared_rhs_kind_does_not_depend_on_held_date_left(row):
    from datetime import datetime,timezone
    from hiitl.core.operator_kinds import OperatorKindError
    with pytest.raises(OperatorKindError,match=row['operator']):
        PolicyEvaluator()._evaluate_operator(datetime(2026,11,15,tzinfo=timezone.utc),row['operator'],row['right'])


@pytest.mark.parametrize('row',[r for r in DATA['cases'] if r['expected']=={'stage':'load'}],ids=lambda r:r['id'])
def test_direct_condition_literal_admission(row):
    from hiitl.core.types import Condition
    policy,_=inputs(row)
    error=None
    try:Condition.model_validate(policy['rules'][0]['conditions'])
    except ValueError as caught:error=caught
    assert error is not None
    assert row['operator'] in str(error)
    assert 'parameters.probe' in str(error)
