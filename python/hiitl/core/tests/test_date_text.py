"""The envelope's declared date text is data; instant readers remain separate."""
import copy,json,re
from datetime import datetime,timezone,timedelta
import pytest
from pydantic import TypeAdapter,ValidationError
from hiitl.core import Envelope,PolicyEvaluator
from hiitl.core.date_time import read
from hiitl.core.operator_kinds import OperatorKindError
from hiitl.core.tests.date_text_support import ROOT,DATA,ORIGINAL,at

@pytest.mark.parametrize('row',DATA['cases'],ids=lambda r:r['id'])
def test_source_date_operator_answer(row):
    if row['expected']=='error':
        with pytest.raises(OperatorKindError):PolicyEvaluator().evaluate(row['envelope'],row['policy'])
    else:assert PolicyEvaluator().evaluate(row['envelope'],row['policy']).allowed is row['expected']

@pytest.mark.parametrize('member',DATA['date_members'],ids=lambda r:str(r['path']))
def test_date_text_is_preserved_in_every_model_read_and_dump(member):
    rows=json.loads((ROOT/'tests/conformance/date_time/case_001_written_date_times.json').read_text())['date_times']
    for row in rows:
        written,instant=row[:2]
        raw=copy.deepcopy(ORIGINAL[0]['envelope']);parent=raw
        for key in member['path'][:-1]:parent=parent[key]
        parent[member['path'][-1]]=written
        if instant is None:
            with pytest.raises(ValidationError):Envelope.model_validate(raw)
            continue
        for model in (Envelope.model_validate(raw),Envelope.model_validate_json(json.dumps(raw))):
            assert at(model,member['path'])==written
            assert at(model.model_dump(mode='python'),member['path'])==written
            assert at(model.model_dump(mode='json'),member['path'])==written
            assert at(json.loads(model.model_dump_json()),member['path'])==written
            assert at(Envelope.model_validate(model),member['path'])==written
            assert read(at(model,member['path']))==read(written)

@pytest.mark.parametrize('member',DATA['date_members'],ids=lambda r:str(r['path']))
@pytest.mark.parametrize('zone',[timezone.utc,timezone(timedelta(hours=5,minutes=30)),timezone(-timedelta(hours=4))])
def test_native_datetime_has_its_existing_json_form(member,zone):
    value=datetime(2026,11,14,1,2,3,123456,tzinfo=zone);expected=TypeAdapter(datetime).dump_python(value,mode='json')
    raw=copy.deepcopy(ORIGINAL[0]['envelope']);parent=raw
    for key in member['path'][:-1]:parent=parent[key]
    parent[member['path'][-1]]=value
    model=Envelope.model_validate(raw)
    assert at(model,member['path'])==expected
    assert at(model.model_dump(mode='json'),member['path'])==expected
    parent[member['path'][-1]]=value.replace(tzinfo=None)
    with pytest.raises(ValidationError,match='offset'):Envelope.model_validate(raw)

def test_emitted_schema_keeps_each_declared_date_format():
    schema=Envelope.model_json_schema()
    for member in DATA['date_members']:
        node=schema
        for key in member['path']:
            while '$ref' in node:
                node=schema['$defs'][node['$ref'].split('/')[-1]]
            if 'anyOf' in node:node=next(c for c in node['anyOf'] if c.get('type')!='null')
            while '$ref' in node:node=schema['$defs'][node['$ref'].split('/')[-1]]
            node=node['properties'][key]
        if 'anyOf' in node:node=next(c for c in node['anyOf'] if c.get('type')!='null')
        assert node.get('type')=='string' and node.get('format')=='date-time'


def test_date_refusal_keeps_nested_location_and_authored_name():
    raw=copy.deepcopy(ORIGINAL[0]['envelope']);raw['principal']['verified_at']='2026-01-02T03:04:05+01:60'
    with pytest.raises(ValidationError) as caught:Envelope.model_validate(raw)
    errors=caught.value.errors()
    assert [error['loc'] for error in errors]==[('principal','verified_at')]
    assert "verified_at has offset minute 60; an offset's minute is 00 to 59" in errors[0]['msg']


@pytest.mark.parametrize('member',DATA['date_members'],ids=lambda r:str(r['path']))
@pytest.mark.parametrize('offset',[timedelta(0),timedelta(hours=1),timedelta(seconds=30),-timedelta(seconds=30),timedelta(seconds=30,microseconds=1),-timedelta(seconds=30,microseconds=1)])
def test_native_text_and_instant_survive_python_copies_but_json_is_just_text(member,offset):
    native=datetime(2026,11,14,1,2,3,123456,tzinfo=timezone(offset))
    expected=TypeAdapter(datetime).dump_python(native,mode='json')
    raw=copy.deepcopy(ORIGINAL[0]['envelope']);parent=raw
    for key in member['path'][:-1]:parent=parent[key]
    parent[member['path'][-1]]=native
    model=Envelope.model_validate(raw)
    # Omitted optional members stay omitted at a fresh mapping boundary; the
    # implementation's unset None defaults are not supplied JSON nulls.
    for carried in (model,model.model_copy(),model.model_copy(deep=True),copy.copy(model),copy.deepcopy(model),Envelope.model_validate(model.model_dump(mode='python',exclude_unset=True))):
        value=at(carried,member['path'])
        assert isinstance(value,str) and value==expected
        assert read(value)==native
        assert at(carried.model_dump(mode='json'),member['path'])==expected
        assert PolicyEvaluator()._resolve_field_path(carried,'.'.join(member['path'])+'._instant') is None
    written=json.loads(model.model_dump_json(exclude_unset=True))
    assert at(written,member['path'])==expected
    reparsed=Envelope.model_validate(written)
    assert read(at(reparsed,member['path']))==read(expected)


@pytest.mark.parametrize('offset',[timedelta(0),timedelta(seconds=30),-timedelta(seconds=30),timedelta(seconds=30,microseconds=1),-timedelta(seconds=30,microseconds=1)])
def test_native_temporal_remediation_reads_the_original_instant(offset):
    native=datetime(2026,11,14,1,2,3,123456,tzinfo=timezone(offset))
    raw=copy.deepcopy(ORIGINAL[0]['envelope']);raw['timestamp']=native
    policy=copy.deepcopy(ORIGINAL[0]['policy']);rule=policy['rules'][0]
    rule['conditions']={'field':'action','operator':'equals','value':raw['action']};rule['decision']='BLOCK'
    rule['remediation']={'type':'temporal','message':'An authored time rule','suggestion':'Retry later','details':{}}
    decision=PolicyEvaluator().evaluate(raw,policy)
    assert decision.remediation.details=={'current_time':native.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec='milliseconds')+'Z'}
