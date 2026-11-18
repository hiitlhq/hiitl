import json,sys,time,os
from pathlib import Path
root,directory=map(Path,sys.argv[1:3]);case=json.loads((directory/'case.json').read_text());payload=json.loads((directory/'payload.json').read_text())
producer_events=[]
phase='imports'
observing_producers = '--producers' in sys.argv
clock = (lambda: 0.0) if observing_producers else time.perf_counter
if '--producers' in sys.argv:
 import ast,threading
 builders=set()
 for package in ('core','sdk'):
  for source in (root/'python/hiitl'/package).glob('*.py'):
   for node in ast.walk(ast.parse(source.read_text())):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and any('lru_cache' in ast.unparse(d) for d in node.decorator_list):
     builders.add((str(source),node.name))
 main_thread=threading.get_ident()
 def observe(frame,event,arg):
  if event=='call':
   code=frame.f_code
   if (code.co_filename,code.co_name) in builders or code.co_name in ('model_json_schema','json_schema') and 'pydantic' in code.co_filename:
    producer_events.append({'phase':phase if threading.get_ident()==main_thread else 'first_sync_cycle',
      'file':code.co_filename,'producer':code.co_name,'owner':str(frame.f_locals.get('cls',frame.f_locals.get('model','')))})
 sys.setprofile(observe);threading.setprofile(observe)
loaded_before=set(sys.modules)
start=clock()
clock_loads=sorted(set(sys.modules)-loaded_before)
import httpx
from hiitl import HIITL
imports_ms=(clock()-start)*1000
import builtins
startup_wait_ms=0.0
# Observe the method only when the real constructor imports its module. A
# measurement must not pre-import hybrid dependencies for a local client, or
# remove a lazy import from the construction time it reports.
real_import=builtins.__import__
observed_sync=False
def observed_import(name,*args,**kwargs):
 global observed_sync
 module=real_import(name,*args,**kwargs)
 if name=='hiitl.sdk.sync_engine' and not observed_sync:
  observed_sync=True
  initial_sync=module.SyncEngine.initial_sync
  def timed_initial_sync(self,*call_args,**call_kwargs):
   global startup_wait_ms, phase
   previous_phase=phase;phase="first_sync_cycle"
   began=clock()
   try:return initial_sync(self,*call_args,**call_kwargs)
   finally:
    startup_wait_ms+=(clock()-began)*1000
    phase=previous_phase
  module.SyncEngine.initial_sync=timed_initial_sync
 return module
policy_reads=0
real_open=builtins.open
def counted_open(file,*args,**kwargs):
 global policy_reads
 if isinstance(file,(str,os.PathLike)) and Path(file) in (directory/'policy.json',directory/'policy.yaml'):policy_reads+=1
 return real_open(file,*args,**kwargs)
builtins.open=counted_open
requests=[]
def wire(request):
 requests.append(request.url.path)
 if request.url.path=='/v1/evaluate':
  body=json.loads(request.content)
  return httpx.Response(200,json={'action_id':body['action_id'],'decision':'BLOCK','allowed':False,'reason_codes':['STARTUP_GUARD'],'policy_version':'v1.0.0','timing':{'total_ms':0.0}})
 if case['source'] in ('none','json','yaml'):return httpx.Response(401,json={'detail':{'error':'UNAUTHORIZED','message':'fixture offline'}})
 if request.url.path.endswith('/policies'):body=payload
 elif request.url.path.endswith('/routes'):body={'routes':[],'etag':'startup'}
 elif request.url.path.endswith('/kill-switches'):body={'kill_switches':[],'server_time':'2026-11-16T00:00:00Z'}
 else:body={'accepted':0,'duplicates':0,'errors':[]}
 return httpx.Response(200,json=body)
OriginalClient=httpx.Client
class FixtureClient(OriginalClient):
 def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(wire);super().__init__(*args,**kwargs)
httpx.Client=FixtureClient
options=dict(org_id='org_startup000000000000',environment='dev',agent_id='startup',mode=case['evaluation'],audit_db_path=str(directory/'audit.db'))
if case['source'] in ('json','yaml'):options['policy_path']=str(directory/('policy.'+case['source']))
if case['mode'] in ('hybrid','hosted'):options.update(api_key='local-startup-fixture-key',server_url='https://fixture.invalid',cache_dir=str(directory/'cache'),cold_start_behavior=case['cold_start'])
if case['mode']=='hosted':options.update(evaluation='remote',signature_key='local-startup-fixture-signature-key')
row={'transport':'in-process fixed HTTP wire fixture; no network/hosted service time','imports_ms':imports_ms,'clock_loads':clock_loads}
client=None
try:
 if case['mode']=='hybrid':builtins.__import__=observed_import
 phase='construction'
 start=clock()
 try:client=HIITL(**options)
 finally:builtins.__import__=real_import
 row['construction_ms']=(clock()-start)*1000
 row['resolved_mode']=client.mode
 row['startup_wait_ms']=startup_wait_ms;row['construction_policy_reads']=policy_reads
 for name in ('first','repeated'):
  phase=name
  reads_before=policy_reads
  start=clock();decision=client.evaluate('guarded',parameters={'amount':100});row[name+'_ms']=(clock()-start)*1000
  row[name+'_policy_reads']=policy_reads-reads_before
  row[name+'_decision']={'decision':str(decision.decision),'policy_version':decision.policy_version,'reason_codes':decision.reason_codes,'cache_status':getattr(decision,'cache_status',None),'timing':decision.timing.model_dump()}
except Exception as error:
 row['error']=type(error).__name__+': '+str(error)
finally:
 phase='close'
 if client:client.close()
 if '--producers' in sys.argv:sys.setprofile(None);threading.setprofile(None);row['producer_events']=producer_events
row['requests']=requests
print('HTL45_SAMPLE '+json.dumps(row))
