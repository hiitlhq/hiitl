"""Row 159 (HTL-22): the error decisions are one set, the spec's.

decision_response.md, Error Handling: "All errors produce structured decision responses", and its error decisions.
The spec is read at its producer: the decision schema's enum and the Error Handling list. Design: the HTL-22 test
design, row 159, behavior 10. Mirrors typescript/packages/core/tests/unit/row159.test.ts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hiitl.core.error_decisions import ERROR_DECISIONS, MESSAGES, audit_write_failed, error_decision
from hiitl.core.types import PRODUCED_DECISIONS, DecisionType

SPEC = (Path(__file__).resolve().parents[4] / "docs" / "specs" / "decision_response.md").read_text(encoding="utf-8")


def _schema_decisions() -> set[str]:
    enum = re.search(r'"decision": \{\s*"type": "string",\s*"enum": (\[[^\]]*\])', SPEC)
    return set(json.loads(enum.group(1)))


def _error_handling_decisions() -> set[str]:
    section = SPEC.split("## Error Handling", 1)[1].split("**Error decisions**:", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"^- `([A-Z_]+)`", section, re.M))


def test_the_error_decisions_are_the_spec_s():
    listed = _error_handling_decisions()
    assert ERROR_DECISIONS == listed
    assert listed <= _schema_decisions() == {d.value for d in DecisionType}
    assert listed <= set(PRODUCED_DECISIONS), "an error decision is the path's, never a rule's to write"


def test_an_error_decision_carries_its_decision_as_its_code_and_its_cause_as_its_reason():
    d = error_decision("act_r159core00000000000", "POLICY_ERROR", "POLICY_NOT_FOUND", MESSAGES["POLICY_NOT_FOUND"])
    assert (d.decision, d.allowed, d.reason_codes, d.error.code) == (
        "POLICY_ERROR", False, ["POLICY_NOT_FOUND"], "POLICY_ERROR")
    blocked = audit_write_failed(d)
    assert (blocked.decision, blocked.allowed, blocked.error.code) == ("BLOCK", False, "AUDIT_WRITE_FAILED")
