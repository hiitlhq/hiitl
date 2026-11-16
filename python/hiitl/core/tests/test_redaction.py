"""Row 139 (HTL-20): what a store writes, the record with each declared field's value replaced.

Ruled 2026-11-04: "a declared redaction list applies before every write in both stores; the gateway records argument
names with hashed values unless a field is declared". The contract is event_format.md §Redaction; these are the
row's test design cells 1-6. The TypeScript twin is
typescript/packages/core/tests/unit/redaction.test.ts.
"""

import copy

import pytest

from hiitl.core.redaction import KEY_BYTES, MARKER, Redaction, value_hash

KEY = bytes(range(KEY_BYTES))       # the store's value-hash key (row 163(c)): a fixed one, so a hash can be restated

# A payout agent's call: the account it pays into, the payee's email, the amount, and the invoice lines it settles
ENVELOPE = {
    "org_id": "org_test0123456789ab",
    "environment": "prod",
    "action_id": "act_0123456789abcdefghij",
    "agent_id": "payout-agent",
    "action": "pay",
    "target": {"email": "dana@example.com", "vendor_id": "vnd_42"},
    "parameters": {
        "account_number": "GB29NWBK60161331926819",
        "amount": 1250,
        "currency": "gbp",
        "lines": [{"invoice": "INV-7", "card": "4111 1111 1111 1111"}, {"invoice": "INV-8", "card": "5500 0000 0000 0004"}],
    },
}
DECISION = {"action_id": "act_0123456789abcdefghij", "decision": "ALLOW", "allowed": True, "reason_codes": ["OK"]}


def _blocked(remediation):
    return {**DECISION, "decision": "BLOCK", "allowed": False, "remediation": remediation}


def test_a_declared_field_is_replaced_in_the_stored_copy():
    env, dec = copy.deepcopy(ENVELOPE), copy.deepcopy(DECISION)
    r = Redaction.declared(["parameters.account_number", "target.email", "parameters.lines.card", "parameters.iban"])
    stored, stored_dec = r.record(env, dec)

    assert stored["parameters"]["account_number"] == MARKER
    assert stored["target"]["email"] == MARKER
    assert [line["card"] for line in stored["parameters"]["lines"]] == [MARKER, MARKER], "every item of an array"
    assert [line["invoice"] for line in stored["parameters"]["lines"]] == ["INV-7", "INV-8"]
    assert (stored["parameters"]["amount"], stored["parameters"]["currency"], stored["target"]["vendor_id"]) == (
        1250, "gbp", "vnd_42"), "an undeclared member is as given"
    assert "iban" not in stored["parameters"], "a declared path the call does not carry adds nothing"
    assert {k: stored[k] for k in ("org_id", "environment", "action_id", "agent_id", "action")} == {
        k: ENVELOPE[k] for k in ("org_id", "environment", "action_id", "agent_id", "action")}
    assert stored_dec == DECISION
    assert (env, dec) == (ENVELOPE, DECISION), "the inputs are never changed: the caller's decision is its own"


@pytest.mark.parametrize("entry", ["org_id", "parameters", "parameters.", ".account_number", "parameters..x", "", 7])
def test_a_declaration_names_a_member_never_a_top_level_field(entry):
    with pytest.raises(ValueError, match="event_format.md §Redaction") as e:
        Redaction.declared([entry])
    assert repr(entry) in str(e.value), "the message names the entry"


def test_a_declaration_is_a_list_and_recorded_parameters_a_map_of_names():
    with pytest.raises(ValueError, match="list of field paths"):
        Redaction.declared("parameters.account_number")
    for bad in (["amount"], {"pay": "amount"}, {"pay": ["amount", ""]}, {"pay": [3]}):
        with pytest.raises(ValueError, match="event_format.md §Redaction"):
            Redaction.declared(recorded_parameters=bad)


def test_the_gateway_records_names_with_hashed_values():
    params = ENVELOPE["parameters"]
    stored, _ = Redaction.declared(recorded_parameters={"pay": ["amount"]}).keyed(KEY).record(ENVELOPE, DECISION)
    assert set(stored["parameters"]) == set(params), "every argument's name is recorded"
    assert stored["parameters"]["amount"] == 1250, "an argument declared recorded is as given"
    for name in ("account_number", "currency", "lines"):
        assert stored["parameters"][name] == value_hash(params[name], KEY)
    assert stored["target"] == ENVELOPE["target"], "the gateway hashes arguments, nothing else"

    other = {**ENVELOPE, "action": "read_file", "parameters": {"amount": 1250, "path": "/etc/passwd"}}
    stored_other, _ = Redaction.declared(recorded_parameters={"pay": ["amount"]}).keyed(KEY).record(other, DECISION)
    assert stored_other["parameters"] == {"amount": value_hash(1250, KEY), "path": value_hash("/etc/passwd", KEY)}, \
        "a name recorded for one tool is hashed for another"

    nothing, _ = Redaction.declared(recorded_parameters={}).keyed(KEY).record(ENVELOPE, DECISION)
    assert all(v == value_hash(params[k], KEY) for k, v in nothing["parameters"].items()), "{} hashes every argument"

    both, _ = Redaction.declared(["parameters.account_number", "parameters.amount"],
                                 recorded_parameters={"pay": ["amount"]}).keyed(KEY).record(ENVELOPE, DECISION)
    assert both["parameters"]["account_number"] == MARKER, "a declared field is the marker, never a hash of it"
    assert both["parameters"]["amount"] == MARKER, "a declared field is the marker even when recorded as given"


def test_a_remediation_that_states_a_value_takes_its_fields_treatment():
    r = Redaction.declared(["parameters.amount", "parameters.card"])
    over = _blocked({"type": "threshold", "message": "over the limit",
                     "details": {"threshold": 1000, "current_value": 1250, "max_allowed": 1000,
                                 "field": "parameters.amount"}})
    _, stored = r.record(ENVELOPE, over)
    assert stored["remediation"]["details"] == {"threshold": 1000, "current_value": MARKER, "max_allowed": 1000,
                                                "field": "parameters.amount"}
    assert over["remediation"]["details"]["current_value"] == 1250, "the caller's decision keeps it"

    under = _blocked({"type": "threshold", "details": {"current_value": 4111, "field": "parameters.card.prefix"}})
    assert r.record(ENVELOPE, under)[1]["remediation"]["details"]["current_value"] == MARKER, "under a declared field"

    cards = Redaction.declared(["parameters.lines.card"])
    for ref in ("parameters.lines.card", "parameters.lines"):
        restricted = _blocked({"type": "field_restriction",
                               "details": {"blocked_fields": ["5500 0000 0000 0004"], "field_ref": ref}})
        details = cards.record(ENVELOPE, restricted)[1]["remediation"]["details"]
        assert details == {"blocked_fields": MARKER, "field_ref": ref}, f"a field_ref that is or holds one: {ref}"

    nested = {**DECISION, "audit": {"remediation": over["remediation"]}}
    assert r.record(ENVELOPE, nested)[1]["audit"]["remediation"]["details"]["current_value"] == MARKER, \
        "wherever in the decision a remediation sits"

    gateway = Redaction.declared(recorded_parameters={"pay": ["currency"]}).keyed(KEY)
    assert gateway.record(ENVELOPE, over)[1]["remediation"]["details"]["current_value"] == value_hash(1250, KEY), \
        "a hashed parameter's value is hashed in the remediation too"

    elsewhere = _blocked({"type": "threshold", "details": {"current_value": 3, "field": "parameters.retries"}})
    assert r.record(ENVELOPE, elsewhere)[1] == elsewhere, "an undeclared field's remediation is as given"
    scope = _blocked({"type": "scope", "details": {"current_value": 1250, "field": "parameters.amount"}})
    assert r.record(ENVELOPE, scope)[1] == scope, "a remediation type that states no value at a field is as given"


def test_no_declaration_writes_the_record_as_given():
    for r in (Redaction(), Redaction.declared(), Redaction.declared([], None)):
        assert not r.active
        stored, stored_dec = r.record(ENVELOPE, DECISION)
        assert stored is ENVELOPE and stored_dec is DECISION

# The hash's literal in both languages is row 163's cell (python/hiitl/core/tests/test_row163.py), since its key
