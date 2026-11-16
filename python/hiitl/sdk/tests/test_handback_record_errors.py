"""The canonical numeric member matrix reaches public record writers/readers."""
import copy,json
from pathlib import Path
import httpx,pytest
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.http_client import HostedClient
from hiitl.sdk.config import HostedModeConfig
from hiitl.sdk.exceptions import AuditLogError,ServerError
from hiitl.sdk.tests.test_numeric_boundaries import ENV,DEC
from hiitl.sdk.tests.test_handback_numeric_errors import typed
from hiitl.core.numeric_domain import NUMERIC_BOUND
ROOT=Path(__file__).resolve().parents[4]
MEMBERS=json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['cases']
RECORD_MEMBERS=[r for r in MEMBERS if r['format'] in ('envelope','decision')]

def invalid(row):
    value=copy.deepcopy(row['control']);at=value
    for part in row['path'][:-1]:at=at[part]
    at[row['path'][-1]]=NUMERIC_BOUND
    return value

@pytest.mark.parametrize('row',RECORD_MEMBERS,ids=lambda r:r['id'])
def test_new_record_refusal_keeps_audit_error(row,tmp_path):
    writer=AuditLogger(str(tmp_path/'audit.db'))
    terms={'envelope':copy.deepcopy(ENV),'decision':copy.deepcopy(DEC)}
    terms[row['format']]=row['control']
    event=writer.write(**terms);assert writer.verify_integrity(event)
    before=writer.get_unsynced()
    terms[row['format']]=invalid(row)
    with public_error(AuditLogError)as caught:writer.write(**terms)
    assert getattr(caught.value,'reason',None) is None
    typed(caught.value,[row['format'],*row['path']],row['type'],row['range'].values())
    assert writer.get_unsynced()==before

@pytest.mark.parametrize('row',[r for r in MEMBERS if r['format']=='decision'],ids=lambda r:r['id'])
def test_hosted_numeric_reply_keeps_server_error(row,tmp_path,monkeypatch):
    config=HostedModeConfig(environment='dev',agent_id='fixture',org_id=ENV['org_id'],api_key='local-contract-fixture-key',server_url='https://fixture.invalid',audit_db_path=str(tmp_path/'hosted.db'))
    client=HostedClient(config)
    data=copy.deepcopy(row['control'])
    monkeypatch.setattr(client,'_push_first',lambda:None)
    monkeypatch.setattr(client,'_ask',lambda *a,**kw:(httpx.Response(200,json=data),None))
    try:
        assert client.evaluate(ENV).action_id==data['action_id']
        data=invalid(row)
        with public_error(ServerError)as caught:client.evaluate(ENV)
        assert caught.value.status_code==200
        assert caught.value.error_code=='UNKNOWN_ERROR'
        typed(caught.value,row['path'],row['type'],row['range'].values())
    finally:client.close()

from hiitl.core.tests.handback_assertions import public_error
