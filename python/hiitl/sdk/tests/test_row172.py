"""Row 172 (HTL-22): one telemetry setting, the spec's.

Trevor's ruling on HTL-20: "one telemetry setting, `HIITL_TELEMETRY_LEVEL` with `off`, top-level; the `HIITL_SYNC_` name
dropped". telemetry_schema.md §5 Configuration is read at its producer, so the option, its variable, its values and its
default are the spec's table. Design: the HTL-22 test design, row 172, behaviors 1-4. What a level sends to the service
is the service-side row 172 cell.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from hiitl import HIITL
from hiitl.sdk.config import ClientSettings, SyncConfig
from hiitl.settings import variable
from hiitl.sdk.exceptions import ConfigurationError

SPEC = Path(__file__).resolve().parents[4] / "docs" / "specs" / "telemetry_schema.md"


def _configuration() -> dict[str, str]:
    """§5's Configuration table: each method and its setting."""
    text = SPEC.read_text(encoding="utf-8")
    table = text[text.index("### Configuration"):].split("\n\n")[1]
    rows = ([cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]] for line in table.splitlines()[2:])
    return {method: setting for method, setting in rows}


CONFIGURATION = _configuration()
OPTION, VALUES = re.fullmatch(r"`(\w+): (.+)`", CONFIGURATION["Constructor option"]).groups()
LEVELS = re.findall(r'"(\w+)"', VALUES)
VARIABLE = CONFIGURATION["Environment variable"].strip("`")
(DEFAULT,) = re.findall(r'"(\w+)"', CONFIGURATION["Default"])
OFF = "off"  # §5: "To disable telemetry entirely, set `telemetry_level` to `"off"`"


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """Each cell sets the variables it reads; none comes from the shell that runs the suite."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hybrid(tmp_path, **kwargs):
    """A hybrid client whose sync engine is a stand-in: the client, and what it handed the engine."""
    engine = MagicMock()
    engine.initial_sync.return_value = False
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine) as engine_class:
        client = HIITL(api_key="sk_test_row172", audit_db_path=str(tmp_path / "audit.db"),
                       sync_config=SyncConfig(cache_dir=str(tmp_path / "cache")), **kwargs)
    return client, engine_class.call_args.kwargs


def _at(level, given, monkeypatch) -> dict:
    """The level as an argument, or as the variable with no argument."""
    if given == "argument":
        return {OPTION: level}
    monkeypatch.setenv(VARIABLE, level)
    return {}


def test_the_setting_is_the_specs(tmp_path, monkeypatch):
    """Behavior 1: the reader's variable, default and values are §5's; another value is refused, naming each."""
    assert OFF in LEVELS
    assert variable(ClientSettings, OPTION) == VARIABLE, "the variable the setting is read from"
    assert ClientSettings.model_fields[OPTION].default == DEFAULT
    for level in LEVELS:
        assert getattr(ClientSettings(**{OPTION: level}), OPTION) == level

    for given in ("argument", "variable"):
        refused = None
        try:
            HIITL(audit_db_path=str(tmp_path / "audit.db"), **_at("verbose", given, monkeypatch)).close()
        except ConfigurationError as e:
            refused = e
        assert refused is not None, f"'verbose' by {given} was taken"
        assert all(f"'{level}'" in str(refused) for level in LEVELS), str(refused)


@pytest.mark.parametrize("given", ["argument", "variable"])
def test_off_collects_nothing(tmp_path, monkeypatch, given):
    """Behavior 2: at `off` the hybrid client holds no collector and hands its sync engine none."""
    client, engine = _hybrid(tmp_path, **_at(OFF, given, monkeypatch))

    assert client._telemetry_collector is None
    assert engine.get("telemetry_collector") is None


@pytest.mark.parametrize("given", ["argument", "variable"])
@pytest.mark.parametrize("level", [level for level in LEVELS if level != OFF])
def test_a_level_reaches_the_collector(tmp_path, monkeypatch, given, level):
    """Behavior 3: each other level is the collector's, and the engine sends that collector's records."""
    client, engine = _hybrid(tmp_path, **_at(level, given, monkeypatch))

    collector = engine.get("telemetry_collector")
    assert collector is not None and collector is client._telemetry_collector
    assert collector.status()["level"] == level


def test_the_argument_outranks_the_variable(tmp_path, monkeypatch):
    """Behavior 3: config.py's precedence, "1. Constructor arguments (highest priority) 2. Environment variables"."""
    monkeypatch.setenv(VARIABLE, OFF)
    _, engine = _hybrid(tmp_path / "a", **{OPTION: DEFAULT})
    assert engine.get("telemetry_collector") is not None

    monkeypatch.setenv(VARIABLE, DEFAULT)
    _, engine = _hybrid(tmp_path / "b", **{OPTION: OFF})
    assert engine.get("telemetry_collector") is None


def test_the_sync_config_has_no_level():
    """Behavior 4: the sync engine's settings carry no level; one given there is refused, naming it."""
    assert OPTION not in SyncConfig.model_fields
    refused = None
    try:
        SyncConfig(**{OPTION: OFF})
    except ValidationError as e:
        refused = e
    assert refused is not None and OPTION in str(refused), f"SyncConfig took {OPTION}"
