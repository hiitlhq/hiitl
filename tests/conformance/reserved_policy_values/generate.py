"""88579bbd: policy markers are forms only where the existing reader reads them."""
import copy,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
KEYS=['$field','$declared','$uncalibrated']
W=ROOT/'tests/conformance/input_contract/policy-witnesses.json'
BASE={'name':'reserved-values','version':'v1.0.0','description':'reserved value forms','scope':{'org_id':'org_1234567890abcdef','environment':'dev'},'rules':[{'name':'r','description':'r','priority':1,'conditions':{'field':'parameters.probe','operator':'equals','value':'ok'},'decision':'BLOCK','reason_code':'HIT'}]}
def at(value,path):
 for key in path:value=value[key]
 return value
def objects(value,path=()):
 if isinstance(value,dict):
  yield path
  for key,child in value.items():yield from objects(child,(*path,key))
 elif isinstance(value,list):
  for i,child in enumerate(value):yield from objects(child,(*path,i))
def build():
 rows=[];seen=set()
 # Existing typed-member controls supply every container class; expectation is
 # the ruling's sole-key rule, never whether either parser happens to accept it.
 for witness in json.loads(W.read_text())['witnesses']:
  original=witness['input']
  for path in objects(original):
   container=at(original,path)
   if not container or any(k in container for k in KEYS):continue
   normal=tuple('*' if isinstance(x,int) else x for x in path)
   if normal in seen:continue
   seen.add(normal)
   for key in KEYS:
    data=copy.deepcopy(original);at(data,path)[key]='probe'
    rows.append({'id':witness['id']+':'+'.'.join(map(str,path))+':'+key,'input':data,'control':original,'accept':False,'path':list(path),'cause':'marker beside another key'})
 # A field reference is read only as the direct atomic condition value.
 for marker in KEYS:
  for wrapper in ['sole','sibling','nested-object','nested-array','metadata']:
   data=copy.deepcopy(BASE);value={marker:'parameters.limit' if marker=='$field' else 'set the bound'}
   if wrapper=='sibling':value['note']='cap'
   if wrapper=='nested-object':value={'child':value}
   if wrapper=='nested-array':value=[value]
   path=['rules',0,'conditions','value']
   if wrapper=='metadata':data['metadata']={'probe':value};path=['metadata','probe']
   else:data['rules'][0]['conditions']['value']=value
   accept=wrapper=='sole' or (marker!='$field' and wrapper in ['nested-object','nested-array'])
   rows.append({'id':marker+':'+wrapper,'input':data,'control':BASE,'accept':accept,'path':path,'cause':'existing reader reach and sole key'})
 for key in KEYS:
  data=copy.deepcopy(BASE);data['rules'][0]['conditions']['value']={'$field':{key:'set the field'}}
  rows.append({'id':'reference-path:'+key,'input':data,'control':BASE,'accept':key=='$declared','path':['rules',0,'conditions','value','$field'],'cause':'declared field-reference path'})
 # Rate bounds already read the uncalibrated form, including the legacy list.
 for legacy in [False,True]:
  control=copy.deepcopy(BASE)
  window={'scope':'org','limit':10,'window_seconds':60}
  if legacy:
   control['metadata']={'rate_limits':[window]};base=['metadata','rate_limits',0]
  else:
   control['rules'][0]['decision']='RATE_LIMIT';control['rules'][0]['rate_limit']=window;base=['rules',0,'rate_limit']
  for member in ['limit','window_seconds']:
   for marker in KEYS:
    for sibling in [False,True]:
     data=copy.deepcopy(control);value={marker:'set the bound'}
     if sibling:value['note']='cap'
     at(data,base)[member]=value
     rows.append({'id':f'rate:{legacy}:{member}:{marker}:{sibling}','input':data,'control':control,'accept':marker=='$uncalibrated' and not sibling,'path':base+[member],'cause':'declared uncalibrated rate bound'})
 return {'authority':'policy_format.md Reserved value forms; 88579bbd','source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['docs/specs/policy_format.md','tests/conformance/input_contract/policy-witnesses.json']},'cases':rows}
if __name__=='__main__':
 out=Path(__file__).with_name('cases.json');out.write_text(json.dumps(build(),indent=2)+'\n');print(len(build()['cases']))
