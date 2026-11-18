"""Both real policy file formats read the source-derived operand corpus."""
import json
import pytest
import yaml
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.tests.operator_kind_support import DATA,inputs,evaluated,assert_named
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl import HIITL

@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('row',DATA['cases'],ids=lambda r:r['id'])
def test_file_operand_answer(row,wire,tmp_path):
    policy,envelope=inputs(row);path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    try:loaded=PolicyLoader(path).load()
    except Exception as error:
        assert row['expected']=={'stage':'load'}
        assert_named(error,row)
        return
    actual,error=evaluated(PolicyEvaluator(),envelope,loaded)
    assert actual==row['expected']
    if error:assert_named(error,row)

@pytest.mark.parametrize('mode',['RESPECT_POLICY','OBSERVE_ALL'])
def test_public_error_names_operator_and_fields_and_records_once(tmp_path,mode):
    row={'operator':'greater_than','left':'private-operand-value','right':1,'reference':True}
    policy,envelope=inputs(row);path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=envelope['org_id'],environment=envelope['environment'],agent_id=envelope['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode=mode)
    try:
        decision=client.evaluate(envelope['action'],parameters=envelope['parameters'])
        assert (decision.decision,decision.allowed,decision.reason_codes,decision.error.code)==('POLICY_ERROR',False,['POLICY_EVALUATION_FAILED'],'POLICY_ERROR')
        assert_named(decision.error.message,row)
        assert row['left'] not in decision.error.message
        records=client._audit_logger.get_unsynced(limit=10)
        assert [r['decision']['decision'] for r in records]==['POLICY_ERROR']
        assert records[0]['decision']['error']['message']==decision.error.message
    finally:client.close()


@pytest.mark.parametrize('operator',['in','not_in'])
def test_date_field_does_not_exempt_the_referenced_array_kind(tmp_path,operator):
    row={'operator':operator,'left':None,'right':'abc','reference':True}
    policy,envelope=inputs(row);policy['rules'][0]['conditions']['field']='timestamp'
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=envelope['org_id'],environment=envelope['environment'],agent_id=envelope['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY')
    try:
        decision=client.evaluate(envelope['action'],parameters=envelope['parameters'])
        assert (decision.decision,decision.allowed,decision.reason_codes)==('POLICY_ERROR',False,['POLICY_EVALUATION_FAILED'])
        assert operator in decision.error.message
        assert 'timestamp' in decision.error.message
        assert 'parameters.other' in decision.error.message
        assert [r['decision']['decision'] for r in client._audit_logger.get_unsynced(10)]==['POLICY_ERROR']
    finally:client.close()


@pytest.mark.parametrize('source',['local','hybrid','tick'])
@pytest.mark.parametrize('generic',[False,True])
def test_each_local_evaluation_entry_maps_only_typed_failures(tmp_path,source,generic):
    from types import SimpleNamespace
    from hiitl.core.error_decisions import MESSAGES
    row={'operator':'greater_than','left':'private-operand-value','right':1,'reference':True}
    policy,envelope=inputs(row);path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=envelope['org_id'],environment=envelope['environment'],agent_id=envelope['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY')
    if source!='local':
        client._mode='hybrid'
        from hiitl.core.types import PolicySet
        client._sync_cache=SimpleNamespace(tick_part=lambda:policy if source=='tick' else None,get_policy_set=lambda:PolicySet(**policy),cache_status=lambda:'synced')
    if generic:
        def fail(*args,**kwargs):raise RuntimeError('private-operand-value')
        client._evaluator.evaluate=fail
    try:
        decision=client.evaluate(envelope['action'],parameters=envelope['parameters'])
        assert (decision.decision,decision.allowed,decision.reason_codes)==('POLICY_ERROR',False,['POLICY_EVALUATION_FAILED'])
        if generic:assert decision.error.message==MESSAGES['POLICY_EVALUATION_FAILED']
        else:assert_named(decision.error.message,row)
        assert 'private-operand-value' not in decision.error.message
        records=client._audit_logger.get_unsynced(10)
        assert [r['decision']['error']['message'] for r in records]==[decision.error.message]
    finally:client.close()


def test_route_answer_kind_failure_is_recorded_after_actual_reevaluation(tmp_path):
    from copy import deepcopy
    from types import SimpleNamespace
    row={'operator':'greater_than','left':0,'right':1,'reference':False}
    policy,envelope=inputs(row)
    policy['rules'][0]['conditions']['field']='external.check.score'
    policy['rules'][0]['priority']=800
    route_rule=deepcopy(policy['rules'][0]);route_rule.update(name='ask',priority=500,decision='ROUTE',route='check',conditions={'field':'action','operator':'equals','value':envelope['action']})
    policy['rules'].append(route_rule)
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=envelope['org_id'],environment=envelope['environment'],agent_id=envelope['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY')
    route={'name':'check','direction':'bidirectional','response_schema':{'required_fields':['score']}}
    client._route_loader=SimpleNamespace(get=lambda name:route)
    asked=[]
    def answer(route,payload):asked.append(payload);return {'score':'private-operand-value'}
    client._ask_route=answer
    try:
        decision=client.evaluate(envelope['action'],parameters={})
        assert len(asked)==1
        assert (decision.decision,decision.allowed,decision.reason_codes)==('POLICY_ERROR',False,['POLICY_EVALUATION_FAILED'])
        assert 'greater_than' in decision.error.message and 'external.check.score' in decision.error.message
        assert 'private-operand-value' not in decision.error.message
        assert [r['decision']['error']['message'] for r in client._audit_logger.get_unsynced(10)]==[decision.error.message]
    finally:client.close()


@pytest.mark.parametrize('names,selected',[(('A','a'),'A'),(('é','e\u0301'),'e\u0301'),(('😀','\ue000'),'\ue000')])
@pytest.mark.parametrize('reverse',[False,True])
def test_multiple_failures_choose_the_same_code_point_order(tmp_path,names,selected,reverse):
    policy,envelope=inputs({'operator':'greater_than','left':'invalid','right':1,'reference':False})
    conditions=[{'field':'parameters.'+name,'operator':'greater_than','value':1} for name in names]
    if reverse:conditions.reverse()
    policy['rules'][0]['conditions']={'all_of':conditions}
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=envelope['org_id'],environment=envelope['environment'],agent_id=envelope['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY')
    try:
        decision=client.evaluate(envelope['action'],parameters={name:'invalid' for name in names})
        assert (decision.decision,decision.allowed)==('POLICY_ERROR',False)
        assert decision.error.message==f'Operator `greater_than` has an operand of the wrong declared kind at field `parameters.{selected}`. Correct the field value or policy to use the operator’s declared operand kinds.'
    finally:client.close()


@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('reference',[False,True])
@pytest.mark.parametrize('schema',DATA['schema_cases'],ids=lambda r:r['id'])
def test_referenced_parameter_schema_uses_literal_grammar(tmp_path,wire,reference,schema):
    row={'operator':'conforms_to','left':schema['left'],'right':schema['schema'],'reference':reference}
    policy,envelope=inputs(row);path=tmp_path/f'policy.{wire}'
    path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    expected={'stage':'load'} if not reference and not schema['valid_schema'] else {'stage':'operand'} if not schema['valid_schema'] and schema['schema'] is not None else {'stage':'decision','matched':schema['matched'] if schema['valid_schema'] else False}
    try:loaded=PolicyLoader(path).load()
    except Exception:
        assert expected=={'stage':'load'}
        return
    before=json.dumps(envelope,sort_keys=True)
    actual,error=evaluated(PolicyEvaluator(),envelope,loaded)
    assert json.dumps(envelope,sort_keys=True)==before
    assert actual==expected
    if error:assert_named(error,row)


@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('cost,expected',[({}, {'stage':'decision','matched':True}),({'dollars':1},{'stage':'operand'})])
def test_declared_object_reference_can_be_a_schema(tmp_path,wire,cost,expected):
    row={'operator':'conforms_to','left':{},'right':{},'reference':True}
    policy,envelope=inputs(row);policy['rules'][0]['conditions']['value']={'$field':'cost_estimate'};envelope['cost_estimate']=cost
    path=tmp_path/f'policy.{wire}';path.write_text(json.dumps(policy) if wire=='json' else yaml.safe_dump(policy))
    actual,error=evaluated(PolicyEvaluator(),envelope,PolicyLoader(path).load())
    assert actual==expected
    if error:
        assert 'conforms_to' in str(error)
        assert 'parameters.probe' in str(error)
        assert 'cost_estimate' in str(error)
