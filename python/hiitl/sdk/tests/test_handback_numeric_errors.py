"""aa0cf726/88579bbd: public refusals retain their documented error and cause.

The configuration members come from the models, and each named public input is
exercised through its actual entry. Open-data remedies and typed remedies differ.
"""
import copy, json
from pathlib import Path
from typing import get_args
import pytest, yaml
from hiitl.sdk import HIITL
from hiitl.sdk.config import ClientSettings
from hiitl.sdk.exceptions import ConfigurationError, EnvelopeValidationError, LifecycleError, PolicyLoadError
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.core.numeric_domain import NUMERIC_BOUND
from hiitl.sdk.tests.test_numeric_boundaries import ENV,POL

CONFIG_NUMBERS=[name for name,field in ClientSettings.model_fields.items() if {field.annotation,*get_args(field.annotation)} & {int,float}]

def typed(error,path,kind,limits=()):
    text=str(error)
    assert '<root>'+''.join('['+json.dumps(p)+']' for p in path) in text
    assert kind in text and str(NUMERIC_BOUND) in text
    for value in limits: assert f'{value:g}' in text
    assert 'pass the value as text' not in text

@pytest.mark.parametrize('name',CONFIG_NUMBERS)
def test_constructor_numeric_members_use_configuration_error(name,tmp_path):
    with public_error(ConfigurationError) as caught:
        HIITL(**{name:NUMERIC_BOUND},audit_db_path=str(tmp_path/'config.db'),sync=False)
    field=ClientSettings.model_fields[name]
    typed(caught.value,[name],'integer' if int in {field.annotation,*get_args(field.annotation)} else 'number',
          (0.1,30) if name=='timeout' else (0,10) if name=='max_retries' else ())

@pytest.mark.parametrize('format',['json','yaml'])
@pytest.mark.parametrize('path',[['metadata','probe'],['rules',0,'priority']])
def test_policy_loader_numeric_refusal_is_cause_not_syntax(format,path,tmp_path):
    data=copy.deepcopy(POL)
    data['rules']=[{'name':'r','description':'r','priority':1,'conditions':{'all_of':[]},'decision':'BLOCK','reason_code':'R'}]
    data['metadata']={'probe':1}
    file=tmp_path/('policy.'+format)
    write=lambda: file.write_text(json.dumps(data) if format=='json' else yaml.safe_dump(data))
    write();assert PolicyLoader(file).load().name==data['name']
    parent=data
    for part in path[:-1]:parent=parent[part]
    parent[path[-1]]=NUMERIC_BOUND;write()
    with public_error(PolicyLoadError) as caught:PolicyLoader(file).load()
    assert caught.value.reason=='POLICY_VALIDATION_ERROR'
    if path[-1]=='priority':typed(caught.value,path,'integer')
    else:
        assert '<root>["metadata"]["probe"]' in str(caught.value)
        assert 'pass the value as text' in str(caught.value)
    assert 'syntax errors' not in str(caught.value) and 'readable' not in str(caught.value)

@pytest.mark.parametrize('mode',['local','hybrid','hosted'])
def test_public_result_has_body_path_in_every_mode(mode,tmp_path,monkeypatch):
    import httpx
    from hiitl.sdk.tests.test_numeric_boundaries import DEC
    monkeypatch.setattr(SyncEngine,'initial_sync',lambda *a,**kw:True)
    monkeypatch.setattr(SyncEngine,'start',lambda *a,**kw:None)
    monkeypatch.setattr(SyncEngine,'stop',lambda *a,**kw:None)
    def respond(self,request,*a,**kw):
        body=json.loads(request.content)
        return httpx.Response(200,request=request,json={**DEC,'action_id':body.get('action_id',ENV['action_id'])} if request.url.path.endswith('/evaluate') else {'execution_result':body})
    monkeypatch.setattr(httpx.Client,'send',respond)
    client=HIITL(sync=mode!='local',api_key='local-contract-fixture-key' if mode!='local' else None,
                 evaluation='remote' if mode=='hosted' else 'local',signature_key='local-fixture-signing-secret',server_url='https://fixture.invalid',
                 org_id=ENV['org_id'],environment='dev',cache_dir=str(tmp_path/'cache'),audit_db_path=str(tmp_path/'results.db'))
    try:
        assert client._mode==mode
        decision=client.evaluate('read')
        assert client.record_result(decision.action_id,'succeeded',duration_ms=1)['execution_result']['duration_ms']==1
        with public_error(LifecycleError) as caught:client.record_result(decision.action_id,'succeeded',duration_ms=NUMERIC_BOUND)
        assert caught.value.reason=='RESULT_INVALID'
        typed(caught.value,['duration_ms'],'number',(0,))
    finally:client.close()

@pytest.mark.parametrize('options,path,kind',[
    ({'parameters':{'probe':NUMERIC_BOUND}},['parameters','probe'],None),
    ({'confidence':NUMERIC_BOUND},['confidence'],'number'),
    ({'cost_estimate':{'api_calls':NUMERIC_BOUND}},['cost_estimate','api_calls'],'integer'),
])
def test_evaluate_numeric_refusal_precedes_envelope(options,path,kind,tmp_path):
    client=HIITL(sync=False,audit_db_path=str(tmp_path/'evaluate.db'))
    try:
        assert client.evaluate('read').allowed
        with public_error(EnvelopeValidationError) as caught:client.evaluate('read',**options)
        if kind:typed(caught.value,path,kind)
        else:assert '<root>["parameters"]["probe"]' in str(caught.value) and 'pass the value as text' in str(caught.value)
    finally:client.close()

@pytest.mark.parametrize('bad',[False,True])
def test_verifier_claims_are_supplied_input_before_projection(bad,tmp_path):
    policy=copy.deepcopy(POL)
    policy['rules']=[{'name':'identity','description':'identity','priority':2,'conditions':{'field':'principal.sub','operator':'exists','value':False},'decision':'BLOCK','reason_code':'NO_ID'}, {'name':'allow','description':'allow','priority':1,'conditions':{'all_of':[]},'decision':'ALLOW','reason_code':'OK'}]
    file=tmp_path/'policy.json';file.write_text(json.dumps(policy))
    client=HIITL(sync=False,mode='RESPECT_POLICY',policy_path=str(file),audit_db_path=str(tmp_path/'claims.db'),principal_verifier=lambda token:{'sub':'verified','unread':{'probe':NUMERIC_BOUND if bad else 1}})
    try:assert client.evaluate('read',principal_token='fixture').decision==('BLOCK' if bad else 'ALLOW')
    finally:client.close()

# The same canonical member corpus drives both SDKs' actual file entries.
from hiitl.sdk.route_loader import RouteLoader
from hiitl.sdk.exceptions import RouteLoadError, SyncError
from hiitl.sdk.sync_client import SyncClient
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.sync_engine import SyncEngine
ROOT=Path(__file__).resolve().parents[4]
MEMBERS=json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['cases']
FILE_MEMBERS=[r for r in MEMBERS if r['format'] in ('policy','routes')]
@pytest.mark.parametrize('format',['json','yaml'])
@pytest.mark.parametrize('row',FILE_MEMBERS,ids=lambda r:r['id'])
def test_each_file_numeric_member_retains_its_declared_remedy(row,format,tmp_path,monkeypatch):
    monkeypatch.setenv('HTL41_ROUTE_FIXTURE','local-fixture')
    data=copy.deepcopy(row['control'])
    file=tmp_path/(data['name']+'.'+format)
    def write():file.write_text(json.dumps(data) if format=='json' else yaml.safe_dump(data))
    def load():return PolicyLoader(file).load() if row['format']=='policy' else RouteLoader(str(tmp_path)).get(data['name'])
    write();assert load().name==data['name']
    at=data
    for part in row['path'][:-1]:at=at[part]
    at[row['path'][-1]]=NUMERIC_BOUND;write()
    with public_error(PolicyLoadError if row['format']=='policy' else RouteLoadError)as caught:load()
    if row['format']=='policy':assert caught.value.reason=='POLICY_VALIDATION_ERROR'
    else:assert getattr(caught.value,'reason',None) is None
    typed(caught.value,row['path'],row['type'],row['range'].values())

SYNC_NUMBERS=[name for name,field in SyncConfig.model_fields.items() if field.annotation in (int,float)]
@pytest.mark.parametrize('name',SYNC_NUMBERS)
def test_supplied_sync_settings_use_constructor_refusal(name,tmp_path,monkeypatch):
    monkeypatch.setattr(SyncEngine,'initial_sync',lambda *a,**kw:True)
    monkeypatch.setattr(SyncEngine,'start',lambda *a:None)
    settings=SyncConfig(cache_dir=str(tmp_path/'cache'))
    client=HIITL(api_key='local-contract-fixture-key',org_id=ENV['org_id'],environment='dev',sync_config=settings,audit_db_path=str(tmp_path/'good.db'))
    assert client._mode=='hybrid';client.close()
    setattr(settings,name,NUMERIC_BOUND)
    with public_error(ConfigurationError)as caught:HIITL(api_key='local-contract-fixture-key',org_id=ENV['org_id'],environment='dev',sync_config=settings,audit_db_path=str(tmp_path/'bad.db'))
    typed(caught.value,[name],'integer' if SyncConfig.model_fields[name].annotation is int else 'number')

@pytest.mark.parametrize('channel,method',[('policy','download_policies'),('routes','download_routes'),('kill_switches','poll_kill_switches')])
def test_sync_reply_numeric_refusal_uses_its_channel(channel,method,monkeypatch):
    import httpx
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev')
    data={'policies':[],'routes':[],'kill_switches':[]}
    monkeypatch.setattr(client,'_send_with_retry',lambda *a,**kw:httpx.Response(200,json=data))
    try:
        getattr(client,method)()
        data['metadata']={'probe':NUMERIC_BOUND}
        with public_error(SyncError)as caught:getattr(client,method)()
        assert caught.value.channel==channel
        assert '<root>["metadata"]["probe"]' in str(caught.value)
        assert 'pass the value as text' in str(caught.value)
    finally:client.close()

from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.http_client import HostedClient
from hiitl.sdk.config import HostedModeConfig

@pytest.mark.parametrize('channel',['policies','routes','kill_switches'])
def test_cache_numeric_refusal_preserves_its_channel_and_prior_contents(channel,tmp_path):
    cache=SyncCache(str(tmp_path),ENV['org_id'],'dev')
    control=[] if channel=='routes' else {'policies':[]} if channel=='policies' else {'kill_switches':[],'policy_set':None}
    getattr(cache,'update_'+channel)(control)
    prior=copy.deepcopy(getattr(cache,'get_'+channel)())
    before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    data=[{'metadata':{'probe':NUMERIC_BOUND}}] if channel=='routes' else {'metadata':{'probe':NUMERIC_BOUND}}
    with public_error(SyncError)as caught:getattr(cache,'update_'+channel)(data)
    assert caught.value.channel==('policy' if channel=='policies' else channel)
    assert '<root>'+('[0]' if channel=='routes' else '')+'["metadata"]["probe"]' in str(caught.value)
    assert 'pass the value as text' in str(caught.value)
    assert getattr(cache,'get_'+channel)()==prior
    assert {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before

@pytest.mark.parametrize('member',['duration_ms','probe'])
def test_exported_hosted_result_uses_lifecycle_refusal(member,tmp_path,monkeypatch):
    config=HostedModeConfig(environment='dev',agent_id='fixture',org_id=ENV['org_id'],api_key='local-contract-fixture-key',server_url='https://fixture.invalid',audit_db_path=str(tmp_path/'hosted.db'))
    client=HostedClient(config)
    monkeypatch.setattr(client,'_push_first',lambda:(_ for _ in ()).throw(AssertionError('refused input reached the drain')))
    try:
        with public_error(LifecycleError)as caught:client.record_result(ENV['action_id'],{'status':'succeeded',member:NUMERIC_BOUND})
        assert caught.value.reason=='RESULT_INVALID'
        if member=='duration_ms':typed(caught.value,[member],'number',(0,))
        else:assert '<root>["probe"]' in str(caught.value) and 'not declared' in str(caught.value)
    finally:client.close()

@pytest.mark.parametrize('component,member,kind',[
    ('sync','timeout','number'),('sync','max_retries','integer'),('cache','max_stale_age','number'),
    ('telemetry','buffer_size','integer'),('telemetry','sample_rate','number'),
])
def test_component_constructor_refusal_keeps_configuration_error(component,member,kind,tmp_path):
    from hiitl.sdk.telemetry import TelemetryCollector
    def construct(value):
        options={member:value}
        if component=='sync':return SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev',**options)
        if component=='cache':return SyncCache(str(tmp_path),ENV['org_id'],'dev',**options)
        return TelemetryCollector(ENV['org_id'],'dev',**options)
    control=construct(1)
    if component=='sync':control.close()
    with public_error(ConfigurationError)as caught:construct(NUMERIC_BOUND)
    typed(caught.value,[member],kind)

@pytest.mark.parametrize('member',['status','error'])
def test_result_nonnumeric_member_does_not_offer_numeric_text(member,tmp_path):
 client=HIITL(sync=False,audit_db_path=str(tmp_path/'result-kind.db'))
 try:
  with public_error(LifecycleError)as caught:client.record_result('act_01234567890123456789',NUMERIC_BOUND if member=='status' else 'failed',**({'error':NUMERIC_BOUND}if member=='error' else {}))
  assert caught.value.reason=='RESULT_INVALID'
  assert '<root>["'+member+'"]'in str(caught.value)
  assert 'requires a JSON string'in str(caught.value)
  assert 'pass the value as text'not in str(caught.value)
 finally:client.close()

from hiitl.core.tests.handback_assertions import public_error

@pytest.mark.parametrize('mode',['local','hybrid','hosted'])
@pytest.mark.parametrize('row',[r for r in MEMBERS if r['format']=='envelope'],ids=lambda r:r['id'])
def test_each_public_evaluate_numeric_member_in_every_mode(row,mode,tmp_path,monkeypatch):
 import httpx
 from hiitl.sdk.tests.test_numeric_boundaries import DEC
 monkeypatch.setattr(SyncEngine,'initial_sync',lambda *a,**kw:True)
 monkeypatch.setattr(SyncEngine,'start',lambda *a,**kw:None)
 monkeypatch.setattr(SyncEngine,'stop',lambda *a,**kw:None)
 def respond(self,request,*a,**kw):
  body=json.loads(request.content)
  return httpx.Response(200,request=request,json={**DEC,'action_id':body.get('action_id',ENV['action_id'])})
 monkeypatch.setattr(httpx.Client,'send',respond)
 client=HIITL(sync=mode!='local',api_key='local-contract-fixture-key' if mode!='local' else None,evaluation='remote' if mode=='hosted' else 'local',signature_key='local-fixture-signing-secret',server_url='https://fixture.invalid',org_id=ENV['org_id'],environment='dev',cache_dir=str(tmp_path/'cache'),audit_db_path=str(tmp_path/'evaluate-matrix.db'))
 options={row['path'][0]:copy.deepcopy(row['control'][row['path'][0]])}
 try:
  assert client._mode==mode
  assert client.evaluate('read',**options).allowed
  at=options
  for part in row['path'][:-1]:at=at[part]
  at[row['path'][-1]]=NUMERIC_BOUND
  with public_error(EnvelopeValidationError)as caught:client.evaluate('read',**options)
  assert getattr(caught.value,'reason',None)is None
  typed(caught.value,row['path'],row['type'],row['range'].values())
 finally:client.close()
