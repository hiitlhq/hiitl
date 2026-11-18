"""70254bbc: content confirms an entry while the platform clock is still tied."""
import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from hiitl.sdk.client import HIITL

FIXTURE = Path(__file__).resolve().parents[4] / 'tests/conformance/sdk_startup'


@pytest.mark.parametrize('suffix', ['json', 'yaml'])
def test_same_tick_rewrite_and_settled_unchanged_reading(suffix, tmp_path, monkeypatch):
    policy = json.loads((FIXTURE / 'policy.json').read_text())
    policy['rules'][0]['decision'] = 'ALLOW'
    path = tmp_path / ('policy.' + suffix)
    path.write_text(json.dumps(policy))
    client = HIITL(policy_path=str(path), mode='RESPECT_POLICY', org_id=policy['scope']['org_id'],
                   audit_db_path=str(tmp_path / 'audit.db'))
    loader = client._policy_loader
    source = path.stat()
    clock = [source.st_ctime_ns]
    read_count = [0]
    stat, fstat, opened = Path.stat, os.fstat, builtins.open

    def stamp(value, time_ns):
        fields = {name: getattr(value, name) for name in dir(value) if name.startswith('st_')}
        fields.update(st_ctime_ns=time_ns, st_ctime=time_ns / 1_000_000_000,
                      st_mtime_ns=source.st_mtime_ns, st_mtime=source.st_mtime)
        return SimpleNamespace(**fields)

    def file_stat(self, *args, **kwargs):
        value = stat(self, *args, **kwargs)
        return stamp(value, source.st_ctime_ns) if self == path else value

    def counted_open(file, *args, **kwargs):
        if file == path: read_count[0] += 1
        return opened(file, *args, **kwargs)

    with monkeypatch.context() as platform:
        platform.setattr(Path, 'stat', file_stat)
        platform.setattr(os, 'fstat', lambda fd: stamp(fstat(fd), clock[0]))
        platform.setattr(builtins, 'open', counted_open)
        loader.invalidate_cache()
        old = loader.load()
        policy['version'] = 'v2.0.0'; policy['rules'][0]['decision'] = 'BLOCK'
        path.write_text(json.dumps(policy))
        # The source identity/size/mtime/ctime all still read as the same tick.
        assert loader._cached_metadata == (source.st_dev, source.st_ino, path.stat().st_size,
            source.st_mtime_ns, source.st_ctime_ns, source.st_mode, source.st_uid,
            source.st_gid, source.st_nlink, getattr(source, 'st_flags', None))
        decision = client.evaluate('guarded', parameters={'amount': 100})
        assert str(decision.decision) == 'BLOCK'
        assert decision.policy_version == 'v2.0.0'
        assert client._audit_logger.get_unsynced(limit=10)[0]['decision']['decision'] == 'BLOCK'
        held = loader.load()
        assert held is not old
        # A later platform timestamp is a different tick, not a chosen duration.
        clock[0] += 1
        assert loader.load() is held
        reads = read_count[0]
        assert loader.load() is held
        assert read_count[0] == reads
    client.close()


def test_unavailable_clock_confirms_content_without_new_source_permission(tmp_path, monkeypatch):
    from hiitl.sdk import file_clock
    from hiitl.sdk.policy_loader import PolicyLoader
    policy = json.loads((FIXTURE / 'policy.json').read_text())
    path = tmp_path / 'policy.json'; path.write_text(json.dumps(policy))
    def unavailable(): raise PermissionError('clock directory is read-only')
    monkeypatch.setattr(file_clock.tempfile, 'TemporaryFile', unavailable)
    loader = PolicyLoader(str(path)); held = loader.load()
    assert loader.load() is held
    policy['version'] = 'v2.0.0'; path.write_text(json.dumps(policy))
    assert loader.load().version == 'v2.0.0'
