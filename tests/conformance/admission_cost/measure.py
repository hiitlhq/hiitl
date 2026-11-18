"""Record the existing benchmark shapes; durations never become chosen limits.

Usage: python measure.py <source-root> <source-label> <new-output-file>
Run serially with the TypeScript measurement, outside other suites.
Each shape is read through the core, and through the SDK with its policy held from each place it is supplied:
the policy file (sdk), a pull the cache receives (sdk_pull) and the cache on disk at a warm start (sdk_disk).
Each row also records the timing the decision itself reports (decision_response.md Timing Metadata; HTL-43 gap 303).
"""
import hashlib,json,sys,tempfile,time
from pathlib import Path
source=Path(sys.argv[1]).resolve();label=sys.argv[2];output=Path(sys.argv[3])
assert not output.exists(), 'Keep each measurement attempt'
sys.path.insert(0,str(source/'python'))
from hiitl.core.tests.test_hot_path_benchmark import SCENARIOS,_envelope,ITERATIONS,WARMUP
from hiitl.core import numeric_domain
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.statistics import percentile
from hiitl.sdk import HIITL
from hiitl.sdk.sync_engine import SyncEngine
from pydantic import BaseModel
from collections.abc import Mapping
# No transport: the engine's start and first pull are stubbed, as the SDK's hybrid tests do; a pull lands through
# the cache as the engine writes it.
SyncEngine.start=lambda self:None
SyncEngine.initial_sync=lambda self,timeout=10.0:False

def work(call):
    visits=roots=0;at=[]
    def trace(frame,event,arg):
        nonlocal visits,roots
        if event!='call' or frame.f_code is not numeric_domain.validate_numeric_domain.__code__:return
        if getattr(numeric_domain,'numbers_are_admitted',lambda:False)():return
        visits+=1
        if frame.f_back.f_code is not numeric_domain.validate_numeric_domain.__code__ and isinstance(frame.f_locals['value'],(Mapping,BaseModel)):
            roots+=1;at.append(list(frame.f_locals.get('path',())))
    sys.setprofile(trace)
    try:call()
    finally:sys.setprofile(None)
    return {'numeric_visits':visits,'admission_roots':roots,'root_paths':at}

def measure(call):
    for _ in range(WARMUP):call()
    times=[];reported={'ingest_ms':[],'total_ms':[]}
    for _ in range(ITERATIONS):
        start=time.perf_counter_ns();decision=call();times.append((time.perf_counter_ns()-start)/1e6)
        for key,values in reported.items():values.append(getattr(decision.timing,key))
    return {'p50_ms':percentile(times,.5),'p95_ms':percentile(times,.95),'p99_ms':percentile(times,.99),
            'reported':{key:{'p50_ms':percentile(v,.5),'p95_ms':percentile(v,.95),'p99_ms':percentile(v,.99)} for key,v in reported.items()},
            **work(call)}

def through(client,version):
    call=lambda:client.evaluate('send_email',parameters={'subject':'x','body':'y'},target={'to':'alice@example.com'})
    try:
        assert call().policy_version==version, 'the held policy decides'
        return measure(call)
    finally:client.close()
rows=[]
for name,builder in SCENARIOS.items():
    policy=builder();envelope=_envelope();evaluator=PolicyEvaluator()
    core=measure(lambda:evaluator.evaluate(envelope,policy))
    with tempfile.TemporaryDirectory(prefix='htl43-benchmark-')as temporary:
        path=Path(temporary);policy_file=path/'policy.json';policy_file.write_text(policy.model_dump_json(exclude_none=True))
        sdk=through(HIITL(sync=False,evaluation='local',mode='RESPECT_POLICY',org_id=envelope.org_id,environment='dev',policy_path=str(policy_file),audit_db_path=str(path/'audit.db')),policy.version)
        hybrid=dict(api_key='local-contract-fixture-key',server_url='https://fixture.invalid',mode='RESPECT_POLICY',org_id=envelope.org_id,environment='dev',cache_dir=str(path/'cache'),cold_start_behavior='observe-silent')
        pulled=HIITL(**hybrid,audit_db_path=str(path/'pull.db'))
        pulled._sync_cache.update_policies({'policies':[{'name':policy.name,'active':True,'content':json.loads(policy_file.read_text())}]})
        sdk_pull=through(pulled,policy.version)
        sdk_disk=through(HIITL(**hybrid,audit_db_path=str(path/'disk.db')),policy.version)
    rows.append({'shape':name,'core':core,'sdk':sdk,'sdk_pull':sdk_pull,'sdk_disk':sdk_disk})
# The measured source as one digest over each file's hash, so the record names no path (E4)
source_files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((source/'python/hiitl').rglob('*.py'))}
source_manifest=hashlib.sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest()
output.write_text(json.dumps({'source':label,'source_manifest_sha256':source_manifest,'measurement_driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'runtime':sys.version,'iterations':ITERATIONS,'warmup':WARMUP,'rows':rows},indent=2)+'\n')
print(json.dumps([{r['shape']:{k:v['admission_roots'] for k,v in r.items() if k!='shape'}} for r in rows]))
