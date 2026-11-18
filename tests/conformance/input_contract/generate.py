"""Canonical input cases: JSON Schema and source tables/forms, never SDK models.

Generation uses the existing verification-only jsonschema dependency. Neither
it nor this independent oracle is a customer-package runtime dependency.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
POLICY = 'docs/specs/policy_format.md'
DECISION = 'docs/specs/decision_response.md'
ENVELOPE = 'docs/specs/envelope_schema.json'
ROUTES = 'docs/specs/routes.md'
NUMERIC = 'docs/specs/sync_engine.md'


def read(file): return (ROOT / file).read_text()
def digest(file): return hashlib.sha256((ROOT / file).read_bytes()).hexdigest()
def obj(properties=None, closed=False, **extra):
    return {'type':'object', 'properties':properties or {}, 'additionalProperties':not closed, **extra}
def arr(items): return {'type':'array', 'items':items}
def escape(text): return str(text).replace('~','~0').replace('/','~1')
def section(file, heading):
    text=read(file); marker=re.escape(heading)
    match=re.search(r'^'+marker+r'\s*\n(.*?)(?=^#{1,'+str(len(heading.split(' ')[0]))+r'} |\Z)',text,re.M|re.S)
    if not match: raise ValueError(f'Unread source heading {file} {heading}')
    return match[1]
def owner(file, heading, member=''):
    return file+'#'+heading.lstrip('# ').lower().replace(' ','-')+('/'+member if member else '')
def annotate(node, address):
    node['$comment']=address
    return node

def type_column(text):
    text=text.strip('` ')
    if text.startswith('array[') and text.endswith(']'):return arr(type_column(text[6:-1]))
    if text.endswith('[]'):return arr(type_column(text[:-2]))
    if text in ('datetime','string (date-time)'):return {'type':'string'}
    if text=='object or array':return {'type':['object','array']}
    if text not in ('string','boolean','integer','number','object','array'):raise ValueError(f'Unread canonical type {text}')
    return {'type':text}

def table(file, heading):
    block=section(file,heading); found=[]
    for row in block.splitlines():
        match=re.match(r'^\| `([^`]+)` \| ([^|]+) \|',row)
        if match:
            node=annotate(type_column(match[2]),owner(file,heading,match[1]))
            found.append((match[1],node))
    if not found and heading!='### Type: `custom`':raise ValueError(f'No type rows {file} {heading}')
    return found

def fields(file, heading, strip=''):
    result={}
    for name,node in table(file,heading):
        name=name.removeprefix(strip);parts=name.split('.');p=result
        for part in parts[:-1]:
            if part not in p: raise ValueError(f'Missing declared parent {name}')
            p=p[part].setdefault('properties',{})
        p[parts[-1]]=node
    return result

def yaml_form(heading):
    block=section(POLICY,heading);code=re.search(r'```yaml\n(.*?)\n```',block,re.S)
    if not code: raise ValueError(f'Unread YAML form {heading}')
    # These source-owned forms declare scalar strings/numbers or lists of strings.
    # Unknown forms fail instead of taking a model's type.
    props={}
    for line in code[1].splitlines()[1:]:
        match=re.match(r'^  ([a-z_]+):\s*(.*?)\s*(?:#.*)?$',line)
        if not match: raise ValueError(f'Unread source form {heading}: {line}')
        value=json.loads(match[2]);typ='array' if isinstance(value,list) else 'string' if isinstance(value,str) else 'integer' if type(value)==int else None
        if typ is None:raise ValueError(f'Unread source form value {heading}: {line}')
        node={'type':typ}
        if typ=='array':
            if not value or not all(isinstance(v,str) for v in value):raise ValueError('Unread form items')
            node['items']={'type':'string'}
        props[match[1]]=annotate(node,owner(POLICY,heading,match[1]))
    return props


def policy_schema(envelope):
    """Adapter of existing policy nouns to their tables and stated JSON forms.

    Every type-column table under an owning Field heading must be consumed. Form
    adapters quote/recognize their producer; a changed grammar is not guessed.
    """
    rule_heading='### Rule Fields'; set_heading='### Policy Set Fields'
    used={rule_heading,set_heading,'#### Metadata Fields','#### Suggested-by fields','#### Requirement-citation fields','#### Waits-on fields'}
    text=read(POLICY);all_tables=set()
    current=''
    for line in text.splitlines():
        if line.startswith('#'):current=line
        if re.match(r'^\| Field \| Type \|',line):all_tables.add(current)
    if all_tables!=used:raise ValueError(f'Unread field table(s): {all_tables ^ used}')
    root=obj(fields(POLICY,set_heading,'policy_set.'),True)
    rule=obj(fields(POLICY,rule_heading),True)
    root['properties']['rules']['items']=rule
    metadata=root['properties']['metadata'];metadata.update(obj(fields(POLICY,'#### Metadata Fields','metadata.')))
    for heading,parent in [('#### Suggested-by fields','suggested_by'),('#### Requirement-citation fields','requirement_citation'),('#### Waits-on fields','waits_on')]:
        node=obj(fields(POLICY,heading,parent+'.'),True)
        for child in node['properties'].values():
            if child.get('type')=='object':child['additionalProperties']=False
        if parent=='requirement_citation':
            node['$comment']=rule['properties'][parent]['$comment']
            rule['properties'][parent]={'anyOf':[node,arr(deepcopy(node))], '$comment':node['$comment']}
        else:rule['properties'][parent].update(node)
    root['properties']['scope'].update(obj(yaml_form('### Scope Fields (Schema Support)'),True))
    rule['properties']['scope'].update(obj(yaml_form('### Scope'),True))
    percent=re.search(r'`scope.percentage` is an optional integer from (\d+) through (\d+) inclusive',text)
    if not percent:raise ValueError('Unread percentage declaration')
    rule['properties']['scope']['properties']['percentage'].update(minimum=int(percent[1]),maximum=int(percent[2]))
    envs=envelope['properties']['environment']['enum']
    root['properties']['scope']['properties']['environment']['enum']=envs
    rule['properties']['scope']['properties']['environments']['items']['enum']=envs
    # Recursive condition keys come from the source's logical-operator taxonomy.
    logical=re.findall(r'^\*\*`([^`]+)`\*\* \((?:AND|OR|NOT)\):',section(POLICY,'#### Logical Operators'),re.M)
    if not logical:raise ValueError('Unread condition taxonomy')
    condition=obj({name:annotate(arr({'$ref':'#/$defs/condition'}),owner(POLICY,'#### Logical Operators',name)) for name in logical},True)
    for name,node in [('field',{'type':'string'}),('operator',{'type':'string'}),('value',{})]:
        condition['properties'][name]=annotate(node,owner(POLICY,'#### Comparison Operators',name))
    condition['$comment']=owner(POLICY,'## Condition Syntax')
    rule['properties']['conditions']={'$ref':'#/$defs/condition', '$comment':rule['properties']['conditions']['$comment']}
    # 88579bbd closes the reserved forms; their child kinds remain unchanged.
    if 'A marker is its form only as the sole key' not in text:
        raise ValueError('Unread reserved-value ruling')
    declared=obj({'$declared':{'type':'string'}},True,required=['$declared'])
    operand={'allOf':[{'if':{'type':'object','required':[key]},'then':obj({key:child},True)} for key,child in [('$field',{'anyOf':[{'type':'string'},declared]}),('$uncalibrated',{'type':'string'}),('$declared',{'type':'string'})]]}
    condition['properties']['value'].update(operand)
    parameter_text=section(POLICY,'#### Comparison Operators')
    expected='"required": ["<name>", …], "additionalProperties": true|false}'
    if expected not in parameter_text:raise ValueError('Unread parameter schema form')
    typed=re.search(r'<(string\|number\|integer\|boolean\|array\|object)>',parameter_text)
    if not typed:raise ValueError('Unread parameter descriptor type taxonomy')
    parameter=obj({'type':{'type':'string','const':'object'},'properties':obj({},False,additionalProperties=obj({'type':{'type':'string','enum':typed[1].split('|')}},True)), 'required':arr({'type':'string'}),'additionalProperties':{'type':'boolean'}},True)
    condition['allOf']=[{'if':{'properties':{'operator':{'const':'conforms_to'}},'required':['operator']},'then':{'properties':{'value':parameter}}}]
    # A direct typed rate window and its source-declared placeholder.
    if 'The numeric `limit` and `window_seconds` members are positive integers' not in text:raise ValueError('Unread rate-window bound')
    placeholder=annotate(obj({'$uncalibrated':{'type':'string'}},True,required=['$uncalibrated']),owner(POLICY,'### Uncalibrated bounds (C6)'))
    bound={'anyOf':[{'type':'integer','exclusiveMinimum':0},placeholder]}
    rate_text=section(POLICY,'### Rate-limit rules (A3; ruled 2026-10-08, R-0852)')
    scope_match=re.search(r'Scope `([^`]+)`',rate_text)
    # Scope's type is given in the source's rule form; its enumeration is
    # already held by existing model tests, not copied as a new oracle here.
    rate=obj({'limit':deepcopy(bound),'window_seconds':deepcopy(bound),'scope':{'type':'string'}},True)
    rule['properties']['rate_limit'].update(rate)
    legacy=obj({'scope':{'type':'string'},'window':{'type':'string'},'window_seconds':deepcopy(bound),'limit':deepcopy(bound)},True)
    metadata['properties']['rate_limits']=annotate(arr(legacy),owner(POLICY,'### Rate-limit rules (A3; ruled 2026-10-08, R-0852)','legacy-set-list'))
    # The rule's response-shaped remediation reads subtype-owned tables.
    response=json.loads(re.search(r'^```json\n(.*?)\n```',section(DECISION,'### JSON Schema'),re.M|re.S)[1])
    rem=deepcopy(response['properties']['remediation']);rem['additionalProperties']=False
    subtypes=re.findall(r'^### Type: `([^`]+)`$',read(DECISION),re.M)
    if set(subtypes)!=set(rem['properties']['type']['enum']):raise ValueError('Unread remediation subtype table')
    rem['allOf']=[]
    for subtype in subtypes:
        detail=obj(fields(DECISION,f'### Type: `{subtype}`')) if subtype!='custom' else obj()
        if subtype=='field_restriction':
            # Gap 286 retains the computed form's operand grammar. Only the
            # outer alternative is declared; no type for its arbitrary leaves.
            detail['properties']['blocked_fields']={'anyOf':[detail['properties']['blocked_fields'],obj({'ref':{'type':'string'},'filter':arr({})},True,required=['ref','filter'])]}
        rem['allOf'].append({'if':{'properties':{'type':{'const':subtype}},'required':['type']},'then':{'properties':{'details':detail}}})
    rem['$comment']=rule['properties']['remediation']['$comment'];rule['properties']['remediation']=rem
    sparse=deepcopy(envelope);sparse.pop('required',None);sparse.pop('$id',None)
    rule['properties']['tests']['items']=annotate(obj({'envelope':sparse,'expect':{'type':'string'}},True),owner(POLICY,'### Tests shipped with a rule (C7)'))
    root['$defs']={'condition':condition};root['$schema']='https://json-schema.org/draft/2020-12/schema'
    return root


def route_schema():
    text=section(ROUTES,'### JSON Schema')
    return json.loads(re.search(r'^```json\n(.*?)\n```',text,re.M|re.S)[1])

def validator(schema,envelope):
    resource=Resource.from_contents(envelope)
    return Draft202012Validator(schema,registry=Registry().with_resources([('https://hiitl.com/schemas/route/envelope_schema.json',resource),('envelope_schema.json',resource),(envelope['$id'],resource)]))

def get(value,path):
    for key in path:value=value[key]
    return value

def replace(value,path,changed):
    if not path:return deepcopy(changed)
    result=deepcopy(value);parent=get(result,path[:-1]);parent[path[-1]]=deepcopy(changed);return result

def ref_node(root,node,envelope,address):
    if '$ref' not in node:return root,node,address
    file,fragment=node['$ref'].split('#',1);root=envelope if file=='envelope_schema.json' else root
    if file not in ('','envelope_schema.json'):raise ValueError(f'Unread reference {file}')
    target=root
    for key in fragment[1:].split('/') if fragment else []:target=target[key.replace('~1','/').replace('~0','~')]
    return root,target,(file or address.split('#')[0])+'#'+fragment


def nodes(root,raw,value,envelope,path=(),address='#',refs=()):
    """Finite input traversal, so a recursive condition has no fixture-depth rule."""
    if isinstance(raw,bool):return
    if '$ref' in raw:
        owner,node,target=ref_node(root,raw,envelope,address)
        if target in refs:raise ValueError(f'Reference cycle without an instance step: {target}')
        yield from nodes(owner,node,value,envelope,path,target,(*refs,target))
        siblings={key:item for key,item in raw.items() if key!='$ref'}
        if siblings:yield from nodes(root,siblings,value,envelope,path,address)
        return
    owner,node=root,raw
    yield node,path,address
    for key in ('allOf','anyOf','oneOf'):
        for i,child in enumerate(node.get(key,[])):
            if key=='allOf' or validator({**child,'$defs':owner.get('$defs',{})},envelope).is_valid(value):
                yield from nodes(owner,child,value,envelope,path,f'{address}/{key}/{i}')
    if 'if' in node:
        branch='then' if validator(node['if'],envelope).is_valid(value) else 'else'
        if branch in node:yield from nodes(owner,node[branch],value,envelope,path,f'{address}/{branch}')
    if isinstance(value,dict):
        for key,child in node.get('properties',{}).items():
            if key in value:yield from nodes(owner,child,value[key],envelope,(*path,key),f'{address}/properties/{escape(key)}')
        extra=node.get('additionalProperties')
        if isinstance(extra,dict):
            for key,child in value.items():
                if key not in node.get('properties',{}):yield from nodes(owner,extra,child,envelope,(*path,key),f'{address}/additionalProperties')
    if isinstance(value,list) and 'items' in node:
        for i,child in enumerate(value):yield from nodes(owner,node['items'],child,envelope,(*path,i),f'{address}/items')


def declarations(root,envelope):
    rows={};seen=set()
    def visit(owner,raw,address):
        if isinstance(raw,bool):return
        if address in seen:return
        seen.add(address)
        if '$ref' in raw:
            target_owner,target,target_address=ref_node(owner,raw,envelope,address)
            visit(target_owner,target,target_address)
        node={key:value for key,value in raw.items() if key!='$ref'}
        if 'type' in node or node.get('additionalProperties') is False:rows[address]=node
        for key,child in node.get('properties',{}).items():visit(owner,child,f'{address}/properties/{escape(key)}')
        for key in ('items','additionalProperties','then','else'):
            if isinstance(node.get(key),dict):visit(owner,node[key],f'{address}/{key}')
        for key in ('allOf','anyOf','oneOf'):
            for i,child in enumerate(node.get(key,[])):visit(owner,child,f'{address}/{key}/{i}')
        for key in ('patternProperties','prefixItems','contains','propertyNames','dependentSchemas','not','unevaluatedProperties','unevaluatedItems'):
            if key in node:raise ValueError(f'Unread input-contract schema construct {address}/{key}')
        if 'if' in node:
            # Conditional predicates select a declaration; they do not themselves
            # add an unconditional input type. Typed selectors require a read.
            allowed={'type','required','properties'}
            if set(node['if'])-allowed:raise ValueError(f'Unread conditional selector {address}')
    visit(root,root,'#');return rows

SAMPLES={'null':None,'boolean':True,'integer':0,'number':0.5,'string':'17','array':[],'object':{}}
def matches(types,value):
    types=types if isinstance(types,list) else [types]
    return any(Draft202012Validator({'type':t}).is_valid(value) for t in types)

def probe_samples(fmt,path,envelope):
    samples=dict(SAMPLES)
    if fmt=='policy' and path[-1:]==('$field',):
        # A string is the other union arm: it must also name a real field
        # (policy format 2.6), not the numeric-text wrong-type sentinel.
        samples['string']=next(name for name,node in envelope['properties'].items() if node.get('type')=='string')
    return samples

def generated():
    envelope=json.loads(read(ENVELOPE));schemas={'envelope':envelope,'routes':route_schema(),'policy':policy_schema(envelope)}
    witnesses={fmt:json.loads((HERE/f'{fmt}-witnesses.json').read_text())['witnesses'] for fmt in ('envelope','policy')}
    witnesses['routes']=json.loads(read('tests/conformance/typed_members/witnesses.json'))['witnesses']
    # Sparse test envelopes inherit the Envelope class in every concrete context.
    base=deepcopy(witnesses['policy'][0]['input'])
    for witness in witnesses['envelope']:
        control=deepcopy(base);control['rules'][0]['tests']=[{'envelope':witness['input'],'expect':'NOT_MATCHED'}]
        witnesses['policy'].append({'id':'nested-'+witness['id'],'input':control})
    all_rows=[];all_declarations=[]
    for fmt,schema in schemas.items():
        validate=validator(schema,envelope);decls=declarations(schema,envelope);covered=set();dedupe=set()
        for witness in witnesses[fmt]:
            control=witness['input'];errors=list(validate.iter_errors(control))
            if errors:raise ValueError(f'Invalid source control {fmt}:{witness["id"]}: '+ '; '.join(f'{list(e.path)} {e.message}' for e in errors[:4]))
            for node,path,address in nodes(schema,schema,control,envelope):
                if address not in decls:continue
                covered.add(address);value=get(control,path);probes=[]
                for name,sample in probe_samples(fmt,path,envelope).items():
                    if 'type' in node and not matches(node['type'],sample):probes.append(('null' if name=='null' else 'wrong_type',name,sample,path))
                if isinstance(value,dict):
                    added={**value,'htl43_unknown':None}
                    probes.append(('unknown_field','extra_member',added,path))
                if isinstance(value,(int,float)) and not isinstance(value,bool):
                    for key,direction in [('minimum',-1),('maximum',1),('exclusiveMinimum',0),('exclusiveMaximum',0)]:
                        if key in node:probes.append(('number_range',key,node[key]+direction,path))
                for kind,label,changed,instance in probes:
                    key=(address,json.dumps(instance),kind,label,json.dumps(value,sort_keys=True))
                    if key in dedupe:continue
                    dedupe.add(key);input_=replace(control,instance,changed)
                    all_rows.append({'format':fmt,'id':f'{fmt}-{len(all_rows):05d}-{kind}-{label}', 'declaration':address,'path':list(instance)+(['htl43_unknown'] if kind=='unknown_field' and not validate.is_valid(input_) else []),'control':control,'input':input_,'expected_accept':validate.is_valid(input_),'kind':kind,'subtype':witness['id']})
        unread=sorted(set(decls)-covered)
        if unread:raise ValueError(f'No source witness for {fmt}: {unread}')
        all_declarations.extend({'format':fmt,'address':address,'source':node.get('$comment',address),'types':node.get('type'),'closed':node.get('additionalProperties') is False} for address,node in decls.items())
    files=[POLICY,DECISION,ENVELOPE,ROUTES,NUMERIC,'tests/conformance/typed_members/witnesses.json']+[f'tests/conformance/input_contract/{fmt}-witnesses.json' for fmt in ('envelope','policy')]
    return {'source_hashes':{f:digest(f) for f in files},'declarations':all_declarations,'cases':all_rows}

if __name__=='__main__':
    result=generated();text=json.dumps(result,ensure_ascii=False,indent=2)+'\n';file=HERE/'cases.json'
    if sys.argv[1:] == ['--write']:file.write_text(text)
    elif sys.argv[1:] == ['--check']:
        if file.read_text()!=text:raise SystemExit('Input contract corpus is stale; regenerate from declarations')
    else:raise SystemExit('Use --write or --check')
    print(json.dumps({'declarations':len(result['declarations']),'cases':len(result['cases'])}))
