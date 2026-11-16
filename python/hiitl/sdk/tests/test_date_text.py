"""Actual file loaders, SDK continuation, audit and replay preserve date text."""
import copy,json
import pytest,yaml
from hiitl.core import Envelope,PolicyEvaluator
from hiitl.core.canonical import envelope_hash,envelope_signature,envelope_verifies,audit_hash_matches
from hiitl.core.operator_kinds import OperatorKindError
from hiitl.core.tests.date_text_support import DATA,LEXICAL,HASHES,at
from hiitl.sdk.client import HIITL
from hiitl.sdk.audit import envelope_record
from hiitl.sdk.policy_loader import PolicyLoader

@pytest.mark.parametrize('wire',['json','yaml'])
@pytest.mark.parametrize('row',DATA['cases'],ids=lambda r:r['id'])
def test_file_date_operator_answer(row,wire,tmp_path):
    path=tmp_path/f'policy.{wire}';path.write_text(json.dumps(row['policy']) if wire=='json' else yaml.safe_dump(row['policy']))
    policy=PolicyLoader(path).load()
    if row['expected']=='error':
        with pytest.raises(OperatorKindError):PolicyEvaluator().evaluate(row['envelope'],policy)
    else:assert PolicyEvaluator().evaluate(row['envelope'],policy).allowed is row['expected']

@pytest.mark.parametrize('row',LEXICAL,ids=lambda r:r['id'])
def test_original_lexical_sdk_record_signature_hash_and_replay(row,tmp_path):
    path=tmp_path/'policy.json';path.write_text(json.dumps(row['policy']))
    vector=HASHES[row['id']];raw=copy.deepcopy(vector['envelope'])
    secret='date-text-fixture'
    client=HIITL(org_id=raw['org_id'],environment=raw['environment'],agent_id=raw['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),signature_key=secret,mode='RESPECT_POLICY',enable_rate_limiting=False)
    try:
        model=Envelope.model_validate(raw);record=envelope_record(model)
        assert record==raw
        assert envelope_verifies(secret,record)
        decision=client._decided(model,record,None)
        assert (decision.decision,decision.allowed)==('ALLOW',True)
        assert decision.envelope_hash==vector['envelope_hash']
        stored=client._audit_logger.query_by_action_id(raw['action_id'])
        written=json.loads(stored['envelope']);answer=json.loads(stored['decision'])
        assert written==raw
        assert audit_hash_matches(stored['content_hash'],stored['event_id'],written,answer)
        assert PolicyEvaluator().evaluate(written,client._policy_loader.load(),mode='RESPECT_POLICY').allowed
        uploaded=client._audit_logger.get_unsynced(10)
        assert len(uploaded)==1 and uploaded[0]['envelope']==raw
        assert uploaded[0]['content_hash']==stored['content_hash']
    finally:client.close()


@pytest.mark.parametrize('channel',['background','hosted'])
def test_old_record_keeps_text_hash_integrity_and_upload_bytes(channel,tmp_path):
    from hiitl.core.tests.date_text_support import ROOT
    from hiitl.sdk.audit import AuditLogger
    from hiitl.sdk.tests.test_stored_history import snapshot,hosted
    from hiitl.sdk.sync_client import SyncClient
    from hiitl.sdk.sync_engine import SyncEngine
    from types import SimpleNamespace
    import sqlite3,httpx,gzip,threading
    old=json.loads((ROOT/'tests/conformance/date_text/historical-record.json').read_text())['row']
    store=AuditLogger(str(tmp_path/'history.db'))
    with sqlite3.connect(store.db_path) as db:
        db.execute('INSERT INTO audit_log ('+','.join(old)+') VALUES ('+','.join('?' for _ in old)+')',list(old.values()))
    before=snapshot(store);assert before=={old['event_id']:old}
    assert store.verify_integrity(old['event_id'])
    sent=[]
    def transport(request):
        raw=request.content
        if request.headers.get('Content-Encoding')=='gzip':raw=gzip.decompress(raw)
        payload=json.loads(raw);sent.append(payload)
        return httpx.Response(200,json={'accepted':1,'duplicates':0,'errors':[]})
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',old['org_id'],old['environment']) if channel=='background' else hosted(store.db_path)
    client._client.close();client._client=httpx.Client(base_url='https://fixture.invalid',transport=httpx.MockTransport(transport))
    if channel=='background':
        engine=object.__new__(SyncEngine);engine._audit_logger=store;engine._client=client;engine._config=SimpleNamespace(audit_batch_size=100);engine._audit_sequence=0;engine._stop_event=threading.Event();drain=engine._sync_audit
    else:client._store=store;drain=client._push_first
    expected=store.get_unsynced()
    try:
        drain();assert len(sent)==1;assert sent[0]['records']==expected
        assert sent[0]['records'][0]['envelope']==json.loads(old['envelope'])
        assert sent[0]['records'][0]['content_hash']==old['content_hash']
        assert snapshot(store)=={old['event_id']:{**old,'synced':1}}
        assert store.verify_integrity(old['event_id'])
    finally:client.close();store.close()

@pytest.mark.parametrize('field',['timestamp','principal.verified_at','principal'])
def test_public_builder_native_clock_and_verifier_use_existing_json_form(field,tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from pydantic import TypeAdapter
    import hiitl.sdk.client as cm
    fixed=datetime(2026,11,14,1,2,3,123456,tzinfo=timezone.utc)
    class Clock:
        @staticmethod
        def now(zone=None):return fixed if zone else fixed.replace(tzinfo=None)
    # Builder timestamp was already a supplied isoformat string; verifier date was native.
    timestamp=fixed.isoformat();verified=TypeAdapter(datetime).dump_python(fixed,mode='json')
    values={'timestamp':timestamp,'principal.verified_at':verified,'principal':{'sub':'fixture','verified_by':'sdk_verifier','verified_at':verified}}
    policy=copy.deepcopy(LEXICAL[0]['policy']);policy['rules'][0]['conditions']={'field':field,'operator':'equals','value':values[field]}
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy));raw=LEXICAL[0]['envelope']
    client=HIITL(org_id=raw['org_id'],environment=raw['environment'],agent_id=raw['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY',principal_verifier=lambda token:{'sub':'fixture'})
    monkeypatch.setattr(cm,'datetime',Clock)
    try:
        decision=client.evaluate('read',principal_token='inert-fixture')
        assert (decision.decision,decision.allowed)==('ALLOW',True)
        stored=client._audit_logger.get_unsynced(10)
        assert len(stored)==1
        assert stored[0]['envelope']['timestamp']==timestamp
        assert stored[0]['envelope']['principal']['verified_at']==verified
        assert decision.envelope_hash==envelope_hash(stored[0]['envelope'])
    finally:client.close()


def test_local_dedup_compares_instants_without_changing_recorded_text(tmp_path):
    from hiitl.sdk.audit import AuditLogger
    from hiitl.sdk.tests.test_stored_history import DEC
    store=AuditLogger(str(tmp_path/'dedup.db'));raw=copy.deepcopy(LEXICAL[0]['envelope'])
    raw['timestamp']='2026-11-14t01:02:03.123456789z'
    event=store.write(raw,DEC)
    assert store.first_decision_under_key(raw['org_id'],raw['environment'],raw['idempotency_key'],'2026-11-14T02:02:03.123456+01:00',0)==DEC
    assert json.loads(store.query_by_action_id(raw['action_id'])['envelope'])==raw
    assert store.verify_integrity(event)
    store.close()


@pytest.mark.parametrize('offset_seconds',[30,-30,30.5,-30.5])
def test_native_continuation_keeps_instant_and_dedup_reads_the_written_record(tmp_path,offset_seconds):
    from datetime import datetime,timezone,timedelta
    from pydantic import TypeAdapter
    from hiitl.core.date_time import read
    native=datetime(2026,11,14,1,2,3,123456,tzinfo=timezone(timedelta(seconds=offset_seconds)))
    expected_text=TypeAdapter(datetime).dump_python(native,mode='json')
    raw=copy.deepcopy(LEXICAL[0]['envelope']);raw['timestamp']=native
    policy=copy.deepcopy(LEXICAL[0]['policy']);rule=policy['rules'][0]
    rule['conditions']={'field':'timestamp','operator':'equals','value':expected_text};rule['decision']='BLOCK'
    rule['remediation']={'type':'temporal','message':'An authored time rule','suggestion':'Retry later','details':{}}
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(org_id=raw['org_id'],environment=raw['environment'],agent_id=raw['agent_id'],policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'),mode='RESPECT_POLICY')
    try:
        model=Envelope.model_validate(raw);record=envelope_record(model)
        decision=client._decided(model,record,None)
        assert (decision.decision,decision.allowed)==('BLOCK',False)
        assert decision.remediation.details=={'current_time':native.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec='milliseconds')+'Z'}
        stored=client._audit_logger.get_unsynced(10)
        assert len(stored)==1 and stored[0]['envelope']['timestamp']==expected_text
        # An existing stored timestamp has its written instant, with no invented
        # hidden native metadata. This is the unchanged local dedup boundary.
        found=client._audit_logger.first_decision_under_key(raw['org_id'],raw['environment'],raw['idempotency_key'],expected_text,0)
        assert found==stored[0]['decision']
        assert read(stored[0]['envelope']['timestamp'])==read(expected_text)
        assert client._audit_logger.verify_integrity(stored[0]['event_id'])
    finally:client.close()
