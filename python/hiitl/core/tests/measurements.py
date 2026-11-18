"""Measured test observations, retained through pytest's ordinary report path."""

import json


def record_measurement(record_property, *, metric, unit, source, value):
    record_property("htl30.measurement", json.dumps({
        "metric": metric, "unit": unit, "source": source, "value": value,
    }, sort_keys=True, allow_nan=False))
