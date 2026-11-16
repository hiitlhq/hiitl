"""Row 225 (HTL-27): the `tool_name` alias leaves at envelope schema 2.0.

Ruled 2026-11-08: "the `tool_name` alias leaves at 2.0. An envelope carrying `tool_name` is refused as undefined,
naming `action`; a condition on `tool_name` is refused by the lint, naming `action`". By the 2.0 ruling's "no
acceptance window, no dual handling" and B.foundation.6 (one representation per fact). The rename is read at its
producer, envelope_schema.json (1.1, "Renamed tool_name to action"); policy_format.md 2.17 reads a path as written.
Design: the HTL-27 test design, row 225, behaviors 1, 3 and 6-8, and Codex's review condition 2 with its class (C2.3,
C2.5). Mirrors typescript/packages/core/tests/unit/row225.test.ts.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.lint import lint
from hiitl.core.types import ENVELOPE_RENAMED, ENVELOPE_SCHEMA_VERSION, FIELD_REF_KEY, Envelope, PolicySet

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "docs" / "specs" / "envelope_schema.json").read_text(encoding="utf-8"))
OLD, NEW = "tool_name", "action"


def _envelope(**fields) -> dict:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": "org_r225renamed000000", "environment": "prod",
            "agent_id": "billing-agent", "action_id": "act_r225renamed0000000000", "idempotency_key": "idem_r225",
            "action": "send_invoice", "timestamp": "2026-11-08T12:00:00Z", "signature": "a" * 64, **fields}


def _set(*conditions) -> dict:
    return {"name": "invoice_controls", "version": "v1.0.0", "description": "Invoice controls for the billing agent",
            "scope": {"org_id": "org_r225renamed000000", "environment": "prod"},
            "rules": [{"name": f"rule_{i}", "description": "Invoices to this customer need approval", "priority": 100 - i,
                       "conditions": c, "decision": "REQUIRE_APPROVAL", "reason_code": "INVOICE_REVIEW",
                       "route": "finance-review"} for i, c in enumerate(conditions)]}


def _errors(data: dict) -> dict:
    with pytest.raises(ValidationError) as caught:
        Envelope.model_validate(data)
    return {".".join(map(str, e["loc"])): e for e in caught.value.errors()}


def test_the_rename_record_is_the_schemas():
    """Behavior 1: every old name is a field the schema does not define, every new one a field it does, and the schema's
    own note records the rename."""
    assert ENVELOPE_RENAMED == {OLD: NEW}
    for old, new in ENVELOPE_RENAMED.items():
        assert old not in SCHEMA["properties"] and new in SCHEMA["properties"], (old, new)
        assert f"Renamed {old} to {new}" in SCHEMA["$comment"]


def test_the_1x_envelope_is_refused_naming_action():
    """Behaviors 2-3: `tool_name` alone is refused at `action` (absent) and `tool_name` (undefined); beside `action` at
    `tool_name` alone. The `tool_name` error names `action`; the others stand as they are."""
    legacy = _envelope(**{OLD: "send_invoice"})
    del legacy[NEW]
    errors = _errors(legacy)
    assert {k: e["type"] for k, e in errors.items()} == {NEW: "missing", OLD: "extra_forbidden"}
    assert NEW in errors[OLD]["msg"] and OLD in errors[OLD]["msg"], errors[OLD]["msg"]
    assert errors[NEW]["msg"] == "Field required"

    errors = _errors(_envelope(**{OLD: "send_invoice"}))
    assert {k: e["type"] for k, e in errors.items()} == {OLD: "extra_forbidden"}
    assert NEW in errors[OLD]["msg"]


def test_another_undefined_field_is_refused_as_before():
    """Behavior 3: only a renamed field's error names its new name."""
    errors = _errors(_envelope(amount_usd=120, **{OLD: "send_invoice"}))
    assert errors["amount_usd"]["msg"] == "Extra inputs are not permitted"
    assert NEW in errors[OLD]["msg"]


def test_the_lint_refuses_a_condition_on_tool_name_naming_action():
    """Behavior 6: a condition or a reference on `tool_name` is UNDEFINED_FIELD, an error, naming `action`; the
    parameter of that name is a field the envelope defines."""
    on_old = {"field": OLD, "operator": "equals", "value": "send_invoice"}
    referenced = {"field": "parameters.approver", "operator": "equals", "value": {"$field": OLD}}
    on_parameter = {"field": f"parameters.{OLD}", "operator": "equals", "value": "send_invoice"}
    found = [f for f in lint(_set(on_old, referenced, on_parameter)) if f.code == "UNDEFINED_FIELD"]
    assert [(f.rule, f.severity) for f in found] == [("rule_0", "error"), ("rule_1", "error")]
    for f in found:
        assert f"`{OLD}`" in f.message and f"`{NEW}`" in f.message, f.message


@pytest.mark.parametrize("condition,matches", [
    ({"field": f"parameters.{OLD}", "operator": "equals", "value": "crm_sync"}, True),
    ({"field": f"parameters.{OLD}", "operator": "equals", "value": "send_invoice"}, False),
    ({"field": OLD, "operator": "equals", "value": "send_invoice"}, False),
])
def test_a_path_is_read_as_written(condition, matches):
    """Behavior 7: `parameters.tool_name` is the parameter of that name, never `parameters.action`; a comparison on
    `tool_name` reads an absent field, so it is false under `skip` (what else it reads: conformance 189-191)."""
    envelope = Envelope.model_validate(_envelope(parameters={OLD: "crm_sync", NEW: "send_invoice"}))
    decision = PolicyEvaluator().evaluate(envelope, PolicySet.model_validate(_set(condition)))
    assert (decision.decision == "REQUIRE_APPROVAL") is matches, decision.decision



# Codex's review of PR #13, condition 2 and its class (policy_format.md 2.17): each part of a path is a member the object
# holds as data. Each language's own names, read in both evaluators (Path B).
NOT_DATA = ["toString", "constructor", "__proto__", "__class__", "model_dump", "parameters.toString",
            "parameters.tags.length", "parameters.tags.0", "timestamp.year", "cost_estimate.model_dump",
            "cost_estimate.toString"]
DATA = ["parameters.constructor", "parameters.tags", "cost_estimate.dollars"]


@pytest.mark.parametrize("field,matches", [(f, False) for f in NOT_DATA] + [(f, True) for f in DATA])
def test_a_path_part_is_a_member_the_object_holds_as_data(field, matches):
    """C2.3: `exists: true` on a model's method, `__class__` or a datetime's attribute never matches; a key the call
    carries does, whatever the name."""
    parameters = {"constructor": "Halden Build Ltd", "tags": ["school", "riverside"]}
    envelope = Envelope.model_validate(_envelope(parameters=parameters, cost_estimate={"dollars": 12.5}))
    condition = {"field": field, "operator": "exists", "value": True}
    decision = PolicyEvaluator().evaluate(envelope, PolicySet.model_validate(_set(condition)))
    assert (decision.decision == "REQUIRE_APPROVAL") is matches, decision.decision


def _rollout(field: str) -> str:
    s = _set({"field": "action", "operator": "equals", "value": "send_invoice"})
    s["rules"][0]["scope"] = {"percentage": 90, "rollout_hash_field": field}
    envelope = Envelope.model_validate(_envelope(user_id="usr_4471"))
    return PolicyEvaluator().evaluate(envelope, PolicySet.model_validate(s)).decision


@pytest.mark.parametrize("field", ["toString", "constructor", "__proto__", "__class__", "model_dump"])
def test_a_rollout_hashed_on_a_name_the_envelope_does_not_hold_skips_the_rule(field):
    """C2.5: the rollout's hash field is read as a path's part is; a method or `__class__` is absent, so the rule is
    skipped."""
    assert _rollout(field) != "REQUIRE_APPROVAL"


def test_a_rollout_hashed_on_a_field_the_call_carries_buckets_it_as_before():
    """C2.5: usr_4471's bucket is 69 (SHA-256, the first four bytes big-endian, mod 100), under 90."""
    assert _rollout("user_id") == "REQUIRE_APPROVAL"


def _a_case(name: str) -> bool:
    """A conformance case's set: an input its runners hold to the expected decision on its envelope."""
    rel = name.split(" ")[0]
    if not rel.endswith(".json"):
        return False
    doc = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    return isinstance(doc, dict) and {"envelope", "policy_set", "expected_decision"} <= set(doc)


def _migrated(node):
    """The set as the CHANGELOGs tell a 1.x user to rewrite it: each renamed head read under the name it became."""
    if isinstance(node, list):
        return [_migrated(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in ("field", FIELD_REF_KEY) and isinstance(v, str):
            head, dot, rest = v.partition(".")
            v = ENVELOPE_RENAMED.get(head, head) + dot + rest
        out[k] = _migrated(v)
    return out


def test_no_carried_set_reads_a_field_the_envelope_lacks():
    """Behavior 8: every policy set the repository carries (row 165's walk) lints with no UNDEFINED_FIELD, but a
    conformance case's. A case may carry a 1.x set on purpose, its runners holding what a condition on a renamed head
    decides (Codex's condition 1); it may read a renamed head and no other undefined field."""
    from hiitl.core.tests.test_row165 import CARRIED  # the walk reads the repository's tracked files

    assert CARRIED, "the walk is read"
    assert any(_a_case(n) and _migrated(s) != s for n, s in CARRIED), "a case reading a renamed head is reached"
    undefined = [f"{name}: {f.rule}: {f.message}" for name, s in CARRIED
                 for f in lint(_migrated(s) if _a_case(name) else s) if f.code == "UNDEFINED_FIELD"]
    assert not undefined, "\n".join(undefined)
