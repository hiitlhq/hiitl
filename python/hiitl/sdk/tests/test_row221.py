"""Row 221 (HTL-24): `HIITL_SYNC_RL_INTERVAL`, as built.

Ruled 2026-11-07: "as built … sync_engine.md §9 names row 131 beside it." The class is a §9 row no setting reads: it
states no default and names the gap row that would build it; its variable, set, is refused (row 207's cells), and its
constructor option is refused as an undefined option, naming it. The rows are read from §9 and the read names from the
settings models; no name is listed here. Design: the HTL-24 test design, row 221. Mirrors
typescript/packages/sdk/tests/unit/row221.test.ts.
"""

from __future__ import annotations

import os
import re

import pytest

from hiitl import HIITL
from hiitl.sdk.tests.settings_tables import SYNC, code
from hiitl.sdk.tests.test_row129 import _readers

READ = set(_readers())
UNBUILT = [row for row in SYNC if code(row[2]) not in READ]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def test_a_row_no_setting_reads_names_its_gap_row_and_no_default():
    """Behavior 1: §9 states a default for each row a setting reads, and for a row none reads, the gap row instead."""
    assert UNBUILT, "§9 holds a row no setting reads (row 131's)"
    for row in UNBUILT:
        assert "`" not in row[3] and re.search(r"\(gap row \d+\)", row[3]), row
    assert [row for row in SYNC if code(row[2]) in READ and "`" not in row[3]] == []


@pytest.mark.parametrize("row", UNBUILT, ids=[code(row[1]) for row in UNBUILT])
def test_the_option_of_a_row_no_setting_reads_is_refused_naming_it(tmp_path, row):
    """Behavior 2: the constructor option is not an option the client takes, refused naming it."""
    option = code(row[1])
    with pytest.raises(TypeError) as exc:
        HIITL(audit_db_path=str(tmp_path / "audit.db"), **{option: 60}).close()
    assert repr(option) in str(exc.value)
