"""HTL-45: test order cannot pay for the first evaluate in another process.

Design: tests/conformance/sdk_startup/TEST_DESIGN.md. The process contains
the real client, loader, cache, evaluator and background engine. HTTP alone
is a wire fixture. A missing target is an unread declaration, never a pass.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hiitl.core.tests.declared_values import declared_number, pure_local_budget_ms, typical_core_budget_ms, latency_sample_count, latency_statistic, record_latencies

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / 'tests/conformance/sdk_startup'
CASES = json.loads((FIXTURE / 'cases.json').read_text())


def mode_budget_ms(mode):
    if mode in ('local', 'hybrid'):
        return pure_local_budget_ms()
    if mode == 'hosted':
        return declared_number('docs/specs/decision_response.md',
                               r'^- \*\*Pure hosted mode\*\*: Low tens of milliseconds \(< ([\d.]+)ms, region-dependent\)$')
    raise AssertionError(f'Undeclared deployment mode: {mode}')


@pytest.mark.parametrize('observation', ('timing', 'producers'))
@pytest.mark.parametrize('case', CASES, ids=lambda c: '/'.join(c.values()))
def test_every_fresh_process_call_meets_its_declared_target(case, observation, tmp_path, record_property):
    rows = []
    for sample in range(latency_sample_count() if observation == 'timing' else 1):
        directory = tmp_path / str(sample)
        directory.mkdir()
        policy = json.loads((FIXTURE / 'policy.json').read_text())
        payload = json.loads((FIXTURE / 'policy-response.json').read_text())
        for suffix in ('json', 'yaml'):
            (directory / f'policy.{suffix}').write_text(json.dumps(policy))
        (directory / 'payload.json').write_text(json.dumps(payload))
        (directory / 'case.json').write_text(json.dumps(case))
        if case['source'] == 'disk':
            cache = directory / 'cache' / policy['scope']['org_id'] / policy['scope']['environment']
            cache.mkdir(parents=True)
            data = json.dumps(payload).encode()
            (cache / 'policies.json').write_bytes(data)
            (cache / 'policies.json.sha256').write_text(hashlib.sha256(data).hexdigest())
            (cache / 'policies.etag').write_text(payload['etag'])
        env = {key: value for key, value in os.environ.items()
               if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT')}
        env.update(PYTHONPATH=str(ROOT / 'python'), PYTHONDONTWRITEBYTECODE='1')
        child = subprocess.run([sys.executable, str(FIXTURE / 'python_child.py'), str(ROOT), str(directory)]
                               + (['--producers'] if observation == 'producers' else []),
                               cwd=directory, env=env, capture_output=True, text=True, check=False)
        tagged = [line.removeprefix('HTL45_SAMPLE ') for line in child.stdout.splitlines()
                  if line.startswith('HTL45_SAMPLE ')]
        assert child.returncode == 0 and len(tagged) == 1, (child.stdout, child.stderr)
        row = json.loads(tagged[0])
        assert 'error' not in row, row
        assert row['resolved_mode'] == case['mode']
        assert row['clock_loads'] == [], f"the clock prepays what the first call pays: {row['clock_loads']}"
        rows.append(row)
    record_property('fresh_process_samples', json.dumps({'case': case, 'samples': rows}))
    for row in rows:
        for call in ('first', 'repeated'):
            decision = row[call + '_decision']
            expected = 'BLOCK' if case['mode'] == 'hosted' or case['evaluation'] == 'RESPECT_POLICY' else 'OBSERVE'
            assert decision['decision'] == expected, row
            if case['source'] != 'none':
                assert decision['policy_version'] == 'v1.0.0', row
            if case['source'] in ('json', 'yaml'):
                assert row['construction_policy_reads'] > 0, row
    if observation == 'producers':
        late = [event for row in rows for event in row['producer_events']
                if event['phase'] not in ('imports', 'construction')]
        assert not late, late
        assert any(row['producer_events'] for row in rows), 'Producer observation did not run'
        return
    name = '/'.join(case.values())
    populations = []
    for call in ('first', 'repeated'):
        populations.append((f'fresh/{name}/{call}/call', [row[call + '_ms'] for row in rows],
                            'hosted' if case['mode'] == 'hosted' else 'local'))
        if case['mode'] == 'hybrid':
            populations.append((f'fresh/{name}/{call}/evaluation',
                                [row[call + '_decision']['timing']['evaluation_ms'] for row in rows], 'core'))
    record_latencies(populations)


def test_file_reading_follows_its_source_and_records_refusals(tmp_path, record_property):
    env = {key: value for key, value in os.environ.items()
           if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT')}
    env.update(PYTHONPATH=str(ROOT / 'python'), PYTHONDONTWRITEBYTECODE='1')
    child = subprocess.run([sys.executable, str(FIXTURE / 'file_probe.py'), str(ROOT)],
                           cwd=tmp_path, env=env, capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
    rows = json.loads(next(line.removeprefix('HTL45_FILES ') for line in child.stdout.splitlines()
                           if line.startswith('HTL45_FILES ')))
    record_property('file_observations', json.dumps(rows))
    failures = []
    for row in rows:
        if row['fault'] == 'unreadable' and row['readable']:
            good = row.get('decision') == 'ALLOW' and row.get('version') == 'v1.0.0' and row.get('record_decisions') == ['ALLOW']
        elif row['when'] == 'construction':
            good = row.get('error') == 'PolicyLoadError'
        else:
            expected = 'BLOCK' if row['fault'].startswith(('valid', 'replacement')) else 'POLICY_ERROR'
            good = row.get('decision') == expected and row.get('record_decisions') == [expected]
            if expected == 'BLOCK': good = good and row.get('version') == 'v2.0.0'
        if not good: failures.append(row)
    assert not failures, failures


def test_latency_reads_p95_not_one_sample_or_every_sample():
    n = latency_sample_count()
    assert n == 20
    samples = [0.0] * (n - 1) + [10.0]
    assert latency_statistic(samples) == pytest.approx(0.5)
    assert latency_statistic(reversed(samples)) == pytest.approx(0.5)
    assert latency_statistic([10.0] * n) == 10.0


def test_real_filesystem_tick_rewrites(tmp_path, record_property):
    env = {key: value for key, value in os.environ.items()
           if key in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SYSTEMROOT')}
    env.update(PYTHONPATH=str(ROOT/'python'), PYTHONDONTWRITEBYTECODE='1')
    child = subprocess.run([sys.executable,str(FIXTURE/'same_tick_probe.py')],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert child.returncode == 0, (child.stdout,child.stderr)
    rows = json.loads(next(line.removeprefix('HTL45_TICKS ') for line in child.stdout.splitlines() if line.startswith('HTL45_TICKS ')))
    record_property('real_file_timestamps',json.dumps(rows))
    assert rows and all(row['decision']=='BLOCK' and row['version']=='v2.0.0' for row in rows), rows
