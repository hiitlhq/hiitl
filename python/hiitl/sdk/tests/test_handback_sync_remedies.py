"""Every canonical numeric member at sync/cache entries keeps its declared remedy."""
import copy,json
from pathlib import Path
import httpx,pytest
from hiitl.core.numeric_domain import NUMERIC_BOUND
from hiitl.sdk.sync_client import SyncClient
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.exceptions import SyncError
from hiitl.sdk.tests.test_handback_numeric_errors import typed
from hiitl.sdk.tests.test_numeric_boundaries import ENV
ROOT=Path(__file__).resolve().parents[4]
ROWS=json.loads((ROOT/'tests/conformance/numeric_sync/cases.json').read_text())['cases']
@pytest.mark.parametrize('row',ROWS,ids=lambda r:r['id'])
def test_numeric_sync_entry_uses_channel_path_and_declared_remedy(row,tmp_path,monkeypatch):
    data=copy.deepcopy(row['input']);channel=row['channel']
    client=SyncClient('https://fixture.invalid','local-contract-fixture-key',ENV['org_id'],'dev')
    if row['entry']=='cache':
        cache=SyncCache(str(tmp_path),ENV['org_id'],'dev')
        method={'policy':'update_policies','routes':'update_routes','kill_switches':'update_kill_switches'}[channel]
        call=lambda:getattr(cache,method)(data)
    elif row['entry']=='upload':
        monkeypatch.setattr(client,'_send_with_retry',lambda *a,**kw:httpx.Response(200,json={'accepted':1}))
        call=lambda:client.upload_telemetry(data['records'])
    else:
        monkeypatch.setattr(client,'_send_with_retry',lambda *a,**kw:httpx.Response(200,json=data))
        call={'policy':client.download_policies,'routes':client.download_routes,'kill_switches':client.poll_kill_switches,'audit':lambda:client.upload_audit([],1)}[channel]
    try:
        call()
        at=data
        for part in row['path'][:-1]:at=at[part]
        at[row['path'][-1]]=NUMERIC_BOUND
        with public_error(SyncError)as caught:call()
        assert caught.value.channel==channel
        typed(caught.value,row['path'],row['type'],row['range'].values())
    finally:client.close()

from hiitl.core.tests.handback_assertions import public_error
