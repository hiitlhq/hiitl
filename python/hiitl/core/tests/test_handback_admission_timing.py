"""HTL-43 gap 303, decided by the record (b88dd3e3): the reported timing counts the call's admission.

decision_response.md's timing schema: `ingest_ms` "Time spent ingesting and validating envelope", `total_ms` "Total
request latency". "The clock starts where `evaluate()` starts, in both cores. The admission of the call's tree is counted
in `ingest_ms` and in `total_ms`." A controlled clock moves only while the admitter walks a tree the call supplied, by
the cell's own step, so the reported times are the step times the walks, exactly; no tolerance is chosen. Design:
.github/public/TEST_DESIGN_htl43_handback.md, "Gap 303". Mirrors the TypeScript handback-admission-cost cells.
"""
from types import SimpleNamespace
import pytest
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.numeric_domain import numbers_are_admitted, validate_numeric_domain
from hiitl.core.types import PolicySet
from hiitl.core.tests.test_hot_path_benchmark import SCENARIOS,_envelope
from hiitl.core.tests.test_handback_admission_cost import CALL,_held_client

STEP=0.125   # seconds: a binary fraction, so each walk's milliseconds are exact

class _Clock:
    def __init__(self):self.now=10.0
    def perf_counter(self):return self.now

def _slowed(monkeypatch,module,clock):
    """The admitter `module` calls, slowed by STEP for each tree it walks; a skip inside an admitted reader walks nothing."""
    def admit(value,path=(),**kwargs):
        if value is not None and not numbers_are_admitted():clock.now+=STEP
        return validate_numeric_domain(value,path,**kwargs)
    monkeypatch.setattr(f'{module}.validate_numeric_domain',admit)

def _timing(walks):
    return {'ingest_ms':walks*STEP*1000,'evaluation_ms':0.0,'total_ms':walks*STEP*1000}

@pytest.mark.parametrize('enrichment',[None,{'check':{'score':2}}],ids=['no-route-answer','route-answer'])
@pytest.mark.parametrize('name',SCENARIOS)
def test_core_timing_counts_the_admission_of_each_supplied_tree(name,enrichment,monkeypatch):
    """The envelope, the policy and a route's answer are each walked inside the core's clock."""
    clock=_Clock();monkeypatch.setattr('hiitl.core.evaluator.time',clock)
    _slowed(monkeypatch,'hiitl.core.evaluator',clock)
    decision=PolicyEvaluator().evaluate(_envelope(),SCENARIOS[name](),enrichment=enrichment)
    assert decision.timing.model_dump()==_timing(3 if enrichment else 2)

def _sdk_clock(monkeypatch):
    """The SDK's clock and the core's are one controlled clock; only the SDK's admitter moves it."""
    clock=_Clock()
    monkeypatch.setattr('hiitl.core.evaluator.time',clock)
    monkeypatch.setattr('hiitl.sdk.client.time',clock,raising=False)
    _slowed(monkeypatch,'hiitl.sdk.client',clock)
    return clock

# The held-policy path: each source, each existing benchmark shape (sync_engine.md Numeric domain; gap 295).
@pytest.mark.parametrize('source',['file','pull','disk'])
@pytest.mark.parametrize('name',SCENARIOS)
def test_sdk_timing_counts_the_calls_admission_on_its_held_policy(name,source,tmp_path,monkeypatch):
    _sdk_clock(monkeypatch)
    policy=SCENARIOS[name]();client=_held_client(source,policy,tmp_path,monkeypatch)
    try:
        client.evaluate('send_email',**CALL)
        decision=client.evaluate('send_email',**CALL)
    finally:client.close()
    assert decision.policy_version==policy.version
    assert decision.timing.model_dump()==_timing(1)

ORG=_envelope().org_id
def _rule(name,decision,action,priority=100,**more):
    return {'name':name,'description':name,'priority':priority,'decision':decision,'reason_code':name.upper().replace('-','_'),
            'conditions':{'field':'action','operator':'equals','value':action},**more}
def _set(version,*rules):
    return {'name':'payments','version':version,'description':'payments','scope':{'org_id':ORG,'environment':'dev'},'rules':list(rules)}
HELD=_set('v1.0.0',_rule('allow-pay','ALLOW','pay'),_rule('allow-refund','ALLOW','refund'))
PART=_set('v1.0.1',_rule('halt-payments','KILL_SWITCH','pay'))

def _ticked(tmp_path,policy):
    """A hybrid client whose cache holds `policy` and a kill-switch tick's part no pull has followed (row 240)."""
    from hiitl.sdk import HIITL
    import json
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    client=HIITL(sync=False,evaluation='local',mode='RESPECT_POLICY',org_id=ORG,environment='dev',policy_path=str(path),audit_db_path=str(tmp_path/'audit.db'))
    held,part=PolicySet(**policy),PolicySet(**PART)
    client._mode='hybrid'
    client._sync_cache=SimpleNamespace(tick_part=lambda:part,get_policy_set=lambda:held,cache_status=lambda:'synced')
    return client

@pytest.mark.parametrize('action,decided,version',[('pay','KILL_SWITCH','v1.0.1'),('refund','ALLOW','v1.0.0')],ids=['tick-binds','tick-does-not-bind'])
def test_sdk_timing_counts_the_calls_admission_on_the_ticks_path(action,decided,version,tmp_path,monkeypatch):
    _sdk_clock(monkeypatch)
    client=_ticked(tmp_path,HELD)
    try:decision=client.evaluate(action,parameters={})
    finally:client.close()
    assert (decision.decision,decision.policy_version)==(decided,version)
    assert decision.timing.model_dump()==_timing(1)

def test_sdk_timing_counts_the_calls_admission_on_the_reevaluation_with_a_routes_answer(tmp_path,monkeypatch):
    """policy_format.md 2.7: the route's answer re-enters evaluation; the re-evaluation's decision carries the call's span."""
    _sdk_clock(monkeypatch)
    asking=_set('v1.0.0',_rule('ask','ROUTE','pay',priority=500,route='check'),
                {**_rule('high-score','BLOCK','pay',priority=800),'conditions':{'field':'external.check.score','operator':'greater_than','value':1}})
    client=_ticked(tmp_path,asking);client._sync_cache.tick_part=lambda:None
    client._route_loader=SimpleNamespace(get=lambda name:{'name':'check','direction':'bidirectional','response_schema':{'required_fields':['score']}})
    asked=[]
    client._ask_route=lambda route,payload:asked.append(payload) or {'score':2}
    try:decision=client.evaluate('pay',parameters={})
    finally:client.close()
    assert len(asked)==1
    assert (decision.decision,decision.reason_codes)==('BLOCK',['HIGH_SCORE'])
    assert decision.timing.model_dump()==_timing(1)
