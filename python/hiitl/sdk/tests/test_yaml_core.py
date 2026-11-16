"""Gap263: both real file loaders read YAML1.2 Core scalar classes."""
import copy
import json
from pathlib import Path
import pytest
import yaml
from hiitl.core import PolicyEvaluator
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION
from hiitl.sdk.policy_loader import PolicyLoader, load_yaml
from hiitl.sdk.route_loader import RouteLoader
from hiitl.sdk.exceptions import PolicyLoadError, RouteLoadError

ROOT=Path(__file__).resolve().parents[4]
CASES=json.loads((ROOT/'tests/conformance/yaml_core/cases.json').read_text())['cases']
ROUTE=json.loads((ROOT/'tests/conformance/typed_members/witnesses.json').read_text())['witnesses'][0]['input']
POLICY={'name':'scalar-policy','version':'v1.0.0','description':'YAML scalar contract','scope':{'org_id':'org_1234567890abcdef','environment':'dev'},'rules':[{'name':'scalar-equality','description':'read declared scalar','priority':1,'lifecycle_stage':'active','conditions':{'field':'parameters.probe','operator':'equals','value':['SCALAR_VALUE']},'decision':'ALLOW','reason_code':'SCALAR_EQUAL'}]}
ENVELOPE={'schema_version':ENVELOPE_SCHEMA_VERSION,'org_id':'org_1234567890abcdef','environment':'dev','agent_id':'fixture','action_id':'act_01234567890123456789','idempotency_key':'scalar','action':'read','operation':'execute','target':{},'parameters':{},'timestamp':'2026-11-14T00:00:00Z','signature':'0'*64}

@pytest.mark.parametrize('row',CASES,ids=lambda r:r['id'])
def test_shared_yaml_scalar_read(row):
    if row['expected_accept']:
        error=None
        try: parsed=load_yaml('probe: '+row['input']+'\n')['probe']
        except Exception as caught: error=caught
        assert error is None, f"declared accepted scalar {row['id']} was refused: {error}"
        assert type(parsed) is type(row['expected']) or (isinstance(parsed,(int,float)) and not isinstance(parsed,bool) and isinstance(row['expected'],(int,float)) and not isinstance(row['expected'],bool))
        assert parsed==row['expected']
    else:
        with pytest.raises(ValueError,match='text'): load_yaml('probe: '+row['input']+'\n')

@pytest.mark.parametrize('row',CASES,ids=lambda r:r['id'])
@pytest.mark.parametrize('surface',['policy','route'])
def test_yaml_file_loader_scalar_and_json_control(row,surface,tmp_path,monkeypatch):
    monkeypatch.setenv('HTL41_ROUTE_FIXTURE','local-route-fixture')
    if surface=='policy':
        document=copy.deepcopy(POLICY); name=document['name']; read=lambda p:PolicyLoader(p).load()
    else:
        document=copy.deepcopy(ROUTE);document['metadata']['probe']='SCALAR_VALUE';name=document['name'];read=lambda p:RouteLoader(p.parent).get(name)
    expected=row.get('expected',0)
    control_document=copy.deepcopy(document)
    if surface=='policy': control_document['rules'][0]['conditions']['value']=[expected]
    else: control_document['metadata']['probe']=expected
    path=tmp_path/(name+'.json');path.write_text(json.dumps(control_document))
    control=read(path)
    if surface=='policy':
        assert control.rules[0].conditions.value==[expected]
        envelope=copy.deepcopy(ENVELOPE);envelope['parameters']['probe']=[expected]
        assert PolicyEvaluator().evaluate(envelope,control).decision=='ALLOW'
    else: assert control.metadata['probe']==expected
    path.unlink();path=path.with_suffix('.yaml')
    path.write_text(yaml.safe_dump(document,sort_keys=False).replace('SCALAR_VALUE',row['input']))
    if not row['expected_accept']:
        with pytest.raises(PolicyLoadError if surface=='policy' else RouteLoadError,match='(probe|value).*text'):read(path)
        return
    result=read(path)
    if surface=='policy':
        assert result.rules[0].conditions.value==[expected]
        assert PolicyEvaluator().evaluate(envelope,result).decision=='ALLOW'
    else: assert result.metadata['probe']==expected

@pytest.mark.parametrize('raw,expected',[('!!int 017',17),('!!int 0o17',15),('!!float 1e3',1000),('!!bool TRUE',True),('!!null Null',None),('!!str on','on')])
def test_explicit_core_scalar_tags_use_the_same_grammar(raw,expected):
    assert load_yaml('probe: '+raw)['probe']==expected

@pytest.mark.parametrize('raw',['!!bool yes','!!int 1_000','!!int 1:20','!!int 0b10','!!float 1_0.0','!!null nope','!!timestamp 2026-11-14'])
def test_explicit_tags_cannot_restore_non_core_scalar_rules(raw):
    import yaml
    with pytest.raises(yaml.YAMLError):load_yaml('probe: '+raw)
