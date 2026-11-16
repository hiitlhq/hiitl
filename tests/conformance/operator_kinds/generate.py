"""Expected operand answers from policy_format.md, without loading either evaluator."""
from pathlib import Path
import hashlib, json, re

ROOT=Path(__file__).resolve().parents[3]
VALUES=[('null',None),('boolean',True),('number',1),('string','probe'),('array',[1]),('object',{}),('numeric_text','1'),('fraction',1.5)]

def kind(value):
    if value is None:return 'null'
    if isinstance(value,bool):return 'boolean'
    if isinstance(value,(int,float)):return 'number'
    if isinstance(value,str):return 'string'
    if isinstance(value,list):return 'array'
    if isinstance(value,dict):return 'object'
    raise ValueError('unread non-JSON value')

def declarations(text):
    section=text.split('#### Comparison Operators',1)[1].split('### Field Path Syntax',1)[0]
    rows=[]
    for line in section.splitlines():
        match=re.fullmatch(r'\| `([^`]+)` \| ([^|]+) \| (.+) \|',line)
        if not match:continue
        op,types,description=match.groups();types=types.strip()
        if types=='number':category='number'
        elif types=='string':category='string'
        elif types=='string, array':category='container'
        elif types=='object' and op=='conforms_to':category='schema'
        elif types=='all' and op in ('equals','not_equals'):category='equality'
        elif types=='all' and op in ('in','not_in') and ('array' in description or op=='not_in'):category='set'
        elif types=='all' and op=='exists' and 'true/false' in description:category='exists'
        else:raise ValueError(f'unread operator declaration: {op}')
        rows.append({'operator':op,'types':types,'description':description,'category':category})
    if not rows:raise ValueError('unread operator table')
    return rows

def equal(a,b):
    if kind(a)!=kind(b):return False
    if isinstance(a,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,dict):return set(a)==set(b) and all(equal(a[k],b[k]) for k in a)
    return a==b

def answer(declaration,left,right,reference):
    op,cat=declaration['operator'],declaration['category'];lk,rk=kind(left),kind(right)
    fixed={'number':'number','string':'string','set':'array','exists':'boolean','schema':'object'}.get(cat)
    if reference and cat=='exists' or not reference and fixed and rk!=fixed:return {'stage':'load'}
    if reference and right is None or left is None and cat!='exists':return {'stage':'decision','matched':False}
    bad=cat=='number' and (lk!='number' or rk!='number') or cat=='string' and (lk!='string' or rk!='string') or cat=='container' and (lk not in ('string','array') or lk=='string' and rk!='string') or cat=='set' and rk!='array' or cat=='schema' and (lk!='object' or rk!='object')
    if bad:return {'stage':'operand'}
    if cat=='equality':matched=equal(left,right);matched=not matched if op=='not_equals' else matched
    elif cat=='exists':matched=(left is not None)==right
    elif cat=='number':matched={'greater_than':left>right,'greater_than_or_equal':left>=right,'less_than':left<right,'less_than_or_equal':left<=right}[op]
    elif cat=='string':matched=left.startswith(right) if op=='starts_with' else left.endswith(right) if op=='ends_with' else re.search(right,left) is not None
    elif cat=='container':
        matched=right in left if isinstance(left,str) else any(equal(x,right) for x in left)
        if op=='not_contains':matched=not matched
    elif cat=='set':
        matched=all(any(equal(x,y) for y in right) for x in left) if isinstance(left,list) else any(equal(left,y) for y in right)
        if op=='not_in':matched=not matched
    else:matched=True # Both object representatives are the empty, admitted parameter schema/object.
    return {'stage':'decision','matched':matched}

def generate(text=None):
    source=ROOT/'docs/specs/policy_format.md';text=source.read_text() if text is None else text
    rows=declarations(text);cases=[]
    for declaration in rows:
        for lname,left in VALUES:
            for rname,right in VALUES:
                for reference in (False,True):
                    cases.append({'id':f"{declaration['operator']}:{lname}:{rname}:{'reference' if reference else 'literal'}",'operator':declaration['operator'],'left':left,'right':right,'reference':reference,'expected':answer(declaration,left,right,reference)})
    input_cases=json.loads((ROOT/'tests/conformance/input_contract/cases.json').read_text())['cases']
    schemas=[]
    for case in input_cases:
        try:condition=case['control']['rules'][0]['conditions']
        except (KeyError,TypeError):continue
        if case['format']=='policy' and condition.get('operator')=='conforms_to' and case['path'][:4]==['rules',0,'conditions','value']:
            schemas.append({'id':case['id'],'path':case['path'][4:],'schema':case['input']['rules'][0]['conditions']['value'],'valid_schema':case['expected_accept'],'left':{'sample':'text'},'matched':True})
    schemas += [
        {'id':'valid-empty','schema':{},'valid_schema':True,'left':{},'matched':True},
        {'id':'valid-member','schema':{'properties':{'sample':{'type':'number'}}},'valid_schema':True,'left':{'sample':1},'matched':True},
        {'id':'child-mismatch','schema':{'properties':{'sample':{'type':'number'}}},'valid_schema':True,'left':{'sample':'text'},'matched':False},
        {'id':'own-prototype-member','schema':{'properties':{'__proto__':{'type':'string'}}},'valid_schema':True,'left':{'__proto__':'text'},'matched':True},
        {'id':'own-prototype-invalid-schema','schema':{'properties':{'__proto__':{'type':'uuid'}}},'valid_schema':False,'left':{},'matched':False},
        {'id':'own-prototype-mismatch','schema':{'properties':{'__proto__':{'type':'string'}}},'valid_schema':True,'left':{'__proto__':1},'matched':False},
        {'id':'unknown-keyword','schema':{'pattern':'x'},'valid_schema':False,'left':{},'matched':False},
        {'id':'unknown-member-type','schema':{'properties':{'sample':{'type':'uuid'}}},'valid_schema':False,'left':{},'matched':False},
    ]
    return {'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'declarations':rows,'cases':cases,'schema_cases':schemas}

if __name__=='__main__':
    (Path(__file__).parent/'cases.json').write_text(json.dumps(generate(),indent=2)+'\n')
