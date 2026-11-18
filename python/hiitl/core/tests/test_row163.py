"""Row 163(c) (HTL-22): the gateway's value hash is HMAC-SHA256 under the store's key.

Ruled by Trevor 2026-11-05, on HTL-20: "(c) the gateway's hash is keyed (HMAC)". The sentence it answers is hiitl's
security requirement "Redacted fields are irreversible": with no key, anyone holding the record can test a guessed value
from a small set against its hash. The key is RFC 2104's L bytes, SHA-256's digest size. The literal below is restated
in typescript/packages/core/tests/unit/row163.test.ts. These are the row's test design cells 8-9.
"""

from __future__ import annotations

import hashlib

import pytest

from hiitl.core.canonical import canonical_json
from hiitl.core.redaction import HASH_PREFIX, KEY_BYTES, MARKER, Redaction, value_hash

KEY = bytes(range(KEY_BYTES))
OTHER_KEY = bytes(reversed(KEY))
# A value with a float, a non-ASCII character and keys out of order: what canonical form has to settle
VALUE = {"iban": "GB29NWBK60161331926819", "amount": 1250.5, "memo": "Café №7"}
LITERAL = "hmac-sha256:bf5639138d2279700db8d774d7155aa3a0202b1eaefd1a5203b57f30d713682e"

GATEWAY = Redaction.declared(["parameters.card"], {"approve_refund": ["order_id"]})
CALL = {"action": "approve_refund", "parameters": {"order_id": "ord_8812", "amount": 120, "approved": True,
                                                   "card": "4111 1111 1111 1111"}}


def test_the_value_hash_is_keyed():
    stored, _ = GATEWAY.keyed(KEY).record(CALL, {})
    again, _ = GATEWAY.keyed(KEY).record(CALL, {})
    other, _ = GATEWAY.keyed(OTHER_KEY).record(CALL, {})
    p = stored["parameters"]
    assert p["order_id"] == "ord_8812" and p["card"] == MARKER, "recorded as given; declared"
    assert p["amount"] == value_hash(120, KEY) and p["amount"].startswith(HASH_PREFIX)
    assert stored == again, "one key, one hash: a record's hashes compare within its store"
    assert other["parameters"]["amount"] != p["amount"], "another key, another hash"

    # The guess a reader without the key would make: hash each candidate of a small set, unkeyed
    for name, candidates in (("amount", range(0, 1000)), ("approved", (True, False))):
        unkeyed = {hashlib.sha256(canonical_json(c).encode()).hexdigest() for c in candidates}
        assert not any(h in p[name] for h in unkeyed), f"{name}: no unkeyed hash of the value is in the record"


def test_one_literal_in_both_languages():
    assert value_hash(VALUE, KEY) == LITERAL


def test_a_hash_without_the_stores_key_is_refused():
    with pytest.raises(ValueError, match="key"):
        GATEWAY.record(CALL, {})
    for short in (b"", KEY[:-1]):
        with pytest.raises(ValueError, match=str(KEY_BYTES)):
            GATEWAY.keyed(short)
    with pytest.raises(ValueError):
        GATEWAY.keyed(KEY.hex())
    assert Redaction.declared(["parameters.card"]).record(CALL, {})[0]["parameters"]["card"] == MARKER, \
        "a declaration that hashes nothing needs no key"


def test_the_key_is_never_in_the_declarations_text():
    keyed = GATEWAY.keyed(KEY)
    assert KEY.hex() not in repr(keyed) and str(KEY) not in repr(keyed)
    assert keyed == GATEWAY, "the key is the store's, not part of what the store declares"


def test_a_joined_declaration_redacts_each_path_either_declares():
    sdk = Redaction.declared(["parameters.card"])
    joined = sdk.joined(["target.email", "parameters.card"], source="manual_redact_fields")
    assert joined.fields == (("parameters", "card"), ("target", "email")), "each path once, the store's first"
    env, _ = joined.record({**CALL, "target": {"email": "dana@example.com"}}, {})
    assert (env["parameters"]["card"], env["target"]["email"]) == (MARKER, MARKER)
    assert sdk.joined([], source="manual_redact_fields") is sdk
    with pytest.raises(ValueError, match="manual_redact_fields"):
        sdk.joined(["org_id"], source="manual_redact_fields")
