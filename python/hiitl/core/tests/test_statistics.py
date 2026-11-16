"""The ruled percentile convention, independent of each consumer's precision."""

import pytest


@pytest.mark.parametrize("samples,expected", [
    ([0.0, 10.0], (5.0, 9.5, 9.9)),
    ([9.0, 1.0, 4.0], (4.0, 8.5, 8.9)),
    ([2.3456], (2.3456, 2.3456, 2.3456)),
    ([8.0, 2.0, 2.0, 8.0], (5.0, 8.0, 8.0)),
], ids=["even", "odd-unsorted", "singleton-unrounded", "duplicates"])
def test_percentiles_interpolate_without_rounding(samples, expected):
    from hiitl.core.statistics import percentile

    original = samples.copy()
    assert tuple(percentile(samples, p) for p in (0.50, 0.95, 0.99)) == expected
    assert samples == original


def test_percentile_endpoints():
    from hiitl.core.statistics import percentile

    assert percentile([9.0, 1.0, 4.0], 0.0) == 1.0
    assert percentile([9.0, 1.0, 4.0], 1.0) == 9.0


def test_empty_sample_has_no_percentile():
    from hiitl.core.statistics import percentile

    with pytest.raises(ValueError, match="empty"):
        percentile([], 0.50)
