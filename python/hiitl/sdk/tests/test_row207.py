"""Row 207 (HTL-23): a set variable no setting reads is refused.

Ruled 2026-11-06: "a set `HIITL_*` variable no setting reads is refused at construction, naming its replacement, by
Principle 11 and ontology §4.3". The families the SDK's specs give it are refused (sync_engine.md §9, the
`HIITL_SYNC_*` names; telemetry_schema.md §5, the `HIITL_TELEMETRY_*` names), with each name an earlier release read
(§5, "Names earlier releases read"). The tables are read from the specs and the read names from the settings models,
as row 129 reads them; no name is listed here. Whether the rule reaches other components' names is the plan's
needs-a-ruling, and no cell is written for them. Design: the HTL-23 test design, row 207. Mirrors
typescript/packages/sdk/tests/unit/row207.test.ts.
"""

from __future__ import annotations

import os

import pytest

from hiitl import HIITL
from hiitl.sdk.exceptions import ConfigurationError
from hiitl.sdk.tests.settings_tables import EARLIER, FAMILIES, SYNC, TELEMETRY, code
from hiitl.sdk.tests.test_row129 import _readers

READ = {name for name in _readers() if name.startswith(tuple(FAMILIES))}
# Each family name a spec table names and no setting reads (computed: the tables less the readers)
UNREAD = sorted(name for names in FAMILIES.values() for name in names if name not in READ)
DEFAULTS = {code(row[2]): code(row[3]) for row in SYNC + TELEMETRY if "`" in row[3]}   # a row states a default as a code span


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _refused(tmp_path) -> str:
    """The message the client's construction is refused with."""
    with pytest.raises(ConfigurationError) as exc:
        HIITL(audit_db_path=str(tmp_path / "audit.db")).close()
    return str(exc.value)


@pytest.mark.parametrize("earlier", sorted(EARLIER))
def test_an_earlier_name_is_refused_naming_its_replacement(tmp_path, monkeypatch, earlier):
    """Behavior 1: a name an earlier release read, set, fails construction naming it and its replacement."""
    monkeypatch.setenv(earlier, DEFAULTS[EARLIER[earlier]])
    message = _refused(tmp_path)
    assert earlier in message and EARLIER[earlier] in message, message


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_an_unread_family_name_is_refused_naming_the_family(tmp_path, monkeypatch, family):
    """Behavior 2: a family name no table names fails construction naming it and each name the family's setting
    read."""
    unread = f"{family}R207_UNREAD"
    monkeypatch.setenv(unread, "1")
    message = _refused(tmp_path)
    assert unread in message, message
    assert [name for name in sorted(READ) if name.startswith(family) and name not in message] == [], message


@pytest.mark.parametrize("unread", UNREAD)
def test_a_name_a_table_names_and_no_setting_reads_is_refused(tmp_path, monkeypatch, unread):
    """Behavior 5: a name the spec's table names that this release reads with no setting fails construction, naming
    it, never ignored."""
    monkeypatch.setenv(unread, DEFAULTS.get(unread, "1"))
    assert unread in _refused(tmp_path)


def test_the_sdks_table_is_the_specs():
    """Behavior 3: the SDK's earlier names are §5's."""
    from hiitl.sdk.config import EARLIER_NAMES
    assert EARLIER_NAMES == EARLIER


def test_a_name_a_setting_reads_constructs(tmp_path, monkeypatch):
    """Behavior 4: every family name a setting reads, set to its table's default, constructs."""
    for name in sorted(READ):
        monkeypatch.setenv(name, DEFAULTS.get(name, "1"))
    try:
        HIITL(audit_db_path=str(tmp_path / "audit.db")).close()
    except ConfigurationError as e:
        pytest.fail(f"a name a setting reads was refused: {e}")
