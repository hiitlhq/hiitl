"""One organisation id form (HTL-19 row 144; B.foundation.6): the envelope schema states it, `ORG_ID_PATTERN` reads it,
and the models that carry an org id read `ORG_ID_PATTERN`, so the SDK takes every id the service mints
(sync_engine.md §8). The tree's other statements of the form are read by the service's tests, which see the whole tree."""

import json
from pathlib import Path

from hiitl.core.route_types import RouteScope
from hiitl.core.types import ORG_ID_PATTERN, Envelope

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = [ROOT / "docs" / "specs" / "envelope_schema.json"]


def test_the_pattern_is_the_envelope_schemas():
    for schema in SCHEMAS:
        assert json.loads(schema.read_text())["properties"]["org_id"]["pattern"] == ORG_ID_PATTERN, schema


def test_the_envelope_and_a_routes_scope_read_it():
    for model in (Envelope, RouteScope):
        assert model.model_fields["org_id"].metadata[0].pattern == ORG_ID_PATTERN, model.__name__
