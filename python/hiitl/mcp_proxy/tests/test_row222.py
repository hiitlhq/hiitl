"""Row 222 (HTL-24): the gateway refuses its own family's unread names.

Ruled 2026-11-07: "each component refuses the unread names of its own families (the gateway `HIITL_MCP_*`, the
scanner `HIITL_SCAN_*`), by Principle 11 and ontology §4 commitment 3." The gateway's settings model reads its two
variables, each outranked by its argument; any other `HIITL_MCP_*` name, set, stops the CLI naming the names the
model reads, and so does a log level Python's `logging` does not name (the README, "CLI"; sync_engine.md §9). The
names are read from the settings model; no name is listed here but the two the ruling's README names. Design: the
HTL-24 test design, row 222, behavior 2.
"""

from __future__ import annotations

import logging
import os

import pytest

from hiitl.mcp_proxy import cli
from hiitl.mcp_proxy.config import GatewaySettings
from hiitl.settings import read_variables

FAMILY = GatewaySettings.model_config["env_prefix"]
READ = read_variables(GatewaySettings)
CONFIG = """
servers:
  email:
    command: npx
    args: [email-mcp-server]
""".strip()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def started(monkeypatch):
    """What the CLI started with: the level it configured and the config it ran, in place of the proxy."""
    seen: dict = {}
    monkeypatch.setattr(cli, "_configure_logging", lambda level: seen.setdefault("level", level))

    async def _run(config):
        seen["config"] = config
    monkeypatch.setattr(cli, "run_proxy", _run)
    return seen


def _file(tmp_path, name: str):
    path = tmp_path / name
    path.write_text(CONFIG)
    return path


def test_the_model_reads_the_readmes_two_names():
    assert READ == {f"{FAMILY}CONFIG", f"{FAMILY}LOG_LEVEL"}


def test_an_unread_name_stops_the_cli_naming_the_names_read(tmp_path, monkeypatch, caplog, started):
    monkeypatch.setenv(f"{FAMILY}CONFIG", str(_file(tmp_path, "hiitl-mcp.yaml")))
    monkeypatch.setenv(f"{FAMILY}R222_UNREAD", "1")
    assert cli.main([]) == 2
    assert "config" not in started, "the proxy did not start"
    assert f"{FAMILY}R222_UNREAD" in caplog.text and all(name in caplog.text for name in READ), caplog.text


def test_the_variables_are_read_by_the_model(tmp_path, monkeypatch, started):
    monkeypatch.setenv(f"{FAMILY}CONFIG", str(_file(tmp_path, "from-the-variable.yaml")))
    monkeypatch.setenv(f"{FAMILY}LOG_LEVEL", "warning")
    assert cli.main([]) == 0
    assert started["level"].upper() == "WARNING" and list(started["config"].servers) == ["email"]


def test_the_argument_outranks_the_variable(tmp_path, monkeypatch, started):
    monkeypatch.setenv(f"{FAMILY}CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv(f"{FAMILY}LOG_LEVEL", "WARNING")
    assert cli.main(["--config", str(_file(tmp_path, "from-the-argument.yaml")), "--log-level", "DEBUG"]) == 0
    assert started["level"].upper() == "DEBUG" and list(started["config"].servers) == ["email"]


@pytest.mark.parametrize("where", ["variable", "argument"])
def test_a_level_logging_does_not_name_is_refused_naming_it(tmp_path, monkeypatch, caplog, started, where):
    monkeypatch.setenv(f"{FAMILY}CONFIG", str(_file(tmp_path, "hiitl-mcp.yaml")))
    argv = []
    if where == "variable":
        monkeypatch.setenv(f"{FAMILY}LOG_LEVEL", "LOUD")
    else:
        argv = ["--log-level", "LOUD"]
    assert cli.main(argv) == 2
    assert "config" not in started
    assert "LOUD" in caplog.text and all(level in caplog.text for level in ("DEBUG", "INFO", "WARNING", "ERROR")), \
        caplog.text


def test_the_default_level_is_info(tmp_path, monkeypatch, started):
    monkeypatch.setenv(f"{FAMILY}CONFIG", str(_file(tmp_path, "hiitl-mcp.yaml")))
    assert cli.main([]) == 0
    assert logging.getLevelName(started["level"].upper()) == logging.INFO
