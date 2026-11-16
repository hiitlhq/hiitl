"""Independent source oracle: a kind-tagged normal form, never either evaluator."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
SPEC='docs/specs/policy_format.md'

def tagged(value):
    if value is None:return ('null',)
    if isinstance(value,bool):return ('boolean',value)
    if isinstance(value,(int,float)):return ('number',value)
    if isinstance(value,str):return ('string',value)
    if isinstance(value,list):return ('array',tuple(map(tagged,value)))
    if isinstance(value,dict):return ('object',tuple((key,tagged(value[key])) for key in sorted(value)))
    raise ValueError(f'unread JSON kind {type(value).__name__}')

def expected(op,left,right):
    if left is None:return False  # the declared field gate precedes comparison
    a,b=tagged(left),tagged(right)
    if op=='equals':return a==b
    if op=='not_equals':return a!=b
    if op in ('contains','not_contains'):
        member=right in left if isinstance(left,str) else b in a[1]
        return member if op=='contains' else not member
    if op in ('in','not_in'):
        members=a[1] if isinstance(left,list) else (a,)
        subset=set(members)<=set(b[1])
        return subset if op=='in' else not subset
    raise ValueError(f'unread comparison operator {op}')

def build():
    spec=(ROOT/SPEC).read_text()
    table=spec.split('#### Comparison Operators',1)[1].split('**An array on the left',1)[0]
    operators=[m[1] for m in re.finditer(r'^\| `([^`]+)` \|[^\n]+$',table,re.M) if 'JSON-value' in m[0]]
    data=json.loads((HERE/'inputs.json').read_text())
    if set(operators)!={row['operator'] for row in data['cases']}:raise ValueError('unread source operator or missing input class')
    cases=[]
    for row in data['cases']:
        yes=expected(row['operator'],row['left'],row['right'])
        cases.append({**row,'expected':{'decision':'ALLOW' if yes else 'BLOCK','allowed':yes,'reason_codes':['SCALAR_EQUAL' if yes else 'NO_MATCHING_RULE']}})
    return {'source_sha256':{SPEC:hashlib.sha256((ROOT/SPEC).read_bytes()).hexdigest(),'inputs.json':hashlib.sha256((HERE/'inputs.json').read_bytes()).hexdigest()},'operators':operators,'base':data['base'],'cases':cases}

if __name__=='__main__':
    import sys
    raw=json.dumps(build(),indent=2)+'\n'
    if '--check' in sys.argv:
        if (HERE/'cases.json').read_text()!=raw:raise SystemExit('comparison corpus is stale')
    else:(HERE/'cases.json').write_text(raw)
