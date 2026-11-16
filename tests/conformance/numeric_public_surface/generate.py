"""Locate every SDK admission call and public export; unknown sites are unread.

The contracts file is the reviewed reach of each located producer, not a list
used by the product. Adding or moving a guard requires a new recorded reach.
"""
import ast,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
NAMES={'validate_numeric_domain','validate_numbers','number_input','assertNumericDomain','assertSchemaNumbers','admit_sync','admitSync','admit_configuration','admitConfiguration','_admit_audit','auditNumbers','_admit_response','admitResponse','numericInput','parseAdmittedNumbers','admitted_numbers'}
def found():
 sites=[];exports=[]
 for file in sorted((ROOT/'python/hiitl/sdk').rglob('*.py')):
  if 'tests'in file.parts:continue
  source=file.read_text();tree=ast.parse(source);parents={child:parent for parent in ast.walk(tree)for child in ast.iter_child_nodes(parent)}
  for node in ast.walk(tree):
   if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id in NAMES:
    names=[];at=parents.get(node)
    while at:
     if isinstance(at,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):names.insert(0,at.name)
     at=parents.get(at)
    sites.append({'language':'python','path':str(file.relative_to(ROOT)),'line':node.lineno,'owner':'.'.join(names),'guard':node.func.id,'arguments':[ast.get_source_segment(source,a)for a in node.args]+[ast.get_source_segment(source,k)for k in node.keywords]})
   if file.name=='__init__.py'and file.parent.name=='sdk'and isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='__all__'for t in node.targets):
    exports.extend({'language':'python','name':n}for n in ast.literal_eval(node.value))
 ts=json.loads(subprocess.check_output(['node',str(Path(__file__).with_name('typescript.cjs')),str(ROOT),json.dumps(sorted(NAMES))],text=True))
 return sorted(sites+ts['sites'],key=lambda r:(r['path'],r['line'])),exports+ts['exports']
def generated():
 sites,exports=found();contracts=json.loads(Path(__file__).with_name('contracts.json').read_text())
 seen={s['path']+'::'+s['owner']for s in sites}
 if seen!=set(contracts):raise ValueError({'unread':sorted(seen-set(contracts)),'stale':sorted(set(contracts)-seen)})
 return {'authority':'aa0cf726/88579bbd; existing telemetry/counter responses under 5203d233','sites':[{**s,**contracts[s['path']+'::'+s['owner']]}for s in sites],'public_exports':exports,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()for p in sorted({s['path']for s in sites})}}
if __name__=='__main__':Path(__file__).with_name('sites.json').write_text(json.dumps(generated(),indent=2)+'\n')
