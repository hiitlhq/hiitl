"""Numeric-domain admission happens before effects, projection or redaction.

sync_engine.md#numeric-domain; historical records still verify under unchanged C.
"""
from hiitl.sdk.exceptions import AuditLogError,SyncError,ServerError,ConfigurationError,EnvelopeValidationError
import copy
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock
import httpx
import pytest
from hiitl.core import PolicyEvaluator
from hiitl.core.types import Envelope, PolicySet, Decision
from hiitl.core.numeric_domain import NumericDomainError
from hiitl.core.redaction import Redaction
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.config import ClientSettings, HostedModeConfig, SyncConfig
from hiitl.sdk.http_client import HostedClient
from hiitl.sdk.sync_client import SyncClient
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.telemetry import TelemetryCollector

ROOT=Path(__file__).resolve().parents[4]
B=json.loads((ROOT/'tests/conformance/numeric_domain/cases.json').read_text())['bound']
ENV={'schema_version':'v2.0','org_id':'org_1234567890abcdef','environment':'dev','agent_id':'fixture','action_id':'act_01234567890123456789','idempotency_key':'numeric','action':'read','operation':'execute','target':{},'parameters':{},'timestamp':'2026-11-14T00:00:00Z','signature':'0'*64}
POL={'name':'numeric','version':'v1.0.0','description':'numeric admission','scope':{'org_id':ENV['org_id'],'environment':'dev'},'rules':[]}
DEC={'action_id':ENV['action_id'],'decision':'ALLOW','allowed':True,'reason_codes':[],'policy_version':'v1.0.0','timing':{'ingest_ms':0,'evaluation_ms':0,'total_ms':0}}

@pytest.mark.parametrize('surface',['envelope','policy','enrichment'])
def test_existing_mutated_models_cannot_bypass_evaluation_admission(surface):
    env=Envelope.model_validate(ENV);policy=PolicySet.model_validate(POL);enrichment={}
    assert PolicyEvaluator().evaluate(env,policy).decision=='BLOCK'
    if surface=='envelope':env.parameters['probe']=B
    elif surface=='policy':policy.metadata={'probe':B}
    else:enrichment={'route':{'probe':B}}
    with pytest.raises(NumericDomainError,match='probe.*text'):
        PolicyEvaluator().evaluate(env,policy,enrichment=enrichment)

@pytest.mark.parametrize('surface',['envelope','decision','held_result','result','redacted'])
def test_audit_refuses_raw_numbers_before_any_record_is_added(surface,tmp_path):
    redaction=Redaction.declared(['parameters.probe']) if surface=='redacted' else None
    store=AuditLogger(str(tmp_path/'audit.db'),redaction=redaction)
    env=copy.deepcopy(ENV);decision=copy.deepcopy(DEC)
    event=store.write(env,decision); decided=store.lifecycle(ENV['org_id'],'dev',ENV['action_id'])[0]
    assert store.verify_integrity(event)
    if surface in ('envelope','redacted'):
        env['parameters']['probe']=B;call=lambda:store.write(env,decision)
    elif surface=='decision':
        model=Decision.model_validate(decision);model.timing.total_ms=float('nan')
        call=lambda:store.write(env,model)
    elif surface=='held_result':call=lambda:store.hold_result(ENV['action_id'],{'probe':B})
    else:call=lambda:store.write_result(decided,{'status':'succeeded','probe':B})
    with pytest.raises(AuditLogError,match='JSON number' if surface=='decision' else 'not declared' if surface in ('held_result','result') else 'text'):call()
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM audit_log').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM held_results').fetchone()[0]==0


def test_a_stored_historical_record_remains_readable_and_verifiable(tmp_path):
    case=json.loads((ROOT/'tests/conformance/audit_hash/case_001_fixed_record.json').read_text())
    store=AuditLogger(str(tmp_path/'old.db'))
    env=copy.deepcopy(ENV);event=store.write(env,DEC)
    # Restore exact existing fixture bytes/hash as a previously stored row, not a new writer call.
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('UPDATE audit_log SET event_id=?, envelope=?, decision=?, content_hash=? WHERE event_id=?',(case['event_id'],json.dumps(case['envelope']),json.dumps(case['decision']),case['expected']['content_hash'],event))
    assert store.get_unsynced()[0]['content_hash']==case['expected']['content_hash']
    assert store.verify_integrity(case['event_id']) is True
    with pytest.raises(AuditLogError):store.write(case['envelope'],case['decision'])

@pytest.mark.parametrize('channel',['policies','routes','kill_switches'])
def test_cache_refuses_before_memory_or_disk_update(channel,tmp_path):
    cache=SyncCache(str(tmp_path),ENV['org_id'],'dev')
    value=[{'probe':B}] if channel=='routes' else {'probe':B}
    with pytest.raises(SyncError,match='probe.*text'):
        getattr(cache,'update_'+channel)(value)
    assert getattr(cache,'get_'+channel)() is None
    assert list(tmp_path.rglob('*.json'))==[]

@pytest.mark.parametrize('field',['dedup_window_seconds','timeout','max_retries'])
def test_configuration_admits_numbers_before_type_conversion(field):
    assert getattr(ClientSettings(**{field:1}),field)==1
    with pytest.raises(ValueError,match=field+'.*JSON (integer|number)'):ClientSettings(**{field:B})


def test_hosted_refuses_before_push_or_send(tmp_path,monkeypatch):
    config=HostedModeConfig(environment='dev',agent_id='fixture',org_id=ENV['org_id'],api_key='local-contract-fixture-key',server_url='https://fixture.invalid',audit_db_path=str(tmp_path/'audit.db'))
    client=HostedClient(config);push=Mock(return_value=None);ask=Mock(return_value=(httpx.Response(200,json=DEC),None))
    monkeypatch.setattr(client,'_push_first',push);monkeypatch.setattr(client,'_ask',ask)
    env=copy.deepcopy(ENV);env['parameters']['probe']=B
    with pytest.raises(EnvelopeValidationError,match='probe.*text'):client.evaluate(env)
    assert push.call_count==0 and ask.call_count==0
    client.close()


def test_hosted_response_guard_precedes_unknown_field_projection():
    client=object.__new__(HostedClient)
    assert client._parse_response(httpx.Response(200,json=DEC)).decision=='ALLOW'
    with pytest.raises(ServerError,match='probe.*text'):
        client._parse_response(httpx.Response(200,json={**DEC,'unread':{'probe':B}}))

@pytest.mark.parametrize('channel',['audit','telemetry'])
def test_new_sync_input_refuses_before_send(channel,monkeypatch):
    client=SyncClient('https://fixture.invalid','fixture',ENV['org_id'],'dev');send=Mock(return_value=httpx.Response(200,json={'accepted':1}))
    monkeypatch.setattr(client,'_send_with_retry',send)
    call=(lambda:client.upload_audit([],B)) if channel=='audit' else (lambda:client.upload_telemetry([{'probe':B}]))
    with pytest.raises(SyncError,match='sync_sequence.*JSON integer' if channel=='audit' else 'probe.*text'):call()
    assert send.call_count==0
    client.close()


@pytest.mark.parametrize('surface',['envelope','decision'])
def test_telemetry_refuses_raw_input_before_aggregation(surface):
    collector=TelemetryCollector(ENV['org_id'],'dev',level='full')
    env=Envelope.model_validate(ENV);decision=Decision.model_validate(DEC)
    if surface=='envelope':env.parameters['probe']=B
    else:decision.timing.total_ms=B
    with pytest.raises(NumericDomainError,match='text' if surface=='envelope' else 'total_ms.*JSON number'):collector.record(env,decision)
    assert collector.status()['window_eval_count']==0
    assert collector.status()['total_evaluations']==0

@pytest.mark.parametrize('method',['download_policies','download_routes','poll_kill_switches'])
def test_sync_replies_are_admitted_before_member_projection(method,monkeypatch):
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev')
    monkeypatch.setattr(client,'_send_with_retry',lambda *a,**kw:httpx.Response(200,json={'policies':[],'routes':[],'kill_switches':[],'unread':{'probe':B}}))
    with pytest.raises(SyncError,match='probe.*text'):getattr(client,method)()
    client.close()


def test_cache_disk_read_refuses_without_rewriting_prior_bytes(tmp_path):
    import hashlib
    cache=SyncCache(str(tmp_path),ENV['org_id'],'dev');cache.update_policies({'policies':[]})
    path=next(tmp_path.rglob('policies.json'));raw=json.dumps({'policies':[],'probe':B}).encode();path.write_bytes(raw)
    Path(str(path)+'.sha256').write_text(hashlib.sha256(raw).hexdigest())
    with pytest.raises(SyncError,match='probe.*text'):
        SyncCache(str(tmp_path),ENV['org_id'],'dev').load_from_disk()
    assert path.read_bytes()==raw


def test_environment_configuration_numbers_are_checked_after_text_read(monkeypatch):
    monkeypatch.setenv('HIITL_DEDUP_WINDOW_SECONDS',str(B))
    with pytest.raises(ValueError,match='dedup_window_seconds.*JSON integer'):ClientSettings()


def test_model_record_projection_cannot_erase_nonfinite_values():
    from hiitl.sdk.audit import envelope_record
    env=Envelope.model_validate(ENV);env.parameters['probe']=float('nan')
    with pytest.raises(NumericDomainError,match='probe.*text'):envelope_record(env)

@pytest.mark.parametrize('surface',['sync','cache','telemetry'])
def test_numeric_settings_of_direct_helpers_are_admitted(surface,tmp_path):
    calls={'sync':lambda:SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev',timeout=B),
           'cache':lambda:SyncCache(str(tmp_path),ENV['org_id'],'dev',max_stale_age=B),
           'telemetry':lambda:TelemetryCollector(ENV['org_id'],'dev',sample_rate=B)}
    with pytest.raises(ConfigurationError,match='JSON number'):calls[surface]()

from typing import get_args
from hiitl.sdk.config import LocalModeConfig
CONFIGS=[(ClientSettings,{}),(LocalModeConfig,{'org_id':ENV['org_id'],'environment':'dev','agent_id':'fixture'}),(HostedModeConfig,{'org_id':ENV['org_id'],'environment':'dev','agent_id':'fixture','api_key':'local-contract-fixture-key','server_url':'https://fixture.invalid'}),(SyncConfig,{})]
CONFIG_FIELDS=[(model,base,name,field) for model,base in CONFIGS for name,field in model.model_fields.items() if ({field.annotation} | set(get_args(field.annotation))) & {int,float}]

@pytest.mark.parametrize('model,base,name,field',CONFIG_FIELDS,ids=[f'{m.__name__}.{n}' for m,b,n,f in CONFIG_FIELDS])
def test_native_numeric_settings_do_not_coerce_bool_or_text(model,base,name,field):
    control=field.default if field.default is not None else 1
    assert getattr(model(**base,**{name:control}),name)==control
    for key in dict.fromkeys([name,field.validation_alias] if isinstance(field.validation_alias,str) else [name]):
        for value in [True,str(control)]:
            with pytest.raises(ValueError,match=name+'.*native number'):
                model(**base,**{key:value})

@pytest.mark.parametrize('model,base,name,field',CONFIG_FIELDS,ids=[f'{m.__name__}.{n}' for m,b,n,f in CONFIG_FIELDS])
def test_declared_environment_numeric_text_keeps_its_settings_read(model,base,name,field,monkeypatch):
    control=field.default if field.default is not None else 1
    key=field.validation_alias if isinstance(field.validation_alias,str) else model.model_config['env_prefix']+name.upper()
    monkeypatch.setenv(key,str(control))
    assert getattr(model(**base),name)==control


def test_telemetry_output_is_admitted_before_window_reset_or_buffer(monkeypatch):
    collector=TelemetryCollector(ENV['org_id'],'dev',level='full')
    collector.record(Envelope.model_validate(ENV),Decision.model_validate(DEC))
    before=collector.status().copy()
    build=collector._build_record
    def invalid_record(*args):
        value=build(*args);value['system_metrics']['total_evaluations']=B;return value
    monkeypatch.setattr(collector,'_build_record',invalid_record)
    with pytest.raises(NumericDomainError,match='total_evaluations.*JSON integer'):collector.flush()
    assert collector.status()==before
    assert collector.get_pending()==[]
    monkeypatch.setattr(collector,'_build_record',build)
    record=collector.flush()
    assert record['system_metrics']['total_evaluations']==1
    assert collector.get_pending()==[record]
    assert collector.status()['window_eval_count']==0
