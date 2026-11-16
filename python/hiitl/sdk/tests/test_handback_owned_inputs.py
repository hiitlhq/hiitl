"""Admission owns the supplied tree before callbacks, once at each boundary."""
import copy,json,sys
from pathlib import Path
import httpx,pytest
from pydantic import BaseModel
from hiitl.sdk import HIITL
from hiitl.sdk.http_client import HostedClient
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import EnvelopeValidationError
from hiitl.core import numeric_domain
from hiitl.core.numeric_domain import NUMERIC_BOUND
from hiitl.sdk.tests.test_numeric_boundaries import ENV,DEC,POL
from hiitl.sdk.tests.test_handback_numeric_errors import typed
ROOT=Path(__file__).resolve().parents[4]
ROWS=[r for r in json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['cases'] if r['format']=='envelope']

def config(tmp_path):return HostedModeConfig(environment='dev',org_id=ENV['org_id'],agent_id='fixture',api_key='local-contract-fixture-key',server_url='https://fixture.invalid',audit_db_path=str(tmp_path/'audit.db'))

@pytest.mark.parametrize('row',ROWS,ids=lambda r:r['id'])
def test_exported_hosted_input_has_envelope_refusal(row,tmp_path,monkeypatch):
 client=HostedClient(config(tmp_path));monkeypatch.setattr(client,'_push_first',lambda:None)
 monkeypatch.setattr(client,'_ask',lambda *a,**kw:(httpx.Response(200,json=DEC),None))
 try:
  assert client.evaluate(row['control']).allowed
  data=copy.deepcopy(row['control']);at=data
  for part in row['path'][:-1]:at=at[part]
  at[row['path'][-1]]=NUMERIC_BOUND
  with public_error(EnvelopeValidationError)as caught:client.evaluate(data)
  typed(caught.value,row['path'],row['type'],row['range'].values())
 finally:client.close()

@pytest.mark.parametrize('entry',['public_sdk','hosted_component'])
def test_hosted_evaluation_admits_each_supplied_tree_once(entry,tmp_path,monkeypatch):
 monkeypatch.setattr(HostedClient,'_push_first',lambda self:None)
 monkeypatch.setattr(HostedClient,'_ask',lambda *a,**kw:(httpx.Response(200,json=DEC),None))
 if entry=='public_sdk':
  client=HIITL(sync=True,evaluation='remote',api_key='local-contract-fixture-key',signature_key='local-fixture-signing-secret',server_url='https://fixture.invalid',org_id=ENV['org_id'],environment='dev',audit_db_path=str(tmp_path/'sdk.db'))
  call=lambda:client.evaluate('read',parameters={'probe':1})
 else:
  client=HostedClient(config(tmp_path));call=lambda:client.evaluate(copy.deepcopy(ENV))
 roots=[]
 def trace(frame,event,arg):
  if event=='call' and frame.f_code is numeric_domain.validate_numeric_domain.__code__ and not numeric_domain.numbers_are_admitted() and not frame.f_locals.get('path',()) and isinstance(frame.f_locals['value'],dict):roots.append(frame.f_locals['value'])
 try:
  sys.setprofile(trace)
  answer=call()
 finally:sys.setprofile(None);client.close()
 assert answer.allowed
 assert len(roots)==2, [('decision'if 'allowed'in r else'envelope'if 'action_id'in r else'options')for r in roots]

@pytest.mark.parametrize('member',['target','parameters'])
def test_verifier_cannot_change_the_already_admitted_owned_input(member,tmp_path):
 supplied={'probe':1}
 policy=copy.deepcopy(POL);policy['rules']=[{'name':'original','description':'original','priority':1,'conditions':{'field':f'{member}.probe','operator':'equals','value':1},'decision':'ALLOW','reason_code':'ORIGINAL'}]
 file=tmp_path/'policy.json';file.write_text(json.dumps(policy))
 def verifier(token):supplied['probe']=NUMERIC_BOUND;return {'sub':'verified'}
 client=HIITL(sync=False,mode='RESPECT_POLICY',policy_path=str(file),audit_db_path=str(tmp_path/'owned.db'),principal_verifier=verifier)
 try:
  result=client.evaluate('read',principal_token='fixture',**{member:supplied})
  assert result.reason_codes==['ORIGINAL'] and result.allowed
  record=client._audit_logger.get_unsynced()[-1]
  assert record['envelope'][member]['probe']==1 and supplied['probe']==NUMERIC_BOUND
 finally:client.close()

from hiitl.core.tests.handback_assertions import public_error

from hiitl.sdk.exceptions import ConfigurationError
HOSTED_NUMBERS=[name for name,field in HostedModeConfig.model_fields.items()if field.annotation in (int,float)]
@pytest.mark.parametrize('member',HOSTED_NUMBERS)
def test_direct_hosted_constructor_admits_mutable_supplied_settings(member,tmp_path):
 settings=config(tmp_path)
 control=HostedClient(settings);control.close()
 setattr(settings,member,NUMERIC_BOUND)
 with public_error(ConfigurationError) as caught:HostedClient(settings)
 typed(caught.value,[member],'integer'if HostedModeConfig.model_fields[member].annotation is int else'number')


def test_hosted_sdk_constructor_admits_supplied_settings_once(tmp_path):
 roots=[]
 def trace(frame,event,arg):
  if event=='call' and frame.f_code is numeric_domain.validate_numeric_domain.__code__ and not numeric_domain.numbers_are_admitted() and not frame.f_locals.get('path',()) and isinstance(frame.f_locals['value'],(dict,BaseModel)):roots.append(frame.f_locals['value'])
 client=None
 try:
  sys.setprofile(trace)
  client=HIITL(sync=True,evaluation='remote',api_key='local-contract-fixture-key',signature_key='local-fixture-signing-secret',server_url='https://fixture.invalid',org_id=ENV['org_id'],environment='dev',audit_db_path=str(tmp_path/'settings.db'))
 finally:
  sys.setprofile(None)
  if client:client.close()
 assert len(roots)==1, [type(r).__name__ for r in roots]
