"""Row 195 (HTL-23): each error decision's event type is the table's.

Ruled 2026-11-06 as the row reads: "as built, by the table, since no sentence names a type for the other two". The
table is event_format.md's "Event types"; the error decisions are decision_response.md's "Error decisions", and the
control point's own failures are `BLOCK`s ("Where the error is answered"). Both are read from the specs, never listed
here. Design: the HTL-23 test design, row 195. Mirrors typescript/packages/core/tests/unit/row195.test.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiitl.core.lifecycle import event_type

SPECS = Path(__file__).resolve().parents[4] / "docs" / "specs"


def _error_decisions() -> list[str]:
    """The decisions decision_response.md's "Error decisions" list names, each a bullet under it."""
    text = (SPECS / "decision_response.md").read_text(encoding="utf-8")
    listed = text.split("**Error decisions**:", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^- `([A-Z_]+)` - ", listed, re.M)


def _table() -> tuple[dict[str, str], str]:
    """event_format.md's table, for a decision record: each decision it names, its type; and the type of any other."""
    text = (SPECS / "event_format.md").read_text(encoding="utf-8")
    named, other = {}, None
    for event, decision in re.findall(r"^\| `([a-z_.]+)` \| a decision record \| ([^|]+?) \| none \|$", text, re.M):
        if decision == "any other":
            other = event
        else:
            named[decision.strip("`")] = event
    assert other is not None, "the table names the type of any other decision"
    return named, other


def test_each_error_decision_takes_the_type_the_table_states():
    decisions = _error_decisions()
    assert decisions, "the Error decisions list is read"
    named, other = _table()
    for decision in [*decisions, "BLOCK"]:
        assert event_type(decision) == named.get(decision, other), decision
