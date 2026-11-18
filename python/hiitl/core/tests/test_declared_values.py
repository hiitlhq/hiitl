"""A bound is read from one located source declaration, never an empty/ambiguous parse (HTL-30)."""

import pytest

from hiitl.core.tests import declared_values


@pytest.mark.parametrize("text", ["No declared limit here", "Budget: 7\nBudget: 8"])
def test_missing_or_ambiguous_declaration_is_refused(tmp_path, monkeypatch, text):
    (tmp_path / "spec.md").write_text(text)
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="Expected one declaration"):
        declared_values.declared_number("spec.md", r"^Budget: ([\d.]+)$")


def test_declared_value_is_read_from_the_named_sentence(tmp_path, monkeypatch):
    bound = 7.25
    (tmp_path / "spec.md").write_text(f"Example: 999\nBudget: {bound}\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    assert declared_values.declared_number("spec.md", r"^Budget: ([\d.]+)$") == bound


def test_typical_core_budget_reads_public_timing_metadata(tmp_path, monkeypatch):
    path = tmp_path / "docs/specs/decision_response.md"
    path.parent.mkdir(parents=True)
    bound = 7.25
    path.write_text(f"Example: 999ms\n- **Typical core evaluation**: < {bound}ms for typical policies.\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    assert declared_values.typical_core_budget_ms() == bound


def test_typical_core_budget_refuses_missing_public_declaration(tmp_path, monkeypatch):
    path = tmp_path / "docs/specs/decision_response.md"
    path.parent.mkdir(parents=True)
    path.write_text("- **Pure local mode**: Single-digit milliseconds (< 10ms)\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="Expected one declaration"):
        declared_values.typical_core_budget_ms()


def test_latency_gate_records_normally_and_asserts_only_at_release(tmp_path, monkeypatch):
    import json
    assert callable(getattr(declared_values, 'record_latency', None)), 'release timing recorder is absent'
    monkeypatch.setenv('HIITL_LATENCY_RECORD_DIR', str(tmp_path))
    monkeypatch.delenv('HIITL_RELEASE_LATENCY', raising=False)
    samples = [declared_values.pure_local_budget_ms()] * declared_values.latency_sample_count()
    row = declared_values.record_latency('probe', samples, 'local')
    assert row['samples_ms'] == samples and row['asserted'] is False
    files = list(tmp_path.glob('*.latency.json'))
    assert len(files) == 1, 'samples were not retained'
    assert json.loads(files[0].read_text()) == row
    monkeypatch.setenv('HIITL_RELEASE_LATENCY', '1')
    with pytest.raises(AssertionError, match='p95'):
        declared_values.record_latency('probe', samples, 'local')
    row = json.loads(next(tmp_path.glob('*.latency.json')).read_text())
    assert row['asserted'] is True and row['p95_ms'] == samples[0]


def test_latency_release_requires_a_sample_record(tmp_path, monkeypatch):
    assert callable(getattr(declared_values, 'record_latency', None)), 'release timing recorder is absent'
    monkeypatch.setenv('HIITL_RELEASE_LATENCY', '1')
    monkeypatch.delenv('HIITL_LATENCY_RECORD_DIR', raising=False)
    with pytest.raises(AssertionError, match='record directory'):
        declared_values.record_latency('probe', [0.0] * declared_values.latency_sample_count(), 'local')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.0])
def test_latency_rejects_invalid_measurements(tmp_path, monkeypatch, bad):
    assert callable(getattr(declared_values, 'record_latency', None)), 'release timing recorder is absent'
    monkeypatch.setenv('HIITL_LATENCY_RECORD_DIR', str(tmp_path))
    with pytest.raises(AssertionError, match='finite nonnegative'):
        declared_values.record_latency('probe', [bad] * declared_values.latency_sample_count(), 'local')


def test_release_retains_every_population_before_failing(tmp_path,monkeypatch):
    monkeypatch.setenv('HIITL_RELEASE_LATENCY','1')
    monkeypatch.setenv('HIITL_LATENCY_RECORD_DIR',str(tmp_path))
    n=declared_values.latency_sample_count();bound=declared_values.pure_local_budget_ms()
    with pytest.raises(AssertionError,match='p95'):
        declared_values.record_latencies([('first',[bound]*n,'local'),('repeated',[0.0]*n,'local')])
    assert len(list(tmp_path.glob('*.latency.json')))==2


# HTL-17 19d576ee: an in-process cell is read at the warmup and count its catalogue entry declares.
@pytest.fixture
def in_process(monkeypatch):
    assert callable(getattr(declared_values, 'latency_run', None)), 'in-process run reader is absent'
    cell = {'case': 'probe/in-process', 'target': 'local', 'stages': ['suite'], 'warmup': 3, 'count': 25}
    undeclared = {'case': 'probe/undeclared', 'target': 'local', 'stages': ['suite']}
    monkeypatch.setattr(declared_values, 'timing_cells', lambda: [dict(cell), dict(undeclared)])
    monkeypatch.delenv('HIITL_RELEASE_LATENCY', raising=False)
    monkeypatch.delenv('HIITL_LATENCY_RECORD_DIR', raising=False)
    return cell


def test_latency_reads_each_in_process_run_at_its_declaration(in_process):
    assert declared_values.latency_run(in_process['case']) == (in_process['warmup'], in_process['count'])
    assert declared_values.latency_run('probe') == (0, declared_values.latency_sample_count())


def test_latency_reads_the_python_catalogue():
    import json
    assert callable(getattr(declared_values, 'timing_cells', None)), 'timing catalogue reader is absent'
    path = declared_values._ROOT / 'tests/conformance/sdk_startup/timing_cells.json'
    assert declared_values.timing_cells() == json.loads(path.read_text())['python']


def test_latency_refuses_a_catalogued_case_that_declares_no_run(in_process, monkeypatch):
    with pytest.raises(AssertionError, match='declares no in-process run'):
        declared_values.latency_run('probe/undeclared')
    short = {**in_process, 'count': declared_values.latency_sample_count() - 1}
    monkeypatch.setattr(declared_values, 'timing_cells', lambda: [short])
    with pytest.raises(AssertionError, match='declares no in-process run'):
        declared_values.latency_run(in_process['case'])


def test_latency_refuses_a_dropped_warmup_or_another_count(in_process):
    case, warmup, count = in_process['case'], in_process['warmup'], in_process['count']
    n = declared_values.latency_sample_count()
    with pytest.raises(AssertionError, match='declared run'):
        declared_values.record_latency(case, [0.0] * count, 'local', [])
    with pytest.raises(AssertionError, match='declared run'):
        declared_values.record_latency(case, [0.0] * (count - 1), 'local', [0.0] * warmup)
    with pytest.raises(AssertionError, match='declared run'):
        declared_values.record_latency('probe', [0.0] * (n + 1), 'local')
    with pytest.raises(AssertionError, match='declared run'):
        declared_values.record_latency('probe', [0.0] * n, 'local', [0.0])
    assert declared_values.record_latency(case, [0.0] * count, 'local', [0.0] * warmup).get('warmup_ms') == [0.0] * warmup


def test_latency_reads_the_run_not_its_warmup(in_process, tmp_path, monkeypatch):
    monkeypatch.setenv('HIITL_RELEASE_LATENCY', '1')
    monkeypatch.setenv('HIITL_LATENCY_RECORD_DIR', str(tmp_path))
    case, warmup, count = in_process['case'], in_process['warmup'], in_process['count']
    bound = declared_values.pure_local_budget_ms()
    assert declared_values.record_latency(case, [0.0] * count, 'local', [bound * 2] * warmup)['p95_ms'] == 0.0
    declared_values.record_latencies([(case, [0.0] * count, 'local', [bound * 2] * warmup)])
    with pytest.raises(AssertionError, match='p95'):
        declared_values.record_latency(case, [bound] * count, 'local', [0.0] * warmup)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.0])
def test_latency_rejects_invalid_warmup_times(in_process, bad):
    with pytest.raises(AssertionError, match='finite nonnegative warmup'):
        declared_values.record_latency(in_process['case'], [0.0] * in_process['count'], 'local', [bad] * in_process['warmup'])
