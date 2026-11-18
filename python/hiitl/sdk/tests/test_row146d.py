"""Row 146 (HTL-20), the decision-model members: what a Decision declares is produced, and a code-level override in
production is said. The producer reading over every Decision field is held on the service's
side, since the server is a producer too.

ecp_evaluate_spec.md, Resolved Design Decision 1: "Production uses RESPECT_POLICY ... If a code-level override is
active in a production environment, the SDK logs a warning." The client's OBSERVE_ALL allows every action whatever
the policy says, so a client in the prod environment that runs it logs a warning naming how to respect the policy.
Hosted mode evaluates on the server, which applies its own mode, so the hosted client does not warn.
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from hiitl import HIITL

POLICY = {"name": "p", "version": "v1.0.0", "description": "The p set", "scope": {"org_id": "org_devlocal0000000000", "environment": "prod"}, "rules": [
    {"name": "allow", "description": "d", "priority": 1, "decision": "ALLOW", "reason_code": "OK",
     "conditions": {"field": "action", "operator": "exists", "value": True}}]}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in [n for n in os.environ if n.upper().startswith("HIITL_")]:
        monkeypatch.delenv(name)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and "OBSERVE_ALL in the prod environment" in r.getMessage()]


@pytest.mark.parametrize("environment, mode, warned", [
    ("prod", "OBSERVE_ALL", True),
    ("prod", "RESPECT_POLICY", False),
    ("dev", "OBSERVE_ALL", False),
    ("stage", "OBSERVE_ALL", False),
])
def test_a_code_level_observe_all_in_prod_logs_a_warning(environment, mode, warned, tmp_path, caplog):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(POLICY))
    caplog.set_level(logging.WARNING, logger="hiitl.sdk.client")
    HIITL(environment=environment, mode=mode, policy_path=str(p), audit_db_path=str(tmp_path / "a.db"))
    found = _warnings(caplog)
    assert len(found) == int(warned), found
    if warned:
        assert "HIITL(mode='RESPECT_POLICY')" in found[0] and "HIITL_MODE=RESPECT_POLICY" in found[0]


def test_the_hosted_client_does_not_warn(caplog):
    caplog.set_level(logging.WARNING, logger="hiitl.sdk.client")
    HIITL(environment="prod", api_key="sk_test_1234567890abcdef", server_url="https://ecp.example", evaluation="remote",
          signature_key="s" * 32)
    assert _warnings(caplog) == []

