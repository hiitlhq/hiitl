"""Row 240 (HTL-29): a kill switch binds in its scope under the version the tick names, until a pull lands.

The ruling (HTL-29, 2026-11-09): "in the switch's scope the SDK decides `KILL_SWITCH` under the activation's version the
tick names; outside that scope the cached version binds until the pull lands, the pull retried each tick and the miss
logged at error". Condition 2 (ruled 2026-11-10): the version the tick names is compared by its version string, and a
switch the call cannot read under `fail_closed` blocks it, `MISSING_FIELD` naming the field, under the tick's version.
sync_engine.md 2.4, 6 and 7. Design: the HTL-29 test design, row 240, behaviors 3-10.
Mirrors typescript/packages/sdk/tests/unit/row240.test.ts.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from hiitl import HIITL
from hiitl.core.canonical import canonical_hash
from hiitl.sdk.circuit_breaker import CircuitState
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.exceptions import SyncError
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import KillSwitchResult, PolicyDownloadResult
from hiitl.sdk.sync_engine import SyncEngine

ORG, ENV = "org_test0123456789ab", "dev"
REDACTION = {"manual_redact_fields": []}


def _on(action):
    return {"field": "action", "operator": "equals", "value": action}


def _content(version, *rules, on_missing=None):
    content = {"name": "payments", "version": version, "description": "payments",
               "scope": {"org_id": ORG, "environment": ENV}, "rules": list(rules)}
    if on_missing:
        content["on_missing"] = on_missing
    return content


def _rule(name, decision, stage="active", conditions=None):
    return {"name": name, "description": name, "priority": 100, "conditions": conditions or _on("pay"),
            "decision": decision, "reason_code": name.upper().replace("-", "_"), "lifecycle_stage": stage}


ALLOW_PAY, ALLOW_REFUND = _rule("allow-pay", "ALLOW"), _rule("allow-refund", "ALLOW", conditions=_on("refund"))
RUNNING = _content("v1.0.0", _rule("halt-payments", "KILL_SWITCH", "disabled"), ALLOW_PAY, ALLOW_REFUND)
HALTED = _content("v1.0.1", _rule("halt-payments", "KILL_SWITCH"), ALLOW_PAY, ALLOW_REFUND)
RESUMED = _content("v1.0.2", _rule("halt-payments", "KILL_SWITCH", "disabled"), ALLOW_PAY, ALLOW_REFUND)


def _policy(content, active=True):
    return {"policy_id": f"pol_{content['version']}", "name": content["name"], "version": content["version"],
            "active": active, "content": content, "content_hash": canonical_hash(content)}


def _part(content):
    """The tick's `policy_set` as the service writes it: the set's own fields and its live switches."""
    return {**{k: v for k, v in content.items() if k != "rules"},
            "rules": [r for r in content["rules"] if r["decision"] == "KILL_SWITCH" and r["lifecycle_stage"] == "active"]}


def _tick(content, names=None):
    held = _part(content) if content is not None else None
    named = names if names is not None else [r["name"] for r in (held or {"rules": []})["rules"]]
    return {"kill_switches": [{"rule_name": n, "active": True, "scope": {"environment": ENV}} for n in named],
            "policy_set": held, "server_time": "2026-11-09T00:00:00+00:00"}


def _poll(tick):
    return KillSwitchResult(**tick)


def _download(content):
    return PolicyDownloadResult(policies=[_policy(content)], version=content["version"],
                                etag=f"e-{content['version']}", redaction_policy=REDACTION)


def _engine(tmp_path, cached):
    """A cache holding `cached`, and an engine whose every policy pull fails until a test says otherwise."""
    cache = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    cache.update_policies({"policies": [_policy(cached)], "version": cached["version"], "redaction_policy": REDACTION},
                          etag=f"e-{cached['version']}")
    engine = SyncEngine(sync_config=SyncConfig(server_url="https://api.hiitl.com", cache_dir=str(tmp_path / "cache")),
                        sync_cache=cache, audit_logger=MagicMock(), api_key="sk_test_123", org_id=ORG,
                        environment=ENV)
    engine._client = MagicMock()
    engine._client.download_policies.side_effect = SyncError("policy", "the service is unreachable")
    return engine, cache


def _client(tmp_path, cache, mode="RESPECT_POLICY"):
    local = tmp_path / "local.json"
    local.write_text(json.dumps(_content("v0.0.1", _rule("local-allow", "ALLOW"))))
    hiitl = HIITL(environment=ENV, agent_id="payment-agent", org_id=ORG, policy_path=str(local),
                  audit_db_path=str(tmp_path / "audit.db"), mode=mode)
    hiitl._mode, hiitl._sync_cache = "hybrid", cache
    return hiitl


def _tick_once(engine, tick):
    engine._client.poll_kill_switches.return_value = _poll(tick)
    engine._sync_kill_switches()


def _read(d):
    return d.decision, d.policy_version, [m.rule_name for m in d.matched_rules or []]


# --- Behavior 3: a switch binds before its pull lands ---

def test_a_switch_binds_in_its_scope_under_the_ticks_version_while_its_pull_fails(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))
    engine._client.download_policies.assert_called_once()
    hiitl = _client(tmp_path, cache)

    d = hiitl.evaluate("pay")
    assert _read(d) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"]), "the tick's version decides the switch's scope"
    assert d.reason_codes == ["HALT_PAYMENTS"]
    record = hiitl._audit_logger.query_by_action_id(d.action_id)
    assert (record["decision_type"], record["policy_version"]) == ("KILL_SWITCH", "v1.0.1"), \
        "recorded with the version the tick names"
    assert _read(hiitl.evaluate("refund")) == ("ALLOW", "v1.0.0", ["allow-refund"]), "the cached version outside it"


def test_an_evaluator_that_raises_over_the_ticks_part_is_policy_error_recorded(tmp_path, monkeypatch):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))
    hiitl = _client(tmp_path, cache)

    def raises(envelope, policy, **kwargs):
        raise RuntimeError("the evaluator failed")

    monkeypatch.setattr(hiitl._evaluator, "evaluate", raises)
    d = hiitl.evaluate("pay")
    assert (d.decision, d.allowed, d.reason_codes) == ("POLICY_ERROR", False, ["POLICY_EVALUATION_FAILED"]), \
        "as over the cached version (row 159)"
    assert hiitl._audit_logger.query_by_action_id(d.action_id)["decision_type"] == "POLICY_ERROR"


# --- Behavior 4: observed in observe mode ---

def test_observe_all_observes_the_switch_under_the_ticks_version(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))
    hiitl = _client(tmp_path, cache, mode="OBSERVE_ALL")

    d = hiitl.evaluate("pay")
    assert (d.decision, d.allowed, d.would_be, d.policy_version) == ("OBSERVE", True, "KILL_SWITCH", "v1.0.1")
    assert _read(hiitl.evaluate("refund")) == ("ALLOW", "v1.0.0", ["allow-refund"])


# --- Behavior 5: a switch the call cannot read under fail_closed blocks the call ---

def _halt_large():
    over = {"field": "parameters.amount", "operator": "greater_than", "value": 100}
    return _content("v1.0.1", _rule("halt-large", "KILL_SWITCH", conditions={"all_of": [_on("pay"), over]}),
                    ALLOW_PAY, on_missing="fail_closed")


def test_a_fail_closed_switch_whose_field_the_call_lacks_blocks_the_call_under_the_ticks_version(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(_halt_large()))
    hiitl = _client(tmp_path, cache)

    d = hiitl.evaluate("pay")
    assert _read(d) == ("BLOCK", "v1.0.1", ["halt-large"]), "the switch the call cannot read blocks it"
    assert d.reason_codes == ["MISSING_FIELD"]
    assert d.remediation.details == {"fields": ["parameters.amount"]}, "naming the field"
    record = hiitl._audit_logger.query_by_action_id(d.action_id)
    assert (record["decision_type"], record["policy_version"]) == ("BLOCK", "v1.0.1"), \
        "recorded with the version the tick names"
    assert _read(hiitl.evaluate("pay", parameters={"amount": 500})) == ("KILL_SWITCH", "v1.0.1", ["halt-large"])
    assert _read(hiitl.evaluate("refund")) == ("ALLOW", "v1.0.0", ["allow-refund"]), "read, and the cached version's"


def test_observe_all_reads_a_fail_closed_switch_as_skip_and_leaves_the_call_to_the_cached_version(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(_halt_large()))
    hiitl = _client(tmp_path, cache, mode="OBSERVE_ALL")

    assert _read(hiitl.evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"]), "the switch binds nothing"
    d = hiitl.evaluate("pay", parameters={"amount": 500})
    assert (d.decision, d.would_be, d.policy_version) == ("OBSERVE", "KILL_SWITCH", "v1.0.1")


# --- Behavior 6: a pull that lands ends the tick's part ---

def test_a_304_ends_the_ticks_part(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))
    hiitl = _client(tmp_path, cache)
    assert hiitl.evaluate("pay").decision == "KILL_SWITCH"

    engine._client.download_policies.side_effect = None
    engine._client.download_policies.return_value = None          # 304: the cached version is the server's
    _tick_once(engine, _tick(HALTED))
    assert _read(hiitl.evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"])


def test_a_new_version_that_lands_decides(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))
    hiitl = _client(tmp_path, cache)
    assert hiitl.evaluate("pay").decision == "KILL_SWITCH"

    engine._client.download_policies.side_effect = None
    engine._client.download_policies.return_value = _download(RESUMED)
    _tick_once(engine, _tick(HALTED))
    assert _read(hiitl.evaluate("pay")) == ("ALLOW", "v1.0.2", ["allow-pay"])


# --- Behavior 7: the pull is made every tick, past the breaker, each miss logged at error ---

def test_the_pull_is_made_past_the_breaker_each_miss_recorded_on_it_and_logged_at_error(tmp_path, caplog):
    engine, cache = _engine(tmp_path, RUNNING)
    breaker = engine._breakers["policy"]
    ticks = breaker.failure_threshold + 2      # past the miss that opens it

    with caplog.at_level(logging.ERROR, logger="hiitl.sdk.sync_engine"):
        for n in range(1, ticks + 1):
            _tick_once(engine, _tick(HALTED))
            assert engine._client.download_policies.call_count == n, "every tick pulls, the breaker open or not"
    assert breaker.state == CircuitState.OPEN, "each miss recorded on the breaker"
    misses = [r for r in caplog.records if r.name == "hiitl.sdk.sync_engine" and r.levelno == logging.ERROR]
    assert len(misses) == ticks
    assert all("version v1.0.1 (switches ['halt-payments'])" in r.getMessage()
               and "the cached version v1.0.0 (switches [])" in r.getMessage() for r in misses), \
        [r.getMessage() for r in misses]

    engine._client.download_policies.side_effect = None
    engine._client.download_policies.return_value = _download(HALTED)
    _tick_once(engine, _tick(HALTED))
    assert breaker.state == CircuitState.CLOSED, "the pull that lands closes it"
    assert _read(_client(tmp_path, cache).evaluate("pay")) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"])


# --- Behavior 8: a deactivation holds until its pull lands ---

def test_a_deactivation_binds_by_the_cached_version_until_its_pull_lands(tmp_path):
    engine, cache = _engine(tmp_path, HALTED)
    _tick_once(engine, _tick(RESUMED))
    engine._client.download_policies.assert_called_once()
    assert _read(_client(tmp_path, cache).evaluate("pay")) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"])


# --- Behavior 9: a restart keeps the tick's part ---

def test_a_tick_read_from_disk_at_start_keeps_its_part_until_a_pull_lands(tmp_path):
    engine, _ = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(HALTED))

    restarted = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    assert restarted.load_from_disk()
    hiitl = _client(tmp_path, restarted)
    assert _read(hiitl.evaluate("pay")) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"])

    restarted.update_policies({"policies": [_policy(RUNNING)], "version": "v1.0.0", "redaction_policy": REDACTION},
                              etag="e-v1.0.0")
    assert _read(hiitl.evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"]), "a pull landed"


def _attempt(call):
    try:
        return call()
    except Exception as e:      # the cell names what was raised rather than erroring
        return e


def test_an_earlier_sdks_list_on_disk_loads_and_decides_nothing(tmp_path):
    engine, _ = _engine(tmp_path, RUNNING)
    # The file an earlier SDK wrote: the tick's list alone, as its cache wrote it
    SyncCache(str(tmp_path / "cache"), ORG, ENV)._try_disk_write(
        "kill_switches.json", [{"rule_name": "halt-payments", "active": True, "scope": {"environment": ENV}}])

    restarted = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    assert _attempt(restarted.load_from_disk) is True, "the version and routes still warm-start"
    assert (restarted.tick_part(), restarted.get_kill_switches()) == (None, None)
    assert restarted.get_kill_switches_age_seconds() == float("inf"), "no tick held"
    assert _read(_client(tmp_path, restarted).evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"])


# --- Behavior 10: the rule decides, not the name ---

def test_what_a_switch_stops_is_its_rule(tmp_path):
    halted = _content("v1.0.1", _rule("halt-payments", "KILL_SWITCH", conditions=_on("refund")), ALLOW_PAY)
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(halted))
    hiitl = _client(tmp_path, cache)
    assert _read(hiitl.evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"])
    assert _read(hiitl.evaluate("refund")) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"])


def test_a_tick_carrying_no_policy_set_decides_nothing_and_still_pulls(tmp_path):
    engine, cache = _engine(tmp_path, RUNNING)
    _tick_once(engine, _tick(None, names=["halt-payments"]))
    engine._client.download_policies.assert_called_once()
    assert _read(_client(tmp_path, cache).evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"])


def test_a_switch_edited_under_its_own_name_is_a_new_version_and_binds_through_the_ticks_part(tmp_path):
    # The same switch, its rule edited to stop refunds: the names agree and the version does not (condition 2)
    edited = _content("v1.0.3", _rule("halt-payments", "KILL_SWITCH", conditions=_on("refund")), ALLOW_PAY)
    engine, cache = _engine(tmp_path, HALTED)
    _tick_once(engine, _tick(edited))
    engine._client.download_policies.assert_called_once()
    assert cache.tick_part() is not None
    hiitl = _client(tmp_path, cache)
    assert _read(hiitl.evaluate("refund")) == ("KILL_SWITCH", "v1.0.3", ["halt-payments"]), "the edit binds"
    assert _read(hiitl.evaluate("pay")) == ("KILL_SWITCH", "v1.0.1", ["halt-payments"]), "the cached version outside"


def test_a_tick_naming_the_cached_version_holds_no_part_and_pulls_nothing(tmp_path):
    engine, cache = _engine(tmp_path, HALTED)
    _tick_once(engine, _tick(HALTED))
    engine._client.download_policies.assert_not_called()
    assert cache.tick_part() is None
    assert _read(_client(tmp_path, cache).evaluate("refund")) == ("ALLOW", "v1.0.1", ["allow-refund"])


def test_a_tick_whose_policy_set_the_model_refuses_decides_nothing_is_logged_and_still_pulls(tmp_path, caplog):
    tick = _tick(HALTED)
    tick["policy_set"] = {k: v for k, v in tick["policy_set"].items() if k != "scope"}
    engine, cache = _engine(tmp_path, RUNNING)
    with caplog.at_level(logging.ERROR, logger="hiitl.sdk.sync_cache"):
        _attempt(lambda: _tick_once(engine, tick))
    refused = [r.getMessage() for r in caplog.records if r.name == "hiitl.sdk.sync_cache" and r.levelno == logging.ERROR]
    assert len(refused) == 1 and "policy_set cannot be read" in refused[0] and "scope" in refused[0], refused
    engine._client.download_policies.assert_called_once()
    assert _read(_client(tmp_path, cache).evaluate("pay")) == ("ALLOW", "v1.0.0", ["allow-pay"])
