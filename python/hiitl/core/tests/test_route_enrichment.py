"""A sync route's answer re-enters evaluation (policy_format.md 2.7; TICKET-046 with TICKET-032's sync half).
Design: TEST_DESIGN_route_enrichment.md (E6–E10). The conformance cases (E1–E5) are tests/conformance/cases/enrichment.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiitl.core import routing
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import ENVELOPE_SCHEMA_VERSION


def _env(**kw):
    return {"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": "org_1234567890abcdef", "environment": "prod",
            "agent_id": "agent_ops_bot", "action_id": "act_route0000000000000000000", "timestamp": "2026-10-11T10:00:00Z",
            "operation": "execute", "parameters": {"body": "hello", "channel": "public"}, "idempotency_key": "idem_route",
            "target": {}, "signature": "0" * 64, "action": "publish_post", **kw}


def _rule(name, prio, cond, decision, code, route=None):
    r = {"name": name, "priority": prio, "conditions": cond, "decision": decision, "reason_code": code,
         "description": f"Rule: {name}"}
    if route:
        r["route"] = route
    return r


ASK = _rule("ask_content_check", 500, {"field": "action", "operator": "equals", "value": "publish_post"}, "ROUTE",
            "CONTENT_CHECK", route="content-check")
READ = _rule("block_rejected", 800, {"field": "external.content-check.verdict", "operator": "equals", "value": "rejected"},
             "BLOCK", "CONTENT_REJECTED")
ALLOW = _rule("allow_otherwise", 1, {"field": "action", "operator": "exists", "value": True}, "ALLOW", "ALLOWED")
POLICY = {"version": "v1.0.0", "description": "The p set", "scope": {"org_id": "org_1234567890abcdef", "environment": "prod"}, "name": "p", "rules": [ASK, READ, ALLOW]}


def _route(name="content-check", *, required=("verdict",), optional=("reason",), timeout_action="fail_closed",
           fields=None, include_policy_ref=True, auth=None, direction="bidirectional"):
    r = {"name": name, "direction": direction, "timing": "sync", "endpoint": f"https://checks.example/{name}",
         "response_schema": {"decision_options": ["accept", "reject"], "required_fields": list(required),
                             "optional_fields": list(optional)},
         "sla": {"timeout": "5s", "timeout_action": timeout_action},
         "context": {"include_policy_ref": include_policy_ref, **({"fields": [{"field_path": f} for f in fields]}
                                                                 if fields else {})}}
    if auth:
        r["auth"] = auth
    return r


def _run(answers: dict, routes: dict, envelope=None, policy=POLICY):
    """The loop over a fake route: `answers[name]` is the body, or an exception the ask raises."""
    asked = []
    ev = PolicyEvaluator()
    envelope = envelope or _env()

    def ask(route, payload):
        asked.append((route["name"], payload))
        a = answers[route["name"]]
        if isinstance(a, Exception):
            raise a
        return a
    d = routing.evaluate_with_routes(lambda enrichment: ev.evaluate(envelope, policy, enrichment=enrichment),
                                     routes.get, ask, envelope)
    return d, asked


# ── E6: the envelope cannot carry `external` ─────────────────────────────────────────────────────────────

def test_a_callers_external_key_is_not_the_enrichment_context():
    # The envelope refuses the key, naming it (R-0872, row 147): a value the caller supplies never reaches a rule
    # reading external.*, and is never silently dropped either.
    with pytest.raises(ValidationError) as exc:
        PolicyEvaluator().evaluate(_env(external={"content-check": {"verdict": "rejected"}}),
                                   {"version": "v1.0.0", "description": "A callers external key is not the enrichment context", "scope": {"org_id": "org_1234567890abcdef", "environment": "prod"}, "name": "p", "rules": [READ, ALLOW]})
    assert [(tuple(e["loc"]), e["type"]) for e in exc.value.errors()] == [(("external",), "extra_forbidden")]


# ── E7: each route asked once; evaluated again; the last decision is the decision ─────────────────────────

def test_the_route_is_asked_once_and_its_answer_decides():
    d, asked = _run({"content-check": {"verdict": "rejected", "reason": "slur"}}, {"content-check": _route()})
    assert [n for n, _ in asked] == ["content-check"]
    assert (d.decision, d.reason_codes) == ("BLOCK", ["CONTENT_REJECTED"])
    assert d.enrichment == {"content-check": {"verdict": "rejected", "reason": "slur"}}
    assert [(r.rule_name, r.route, r.outcome, r.fields) for r in d.routes] == \
        [("ask_content_check", "content-check", "answered", ["verdict", "reason"])]


def test_an_answer_no_rule_reads_does_not_ask_again():
    d, asked = _run({"content-check": {"verdict": "accepted"}}, {"content-check": _route()})
    assert len(asked) == 1 and d.decision == "ALLOW"


def test_a_rule_without_a_sync_route_stays_terminal_and_asks_nothing():
    d, asked = _run({}, {"content-check": _route(direction="outbound")})
    assert asked == [] and d.decision == "ROUTE" and d.route_ref == "content-check" and not d.routes


# ── E8: declared fields only; a missing required field is no answer ──────────────────────────────────────

def test_only_declared_fields_re_enter():
    d, _ = _run({"content-check": {"verdict": "accepted", "internal_score": 0.2}}, {"content-check": _route()})
    assert d.enrichment == {"content-check": {"verdict": "accepted"}}


def test_an_answer_missing_a_required_field_is_no_answer():
    d, _ = _run({"content-check": {"reason": "n/a"}}, {"content-check": _route()})
    assert (d.decision, d.allowed) == ("ROUTE", False) and routing.UNANSWERED in d.reason_codes
    (r,) = d.routes
    assert r.outcome == "unanswered" and "verdict" in r.error and not d.enrichment


# ── E9: no answer — fail closed by default, fail open re-evaluates with nothing ────────────────────────────

@pytest.mark.parametrize("action", ["fail_closed", "escalate", "extend"])
def test_an_unanswered_route_fails_closed(action):
    d, _ = _run({"content-check": routing.RouteUnanswered("timed out after 5s")},
                {"content-check": _route(timeout_action=action)})
    assert (d.decision, d.allowed, d.route_ref) == ("ROUTE", False, "content-check")
    assert routing.UNANSWERED in d.reason_codes and d.routes[0].outcome == "unanswered"
    assert d.routes[0].error == "timed out after 5s"


def test_fail_open_evaluates_again_with_nothing_and_other_rules_still_bind():
    hold = _rule("hold_public_posts", 300, {"field": "parameters.channel", "operator": "equals", "value": "public"},
                 "REQUIRE_APPROVAL", "PUBLIC_POST_HELD")
    policy = {"version": "v1.0.0", "description": "Fail open evaluates again with nothing and other rules still bind", "scope": {"org_id": "org_1234567890abcdef", "environment": "prod"}, "name": "p", "rules": [ASK, READ, hold, ALLOW]}
    d, asked = _run({"content-check": routing.RouteUnanswered("503")},
                    {"content-check": _route(timeout_action="fail_open")}, policy=policy)
    assert len(asked) == 1 and d.enrichment == {"content-check": {}} and d.routes[0].outcome == "failed_open"
    assert (d.decision, d.reason_codes) == ("REQUIRE_APPROVAL", ["PUBLIC_POST_HELD"]), "the next rule binds"
    d, _ = _run({"content-check": routing.RouteUnanswered("503")}, {"content-check": _route(timeout_action="fail_open")})
    assert d.decision == "ALLOW"


# ── E10: the payload is the route's context ─────────────────────────────────────────────────────────────────

def test_the_payload_carries_the_routes_context_fields_or_the_envelope():
    _, asked = _run({"content-check": {"verdict": "accepted"}},
                    {"content-check": _route(fields=["parameters.body", "action"])})
    (_, p), = asked
    assert p == {"route": "content-check", "rule": "ask_content_check", "action": "publish_post",
                 "fields": {"parameters.body": "hello", "action": "publish_post"}}
    _, asked = _run({"content-check": {"verdict": "accepted"}}, {"content-check": _route(include_policy_ref=False)})
    (_, p), = asked
    assert "rule" not in p and p["fields"]["parameters"] == {"body": "hello", "channel": "public"}


def test_auth_reads_the_secret_ref_from_the_environment():
    route = _route(auth={"type": "bearer_token", "header": "Authorization", "secret_ref": "env:CHECKS_TOKEN"})
    assert routing.auth_headers(route, {"CHECKS_TOKEN": "t0k"}) == {"Authorization": "Bearer t0k"}
    route = _route(auth={"type": "api_key", "header": "X-Api-Key", "secret_ref": "env:CHECKS_KEY"})
    assert routing.auth_headers(route, {"CHECKS_KEY": "k"}) == {"X-Api-Key": "k"}
    assert routing.auth_headers(_route(), {}) == {}


def test_the_sla_timeout_is_read_in_seconds():
    assert [routing.timeout_seconds({"sla": {"timeout": t}}) for t in ("30s", "2m", "1h")] == [30.0, 120.0, 3600.0]
