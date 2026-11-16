"""93d/5203: actual stored rows drain unchanged; new result intents stay supplied inputs."""
from hiitl.sdk.exceptions import AuditLogError,LifecycleError
import copy
import gzip
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from hiitl.core.canonical import AUDIT_FURTHER
from hiitl.core.numeric_domain import NumericDomainError
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.http_client import HostedClient
from hiitl.sdk.sync_client import SyncClient
from hiitl.sdk.sync_engine import SyncEngine

ROOT=Path(__file__).resolve().parents[4]
CASES=[json.loads(p.read_text()) for p in sorted((ROOT/'tests/conformance/audit_hash').glob('*.json'))]
BOUND=json.loads((ROOT/'tests/conformance/numeric_domain/cases.json').read_text())['bound']
ENV={'schema_version':'v2.0','org_id':'org_1234567890abcdef','environment':'dev','agent_id':'fixture','action_id':'act_01234567890123456789','idempotency_key':'history','action':'read','operation':'execute','target':{},'parameters':{},'timestamp':'2026-11-14T00:00:00Z','signature':'0'*64}
DEC={'action_id':ENV['action_id'],'decision':'ALLOW','allowed':True,'reason_codes':[],'policy_version':'v1.0.0','timing':{'ingest_ms':0,'evaluation_ms':0,'total_ms':0}}

def restore(store,case,last=False):
    """Restore a pre-rule fixed vector, without passing it through today's new writer."""
    event=store.write(ENV,DEC)
    values={'event_id':case['event_id'],'timestamp':'2090-01-01T00:00:00Z' if last else '2000-01-01T00:00:00Z',
        'envelope':json.dumps(case['envelope']),'decision':json.dumps(case['decision']),
        'content_hash':case['expected']['content_hash'],
        **{k:case['envelope'].get(k) for k in ['org_id','environment','action_id','action','agent_id']},
        'decision_type':case['decision']['decision'],'policy_version':case['decision']['policy_version'],
        **{k:json.dumps(case[k]) if k in case else None for k in AUDIT_FURTHER}}
    with sqlite3.connect(store.db_path) as db:
        db.execute('UPDATE audit_log SET '+','.join(k+'=?' for k in values)+' WHERE event_id=?',(*values.values(),event))
    return case['event_id']

def snapshot(store):
    with sqlite3.connect(store.db_path) as db:
        db.row_factory=sqlite3.Row
        return {r['event_id']:dict(r) for r in db.execute('SELECT * FROM audit_log')}

def hosted(path):
    return HostedClient(HostedModeConfig(org_id=ENV['org_id'],environment='dev',agent_id='fixture',api_key='local-contract-fixture-key',server_url='https://fixture.invalid',audit_db_path=str(path)))

@pytest.mark.parametrize('channel',['background','hosted'])
@pytest.mark.parametrize('last',[False,True])
@pytest.mark.parametrize('case',[None,*CASES],ids=['valid-only',*[c['event_id'] for c in CASES]])
def test_stored_records_and_followers_drain_as_written(channel,last,case,tmp_path):
    store=AuditLogger(str(tmp_path/'history.db'))
    if case:restore(store,case,last)
    store.write(ENV,DEC)
    before=snapshot(store); expected=store.get_unsynced(); sent=[]
    if case:
        old=next(r for r in expected if r['event_id']==case['event_id'])
        for member in ['envelope','decision',*AUDIT_FURTHER]:
            assert (member in old)==(member in case)
            if member in case:assert old[member]==case[member]
        assert old['content_hash']==case['expected']['content_hash']
        assert store.verify_integrity(case['event_id'])
        assert expected[-1 if last else 0]['event_id']==case['event_id']
    def transport(request):
        assert request.url.path=='/v1/sync/audit'
        raw=request.content
        if request.headers.get('Content-Encoding')=='gzip':raw=gzip.decompress(raw)
        payload=json.loads(raw);sent.append(payload)
        return httpx.Response(200,json={'accepted':len(payload['records']),'duplicates':0,'errors':[]})
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev') if channel=='background' else hosted(store.db_path)
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    if channel=='background':
        engine=object.__new__(SyncEngine);engine._audit_logger=store;engine._client=client
        engine._config=SimpleNamespace(audit_batch_size=100);engine._audit_sequence=0;engine._stop_event=threading.Event()
        drain=engine._sync_audit
    else:
        client._store=store;drain=client._push_first
    try:
        error=None
        try:drain()
        except Exception as caught:error=caught
        assert error is None, f'stored history is not new input: {error}'
        assert len(sent)==1
        assert sent[0]['records']==expected
        assert store.count_unsynced()==0
        drain();assert len(sent)==1
        after=snapshot(store)
        assert after=={event:{**row,'synced':1} for event,row in before.items()}
        for event in before:assert store.verify_integrity(event)
        # Local query/export data keeps every original content term and digest.
        for record in store.query_by_org(ENV['org_id']):
            original=before[record['event_id']]
            assert record['content_hash']==original['content_hash']
            assert record['envelope']==original['envelope']
    finally:client.close();store.close()

@pytest.mark.parametrize('member',['execution_result','review'])
def test_new_result_on_history_keeps_old_terms_but_admits_new_terms(member,tmp_path):
    store=AuditLogger(str(tmp_path/'result.db'));case=CASES[-1];restore(store,case)
    old=store.lifecycle(case['envelope']['org_id'],case['envelope']['environment'],case['envelope']['action_id'])[0]
    before=snapshot(store);result={'status':'succeeded','duration_ms':1}
    error=None;record=None
    try:record=store.write_result(old,result)
    except Exception as caught:error=caught
    assert error is None, f'copied decision history must not be re-admitted: {error}'
    assert record['envelope']==old['envelope'] and record['decision']==old['decision']
    for field in AUDIT_FURTHER:
        if field!='execution_result' and field in old:assert record[field]==old[field]
    assert record['execution_result']==result
    assert snapshot(store)[case['event_id']]==before[case['event_id']]
    assert store.verify_integrity(record['event_id'])
    invalid={'status':'succeeded','probe':BOUND} if member=='execution_result' else {'probe':BOUND}
    with pytest.raises(AuditLogError) as error:
        store.write_result(old,invalid if member=='execution_result' else result,invalid if member=='review' else None)
    assert error.value.__cause__.path==(member,'probe')
    assert len(snapshot(store))==2


def test_hosted_returns_existing_record_without_readmission(tmp_path):
    case=CASES[1];expected={k:v for k,v in case.items() if k not in ('expected','description')};expected['content_hash']=case['expected']['content_hash']
    client=hosted(tmp_path/'absent.db');sent=[]
    def transport(request):
        sent.append(json.loads(request.content));return httpx.Response(200,json=expected)
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    try:
        result={'status':'succeeded','duration_ms':1};error=None;actual=None
        try:actual=client.record_result(ENV['action_id'],result)
        except Exception as caught:error=caught
        assert error is None, f'returned result record is stored history: {error}'
        assert actual==expected and sent==[result]
        with pytest.raises(LifecycleError):client.record_result(ENV['action_id'],{'probe':BOUND})
        assert sent==[result]
    finally:client.close()

@pytest.mark.parametrize('invalid',[False,True])
def test_held_result_intent_is_admitted_before_its_new_request(invalid,tmp_path):
    store=AuditLogger(str(tmp_path/'intent.db'));result={'status':'succeeded','duration_ms':BOUND if invalid else 1}
    # Restoring an old intent does not turn it into an already-hashed audit record.
    with sqlite3.connect(store.db_path) as db:db.execute('INSERT INTO held_results(action_id,execution_result) VALUES (?,?)',(ENV['action_id'],json.dumps(result)))
    client=hosted(store.db_path);client._store=store;sent=[]
    def transport(request):sent.append(json.loads(request.content));return httpx.Response(200,json={})
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    try:
        if invalid:
            with pytest.raises(NumericDomainError) as error:client._push_first()
            assert error.value.path==('execution_result','duration_ms')
            assert sent==[] and store.held_results()==[{'action_id':ENV['action_id'],'execution_result':result}]
        else:
            client._push_first();assert sent==[result] and store.held_results()==[]
    finally:client.close();store.close()

@pytest.mark.parametrize('surface',['sequence','acknowledgement'])
def test_hosted_new_frame_and_current_acknowledgement_remain_admitted(surface,tmp_path):
    store=AuditLogger(str(tmp_path/'frame.db'));store.write(ENV,DEC)
    client=hosted(store.db_path);client._store=store;sent=[]
    if surface=='sequence':client._sequence=BOUND-1
    def transport(request):sent.append(json.loads(request.content));return httpx.Response(200,json={'accepted':BOUND if surface=='acknowledgement' else 1,'errors':[]})
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    try:
        with public_error(NumericDomainError if surface=='sequence' else ServerError) as error:client._push_first()
        if surface=='sequence':assert error.value.path==('sync_sequence',)
        else:
            assert error.value.status_code==200 and error.value.error_code=='UNKNOWN_ERROR'
            assert '<root>["accepted"]' in str(error.value) and 'JSON integer' in str(error.value)
            assert 'pass the value as text' not in str(error.value)
        assert len(sent)==(0 if surface=='sequence' else 1)
        assert store.count_unsynced()==1
        assert all(row['refused'] is None for row in snapshot(store).values())
    finally:client.close();store.close()

# Public sync producers are discovered by their calls, not a frozen method-name list.
import ast
import inspect
from hiitl.sdk import sync_client as sync_module, http_client as hosted_module
from hiitl.sdk.exceptions import ServerError, SyncError

def sync_producers():
    tree=ast.parse(inspect.getsource(SyncClient))
    found=[]
    for method in tree.body[0].body:
        if isinstance(method,ast.FunctionDef) and not method.name.startswith('_') and any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_send_with_retry' for n in ast.walk(method)):
            names=[a.arg for a in method.args.args if a.arg!='self']
            fixture={'records':[],'sync_sequence':1,'etag':None}
            assert set(names)<=set(fixture), f'unread transport input: {names}'
            found.append((method.name,[fixture[n] for n in names]))
    return found

@pytest.mark.parametrize('method,args',sync_producers())
@pytest.mark.parametrize('status',[400,*sorted(sync_module._RETRYABLE_STATUS_CODES)])
@pytest.mark.parametrize('retries',[0,1])
@pytest.mark.parametrize('invalid',[False,True])
def test_every_sync_error_body_is_admitted_before_retry_or_projection(method,args,status,retries,invalid,monkeypatch):
    monkeypatch.setattr(sync_module.time,'sleep',lambda _:None)
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev',max_retries=retries)
    sent=[]
    def transport(request):sent.append(request.url.path);return httpx.Response(status,json={'extra':{'probe':BOUND if invalid else 1}})
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    error=None
    try:
        try:getattr(client,method)(*args)
        except Exception as caught:error=caught
        if invalid:
            assert isinstance(error,SyncError), f'current body must refuse before projection: {error}'
            assert isinstance(error.cause,NumericDomainError)
            assert error.cause.path==('extra','probe') and 'text' in str(error)
            assert len(sent)==1
        else:
            assert isinstance(error,SyncError), f'admitted control keeps its established service refusal: {error}'
            assert len(sent)==(retries+1 if status in sync_module._RETRYABLE_STATUS_CODES else 1)
    finally:client.close()

@pytest.mark.parametrize('producer',['evaluate','result','audit','held-result'])
@pytest.mark.parametrize('status',[400,*sorted(hosted_module._RETRYABLE_STATUS_CODES)])
@pytest.mark.parametrize('retries',[0,1])
@pytest.mark.parametrize('invalid',[False,True])
def test_every_hosted_current_error_body_is_admitted_before_classification(producer,status,retries,invalid,tmp_path,monkeypatch):
    monkeypatch.setattr(hosted_module.time,'sleep',lambda _:None)
    path=tmp_path/'current.db';store=AuditLogger(str(path));result={'status':'succeeded','duration_ms':1}
    if producer=='audit':store.write(ENV,DEC)
    if producer=='held-result':store.hold_result(ENV['action_id'],result)
    client=hosted(path);client._store=store;client._config.max_retries=retries;client._unpushed=False
    before=snapshot(store);held=store.held_results();sent=[]
    def transport(request):sent.append(request.url.path);return httpx.Response(status,json={'extra':{'probe':BOUND if invalid else 1}})
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    calls={'evaluate':lambda:client.evaluate(copy.deepcopy(ENV)),'result':lambda:client.record_result(ENV['action_id'],result),'audit':lambda:client._push_records(store),'held-result':lambda:client._push_results(store)}
    error=None;actual=None
    try:
        try:actual=calls[producer]()
        except Exception as caught:error=caught
        if invalid:
            assert isinstance(error,ServerError), f'current body must refuse before classification: {error}'
            assert error.status_code==status and error.error_code=='UNKNOWN_ERROR'
            assert '<root>["extra"]["probe"]' in str(error) and 'text' in str(error)
            assert len(sent)==1
            assert snapshot(store)==before and store.held_results()==held
        else:
            assert len(sent)==(retries+1 if status in hosted_module._RETRYABLE_STATUS_CODES else 1)
            if producer in ('evaluate','result') and status==400:assert isinstance(error,ServerError)
            elif producer=='evaluate':assert error is None and actual.decision=='CONTROL_PLANE_UNAVAILABLE' and actual.reason_codes==['CONTROL_PLANE_UNREACHABLE'] and actual.allowed is False
            elif producer=='result':assert error is None and actual=={'action_id':ENV['action_id'],'execution_result':result,'held':True}
            else:assert error is None and actual==(('CONTROL_PLANE_UNREACHABLE',f'HTTP {status}') if status in hosted_module._RETRYABLE_STATUS_CODES else None)
    finally:client.close();store.close()

from hiitl.core.tests.handback_assertions import public_error
