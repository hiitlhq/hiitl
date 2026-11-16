"""Row 147 (HTL-20) through the SDK: a cached policy is read through the model before it is taken.

R-0872: "no field is ever silently dropped". sync_engine.md §6: "Precedence: Server cache > local policy files >
empty". Design: the HTL-20 test design, row 147. The TypeScript SDK's twin is sdk/tests/unit/row147.test.ts.
"""

import json
import logging

from hiitl import HIITL
from hiitl.sdk.sync_cache import SyncCache


def _rule(name, decision):
    return {"name": name, "description": f"Invoices: {decision}", "priority": 100,
            "conditions": {"field": "action", "operator": "equals", "value": "send_invoice"},
            "decision": decision, "reason_code": f"INVOICE_{decision}"}


def _cache(tmp_path, *contents):
    """The sync cache a hybrid client reads, holding the given server policies as a pull lands them: the cache reads
    them through the model where they are received (sync_engine.md Numeric domain; HTL-43 gap 295)."""
    cache = SyncCache(cache_dir=str(tmp_path / "cache"), org_id="org_test000000000000000", environment="dev")
    cache.update_policies({"policies": [{"name": f"server_{i}", "active": True, "content": c}
                                        for i, c in enumerate(contents)]})
    return cache


def _client(tmp_path, *contents):
    policy = tmp_path / "invoices.json"
    policy.write_text(json.dumps({"version": "v1.0.0", "description": "The file_policy set", "scope": {"org_id": "org_test000000000000000", "environment": "dev"}, "name": "file_policy", "rules": [_rule("file_rule", "ALLOW")]}))
    hiitl = HIITL(environment="dev", agent_id="billing-agent", org_id="org_test000000000000000",
                  policy_path=str(policy), audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY")
    hiitl._mode, hiitl._sync_cache = "hybrid", _cache(tmp_path, *contents)
    return hiitl


def test_a_cached_policy_the_model_refuses_is_skipped_naming_the_field(tmp_path, caplog):
    refused = {"version": "v1.0.0", "description": "A cached policy the model refuses is skipped naming the field", "scope": {"org_id": "org_test000000000000000", "environment": "dev"}, "name": "server_policy", "rules": [{**_rule("server_rule", "BLOCK"), "enabled_for": "all"}]}
    with caplog.at_level(logging.WARNING):
        d = _client(tmp_path, refused).evaluate("send_invoice")
    assert [m.rule_name for m in d.matched_rules] == ["file_rule"], "the next source decides"
    said = "\n".join(r.getMessage() for r in caplog.records)
    assert "Failed to parse cached policy 'server_0'" in said and "enabled_for" in said, "the field is named"

    accepted = {"version": "v1.0.0", "description": "A cached policy the model refuses is skipped naming the field", "scope": {"org_id": "org_test000000000000000", "environment": "dev"}, "name": "server_policy", "rules": [_rule("server_rule", "BLOCK")]}
    d = _client(tmp_path, refused, accepted).evaluate("send_invoice")
    assert [m.rule_name for m in d.matched_rules] == ["server_rule"]
