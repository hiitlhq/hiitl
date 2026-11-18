from pathlib import Path
import argparse,json,os,subprocess,sys,tempfile,hashlib,statistics,time,shutil
HERE=Path(__file__).parent
POLICY=json.loads((HERE/'policy.json').read_text())
PAYLOAD=json.loads((HERE/'policy-response.json').read_text())
ORG=POLICY['scope']['org_id']
def cases():
 return json.loads((HERE/'cases.json').read_text())
def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('language');p.add_argument('output',type=Path);p.add_argument('--samples',type=int,default=None);p.add_argument('--profile',action='store_true');p.add_argument('--producers',action='store_true');p.add_argument('--case',default='');p.add_argument('--node',default=shutil.which('node'));a=p.parse_args()
 if a.samples is None:
  import re,math
  from fractions import Fraction
  text=(HERE.parents[2]/'docs/specs/decision_response.md').read_text()
  matches=re.findall(r'^If the p(\d+) of evaluation or round-trip latency is at or over',text,re.M);assert len(matches)==1
  p=Fraction(int(matches[0]),100);a.samples=1
  while math.ceil(p*a.samples)==a.samples:a.samples+=1
 a.output.parent.mkdir(parents=True,exist_ok=True)
 env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SYSTEMROOT')}
 env['PYTHONPATH']=str(a.root/'python');env['PYTHONDONTWRITEBYTECODE']='1'
 node=a.node
 if a.language=='typescript' and not node: raise SystemExit('--node is required when Node is not on PATH')
 rows=[]
 with a.output.open('w') as out:
  for case in cases():
   name='/'.join(case.values())
   if a.case and a.case not in name: continue
   for sample in range(a.samples):
    with tempfile.TemporaryDirectory(prefix='htl45-sample-') as d:
     directory=Path(d);(directory/'policy.json').write_text(json.dumps(POLICY));(directory/'policy.yaml').write_text(json.dumps(POLICY))
     (directory/'payload.json').write_text(json.dumps(PAYLOAD));(directory/'case.json').write_text(json.dumps(case))
     if case['source']=='disk':
      cache=directory/'cache'/ORG/'dev';cache.mkdir(parents=True)
      data=json.dumps(PAYLOAD).encode();(cache/'policies.json').write_bytes(data);(cache/'policies.json.sha256').write_text(hashlib.sha256(data).hexdigest());(cache/'policies.etag').write_text('startup')
     args=[sys.executable,str(HERE/'python_child.py'),str(a.root),d] if a.language=='python' else [node,str(HERE/'typescript_child.mjs'),str(a.root),d]
     if a.profile:args.append('--profile')
     if a.producers:args.append('--producers')
     r=subprocess.run(args,env=env,cwd=d,text=True,capture_output=True,timeout=60)
     tagged=[line.removeprefix('HTL45_SAMPLE ') for line in r.stdout.splitlines() if line.startswith('HTL45_SAMPLE ')]
     row=dict(case=case,sample=sample,returncode=r.returncode,root=str(a.root),language=a.language)
     if len(tagged)==1: row.update(json.loads(tagged[0]))
     else: row.update(error='child produced no unique measurement',stdout=r.stdout,stderr=r.stderr)
     if r.stderr: row['stderr']=r.stderr
     out.write(json.dumps(row)+'\n');out.flush();rows.append(row)
   matching=[r for r in rows if r['case']==case]
   values=[r['first_ms'] for r in matching if 'first_ms' in r]
   print(name,'first ms', [round(min(values),3),round(statistics.median(values),3),round(max(values),3)] if values else 'ERROR',flush=True)
if __name__=='__main__':main()
