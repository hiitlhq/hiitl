"""Row 142 (HTL-20): no raw value leaves in telemetry at any level; the default sends counts only.

Ruled 2026-11-04 by telemetry_schema.md §4 ("Full parameter payloads — Never leave the
SDK"; "Names, emails, etc. are never included") and §6 ("Parameter tracking is opt-in
per tool via configuration to avoid leaking unexpected field names"). These cells hold
the serialised record, the collector's memory, and the client's wiring of the opt-in.
Row 146's telemetry members (the record carries what the schema declares, and only
that) are here too.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hiitl.sdk.config import SyncConfig
from hiitl.sdk.telemetry import TelemetryCollector

SPEC = Path(__file__).resolve().parents[4] / "docs" / "specs" / "telemetry_schema.md"
LEVELS = ("full", "standard", "minimal")

# What a payments agent and a notifications agent send: an amount, a card holder's
# email, a currency, a flag. Distinct amounts so a mean is never one of them.
PAYMENTS = [
    {"amount": 42.5, "currency": "usd", "customer_email": "alice@example.com", "refund": False},
    {"amount": 17.0, "currency": "eur", "customer_email": "bob@example.com", "refund": True},
    {"amount": 99.25, "currency": "usd", "customer_email": "carol@example.com", "refund": False},
    {"amount": 310.0, "currency": "gbp", "customer_email": "alice@example.com", "refund": False},
]
EMAILS = [{"to": f"user{i}@example.com", "subject": f"Invoice {i}", "body": "Your invoice is attached."} for i in range(4)]


def _envelope(action, parameters, user_id="user_alice@example.com"):
    return SimpleNamespace(action=action, operation="execute", agent_id="billing-agent",
                           user_id=user_id, parameters=parameters, target={"account_id": "acct_9f3k2"})


def _decision():
    return SimpleNamespace(decision="ALLOW", reason_codes=["default_allow"],
                           timing=SimpleNamespace(evaluation_ms=0.4), error=None)


def _collect(level, parameter_tools=("process_payment",)):
    collector = TelemetryCollector(org_id="org_test1234567890ab", environment="dev", level=level,
                                   parameter_tools=parameter_tools)
    for params in PAYMENTS:
        collector.record(_envelope("process_payment", params), _decision())
    for params in EMAILS:
        collector.record(_envelope("send_email", params), _decision())
    return collector


def _raw_values():
    return [v for p in PAYMENTS + EMAILS for v in p.values()]


def _leaves(obj):
    """Every scalar in a JSON-shaped value."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            yield from _leaves(v)
    else:
        yield obj


def _summary(record, action):
    return next(ts for ts in record["tool_summaries"] if ts["action"] == action)


def _schema():
    text = SPEC.read_text(encoding="utf-8")
    return json.loads(re.search(r"### JSON Schema\n\n```json\n(.*?)\n```", text, re.S).group(1))


@pytest.mark.parametrize("level", LEVELS)
def test_no_raw_parameter_value_leaves_at_any_level(level):
    record = _collect(level).flush()
    text = json.dumps(record)
    leaves = [v for v in _leaves(record) if not isinstance(v, bool)]
    for raw in _raw_values():
        if isinstance(raw, bool):
            continue                       # True/False are not distinguishable from flags; the str() form is checked below
        if isinstance(raw, str):
            assert raw not in text, f"{raw!r} left the SDK at {level}"
        else:
            assert raw not in leaves, f"the value {raw} left the SDK at {level}"
    assert "True" not in text and "False" not in text      # a boolean parameter's value, as the 1.0 collector sent it


def test_an_untracked_tools_parameters_are_absent():
    record = _collect("full").flush()
    email = _summary(record, "send_email")
    assert "parameter_stats" not in email
    text = json.dumps(record)
    for name in ("to", "subject", "body"):
        assert f'"{name}"' not in text, f"the parameter name {name!r} of an untracked tool left the SDK"


def test_no_tool_is_tracked_by_default():
    collector = TelemetryCollector(org_id="org_test1234567890ab", environment="dev")
    for params in PAYMENTS:
        collector.record(_envelope("process_payment", params), _decision())
    record = collector.flush()
    assert "parameter_stats" not in _summary(record, "process_payment")
    assert "amount" not in json.dumps(record)
    assert SyncConfig().telemetry_parameter_tools == []


def test_the_default_sends_counts_only():
    """At `standard` a tracked numeric parameter is its count; a categorical one its distinct count."""
    stats = {p["parameter_path"]: p for p in _summary(_collect("standard").flush(), "process_payment")["parameter_stats"]}
    assert stats["amount"]["numeric_stats"] == {"count": 4}
    assert stats["currency"]["categorical_stats"] == {"distinct_count": 3}
    assert stats["customer_email"]["categorical_stats"] == {"distinct_count": 3}
    assert stats["refund"]["categorical_stats"] == {"distinct_count": 2}


def test_full_adds_a_mean_never_a_mean_of_one_value():
    stats = {p["parameter_path"]: p for p in _summary(_collect("full").flush(), "process_payment")["parameter_stats"]}
    assert stats["amount"]["numeric_stats"] == {"count": 4, "mean": round((42.5 + 17.0 + 99.25 + 310.0) / 4, 3)}

    collector = TelemetryCollector(org_id="org_test1234567890ab", environment="dev", level="full",
                                   parameter_tools=["process_payment"])
    for _ in range(4):
        collector.record(_envelope("process_payment", {"amount": 500.0}), _decision())
    same = {p["parameter_path"]: p for p in _summary(collector.flush(), "process_payment")["parameter_stats"]}
    assert same["amount"]["numeric_stats"] == {"count": 4}, "the mean of one value is that value"


@pytest.mark.parametrize("level", LEVELS)
def test_the_collector_holds_no_raw_value(level):
    """Walk the collector's window state: no parameter value, user id or target is held."""
    collector = _collect(level)

    def state(obj):
        for slot in getattr(type(obj), "__slots__", ()):
            yield getattr(obj, slot)

    held = []
    for ts in collector._tool_stats.values():
        for v in state(ts):
            held.append(v)
            if isinstance(v, dict):
                held.extend(list(state(s)) for s in v.values())
    for ag in collector._agent_stats.values():
        held.extend(state(ag))
    leaves = [v for v in _leaves(held) if not isinstance(v, bool)]
    for raw in _raw_values() + ["user_alice@example.com", "acct_9f3k2"]:
        if isinstance(raw, bool):
            continue
        assert raw not in leaves, f"the collector holds {raw!r} at {level}"


def test_agent_metrics_at_minimal():
    """§3.2: an agent's counts are sent at every level; distinct_users at standard and above."""
    agents = _collect("minimal").flush().get("agent_summaries", [])
    assert len(agents) == 1, f"the agent's counts are not sent at minimal: {agents}"
    assert agents[0] == {"agent_id": "billing-agent", "action_count": 8,
                     "tools_used": ["process_payment", "send_email"], "decision_counts": {"ALLOW": 8}}
    (standard,) = _collect("standard").flush()["agent_summaries"]
    assert standard["distinct_users"] == 1


def test_the_client_tracks_only_the_tools_its_config_names(tmp_path):
    """Through evaluate(): the hybrid client hands SyncConfig.telemetry_parameter_tools to its collector."""
    from hiitl import HIITL

    engine = MagicMock()
    engine.initial_sync.return_value = False
    with patch("hiitl.sdk.sync_engine.SyncEngine", return_value=engine):
        hiitl = HIITL(api_key="sk_test_abc", audit_db_path=str(tmp_path / "audit.db"),
                      sync_config=SyncConfig(cache_dir=str(tmp_path / "cache"),
                                             telemetry_parameter_tools=["process_payment"]))
    for params in PAYMENTS:
        hiitl.evaluate("process_payment", parameters=params)
    for params in EMAILS:
        hiitl.evaluate("send_email", parameters=params)
    record = hiitl._telemetry_collector.flush()
    assert {p["parameter_path"] for p in _summary(record, "process_payment").get("parameter_stats", [])} == {
        "amount", "currency", "customer_email", "refund"}
    assert "parameter_stats" not in _summary(record, "send_email")
    assert "alice@example.com" not in json.dumps(record)


# ── Row 146, the telemetry members: what the schema declares is what is produced ──

@pytest.mark.parametrize("level", LEVELS)
def test_the_record_carries_only_what_the_schema_declares(level):
    schema = _schema()
    defs = schema["$defs"]
    record = _collect(level).flush()
    assert record["telemetry_version"] == schema["properties"]["telemetry_version"]["const"]
    assert set(record) <= set(schema["properties"])
    for ts in record["tool_summaries"]:
        assert set(ts) <= set(defs["tool_summary"]["properties"])
        for ps in ts.get("parameter_stats", []):
            kind = f'{ps["stat_type"]}_stats'
            assert set(ps[kind]) <= set(defs["parameter_stat"]["properties"][kind]["properties"])
    for ag in record.get("agent_summaries", []):
        assert set(ag) <= set(defs["agent_summary"]["properties"])


def test_every_declared_system_metric_is_produced():
    """A field declared and never produced leaves the schema (row 146): both directions, system_metrics."""
    declared = _schema()["$defs"]["system_metrics"]
    metrics = TelemetryCollector(org_id="org_test1234567890ab", environment="dev").flush()["system_metrics"]
    assert set(metrics) == set(declared["properties"])
    assert set(metrics["error_counts"]) == set(declared["properties"]["error_counts"]["properties"])
    assert "sdk_instance_id" not in _schema()["properties"]
