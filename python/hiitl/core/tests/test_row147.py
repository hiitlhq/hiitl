"""Row 147 (HTL-20): every model refuses what its spec refuses, naming the field (R-0872 / R-0881 swept).

R-0872: "no field is ever silently dropped". R-0881: "every policy-format model refuses an undefined field". The specs
are read at their producer: envelope_schema.json (v1.4), policy_format.md 2.10 (the decisions a rule writes, the
scope's environments), routes.md 1.3. Design: the HTL-20 test design, row 147.
"""

import json
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from hiitl.core.route_types import Route
from hiitl.core.types import DecisionType, ENVELOPE_SCHEMA_VERSION, Envelope, PolicySet, Rule

ROOT = Path(__file__).resolve().parents[4]
SPECS = ROOT / "docs" / "specs"
ENVELOPE_SCHEMA = json.loads((SPECS / "envelope_schema.json").read_text(encoding="utf-8"))


def _route_schema() -> dict:
    text = (SPECS / "routes.md").read_text(encoding="utf-8")
    start = text.index("```json", text.index("JSON Schema")) + len("```json")
    return json.loads(text[start:text.index("```", start)])


def _envelope(**fields) -> dict:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION,
            "org_id": "org_test123456789012", "environment": "dev", "agent_id": "agent-147",
            "action_id": "act_01234567890123456789", "idempotency_key": "idem_row147", "action": "send_invoice",
            "timestamp": "2026-11-04T12:00:00Z", "signature": "a" * 64, **fields}


def _rule(**fields) -> dict:
    return {"name": "invoice_rule", "description": "Invoices are allowed", "priority": 100,
            "conditions": {"field": "action", "operator": "equals", "value": "send_invoice"},
            "decision": "ALLOW", "reason_code": "INVOICE_ALLOWED", **fields}


def _route(**fields) -> dict:
    return {"name": "finance-review", "version": "v1.0.0", "direction": "bidirectional", "timing": "sync",
            "endpoint": "https://hooks.example.com/review", "response_schema": {"decision_options": ["approve", "deny"]},
            "sla": {"timeout": "4h", "timeout_action": "fail_closed"}, **fields}


def _refused_at(exc: pytest.ExceptionInfo, loc: tuple) -> None:
    found = [(tuple(e["loc"]), e["type"]) for e in exc.value.errors()]
    assert (loc, "extra_forbidden") in found, f"refused at {loc}: got {found}"


def _table(text: str, heading: str) -> list[tuple[str, str]]:
    """The rows (value, description) of the first table under a heading."""
    section = text[text.index(heading):]
    rows = re.findall(r"^\| `([A-Z_]+)` \| ([^|]*)\|", section.split("\n---", 1)[0], flags=re.M)
    return [(v, d.strip()) for v, d in rows]


def test_an_envelope_refuses_an_undefined_field_naming_it():
    with pytest.raises(ValidationError) as exc:
        Envelope.model_validate(_envelope(amount_usd=120))
    _refused_at(exc, ("amount_usd",))
    with pytest.raises(ValidationError) as exc:
        Envelope.model_validate(_envelope(tool_name="send_payment"))
    _refused_at(exc, ("tool_name",))  # alone, it is refused too, naming action (row 225; test_row225.py)


def test_a_cost_estimate_refuses_an_undefined_key_naming_it():
    with pytest.raises(ValidationError) as exc:
        Envelope.model_validate(_envelope(cost_estimate={"usd_cents": 3}))
    _refused_at(exc, ("cost_estimate", "usd_cents"))
    defined = set(ENVELOPE_SCHEMA["properties"]["cost_estimate"]["properties"])
    assert Envelope.model_validate(_envelope(cost_estimate={k: 1 for k in defined})).cost_estimate is not None


def _tokens(value):
    try:
        return Envelope.model_validate(_envelope(cost_estimate={"tokens": value})).cost_estimate.tokens
    except ValidationError as e:
        raise AssertionError(f"the envelope refused tokens={value!r}: {e.errors()[0]['msg']}") from None


def test_tokens_is_a_number_kept_as_written():
    assert ENVELOPE_SCHEMA["properties"]["cost_estimate"]["properties"]["tokens"]["type"] == "number"
    assert _tokens(1.5) == 1.5
    whole = _tokens(1500)
    assert whole == 1500 and type(whole) is int, "an integer estimate stays an integer"
    with pytest.raises(ValidationError):
        Envelope.model_validate(_envelope(cost_estimate={"tokens": -1}))


def test_a_rule_writes_only_the_decisions_the_spec_lists():
    rows = _table((SPECS / "policy_format.md").read_text(encoding="utf-8"), "### Valid Decisions")
    errors = _table((SPECS / "decision_response.md").read_text(encoding="utf-8"), "### Error Decisions")
    written = {v for v, d in rows if "not written in rules" not in d}
    produced = {d.value for d in DecisionType} - written
    assert produced == {v for v, d in rows if "not written in rules" in d} | {v for v, _ in errors}, (
        "every decision a rule does not write is one the spec says the evaluator or the control point produces")
    for value in sorted(produced):
        with pytest.raises(ValidationError) as exc:
            PolicySet.model_validate({"name": "p", "version": "v1.0.0", "description": "A rule writes only the decisions the spec lists", "scope": {"org_id": "org_test123456789012", "environment": "dev"}, "rules": [_rule(decision=value)]})
        text = str(exc.value)
        assert "invoice_rule" in text and value in text, f"the refusal of {value} names the rule and the value"
    for value in sorted(written):
        Rule.model_validate(_rule(decision=value, **({"route": "finance-review"} if value == "ROUTE" else {})))


def test_a_scope_takes_only_the_envelopes_environments():
    for env in ENVELOPE_SCHEMA["properties"]["environment"]["enum"]:
        assert Rule.model_validate(_rule(scope={"environments": [env]})).scope.environments == [env]
    with pytest.raises(ValidationError) as exc:
        Rule.model_validate(_rule(scope={"environments": ["prod", "staging"]}))
    assert "staging" in str(exc.value) and ("scope", "environments", 1) in [tuple(e["loc"]) for e in exc.value.errors()]


def test_a_route_refuses_an_undefined_field_at_every_depth():
    with pytest.raises(ValidationError) as exc:
        Route.model_validate(_route(owner="finance"))
    _refused_at(exc, ("owner",))
    with pytest.raises(ValidationError) as exc:
        Route.model_validate(_route(scope={"org_id": "org_test123456789012", "region": "eu"}))
    _refused_at(exc, ("scope", "region"))
    with pytest.raises(ValidationError) as exc:
        Route.model_validate(_route(sla={"timeout": "4h", "timeout_action": "fail_closed", "escalate_after": "1h"}))
    _refused_at(exc, ("sla", "escalate_after"))
    with pytest.raises(ValidationError) as exc:
        Route.model_validate(_route(context={"risk_framing": {"consequences": {"if_approved": "paid", "if_late": "x"}}}))
    _refused_at(exc, ("context", "risk_framing", "consequences", "if_late"))
    assert Route.model_validate(_route(metadata={"owner": "finance"})).metadata == {"owner": "finance"}


def _models(ann, seen: set) -> typing.Iterator[type]:
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        if ann in seen:
            return
        seen.add(ann)
        yield ann
        for field in ann.model_fields.values():
            yield from _models(field.annotation, seen)
    for arg in typing.get_args(ann):
        yield from _models(arg, seen)


def test_every_model_an_artifact_is_read_through_is_closed():
    roots = (Envelope, PolicySet, Route)
    seen: set = set()
    models = [m for root in roots for m in _models(root, seen)]
    # pydantic's own schema names every model under a root ($defs): the walk reaches each of them
    named = {name for root in roots for name, d in root.model_json_schema().get("$defs", {}).items()
             if d.get("type") == "object"} | {root.__name__ for root in roots}
    assert sorted(named - {m.__name__ for m in models}) == [], "the walk reaches every model the schema names"
    open_ = [m.__name__ for m in models if m.model_config.get("extra") != "forbid"]
    assert not open_, f"each refuses an undefined field: open {open_}"


def _model_of(ann) -> typing.Optional[type]:
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann
    return next((m for m in map(_model_of, typing.get_args(ann)) if m), None)


def _resolve(ref: str, schema: dict) -> tuple[dict, dict]:
    # A reference is a document (another spec beside this one, or this one) and a JSON pointer into it
    doc, _, pointer = ref.partition("#")
    schema = json.loads((SPECS / doc).read_text(encoding="utf-8")) if doc else schema
    node = schema
    for part in filter(None, pointer.split("/")):
        node = node[part]
    return node, schema


def _closed_objects(node: dict, schema: dict, model, path: str) -> typing.Iterator[tuple[str, dict, typing.Any]]:
    if "$ref" in node:
        node, schema = _resolve(node["$ref"], schema)
    if node.get("type") == "array" and "items" in node:
        yield from _closed_objects(node["items"], schema, model, path + "[]")
        return
    if "properties" not in node or node.get("additionalProperties") is True:
        return
    yield path, node, model
    for key, sub in node["properties"].items():
        field = model.model_fields.get(key) if model else None
        yield from _closed_objects(sub, schema, _model_of(field.annotation) if field else None, f"{path}.{key}")


def test_each_closed_object_in_the_specs_is_the_models_field_for_field():
    found = []
    for schema, root in ((ENVELOPE_SCHEMA, Envelope), (_route_schema(), Route)):
        for path, node, model in _closed_objects(schema, schema, root, root.__name__):
            assert node.get("additionalProperties") is False, f"{path} defines its fields and is closed in the spec"
            assert model is not None, f"{path}: a model reads it"
            assert set(node["properties"]) == set(model.model_fields), f"{path}: the model's fields are the spec's"
            assert model.model_config.get("extra") == "forbid", f"{path}: the model refuses what the spec refuses"
            found.append(path)
    assert {"Envelope.cost_estimate", "Route.scope", "Route.sla"} <= set(found)
