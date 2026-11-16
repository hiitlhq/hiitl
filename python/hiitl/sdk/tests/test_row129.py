"""Row 129 (HTL-20): a documented setting has an effect.

config.py's precedence, "1. Constructor arguments (highest priority) 2. Environment variables (HIITL_* prefix)
3. Default values", is what `HIITL()` does: a value argument left unset is read from its `HIITL_*` variable. The
readers are `ClientSettings` and `SyncConfig`, so the cells compute the reader set from them and hold the docstring,
the TypeScript SDK's `ENV_SETTINGS` and the readers to one set. Principle 10: no language gets a setting the other
cannot read.
"""

from __future__ import annotations

import json
import logging
import os
import re
from enum import Enum
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import hiitl.sdk.config as config_module
from hiitl import HIITL
from hiitl.sdk.config import ClientSettings, SyncConfig
from hiitl.sdk.exceptions import ConfigurationError

TS_CONFIG = Path(__file__).resolve().parents[4] / "typescript" / "packages" / "sdk" / "src" / "config.ts"

BLOCK_REFUNDS = {"name": "p", "version": "v1.0.0", "description": "The p set", "scope": {"org_id": "org_x0000000000000000", "environment": "dev"}, "rules": [
    {"name": "no_refunds", "description": "d", "priority": 10, "decision": "BLOCK", "reason_code": "NO_REFUNDS",
     "conditions": {"field": "action", "operator": "equals", "value": "refund"}}]}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """Each cell sets the variables it reads; none comes from the shell that runs the suite."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _env_name(model, name: str) -> str:
    alias = model.model_fields[name].validation_alias
    return alias if isinstance(alias, str) else model.model_config["env_prefix"] + name.upper()


def _readers() -> dict[str, tuple[type, str]]:
    """Every variable the settings models read, and the (model, field) it sets."""
    out: dict[str, tuple[type, str]] = {}
    for model in (ClientSettings, SyncConfig):
        for name in model.model_fields:
            out.setdefault(_env_name(model, name), (model, name))
    return out


def _documented() -> set[str]:
    return set(re.findall(r"^\s+(HIITL_[A-Z0-9_]+):", config_module.__doc__, re.M))


def _ts_block(start: str) -> str:
    text = TS_CONFIG.read_text(encoding="utf-8")
    block = text[text.index(start):]
    return block[:block.index("\n}") if start.startswith("export interface") else block.index("];")]


def _ts_settings() -> dict[str, str]:
    """TypeScript's ENV_SETTINGS: variable → the option it sets (`sync_config.<name>` for a sync setting)."""
    return dict(re.findall(r"\['(HIITL_[A-Z0-9_]+)',\s*'([\w.]+)'", _ts_block("export const ENV_SETTINGS")))


def _candidate(model, name: str):
    """A value the field does not default to, inside its declared bounds; the text it is set from."""
    field = model.model_fields[name]
    default = field.default
    bounds = {type(m).__name__: m for m in field.metadata}
    if field.default_factory is list:
        # a list is set from JSON, as pydantic-settings decodes a complex field
        value = ["x"]
        return value, json.dumps(value)
    if isinstance(default, bool):
        value = not default
    elif isinstance(default, Enum):
        value = next(m for m in type(default) if m != default)
    elif isinstance(default, (int, float)) or default is None and field.annotation in (int | None, float | None):
        base = default if default is not None else 1
        value = base + 1
        if "Le" in bounds and value > bounds["Le"].le:
            value = base - 1
    else:
        value = f"{default}/x" if default else "x"
    text = value.value if isinstance(value, Enum) else str(value).lower() if isinstance(value, bool) else str(value)
    return value, text


def test_every_setting_the_docstring_names_is_read_and_every_reader_is_named():
    assert _documented() == set(_readers()), "config.py's docstring and the settings models name one set"


@pytest.mark.parametrize("variable", sorted(_readers()))
def test_each_variable_is_read_by_its_setting(variable, monkeypatch):
    model, name = _readers()[variable]
    value, text = _candidate(model, name)
    monkeypatch.setenv(variable, text)
    try:
        settings = model()
    except ValidationError as e:
        # the variable was read: the field's own check refused the value it carried
        assert any(name in map(str, err["loc"]) or variable in map(str, err["loc"]) for err in e.errors()), e
        return
    assert getattr(settings, name) == value, f"{variable} sets {model.__name__}.{name}"


@pytest.mark.parametrize("variable", sorted(_readers()))
def test_typescript_reads_each_python_setting_into_the_same_option(variable):
    ts = _ts_settings()
    _, name = _readers()[variable]
    # each setting is read in both SDKs: the telemetry family's too, which TypeScript reads and checks (row 208)
    assert variable in ts, f"the TypeScript client's ENV_SETTINGS does not read {variable} (`{name}`)"
    assert ts[variable].split(".")[-1] == name, f"{variable} sets `{name}` in Python and `{ts[variable]}` in TS"


def test_typescript_reads_no_setting_python_does_not():
    assert set(_ts_settings()) <= set(_readers())


def _policy(tmp_path) -> str:
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(BLOCK_REFUNDS))
    return str(p)


def _hybrid_engine():
    engine = MagicMock()
    engine.initial_sync.return_value = True
    return patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine)


def test_hiitl_environment_is_read(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_ENVIRONMENT", "stage")
    assert HIITL(audit_db_path=str(tmp_path / "a.db")).config.environment == "stage"


def test_hiitl_policy_path_and_mode_are_read(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_POLICY_PATH", _policy(tmp_path))
    monkeypatch.setenv("HIITL_MODE", "RESPECT_POLICY")
    d = HIITL(audit_db_path=str(tmp_path / "a.db")).evaluate("refund")
    assert d.blocked and d.reason_codes == ["NO_REFUNDS"], "the variable's policy file binds"


def test_an_argument_outranks_its_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_ENVIRONMENT", "stage")
    monkeypatch.setenv("HIITL_MODE", "RESPECT_POLICY")
    monkeypatch.setenv("HIITL_POLICY_PATH", _policy(tmp_path))
    h = HIITL(environment="dev", mode="OBSERVE_ALL", audit_db_path=str(tmp_path / "a.db"))
    assert h.config.environment == "dev"
    assert h.evaluate("refund").observed, "the mode argument wins over HIITL_MODE"


def test_hiitl_api_key_starts_hybrid_mode_with_the_variables_sync_target(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_API_KEY", "sk_from_the_environment")
    monkeypatch.setenv("HIITL_SERVER_URL", "https://sync.example")
    monkeypatch.setenv("HIITL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HIITL_SYNC_AUDIT_INTERVAL", "45")
    with _hybrid_engine() as engine_class:
        h = HIITL(audit_db_path=str(tmp_path / "a.db"))
    assert h.mode == "hybrid"
    kwargs = engine_class.call_args.kwargs
    assert kwargs["api_key"] == "sk_from_the_environment"
    assert kwargs["sync_config"].server_url == "https://sync.example"
    assert kwargs["sync_config"].cache_dir == str(tmp_path / "cache")
    assert kwargs["sync_config"].audit_sync_interval == 45


def test_hiitl_sync_false_keeps_a_keyed_client_local(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_API_KEY", "sk_from_the_environment")
    monkeypatch.setenv("HIITL_SYNC", "false")
    with _hybrid_engine() as engine_class:
        h = HIITL(audit_db_path=str(tmp_path / "a.db"))
    assert h.mode == "local" and not engine_class.called


def test_hiitl_evaluation_remote_with_a_server_url_is_hosted(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_API_KEY", "sk_from_the_environment")
    monkeypatch.setenv("HIITL_EVALUATION", "remote")
    with pytest.raises(ConfigurationError, match="server_url is required"):
        HIITL()
    monkeypatch.setenv("HIITL_SERVER_URL", "https://ecp.example")
    monkeypatch.setenv("HIITL_SIGNATURE_KEY", "s" * 32)  # hosted signs what it sends (row 134)
    h = HIITL()
    assert h.mode == "hosted" and h.config.server_url == "https://ecp.example"


def test_server_url_and_cache_dir_apply_over_a_given_sync_config(tmp_path):
    given = SyncConfig(server_url="https://given.example", cache_dir=str(tmp_path / "given"), audit_sync_interval=40)
    with _hybrid_engine() as engine_class:
        HIITL(api_key="sk_test_1234567890abcdef", sync_config=given, server_url="https://argument.example",
              cache_dir=str(tmp_path / "argument"), audit_db_path=str(tmp_path / "a.db"))
    used = engine_class.call_args.kwargs["sync_config"]
    assert (used.server_url, used.cache_dir) == ("https://argument.example", str(tmp_path / "argument"))
    assert used.audit_sync_interval == 40, "the rest of the given sync_config stands"


class _Backlog:
    def __init__(self):
        self.count, self.size = 0, 0

    def unsynced_backlog(self):
        return self.count, self.size


def test_buffer_full_is_emitted_once_per_crossing_by_records_or_bytes(tmp_path, caplog):
    from hiitl.sdk.sync_cache import SyncCache
    from hiitl.sdk.sync_engine import SyncEngine

    cfg = SyncConfig(cache_dir=str(tmp_path), max_buffer_records=100, max_buffer_size_bytes=1048576)
    backlog = _Backlog()
    org = "org_x0000000000000000"
    engine = SyncEngine(sync_config=cfg, sync_cache=SyncCache(cache_dir=str(tmp_path), org_id=org, environment="dev"),
                        audit_logger=backlog, api_key="sk_test_1234567890abcdef", org_id=org, environment="dev")

    def full_events():
        return [r for r in caplog.records if r.levelno == logging.WARNING and r.getMessage().startswith("BUFFER_FULL")]

    caplog.set_level(logging.WARNING, logger="hiitl.sdk.sync_engine")
    backlog.count = 99
    engine._check_audit_buffer()
    assert full_events() == [], "below the record limit"
    backlog.count = 100
    engine._check_audit_buffer()
    engine._check_audit_buffer()
    assert len(full_events()) == 1, "the crossing is logged once while the backlog stays full"
    backlog.count = 10
    engine._check_audit_buffer()
    backlog.size = 1048576
    engine._check_audit_buffer()
    assert len(full_events()) == 2, "re-armed below the limit; the byte limit is a crossing too"
    assert "No record is dropped" in full_events()[-1].getMessage()
