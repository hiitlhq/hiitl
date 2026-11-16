"""88579bbd gap298: remedies from canonical typed members, never from SDK answers."""
import copy,hashlib,json,runpy,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
source=runpy.run_path(str(ROOT/'tests/conformance/input_contract/generate.py'))
read=source['read'];env=json.loads(read(source['ENVELOPE']))
schemas={'envelope':env,'policy':source['policy_schema'](env),'routes':source['route_schema']()}
witnesses={fmt:json.loads((ROOT/f'tests/conformance/input_contract/{fmt}-witnesses.json').read_text())['witnesses'] for fmt in ['envelope','policy']}
witnesses['routes']=json.loads(read('tests/conformance/typed_members/witnesses.json'))['witnesses']
base=copy.deepcopy(witnesses['policy'][0]['input'])
for witness in witnesses['envelope']:
 control=copy.deepcopy(base);control['rules'][0]['tests']=[{'envelope':witness['input'],'expect':'NOT_MATCHED'}]
 witnesses['policy'].append({'id':'nested-'+witness['id'],'input':control})
rows=[];seen=set();other_rows=[];other_seen=set()
for fmt,schema in schemas.items():
 for witness in witnesses[fmt]:
  for node,path,address in source['nodes'](schema,schema,witness['input'],env):
   kind=node.get('type')
   other_path=(*path,'undeclared_probe') if kind=='object' and node.get('additionalProperties') is False else path
   other_kind='undeclared' if other_path!=path else kind
   if other_kind in ('undeclared','string','boolean','array','object') and other_path:
    identity=(fmt,address,other_path,other_kind)
    if identity not in other_seen:
     other_seen.add(identity)
     other_rows.append({'id':f'{fmt}:{witness["id"]}:{".".join(map(str,other_path))}:{other_kind}','format':fmt,'control':witness['input'],'path':list(other_path),'type':other_kind,'declaration':address})
   if kind not in ('integer','number'):continue
   identity=(fmt,address,tuple(path),kind)
   if identity in seen:continue
   seen.add(identity)
   rows.append({'id':f'{fmt}:{witness["id"]}:{".".join(map(str,path))}:{kind}','format':fmt,'control':witness['input'],'path':list(path),'type':kind,'range':{key:node[key] for key in ['minimum','maximum','exclusiveMinimum','exclusiveMaximum'] if key in node},'declaration':address})
# Existing Decision source reader names its canonical schema and type-specific tables.
decision=runpy.run_path(str(ROOT/'python/hiitl/core/tests/test_decision_numeric_types.py'))
for path in decision['PATHS']:
 node=decision['SCHEMA']
 for part in path:
  while '$ref' in node:
   target=decision['SCHEMA']
   for part_ in node['$ref'].removeprefix('#/').split('/'):target=target[part_]
   node=target
  node=node['items'] if isinstance(part,int)else node['properties'][part]
 rows.append({'id':'decision:'+'.'.join(map(str,path)),'format':'decision','control':decision['control_for'](path),'path':list(path),'type':node['type'],'range':{key:node[key] for key in ['minimum','maximum','exclusiveMinimum','exclusiveMaximum']if key in node},'declaration':'decision_response.md JSON Schema'})
for subtype,member,kind in decision['detail_numbers']():
 control=decision['control_for'](('timing','total_ms'));control['remediation']={'type':subtype,'message':'Read','suggestion':'Keep','details':{member:1}}
 rows.append({'id':f'decision:{subtype}:{member}','format':'decision','control':control,'path':['remediation','details',member],'type':kind,'range':{},'declaration':f'decision_response.md Type: {subtype}'})
files=['docs/specs/sync_engine.md','docs/specs/decision_response.md','docs/specs/policy_format.md','docs/specs/envelope_schema.json','docs/specs/routes.md']
result={'authority':'88579bbd; sync_engine.md Numeric domain','source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},'cases':rows,'other_cases':other_rows}
Path(__file__).with_name('cases.json').write_text(json.dumps(result,indent=2)+'\n');print(len(rows))
