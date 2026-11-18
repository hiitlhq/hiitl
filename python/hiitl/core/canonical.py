"""One canonical serialisation for the content hashes (docs/specs/sync_engine.md §2.1 and §2.2; Trevor, 2026-10-10): the
JSON Canonicalization Scheme, RFC 8785 — the same bytes as the TypeScript `canonicalJson` (@hiitl/core), proved by
the conformance cases `tests/conformance/audit_hash/` and `tests/conformance/policy_hash/`.

    audit record:            content_hash = SHA-256( "{event_id}:{C(envelope)}:{C(decision)}" )   UTF-8, lowercase hex
    policy set, route config: content_hash = SHA-256( C(content) )                                 UTF-8, lowercase hex
    envelope:                 signature     = HMAC-SHA256( secret, S(envelope) )                    UTF-8, lowercase hex
                              envelope_hash = SHA-256( S(envelope) )

S is the envelope's signed form (the security architecture §1.3; row 127, Trevor 2026-11-04: "one canonical form
everywhere"), proved by `tests/conformance/envelope_signature/`.

Read by every writer and every checker: the SDKs' local audit, the server's upload check, the hosted audit write; the
policy and route create paths, onboarding's seed, the hosted integrity check and both SDKs' download check; both SDKs'
envelope build and local verification, the hosted verification and every envelope_hash.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from typing import Any


def _number(x: float) -> str:
    """ECMAScript Number::toString (RFC 8785 §3.2.2.3): the shortest round-trip digits, placed by the spec's rules."""
    if isinstance(x, bool):
        raise TypeError("a boolean is not a number")
    f = float(x)
    if not math.isfinite(f):
        raise ValueError(f"{x!r} has no JSON form")
    if f == 0:
        return "0"                                         # -0 too
    sign, f = ("-", -f) if f < 0 else ("", f)
    r = repr(f)                                            # Python's repr is the shortest round-trip form
    mant, _, exp = r.partition("e")
    whole, _, frac = mant.partition(".")
    if frac == "0":
        frac = ""
    digits = (whole + frac).lstrip("0")
    n = (int(exp) if exp else 0) + (len(whole) if whole != "0" else -(len(frac) - len(frac.lstrip("0"))))
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        out = (digits if k == 1 else digits[0] + "." + digits[1:]) + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + out


def canonical_json(value: Any) -> str:
    """Compute unchanged RFC8785 C; supplied-input admission is a separate call."""
    return _canonical_json(value)


def _canonical_json(value: Any) -> str:
    """RFC 8785: keys sorted by UTF-16 code units, no whitespace, minimal string escapes, ECMAScript numbers."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _canonical_json(value[k]) for k in keys) + "}"
    raise TypeError(f"{type(value).__name__} is not a JSON value; dump it in JSON mode first")


def canonical_hash(value: Any) -> str:
    """A policy set's or route config's content hash: SHA-256 over its canonical form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# The members an audit record carries beyond its envelope and decision, each a further term of its content hash, in
# the hash's order (event_format.md `content_hash`; row 191, ruled 2026-11-06). The one copy: the SDK's store and the
# hosted service's reads and ingest read it here. Mirrors canonical.ts `AUDIT_FURTHER`.
AUDIT_FURTHER = ("execution_result", "redaction", "review")


def audit_content_hash(event_id: str, envelope: Any, decision: Any, **further: Any) -> str:
    """The audit record's content hash over its JSON values exactly as uploaded.

    Each member of `AUDIT_FURTHER` the record carries joins as a further term, in that order, `further` keyed by the
    record's own member names. A member is a term because the record carries it, whatever its value; a record carrying
    none hashes over the first three. A name `AUDIT_FURTHER` does not hold is refused: it would hash without its
    term, unseen.
    """
    return _audit_content_hash(event_id, envelope, decision, **further)


def _audit_content_hash(event_id: str, envelope: Any, decision: Any, **further: Any) -> str:
    """The shared C computation for both new admitted records and stored-record verification."""
    unnamed = sorted(set(further) - set(AUDIT_FURTHER))
    if unnamed:
        raise TypeError(f"audit_content_hash takes no term {', '.join(unnamed)}; a record's further terms are "
                        f"{', '.join(AUDIT_FURTHER)}")
    terms = [event_id, _canonical_json(envelope), _canonical_json(decision)]
    terms += [_canonical_json(further[member]) for member in AUDIT_FURTHER if member in further]
    return hashlib.sha256(":".join(terms).encode("utf-8")).hexdigest()


def audit_hash_matches(expected: str, event_id: str, envelope: Any, decision: Any, **further: Any) -> bool:
    """Verify an existing record as written; writers admit supplied inputs before hashing."""
    return hmac.compare_digest(expected, _audit_content_hash(event_id, envelope, decision, **further))


def envelope_signed_form(envelope: dict) -> str:
    """The envelope's signed form: the canonical JSON of the envelope without its `signature`, and without a principal
    the hosted service verified — the service's addition after the caller signed, marked by its own `verified_by`.
    The signature and `envelope_hash` are both over it, so the record alone re-derives each."""
    principal = envelope.get("principal")
    added = isinstance(principal, dict) and principal.get("verified_by") == "hosted"
    return canonical_json({k: v for k, v in envelope.items() if k != "signature" and not (added and k == "principal")})


def envelope_signature(secret: str, envelope: dict) -> str:
    """HMAC-SHA256 over the signed form, under the key's signing secret."""
    return hmac.new(secret.encode("utf-8"), envelope_signed_form(envelope).encode("utf-8"), hashlib.sha256).hexdigest()


def envelope_verifies(secret: str, envelope: dict) -> bool:
    """Whether the envelope's `signature` is the signature of its signed form (a constant-time compare)."""
    return hmac.compare_digest(envelope_signature(secret, envelope), str(envelope.get("signature") or ""))


def envelope_hash(envelope: dict) -> str:
    """The decision's envelope_hash (Tier 1): SHA-256 over the signed form; the caller recomputes it from what it sent."""
    return hashlib.sha256(envelope_signed_form(envelope).encode("utf-8")).hexdigest()
