"""Row 130 (HTL-20): the same arguments give the same mode in both SDKs.

docs-site/concepts/deployment-modes.mdx: hosted evaluation "is an explicit opt-in", so an api_key with a server_url is hybrid, and
hosted takes `evaluation="remote"`. Principle 10: no language gets a structural advantage. The TypeScript SDK holds
the same table (typescript/packages/sdk/tests/unit/row130.test.ts).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hiitl import HIITL
from hiitl.sdk.exceptions import ConfigurationError

# every mode takes the signing secret; hosted needs it (row 134)
SIGNING_SECRET = "s" * 32

# the constructor arguments → the mode, or the error a client without what it needs raises
MODES = [
    ({}, "local"),
    ({"api_key": "sk_test_1234567890abcdef"}, "hybrid"),
    ({"api_key": "sk_test_1234567890abcdef", "server_url": "https://ecp.example"}, "hybrid"),
    ({"api_key": "sk_test_1234567890abcdef", "sync": False}, "local"),
    ({"api_key": "sk_test_1234567890abcdef", "server_url": "https://ecp.example", "evaluation": "remote"}, "hosted"),
    ({"server_url": "https://ecp.example", "evaluation": "remote"}, "local"),
    ({"api_key": "sk_test_1234567890abcdef", "evaluation": "remote"}, ConfigurationError),
]


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


@pytest.mark.parametrize("args, mode", MODES, ids=[str(sorted(a)) for a, _ in MODES])
def test_the_mode_table(args, mode, tmp_path):
    engine = MagicMock()
    engine.initial_sync.return_value = True
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine):
        if isinstance(mode, type):
            with pytest.raises(mode):
                HIITL(**args, signature_key=SIGNING_SECRET, audit_db_path=str(tmp_path / "a.db"),
                      cache_dir=str(tmp_path / "c"))
            return
        h = HIITL(**args, signature_key=SIGNING_SECRET, audit_db_path=str(tmp_path / "a.db"),
                  cache_dir=str(tmp_path / "c"))
    assert h.mode == mode


def test_an_unknown_evaluation_is_refused_naming_the_valid_ones(tmp_path):
    with pytest.raises(ConfigurationError, match=r"Must be one of: local, remote\."):
        HIITL(api_key="sk_test_1234567890abcdef", evaluation="remot", audit_db_path=str(tmp_path / "a.db"))


PAGE = Path(__file__).resolve().parents[4] / "docs-site" / "sdk" / "python-configuration.mdx"


def _page_table():
    """The page's "Auto-detection rules" table: each row's arguments and the mode it names."""
    section = PAGE.read_text(encoding="utf-8").split("### Auto-detection rules", 1)[1]
    lines = section.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("|"))
    end = next(i for i in range(start, len(lines)) if not lines[i].startswith("|"))
    out = []
    for row in lines[start + 2:end]:
        api_key, server_url, evaluation, sync, mode = [c.strip() for c in row.strip("|").split("|")]
        args = {}
        if api_key.startswith("present"):
            args["api_key"] = "sk_test_1234567890abcdef"
        if server_url.startswith("present"):
            args["server_url"] = "https://ecp.example"
        if "remote" in evaluation:
            args["evaluation"] = "remote"
        if "False" in sync:
            args["sync"] = False
        named = re.search(r"\*\*(\w+)\*\*", mode)
        out.append((args, named.group(1) if named else ConfigurationError))
    return out


def test_the_configuration_pages_table_is_what_the_client_does(tmp_path):
    table = _page_table()
    assert table
    for args, mode in table:
        test_the_mode_table(args, mode, tmp_path)
    # the page states every row of the client's table
    key = lambda a: tuple(sorted(a.items()))  # noqa: E731
    assert {key(a) for a, _ in table} == {key(a) for a, _ in MODES}
