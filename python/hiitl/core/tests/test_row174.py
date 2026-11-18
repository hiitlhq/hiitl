"""Row 174 (HTL-22): the outage decision's `metadata` is the spec's.

decision_response.md, the decision schema's `metadata`: "Present on CONTROL_PLANE_UNAVAILABLE: the fail mode the
outage applied, and the hosted client's circuit breaker after the call (Example 9)". Read at its producer: the schema
block and Example 9's JSON. Design: the HTL-22 test design, row 174, behaviors 7 and 8. Mirrors
typescript/packages/core/tests/unit/row174.test.ts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from hiitl.core.error_decisions import MESSAGES, error_decision
from hiitl.core.types import Decision, DecisionMetadata

SPEC = (Path(__file__).resolve().parents[4] / "docs" / "specs" / "decision_response.md").read_text(encoding="utf-8")


def _json_after(heading: str) -> dict:
    block = SPEC.split(heading, 1)[1].split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)


def test_metadata_is_the_spec_s():
    schema = _json_after("### JSON Schema")["properties"]["metadata"]
    fields = DecisionMetadata.model_fields
    assert set(fields) == set(schema["properties"]) == set(schema["required"])
    for name, prop in schema["properties"].items():
        assert set(get_args(fields[name].annotation)) == set(prop["enum"]), name
    assert schema["additionalProperties"] is False
    with pytest.raises(ValidationError):
        DecisionMetadata(fail_mode="FAIL_CLOSED", circuit_breaker_state="open", retry_after_ms=1000)


def test_example_9_is_a_decision():
    example = _json_after("### Example 9:")
    d = Decision.model_validate(example)
    assert (d.decision, d.allowed, d.error.code) == ("CONTROL_PLANE_UNAVAILABLE", False, "CONTROL_PLANE_UNAVAILABLE")
    assert d.metadata.model_dump() == example["metadata"]
    assert d.error.message == MESSAGES[d.reason_codes[0]], "the example's message is the cause's"


def test_the_error_decision_carries_its_metadata():
    meta = DecisionMetadata(fail_mode="FAIL_CLOSED", circuit_breaker_state="half_open")
    d = error_decision("act_r174core00000000000", "CONTROL_PLANE_UNAVAILABLE", "CONTROL_PLANE_UNREACHABLE",
                       MESSAGES["CONTROL_PLANE_UNREACHABLE"], metadata=meta)
    assert d.metadata == meta
    assert error_decision("act_r174core00000000000", "POLICY_ERROR", "POLICY_NOT_FOUND",
                          MESSAGES["POLICY_NOT_FOUND"]).metadata is None
