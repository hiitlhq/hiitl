"""Typed sync remedies: source schemas and their existing canonical witnesses."""
import copy,hashlib,json,pprint,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
TELEMETRY='docs/specs/telemetry_schema.md';SYNC='docs/specs/sync_engine.md'
def blocks(path):return [json.loads(text) for text in re.findall(r'```json\n(.*?)\n```',(ROOT/path).read_text(),re.S)]
telemetry_blocks=blocks(TELEMETRY)
schema=next(b for b in telemetry_blocks if b.get('title')=='hiitl Telemetry Record')
control=next(b for b in telemetry_blocks if b.get('telemetry_version')=='2.0')
ack=next(b for b in blocks(SYNC) if set(b.get('required',[]))=={'accepted','duplicates'})
def resolve(node):
 while '$ref' in node:
  target=schema
  for part in node['$ref'].removeprefix('#/').split('/'):target=target[part]
  node=target
 return node
def leaves(node,path=()):
 node=resolve(node)
 if node.get('type') in ('number','integer'):yield path,node
 for key,child in node.get('properties',{}).items():yield from leaves(child,(*path,key))
 if isinstance(node.get('additionalProperties'),dict):yield from leaves(node['additionalProperties'],(*path,'fixture'))
 if 'items' in node:yield from leaves(node['items'],(*path,0))
def set_value(value,path,item):
 at=value
 for i,key in enumerate(path[:-1]):
  nextkey=path[i+1]
  if isinstance(at,list):
   while len(at)<=key:at.append({} if isinstance(nextkey,str)else [])
  elif key not in at:at[key]={} if isinstance(nextkey,str)else []
  at=at[key]
 key=path[-1]
 if isinstance(at,list):
  while len(at)<=key:at.append(None)
 at[key]=item
rows=[]
for path,node in leaves(schema):
 witness=copy.deepcopy(control);set_value(witness,path,0)
 rows.append({'id':'telemetry:'+'.'.join(map(str,path)),'channel':'telemetry','input':{'records':[witness]},'path':['records',0,*path],'type':node['type'],'range':{k:node[k]for k in ('minimum','maximum','exclusiveMinimum','exclusiveMaximum')if k in node},'entry':'upload'})
# The core format corpus is generated from each canonical schema/table.
for row in json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['cases']:
 if row['format']=='policy':
  forms=[('policy',{'policies':[{'policy_id':'fixture','name':'fixture','version':'v1.0.0','content':row['control'],'content_hash':'0'*64}]},['policies',0,'content']),('kill_switches',{'kill_switches':[],'policy_set':row['control']},['policy_set'])]
 elif row['format']=='routes':forms=[('routes',{'routes':[{'name':row['control']['name'],'config':row['control']}]},['routes',0,'config'])]
 else:continue
 for channel,data,prefix in forms:
  for entry in ('reply','cache'):
   is_route_cache=channel=='routes' and entry=='cache'
   rows.append({'id':f'{entry}:{channel}:'+row['id'],'channel':channel,'input':data['routes']if is_route_cache else data,'path':(prefix[1:] if is_route_cache else prefix)+row['path'],'type':row['type'],'range':row['range'],'entry':entry})
for member,node in ack['properties'].items():
 if node.get('type')=='integer':
  rows.append({'id':'audit-ack:'+member,'channel':'audit','input':{'accepted':0,'duplicates':0,'errors':[]},'path':[member],'type':'integer','range':{},'entry':'reply'})
result={'sources':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (TELEMETRY,SYNC)},'cases':rows}
Path(__file__).with_name('cases.json').write_text(json.dumps(result,indent=2)+'\n')
# Only these schema attributes affect numeric diagnostics. No parsing, defaults,
# validation or admission rule is generated: the existing one still decides.
keep={'type','$ref','$defs','definitions','properties','items','additionalProperties','minimum','maximum','exclusiveMinimum','exclusiveMaximum','anyOf','oneOf','allOf','if','then','else','const','required'}
def trim(node):
 if isinstance(node,list):return [trim(v)for v in node]
 if not isinstance(node,dict):return node
 return {k:({n:trim(v)for n,v in value.items()} if k in ('$defs','definitions','properties') else trim(value))for k,value in node.items()if k in keep}
shapes={'telemetry':trim(schema),'audit_ack':trim(ack)}
if '--build' in sys.argv:
 py='"""Generated from telemetry_schema.md and sync_engine.md by numeric_sync/generate.py."""\nSHAPES = '+pprint.pformat(shapes,sort_dicts=False,width=100)+'\n'
 ts='/** Generated from telemetry_schema.md and sync_engine.md by numeric_sync/generate.py. */\nexport const shapes = '+json.dumps(shapes,indent=2)+';\n'
 (ROOT/'python/hiitl/sdk/numeric_declarations.py').write_text(py)
 (ROOT/'typescript/packages/sdk/src/numeric-declarations.ts').write_text(ts)
print(len(rows))
