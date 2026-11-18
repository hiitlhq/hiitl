"""Row 209 (HTL-23): one timeout range, and the hosted client's settings table swept.

Ruled 2026-11-06: "One timeout range in both SDKs, 0.1 to 30 seconds, declared in the spec; Python takes it. The bound
is Trevor's declaration (the TypeScript SDK's declared range is adopted, not chosen anew)." The row found the timeout;
the class is every row of decision_response.md's hosted settings table (item 13), read at its producer: each bound or
member, given as an option or by its variable, constructs and is held; a value past a bound, or not a member, fails
construction naming the range. No name, bound or member is listed here. Design: the HTL-23 test design,
row 209. Mirrors typescript/packages/sdk/tests/unit/row209.test.ts.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal

import pytest

from hiitl import HIITL
from hiitl.sdk.exceptions import ConfigurationError
from hiitl.sdk.tests.settings_tables import HOSTED, code

BOUNDS = re.compile(r"(-?\d+(?:\.\d+)?)–(-?\d+(?:\.\d+)?)")
ORG_ID = "org_r209settings000000"


def _kind(row: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(the bounds or members, values past a bound or not a member, the words a refusal names), from the row's
    range cell."""
    rng = row[4]
    members = re.findall(r"`([^`]+)`", rng)
    if members:
        return members, ["r209-outside"], members
    low, high = BOUNDS.match(rng).groups()
    step = Decimal(1).scaleb(Decimal(low).as_tuple().exponent)  # one unit of the bound's last digit
    return [low, high], [str(Decimal(low) - step), str(Decimal(high) + step)], [low, high]


ROWS = [(code(row[1]), code(row[2]), *_kind(row)) for row in HOSTED]
IDS = [option for option, *_ in ROWS]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """No ambient setting reaches a cell."""
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _hosted(tmp_path, **given) -> HIITL:
    return HIITL(environment="dev", agent_id="r209-agent", org_id=ORG_ID, api_key="sk_test_row209",
                 server_url="https://ecp.r209.example.com", evaluation="remote", signature_key="r209-signing-secret",
                 audit_db_path=str(tmp_path / "audit.db"), **given)


def _typed(text: str):
    """A value as an option takes it: a number as a number, a member as its text."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _given(option, variable, value, how, monkeypatch) -> dict:
    if how == "option":
        return {option: _typed(value)}
    monkeypatch.setenv(variable, value)
    return {}


@pytest.mark.parametrize("how", ["option", "variable"])
@pytest.mark.parametrize("option, variable, inside, outside, words", ROWS, ids=IDS)
def test_each_bound_or_member_is_taken(tmp_path, monkeypatch, option, variable, inside, outside, words, how):
    """Behavior 2: each bound (or member), given either way, constructs and is the value the client holds."""
    for value in inside:
        h = _hosted(tmp_path, **_given(option, variable, value, how, monkeypatch))
        held = getattr(h.config, option)
        h.close()
        assert held == _typed(value), f"{option} given {value} by {how}: held {held!r}"


@pytest.mark.parametrize("how", ["option", "variable"])
@pytest.mark.parametrize("option, variable, inside, outside, words", ROWS, ids=IDS)
def test_a_value_outside_the_range_is_refused_naming_it(tmp_path, monkeypatch, option, variable, inside, outside,
                                                       words, how):
    """Behavior 1: a value past a bound, or not a member, given either way, fails construction naming the range."""
    for value in outside:
        with pytest.raises(ConfigurationError) as exc:
            _hosted(tmp_path, **_given(option, variable, value, how, monkeypatch)).close()
        message = str(exc.value)
        missing = [w for w in words if not re.search(rf"(?<![\w.]){re.escape(w)}(?![\w.])", message)]
        assert missing == [], f"{option} given {value} by {how}: the refusal does not name {missing}: {message}"
