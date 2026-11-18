"""The SDK asks a sync route and evaluates again with its answer (TICKET-046; policy_format.md 2.7; routes.md "A sync
route's answer re-enters evaluation"). Design: hiitl/core/tests/TEST_DESIGN_route_enrichment.md (E10, E11).
"""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from hiitl.sdk.client import HIITL

POLICY = """
version: "v1.0.0"
description: "Posts are checked before they publish"
scope:
  org_id: org_test000000000000000
  environment: dev
name: content_policy
rules:
  - name: ask_content_check
    priority: 500
    conditions: {field: action, operator: equals, value: publish_post}
    decision: ROUTE
    reason_code: CONTENT_CHECK
    route: content-check
    description: Posts are checked before they publish
  - name: block_rejected
    priority: 800
    conditions: {field: external.content-check.verdict, operator: equals, value: rejected}
    decision: BLOCK
    reason_code: CONTENT_REJECTED
    description: A post the check rejects does not publish
  - name: allow_otherwise
    priority: 1
    conditions: {field: action, operator: exists, value: true}
    decision: ALLOW
    reason_code: ALLOWED
    description: Everything else
"""

ROUTE = {
    "name": "content-check", "version": "v1.0.0", "description": "The content check, asked before a post publishes",
    "direction": "bidirectional", "timing": "sync", "purpose": ["assessment"],
    "endpoint": "https://checks.example/v1/content", "protocol": "http",
    "auth": {"type": "bearer_token", "header": "Authorization", "secret_ref": "env:HIITL_TEST_CHECKS_TOKEN"},
    "context": {"fields": [{"field_path": "parameters.body"}], "include_policy_ref": True},
    "response_schema": {"decision_options": ["approve", "deny"], "required_fields": ["verdict"],
                        "optional_fields": ["reason"]},
    "sla": {"timeout": "5s", "timeout_action": "fail_closed"},
}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HIITL_TEST_CHECKS_TOKEN", "t0k")
    (tmp_path / "policy.yaml").write_text(POLICY)
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "content-check.json").write_text(json.dumps(ROUTE))
    seen = []

    def make(handler):
        def h(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)
        client = HIITL(environment="dev", agent_id="poster", org_id="org_test000000000000000",
                       policy_path=str(tmp_path / "policy.yaml"), routes_path=str(routes),
                       audit_db_path=str(tmp_path / "audit.db"), mode="RESPECT_POLICY",
                       route_client=httpx.Client(transport=httpx.MockTransport(h)))
        return client
    return make, seen, tmp_path / "audit.db"


def _last_record(db):
    with sqlite3.connect(db) as c:
        row = c.execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT 1").fetchone()
        cols = [d[0] for d in c.execute("SELECT * FROM audit_log LIMIT 0").description]
    return dict(zip(cols, row))


def test_the_sdk_asks_the_route_and_its_answer_decides_and_is_recorded(setup):
    make, seen, db = setup
    h = make(lambda r: httpx.Response(200, json={"verdict": "rejected", "reason": "slur", "score": 0.9}))
    d = h.evaluate("publish_post", parameters={"body": "a slur"})
    assert (d.decision, d.reason_codes) == ("BLOCK", ["CONTENT_REJECTED"])
    assert d.enrichment == {"content-check": {"verdict": "rejected", "reason": "slur"}}
    assert [(r.route, r.outcome) for r in d.routes] == [("content-check", "answered")]
    (req,) = seen
    assert str(req.url) == "https://checks.example/v1/content" and req.headers["Authorization"] == "Bearer t0k"
    assert json.loads(req.content) == {"route": "content-check", "rule": "ask_content_check", "action": "publish_post",
                                       "fields": {"parameters.body": "a slur"}}
    recorded = json.loads(_last_record(db)["decision"])
    assert recorded["enrichment"] == {"content-check": {"verdict": "rejected", "reason": "slur"}}
    assert [(r["route"], r["outcome"]) for r in recorded["routes"]] == [("content-check", "answered")], \
        "the record carries the decision with the answer it read"


def test_an_unanswered_route_fails_closed_in_the_sdk(setup):
    make, seen, _ = setup
    h = make(lambda r: httpx.Response(503))
    d = h.evaluate("publish_post", parameters={"body": "hello"})
    assert (d.decision, d.allowed, d.route_ref) == ("ROUTE", False, "content-check")
    assert "ROUTE_UNANSWERED" in d.reason_codes and d.routes[0].error == "the route answered 503"
    assert len(seen) == 1


def test_an_answer_that_satisfies_nothing_allows_without_asking_again(setup):
    make, seen, _ = setup
    h = make(lambda r: httpx.Response(200, json={"verdict": "accepted"}))
    assert h.evaluate("publish_post", parameters={"body": "hello"}).decision == "ALLOW" and len(seen) == 1
