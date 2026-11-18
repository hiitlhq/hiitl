"""Row 224 (HTL-27): the codes under which the service refuses a record for its own content, one table.

Ruled 2026-11-08: "a record the service refuses for its own content stays in the local store as written, marked
refused with the service's code, logged at error, and not sent again". sync_engine.md §2.1 names the codes and says
"These codes are one table, `RECORD_REFUSALS` in `hiitl.core.lifecycle` and `@hiitl/core`". The table is read against
that sentence, at its producer. Design: the HTL-27 test design, row 224, behavior 1. Mirrors
typescript/packages/core/tests/unit/row224.test.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiitl.core.lifecycle import RECORD_REFUSALS

SPEC = (Path(__file__).resolve().parents[4] / "docs" / "specs" / "sync_engine.md").read_text()


def _bullet(head: str) -> str:
    """The §2.1 bullet that opens with `head`, to the next bullet."""
    return re.search(rf"^- \*\*{re.escape(head)}\*\*(.*?)(?=^- |\Z)", SPEC, re.M | re.S).group(1)


def final_codes() -> list[str]:
    """The codes the final bullet names as refusing "a record for what it carries"."""
    named = re.search(r"\)\.(.*?) refuse a record for what it carries", _bullet("A refusal of the record's own content "
                                                                               "is final"), re.S).group(1)
    return re.findall(r"`([A-Z][A-Z_]+)`", named)


def test_the_table_is_the_specs():
    assert final_codes(), "the spec names the codes"
    assert list(RECORD_REFUSALS) == final_codes()
