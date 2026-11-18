"""Read a numeric declaration at its source; a missing or ambiguous declaration fails the cell."""

from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[4]


def declared_number(relative_path: str, anchored_regex: str) -> float:
    path = _ROOT / relative_path
    matches = re.findall(anchored_regex, path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert len(matches) == 1, f"Expected one declaration matching {anchored_regex!r} in {path}; found {matches!r}"
    return float(matches[0])


def pure_local_budget_ms() -> float:
    return declared_number(
        "docs/specs/decision_response.md",
        r"^- \*\*Pure local mode\*\*: Single-digit milliseconds \(< ([\d.]+)ms\)$",
    )


def typical_core_budget_ms() -> float:
    return declared_number(
        "docs/specs/decision_response.md",
        r"^- \*\*Typical core evaluation\*\*: < ([\d.]+)ms for typical policies\.$",
    )


def latency_percentile() -> float:
    return declared_number('docs/specs/decision_response.md',
                           r'^If the p(\d+) of evaluation or round-trip latency is at or over') / 100


def latency_sample_count() -> int:
    """70254bbc: first nearest-rank sample whose p95 is below its maximum."""
    from fractions import Fraction
    from math import ceil
    p = Fraction(str(latency_percentile()))
    count = 1
    while ceil(p * count) == count:
        count += 1
    return count


def latency_statistic(samples) -> float:
    from hiitl.core.statistics import percentile
    values = list(samples)
    assert len(values) >= latency_sample_count(), 'Insufficient samples for the declared latency statistic'
    return percentile(values, latency_percentile())


def latency_target(target: str) -> float:
    if target == 'core':
        return typical_core_budget_ms()
    if target == 'local':
        return pure_local_budget_ms()
    assert target == 'hosted', f'Undeclared latency target: {target}'
    return declared_number('docs/specs/decision_response.md',
                           r'^- \*\*Pure hosted mode\*\*: Low tens of milliseconds \(< ([\d.]+)ms, region-dependent\)$')


def timing_cells() -> list:
    import json
    return json.loads((_ROOT / 'tests/conformance/sdk_startup/timing_cells.json').read_text(encoding='utf-8'))['python']


def latency_run(case: str) -> tuple:
    """HTL-17 19d576ee: an in-process cell runs the warmup and count it had before HTL-45, as its catalogue
    entry declares; any other population (a fresh process's) is the sample count above, with no warmup."""
    declared = [cell for cell in timing_cells() if cell['case'] == case]
    assert len(declared) <= 1, f'{case} is catalogued more than once'
    if not declared:
        return 0, latency_sample_count()
    warmup, count = declared[0].get('warmup'), declared[0].get('count')
    assert type(warmup) is int and type(count) is int and warmup >= 0 and count >= latency_sample_count(), \
        f'{case} declares no in-process run in the timing catalogue'
    return warmup, count


def record_latency(case: str, samples, target: str, warmup=()) -> dict:
    """d001d308: identical populations, recorded everywhere, asserted at release."""
    import hashlib
    import json
    import math
    import os
    import platform
    values = list(samples)
    warmup = list(warmup)
    assert all(type(x) in (int, float) and math.isfinite(x) and x >= 0 for x in values), 'Expected finite nonnegative latency samples'
    assert all(type(x) in (int, float) and math.isfinite(x) and x >= 0 for x in warmup), 'Expected finite nonnegative warmup times'
    declared_warmup, declared_count = latency_run(case)
    assert (len(warmup), len(values)) == (declared_warmup, declared_count), \
        f'{case}: recorded {len(warmup)} warmup and {len(values)} calls; its declared run is {declared_warmup} and {declared_count}'
    measured = latency_statistic(values)
    bound = latency_target(target)
    asserted = os.getenv('HIITL_RELEASE_LATENCY') == '1'
    directory = os.getenv('HIITL_LATENCY_RECORD_DIR')
    assert not asserted or directory, 'Release timing requires a record directory'
    row = dict(case=case, target=target, warmup_ms=warmup, samples_ms=values, p95_ms=measured,
               asserted=asserted, language='python', runtime=platform.python_version(),
               stage=os.getenv('HIITL_LATENCY_STAGE', 'suite'),
               export_commit=os.getenv('HIITL_LATENCY_EXPORT_COMMIT'),
               machine=json.loads(os.getenv('HIITL_LATENCY_MACHINE', '{}')))
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        key = json.dumps([row['language'],row['runtime'],row['stage'],case])
        (path / (hashlib.sha256(key.encode()).hexdigest()+'.latency.json')).write_text(json.dumps(row)+'\n')
    print('hiitl.latency ' + json.dumps(row))
    if asserted:
        assert measured < bound, f'{case}: p95 {measured} ms is at/over target {bound} ms'
    return row


def record_latencies(populations) -> None:
    """Retain both calls before reporting any failed release population."""
    failures = []
    for case, samples, target, *warmup in populations:
        try:
            record_latency(case, samples, target, *warmup)
        except AssertionError as error:
            failures.append(str(error))
    assert not failures, failures
