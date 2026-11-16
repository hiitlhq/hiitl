"""Row 173 (HTL-22): `HIITL_TIMEOUT` in seconds, in both SDKs.

Trevor's ruling on HTL-20: "`HIITL_TIMEOUT` in seconds in both SDKs, by Principle 10 and sync_engine §9"; §9 states its
intervals and timeouts in seconds. Design: the HTL-22 test design, row 173, behaviors 1 and 2. The TypeScript side is
typescript/packages/sdk/tests/unit/row173.test.ts, with the same value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hiitl import HIITL

PAGE = Path(__file__).resolve().parents[4] / "docs-site" / "sdk" / "python-configuration.mdx"
SECONDS = "2.5"  # the value row173.test.ts sets


def _page_default() -> float:
    """The configuration page's `timeout` default."""
    (default,) = re.findall(r'<ParamField path="timeout" type="\w+" default="([^"]+)">', PAGE.read_text(encoding="utf-8"))
    return float(default)


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """Each cell sets the variables it reads; none comes from the shell that runs the suite."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hosted_timeout(tmp_path):
    """A hosted client's HTTP timeout, as its HTTP client holds it."""
    client = HIITL(api_key="sk_test_row173", server_url="https://ecp.example.com", evaluation="remote",
                   signature_key="test-signing-secret-0123456789abcdef", audit_db_path=str(tmp_path / "audit.db"))
    try:
        timeout = client._hosted_client._client.timeout
    finally:
        client.close()
    return (timeout.connect, timeout.read, timeout.write, timeout.pool)


def test_the_variable_is_seconds(tmp_path, monkeypatch):
    """Behavior 1: `HIITL_TIMEOUT=2.5` is a timeout of 2.5 seconds on every phase of the request."""
    monkeypatch.setenv("HIITL_TIMEOUT", SECONDS)

    assert _hosted_timeout(tmp_path) == (float(SECONDS),) * 4


def test_the_default_is_the_pages(tmp_path):
    """Behavior 2: with no setting, the timeout is the configuration page's default."""
    assert _hosted_timeout(tmp_path) == (_page_default(),) * 4
