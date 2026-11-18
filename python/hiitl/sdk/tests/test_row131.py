"""Row 131 (HTL-29): the kill-switch tick is the change signal, and the version decides.

policy_format.md "A version identifies what evaluates" and "Same envelope + same policy version = same decision.
Always."; sync_engine.md 2.4, the version the tick names against the version the SDK evaluates (condition 2, 2026-11-10),
and section 6 "Kill Switches — Server Wins, Through the Version". Design: the HTL-29 test design, row 131, behaviors 3-5.
Mirrors typescript/packages/sdk/tests/unit/row131.test.ts.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock

from hiitl import HIITL
from hiitl.core.canonical import canonical_hash
from hiitl.sdk.config import SyncConfig
from hiitl.sdk.sync_cache import SyncCache
from hiitl.sdk.sync_client import KillSwitchResult, PolicyDownloadResult
from hiitl.sdk.sync_engine import SyncEngine

ORG, ENV = "org_test0123456789ab", "dev"
ON_PAY = {"field": "action", "operator": "equals", "value": "pay"}
REDACTION = {"manual_redact_fields": []}


def _content(version, *rules):
    return {"name": "payments", "version": version, "description": "payments",
            "scope": {"org_id": ORG, "environment": ENV}, "rules": list(rules)}


def _rule(name, decision, stage="active"):
    return {"name": name, "description": name, "priority": 100, "conditions": ON_PAY, "decision": decision,
            "reason_code": name.upper().replace("-", "_"), "lifecycle_stage": stage}


HALTED = _content("v1.0.1", _rule("halt-payments", "KILL_SWITCH"), _rule("allow-pay", "ALLOW"))
RUNNING = _content("v1.0.0", _rule("halt-payments", "KILL_SWITCH", "disabled"), _rule("allow-pay", "ALLOW"))
RESUMED = _content("v1.0.2", _rule("halt-payments", "KILL_SWITCH", "disabled"), _rule("allow-pay", "ALLOW"))


def _policy(content, active=True):
    return {"policy_id": f"pol_{content['version']}", "name": content["name"], "version": content["version"],
            "active": active, "content": content, "content_hash": canonical_hash(content)}


def _names(*names):
    """A tick carrying the list alone, no `policy_set`."""
    return KillSwitchResult(kill_switches=[{"rule_name": n, "active": True, "scope": {"environment": ENV}}
                                           for n in names], server_time="2026-11-09T00:00:00+00:00")


def _tick(content):
    """The tick as the service writes it for `content`: its live switches, and its `policy_set` (the set's own fields
    and those switches)."""
    live = [r for r in content["rules"] if r["decision"] == "KILL_SWITCH" and r["lifecycle_stage"] == "active"]
    tick = _names(*(r["name"] for r in live))
    tick.policy_set = {**{k: v for k, v in content.items() if k != "rules"}, "rules": live}
    return tick


def _engine(tmp_path, *cached):
    cache = SyncCache(str(tmp_path / "cache"), ORG, ENV)
    cache.update_policies({"policies": list(cached), "version": "cached", "redaction_policy": REDACTION},
                          etag="e-cached")
    engine = SyncEngine(sync_config=SyncConfig(server_url="https://api.hiitl.com", cache_dir=str(tmp_path / "cache")),
                        sync_cache=cache, audit_logger=MagicMock(), api_key="sk_test_123", org_id=ORG,
                        environment=ENV)
    engine._client = MagicMock()
    engine._client.download_policies.return_value = PolicyDownloadResult(
        policies=[_policy(HALTED)], version="v1.0.1", etag="e-v1.0.1", redaction_policy=REDACTION)
    return engine, cache


# --- Behavior 3: a tick that differs pulls the version ---

def test_a_tick_naming_a_version_other_than_the_cached_one_pulls_in_that_tick(tmp_path):
    engine, cache = _engine(tmp_path, _policy(RUNNING))
    engine._client.poll_kill_switches.return_value = _tick(HALTED)
    engine._sync_kill_switches()
    engine._client.download_policies.assert_called_once_with(etag="e-cached")
    assert [p["version"] for p in cache.get_policies()["policies"]] == ["v1.0.1"], "the version the tick names"


def test_a_tick_naming_the_cached_version_downloads_nothing(tmp_path):
    for cached in (RUNNING, HALTED):
        engine, _ = _engine(tmp_path, _policy(cached))
        engine._client.poll_kill_switches.return_value = _tick(cached)
        engine._sync_kill_switches()
        engine._client.download_policies.assert_not_called()


def test_a_tick_that_drops_a_switch_pulls(tmp_path):
    engine, _ = _engine(tmp_path, _policy(HALTED))
    engine._client.poll_kill_switches.return_value = _tick(RESUMED)
    engine._sync_kill_switches()
    engine._client.download_policies.assert_called_once()


# --- Behavior 4: the version is the one evaluate reads ---

def test_the_tick_compares_the_version_evaluate_reads(tmp_path):
    engine, _ = _engine(tmp_path, _policy(HALTED, active=False), _policy(RUNNING))
    engine._client.poll_kill_switches.return_value = _tick(HALTED)
    engine._sync_kill_switches()
    engine._client.download_policies.assert_called_once()


# --- Behavior 5: the list never decides ---

def test_a_cached_list_naming_a_switch_the_version_does_not_make_live_decides_nothing(tmp_path):
    _, cache = _engine(tmp_path, _policy(RUNNING))
    cache.update_kill_switches(asdict(_names("halt-payments")))     # a tick carrying no policy_set (row 240)

    policy = tmp_path / "local.json"
    policy.write_text(json.dumps(_content("v0.0.1", _rule("local-allow", "ALLOW"))))
    hiitl = HIITL(environment=ENV, agent_id="payment-agent", org_id=ORG, policy_path=str(policy),
                  audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")
    hiitl._mode, hiitl._sync_cache = "hybrid", cache
    d = hiitl.evaluate("pay")
    assert (d.decision, d.policy_version) == ("ALLOW", "v1.0.0"), "the cached version decides"
    assert [m.rule_name for m in d.matched_rules] == ["allow-pay"]
