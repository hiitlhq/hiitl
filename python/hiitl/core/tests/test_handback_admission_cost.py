"""88579bbd: every existing benchmark shape, measured input work versus evaluation.

Timing deltas are records. The exit's pass/fail fact is no repeated admission of
an input and no admission of the evaluator's produced Decision.
"""
import json,os,sys
from pathlib import Path
import pytest
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.numeric_domain import validate_numeric_domain
from hiitl.core.types import PolicySet
from hiitl.core.tests.test_hot_path_benchmark import SCENARIOS,_envelope

ROOT=Path(__file__).resolve().parents[4]
MEASURED=json.loads((ROOT/'tests/conformance/admission_cost/baseline-core-sdk-python.json').read_text())
HISTORY={row['shape']:row for row in MEASURED['rows']}
assert set(HISTORY)==set(SCENARIOS)

@pytest.mark.parametrize('name',SCENARIOS)
def test_admission_work_matches_the_supplied_shapes_once(name,record_property):
    env=_envelope();policy=SCENARIOS[name]()
    def measured(call):
        paths=[]
        def trace(frame,event,arg):
            if event=='call' and frame.f_code is validate_numeric_domain.__code__:
                # Only entered walks count; a call skipped inside an admitted
                # model reader performs no admission work.
                from hiitl.core import numeric_domain
                if not getattr(numeric_domain,'numbers_are_admitted',lambda:False)():paths.append(frame.f_locals.get('path',()))
        sys.setprofile(trace)
        try:call()
        finally:sys.setprofile(None)
        return paths
    baseline=measured(lambda:(validate_numeric_domain(env,('envelope',)),validate_numeric_domain(policy,('policy',)),validate_numeric_domain(None,('enrichment',))))
    evaluator=PolicyEvaluator()
    observed=measured(lambda:evaluator.evaluate(env,policy))
    record_property('admission_baseline',json.dumps({'shape':name,'supplied_visits':len(baseline),'evaluation_visits':len(observed)}))
    record_property('measured_before',json.dumps(HISTORY[name]['core']))
    assert len(observed)<HISTORY[name]['core']['numeric_visits']
    assert sorted(map(str,observed))==sorted(map(str,baseline))

HELD=json.loads((ROOT/'tests/conformance/admission_cost/baseline-held-python.json').read_text())
BEFORE={row['shape']:row for row in HELD['rows']}
assert set(BEFORE)==set(SCENARIOS)
# Each place the SDK's policy is supplied, and the before-record's row for it (sync_engine.md Numeric domain).
SOURCES={'file':'sdk','pull':'sdk_pull','disk':'sdk_disk'}
CALL=dict(parameters={'subject':'x','body':'y'},target={'to':'alice@example.com'})

def _held_client(source,policy,tmp_path,monkeypatch):
    """A client holding the shape's policy through its own load or receipt; nothing stands in for its resolver."""
    from hiitl.sdk import HIITL
    from hiitl.sdk.sync_engine import SyncEngine
    policy_file=tmp_path/'policy.json';policy_file.write_text(policy.model_dump_json(exclude_none=True))
    scope=dict(mode='RESPECT_POLICY',org_id=_envelope().org_id,environment='dev')
    if source=='file':
        return HIITL(sync=False,evaluation='local',**scope,policy_path=str(policy_file),audit_db_path=str(tmp_path/'audit.db'))
    # No transport: the engine's start and first pull are stubbed, as the SDK's hybrid tests do; the pull lands
    # through the cache as the engine writes it, and a second client on the same cache starts warm from disk.
    monkeypatch.setattr(SyncEngine,'start',lambda self:None)
    monkeypatch.setattr(SyncEngine,'initial_sync',lambda self,timeout=10.0:False)
    hybrid=dict(api_key='local-contract-fixture-key',server_url='https://fixture.invalid',**scope,cache_dir=str(tmp_path/'cache'),cold_start_behavior='observe-silent')
    pulled=HIITL(**hybrid,audit_db_path=str(tmp_path/'pull.db'))
    pulled._sync_cache.update_policies({'policies':[{'name':policy.name,'active':True,'content':json.loads(policy_file.read_text())}]})
    if source=='pull':return pulled
    pulled.close()
    return HIITL(**hybrid,audit_db_path=str(tmp_path/'disk.db'))

def _reads_its_held_policy_once(name,source,tmp_path,monkeypatch,record_property):
    """88579bbd item 4 and sync_engine.md Numeric domain: the held policy was admitted where it was supplied, so a
    steady-state evaluate admits one supplied tree, the caller's call, and the held policy decides."""
    from pydantic import BaseModel
    from collections.abc import Mapping
    from hiitl.core import numeric_domain
    policy=SCENARIOS[name]();client=_held_client(source,policy,tmp_path,monkeypatch)
    roots=[]
    def trace(frame,event,arg):
        if event!='call' or frame.f_code is not validate_numeric_domain.__code__:return
        if frame.f_back.f_code is validate_numeric_domain.__code__ or numeric_domain.numbers_are_admitted():return
        if isinstance(frame.f_locals['value'],(Mapping,BaseModel)):roots.append(frame.f_locals['value'])
    try:
        client.evaluate('send_email',**CALL)
        sys.setprofile(trace)
        try:decision=client.evaluate('send_email',**CALL)
        finally:sys.setprofile(None)
    finally:client.close()
    before=BEFORE[name][SOURCES[source]]
    record_property('admission_roots',json.dumps({'shape':name,'source':source,'before':before['admission_roots'],'after':len(roots)}))
    assert decision.policy_version==policy.version
    assert [root.get('parameters') if isinstance(root,Mapping) else type(root).__name__ for root in roots]==[CALL['parameters']]
    assert len(roots)<before['admission_roots']

# One cell per source, so a mutation names the cells of every source it touches.
@pytest.mark.parametrize('name',SCENARIOS)
def test_sdk_reads_its_policy_file_without_admitting_it_again(name,tmp_path,monkeypatch,record_property):
    _reads_its_held_policy_once(name,'file',tmp_path,monkeypatch,record_property)

@pytest.mark.parametrize('name',SCENARIOS)
def test_sdk_reads_its_pulled_policy_without_admitting_it_again(name,tmp_path,monkeypatch,record_property):
    _reads_its_held_policy_once(name,'pull',tmp_path,monkeypatch,record_property)

@pytest.mark.parametrize('name',SCENARIOS)
def test_sdk_reads_its_disk_cached_policy_without_admitting_it_again(name,tmp_path,monkeypatch,record_property):
    _reads_its_held_policy_once(name,'disk',tmp_path,monkeypatch,record_property)

# b88dd3e3: a held reading never outlives what it was read from. A changed file is read again (the loader's mtime
# cache), and a pull that lands replaces the cache's reading, a warm start's too; a kill-switch tick's part is row 240's
# (test_row240.py).
def _payments(version,decision):
    rule={'name':'send','description':'send','priority':100,'decision':decision,'reason_code':'SEND',
          'conditions':{'field':'action','operator':'equals','value':'send_email'}}
    return PolicySet(name='payments',version=version,description='payments',scope={'org_id':_envelope().org_id,'environment':'dev'},rules=[rule])

def _replaced_where_its_source_changes(source,tmp_path,monkeypatch):
    first,then=_payments('v1.0.0','ALLOW'),_payments('v1.0.1','BLOCK')
    client=_held_client(source,first,tmp_path,monkeypatch)
    try:
        kept=client.evaluate('send_email',**CALL)
        content=then.model_dump_json(exclude_none=True)
        if source=='file':
            policy_file=tmp_path/'policy.json';policy_file.write_text(content)
            later=policy_file.stat().st_mtime+60;os.utime(policy_file,(later,later))
        else:client._sync_cache.update_policies({'policies':[{'name':then.name,'active':True,'content':json.loads(content)}]})
        replaced=client.evaluate('send_email',**CALL)
    finally:client.close()
    assert [(d.decision,d.policy_version) for d in (kept,replaced)]==[('ALLOW','v1.0.0'),('BLOCK','v1.0.1')]

def test_sdk_reads_its_policy_file_again_when_the_file_changes(tmp_path,monkeypatch):
    _replaced_where_its_source_changes('file',tmp_path,monkeypatch)

def test_sdk_replaces_its_pulled_policy_when_a_pull_lands(tmp_path,monkeypatch):
    _replaced_where_its_source_changes('pull',tmp_path,monkeypatch)

def test_sdk_replaces_its_disk_cached_policy_when_a_pull_lands(tmp_path,monkeypatch):
    _replaced_where_its_source_changes('disk',tmp_path,monkeypatch)

from hiitl.sdk.tests.test_numeric_boundaries import CONFIG_FIELDS
@pytest.mark.parametrize('model,base,name,field',CONFIG_FIELDS,ids=[f'{m.__name__}.{n}'for m,b,n,f in CONFIG_FIELDS])
def test_settings_admit_each_supplied_numeric_member_once(model,base,name,field):
    """A settings model reads its supplied value once, before producing the model."""
    control=field.default if field.default is not None else 1
    visits=[]
    from hiitl.core import numeric_domain
    def trace(frame,event,arg):
        if event=='call' and frame.f_code is validate_numeric_domain.__code__ and not numeric_domain.numbers_are_admitted():
            path=frame.f_locals.get('path',())
            if path and path[-1] in (name,field.validation_alias):visits.append(path)
    sys.setprofile(trace)
    try:actual=model(**base,**{name:control})
    finally:sys.setprofile(None)
    assert getattr(actual,name)==control
    assert len(visits)==1,visits
