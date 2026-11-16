"""Row 208 (HTL-23): one telemetry family.

Ruled 2026-11-06: "One telemetry family: the spec names the interval, buffer size, sample rate and parameter tools as
`HIITL_TELEMETRY_*` beside `HIITL_TELEMETRY_LEVEL` (spec before cells), both SDKs read them, and the stale
`HIITL_SYNC_TELEMETRY_*` names are refused under row 207. By row 172's ruling and B.foundation.6." Each row of
telemetry_schema.md §5's family table is read at its producer: its variable, set, reaches the setting its option names,
and a value outside its range is refused naming the range. No name, bound or member is listed here. The stale names are
row 207's cells. Design: the HTL-23 test design, row 208. Mirrors
typescript/packages/sdk/tests/unit/row208.test.ts.
"""

from __future__ import annotations

import json
import os
import re
from unittest.mock import MagicMock, patch

import pytest

from hiitl import HIITL
from hiitl.sdk.exceptions import ConfigurationError
from hiitl.sdk.tests.settings_tables import TELEMETRY, code

BOUNDS = re.compile(r"(-?\d+(?:\.\d+)?)–(-?\d+(?:\.\d+)?)")


def _kind(row: list[str]) -> tuple[list, list, list[str]]:
    """(values inside the range, values outside it, the words a refusal names), read from the row's cells: a range of
    members, a range of numbers, or the variable's own form (`(a JSON list)`)."""
    default, rng = code(row[3]), row[4]
    members = re.findall(r"`([^`]+)`", rng)
    if members:
        return [m for m in members if m != default][:1], ["r208-outside"], members
    bounds = BOUNDS.match(rng)
    if bounds:
        low, high = bounds.groups()
        inside = [b for b in (high, low) if float(b) != float(default)][:1]
        outside = [str(float(low) - 1).removesuffix(".0"), str(float(high) + 1).removesuffix(".0")]
        return inside, outside, [low, high]
    form = re.search(r"\(an? ([^)]+)\)", row[2]).group(1)
    assert form == "JSON list", f"{code(row[2])}: a form the cell does not read: {form}"
    return ['["r208_action"]'], ['r208_action'], [form]


ROWS = [(code(row[1]), code(row[2]), *_kind(row)) for row in TELEMETRY]
IDS = [variable for _, variable, *_ in ROWS]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hybrid(tmp_path):
    """A hybrid client whose sync engine is a stand-in: what the client handed the engine."""
    engine = MagicMock()
    engine.initial_sync.return_value = False
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine) as engine_class:
        client = HIITL(api_key="sk_test_row208", audit_db_path=str(tmp_path / "audit.db"),
                       cache_dir=str(tmp_path / "cache"))
    client.close()
    return engine_class.call_args.kwargs


def _held(option: str, handed: dict):
    """The value the client acts on for `option`: the engine's sync settings, or the collector's level."""
    if option.startswith("sync_config."):
        return getattr(handed["sync_config"], option.removeprefix("sync_config."))
    return handed["telemetry_collector"]._level


def _same(held, text: str) -> bool:
    if text.startswith("["):
        return held == json.loads(text)
    try:
        return float(held) == float(text)
    except (TypeError, ValueError):
        return held == text


def test_the_table_is_the_family():
    """Every setting the table names is a `HIITL_TELEMETRY_*` name (the family, one representation per fact)."""
    assert IDS and all(v.startswith("HIITL_TELEMETRY_") for v in IDS), IDS


@pytest.mark.parametrize("option, variable, inside, outside, words", ROWS, ids=IDS)
def test_each_setting_is_read_under_its_spec_name(tmp_path, monkeypatch, option, variable, inside, outside, words):
    """Behavior 1: the variable, set to a value inside its range, reaches the setting its option names."""
    for value in inside:
        monkeypatch.setenv(variable, value)
        try:
            handed = _hybrid(tmp_path)
        except ConfigurationError as e:
            pytest.fail(f"{variable}={value} was refused, not read: {e}")
        held = _held(option, handed)
        assert _same(held, value), f"{variable}={value}: {option} is {held!r}"


@pytest.mark.parametrize("option, variable, inside, outside, words", ROWS, ids=IDS)
def test_a_value_outside_the_range_is_refused_naming_it(tmp_path, monkeypatch, option, variable, inside, outside,
                                                       words):
    """Behavior 1: a value outside the range fails construction, naming the range (§5: "naming the range")."""
    for value in outside:
        monkeypatch.setenv(variable, value)
        with pytest.raises(ConfigurationError) as exc:
            _hybrid(tmp_path)
        message = str(exc.value)
        missing = [w for w in words if not re.search(rf"(?<![\w.]){re.escape(w)}(?![\w.])", message)]
        assert missing == [], f"{variable}={value}: the refusal does not name {missing}: {message}"
