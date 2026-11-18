"""Supplied-text cases from canonical date leaves and the complete operator table."""
from pathlib import Path
import json,hashlib,re,copy
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).parent

# These are the structural/annotation members this bounded reader understands.
# Other reachable grammar is unread, even when a ref hides its date declaration.
SUPPORTED={'$schema','$id','$comment','$defs','definitions','$ref','title','description','type','properties','items','additionalProperties','format','required','enum','const','default','examples','minLength','maxLength','minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minItems','maxItems','uniqueItems','pattern','deprecated','readOnly','writeOnly'}
APPLICATORS=('allOf','anyOf','oneOf','if','then','else','prefixItems')

def date_leaves(schema):
    found=[]
    def walk(node,path,address,active=()):
        if not isinstance(node,dict):raise ValueError(f'unread schema at {address}')
        unknown=set(node)-SUPPORTED-set(APPLICATORS)
        if unknown:raise ValueError(f'unread schema members {sorted(unknown)} at {address}')
        if '$ref' in node:
            ref=node['$ref']
            if not ref.startswith('#/') or ref in active:raise ValueError(f'unread reference {ref}')
            target=schema
            for p in ref[2:].split('/'):target=target[p.replace('~1','/').replace('~0','~')]
            walk(target,path,ref,(*active,ref))
        if node.get('format')=='date-time':found.append({'path':path,'address':address})
        for k,v in node.get('properties',{}).items():walk(v,[*path,k],address+'/properties/'+k,active)
        if 'items' in node:walk(node['items'],[*path,0],address+'/items',active)
        if isinstance(node.get('additionalProperties'),dict):walk(node['additionalProperties'],[*path,'fixture'],address+'/additionalProperties',active)
        for key in APPLICATORS:
            if key in node:raise ValueError(f'unread date-bearing {key} at {address}')
    walk(schema,[],'#')
    return found

def set_at(value,path,child):
    for key in path[:-1]:
        if key not in value:raise ValueError(f'no valid parent witness for {path}')
        value=value[key]
    value[path[-1]]=child

def generate():
    schema=json.loads((ROOT/'docs/specs/envelope_schema.json').read_text())
    text=(ROOT/'docs/specs/policy_format.md').read_text()
    section=text.split('### Comparison Operators',1)[1].split('###',1)[0]
    operators=re.findall(r'^\| `([^`]+)` \|',section,re.M)
    supported={'equals','not_equals','greater_than','greater_than_or_equal','less_than','less_than_or_equal','contains','not_contains','in','not_in','starts_with','ends_with','exists','conforms_to'}
    if set(operators)!=supported:raise ValueError(f'unread operator declaration: {set(operators)^supported}')
    original=json.loads((HERE/'lexical-original.json').read_text());base=copy.deepcopy(original[0]);cases=[]
    for member in date_leaves(schema):
        path=member['path'];field='.'.join(map(str,path));written='2026-11-14t01:02:03.123456789+05:30'
        env=copy.deepcopy(base['envelope']);set_at(env,path,written)
        for op in operators:
            numeric=op in ('greater_than','greater_than_or_equal','less_than','less_than_or_equal')
            right=1 if numeric else [written] if op in ('in','not_in') else True if op=='exists' else {} if op=='conforms_to' else written
            expected='error' if numeric or op=='conforms_to' else op not in ('not_equals','not_contains','not_in')
            for reference in ([False] if op=='exists' else [False,True]):
                e=copy.deepcopy(env);e['parameters']['right']=right
                condition={'field':field,'operator':op,'value':{'$field':'parameters.right'} if reference else right}
                cases.append({'id':f'{field}/{op}/{reference}','member':member,'envelope':e,'condition':condition,'expected':expected})
            # Date on the referenced right, to hold both independently declared operands.
            if op!='exists':
                e=copy.deepcopy(env);e['parameters']['left']=written
                error=numeric or op in ('in','not_in','conforms_to')
                expected='error' if error else op not in ('not_equals','not_contains')
                cases.append({'id':f'{field}/{op}/date-right','member':member,'envelope':e,'condition':{'field':'parameters.left','operator':op,'value':{'$field':field}},'expected':expected})
        # Negatives: same instant is not the same text, and finer fractions are not truncated.
        for other in ('2026-11-14T01:02:03.123456789+05:30','2026-11-14t01:02:03.123456+05:30'):
            cases.append({'id':f'{field}/different-text/{other}','member':member,'envelope':copy.deepcopy(env),'condition':{'field':field,'operator':'equals','value':other},'expected':False})
        for op in ('greater_than','greater_than_or_equal','less_than','less_than_or_equal'):
            bad={'field':field,'operator':op,'value':1};settler={'field':'action','operator':'equals','value':'different'}
            for reverse in (False,True):
                children=[bad,settler];children.reverse() if reverse else None
                cases.append({'id':f'{field}/{op}/settle/{reverse}','member':member,'envelope':copy.deepcopy(env),'condition':{'all_of':children},'expected':False})
    env=copy.deepcopy(base['envelope']);env['principal']['verified_at']='2026-11-14t01:02:03.123456789z'
    for op in ('equals','not_equals','in','not_in'):
        right=env['principal'] if op in ('equals','not_equals') else [env['principal']]
        cases.append({'id':'principal/'+op,'member':None,'envelope':copy.deepcopy(env),'condition':{'field':'principal','operator':op,'value':right},'expected':op in ('equals','in')})
    env['parameters']['objects']=[copy.deepcopy(env['principal'])]
    for op in ('contains','not_contains'):
        cases.append({'id':'principal/list/'+op,'member':None,'envelope':copy.deepcopy(env),'condition':{'field':'parameters.objects','operator':op,'value':{'$field':'principal'}},'expected':op=='contains'})
    cases.append({'id':'principal/conforms_to/string','member':None,'envelope':copy.deepcopy(env),'condition':{'field':'principal','operator':'conforms_to','value':{'properties':{'verified_at':{'type':'string'}}}},'expected':True})
    for n,row in enumerate(cases):
        row['envelope']['action_id']=f'act_{n:020d}'
        row['policy']=copy.deepcopy(base['policy']);row['policy']['rules'][0]['conditions']=row.pop('condition')
    return {'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('docs/specs/envelope_schema.json','docs/specs/policy_format.md','docs/specs/ecp_evaluate_spec.md')},'date_members':date_leaves(schema),'operators':operators,'cases':cases}
if __name__=='__main__':(HERE/'cases.json').write_text(json.dumps(generate(),indent=2)+'\n')
