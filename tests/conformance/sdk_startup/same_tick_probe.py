"""Unmocked filesystem rewrite record; the controlled clock cell holds the tie."""
from pathlib import Path
import json, os, sys, tempfile
import httpx
from hiitl import HIITL
from hiitl.core.tests.declared_values import latency_sample_count
OriginalClient=httpx.Client
class OfflineClient(OriginalClient):
    def __init__(self,*args,**kwargs):
        kwargs['transport']=httpx.MockTransport(lambda request:httpx.Response(401,json={'detail':'fixture offline'}))
        super().__init__(*args,**kwargs)
httpx.Client=OfflineClient
policy=json.loads((Path(__file__).parent/'policy.json').read_text())
rows=[]
for mode in ('local','hybrid'):
    for suffix in ('json','yaml'):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/('policy.'+suffix)
            old={**policy,'version':'v1.0.0','rules':[{**policy['rules'][0],'decision':'ALLOW'}]}
            new={**policy,'version':'v2.0.0'}
            before_text,after_text=map(json.dumps,(old,new));assert len(before_text)==len(after_text)
            path.write_text(before_text)
            options=dict(policy_path=str(path),org_id=policy['scope']['org_id'],mode='RESPECT_POLICY',audit_db_path=str(Path(d)/'audit.db'))
            if mode=='hybrid':options.update(api_key='local-startup-fixture-key',server_url='https://fixture.invalid',cache_dir=str(Path(d)/'cache'))
            client=HIITL(**options)
            try:
                for sample in range(latency_sample_count()):
                    path.write_text(before_text);client._policy_loader.invalidate_cache();client._policy_loader.load()
                    before=path.stat();path.write_text(after_text);os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns));after=path.stat()
                    fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
                    tied=all(getattr(before,k)==getattr(after,k) for k in fields)
                    decision=client.evaluate('guarded',parameters={'amount':100})
                    rows.append(dict(mode=mode,format=suffix,sample=sample,tied=tied,
                        before={k:str(getattr(before,k)) for k in fields},after={k:str(getattr(after,k)) for k in fields},
                        decision=str(decision.decision),version=decision.policy_version))
                assert all(r['decision']['decision']=='BLOCK' for r in client._audit_logger.get_unsynced(limit=latency_sample_count()))
            finally:client.close()
print('HTL45_TICKS '+json.dumps(rows))
