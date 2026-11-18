"""The authored record survives unchanged; a missing record fails the cell."""

import json

import pytest

from hiitl.core.tests.measurements import record_measurement


@pytest.mark.parametrize("value", [0.125, 0, [], {"model": "fixture", "estimate": 0}, ""])
def test_measurement_records_exact_metadata_and_observed_value(value):
    captured = []
    record_measurement(
        lambda name, encoded: captured.append((name, json.loads(encoded))),
        metric="fixture_observation", unit="fixture_unit", source="fixture/source", value=value,
    )
    assert captured == [("htl30.measurement", {
        "metric": "fixture_observation", "unit": "fixture_unit", "source": "fixture/source", "value": value,
    })]
