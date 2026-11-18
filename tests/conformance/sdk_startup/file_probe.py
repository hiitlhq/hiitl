"""Real file operations and audit records, paired with file_probe.mjs."""
from pathlib import Path
import json,tempfile,os,sys,copy
for name in list(os.environ):
 if name.upper().startswith('HIITL_'): del os.environ[name]
import httpx
from hiitl import HIITL
OriginalClient=httpx.Client
class OfflineClient(OriginalClient):
 def __init__(self,*args,**kwargs):
  kwargs['transport']=httpx.MockTransport(lambda request:httpx.Response(401,json={'detail':'fixture offline'}))
  super().__init__(*args,**kwargs)
httpx.Client=OfflineClient
POLICY={'name':'startup','version':'v1.0.0','description':'A guarded action','scope':{'org_id':'org_startup000000000000','environment':'dev'},'rules':[{'name':'guard','description':'Guard the action','priority':100,'conditions':{'field':'action','operator':'equals','value':'guarded'},'decision':'ALLOW','reason_code':'STARTUP_GUARD'}]}
rows=[]
for mode in ('local','hybrid'):
 for suffix in ('json','yaml'):
  for when in ('construction','after-construction'):
   for fault in ('missing','unreadable','unparsable','unparsable-same-mtime','valid-same-mtime','replacement-same-mtime'):
    if when=='construction' and fault.startswith(('valid','replacement')):continue
    with tempfile.TemporaryDirectory() as d:
     p=Path(d)/('policy.'+suffix);p.write_text(json.dumps(POLICY));stat=p.stat();client=None;readable=None
     def damage():
      if fault=='missing':p.unlink()
      elif fault=='unreadable':p.chmod(0)
      else:
       changed=copy.deepcopy(POLICY);changed['version']='v2.0.0';changed['rules'][0]['decision']='BLOCK'
       text=json.dumps(changed) if fault.startswith(('valid','replacement')) else '{not json'
       if fault.startswith('replacement'):
        other=Path(d)/'replacement';other.write_text(text);os.utime(other,ns=(stat.st_atime_ns,stat.st_mtime_ns));other.replace(p)
       else:
        p.write_text(text);os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns if fault.endswith('same-mtime') else stat.st_mtime_ns+1_000_000_000))
     def read_attempt():
      try:p.read_bytes();return True
      except OSError:return False
     try:
      if when=='construction':
       damage();readable=read_attempt()
      options=dict(org_id=POLICY['scope']['org_id'],mode='RESPECT_POLICY',policy_path=str(p),audit_db_path=str(Path(d)/'audit.db'))
      if mode=='hybrid':options.update(api_key='local-startup-fixture-key',server_url='https://fixture.invalid',cache_dir=str(Path(d)/'cache'))
      client=HIITL(**options)
      if when=='after-construction':
       damage();readable=read_attempt()
      result=client.evaluate('guarded');answer={'decision':str(result.decision),'version':result.policy_version,'reasons':result.reason_codes,'record_decisions':[r['decision']['decision'] for r in client._audit_logger.get_unsynced(limit=10)]}
     except Exception as error:answer={'error':type(error).__name__,'reason':getattr(error,'reason',None)}
     finally:
      if p.exists():p.chmod(0o600)
      if client:client.close()
     rows.append(dict(mode=mode,format=suffix,when=when,fault=fault,readable=readable,**answer))
print('HTL45_FILES '+json.dumps(rows))
