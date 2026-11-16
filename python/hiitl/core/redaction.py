"""What a store writes: the record with each declared field's value replaced (HTL-20 row 139, 2026-11-04).

The ruling: "a declared redaction list applies before every write in both stores; the gateway records argument names
with hashed values unless a field is declared". It rests on "Sensitive parameters must be redactable. Never log raw
secrets", "ECP evaluates declared facts, not raw content" and "No prompt logging by default", three of hiitl's
engineering rules. The contract is event_format.md §Redaction.

A store calls `Redaction.record` on the envelope and decision it is about to write. It does so after the envelope's
signature and `envelope_hash` are computed over the envelope as sent, and before the record's `content_hash`, which
is over the record as stored. A field is redacted because it is declared. Nothing here reads a field's name or
content to decide ("No content detection").

The gateway's hash of an argument it records by name is HMAC-SHA256 under a key the gateway's store makes at its first
start and keeps beside itself, never synced and never in a record (HTL-22 row 163(c), ruled 2026-11-05): an unkeyed hash
lets the record's reader recover a value drawn from a small set by hashing each candidate, and "Redacted fields are
irreversible" (hiitl's security requirements). The SDK store unions the org's declaration, which the hybrid policy pull
carries, with its own (row 163(a)).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Tuple

from hiitl.core.canonical import canonical_json

MARKER = "[REDACTED]"
HASH_PREFIX = "hmac-sha256:"

# The value hash's key length: the hash's own output length, the least RFC 2104 §3 allows without "strongly
# discouraged" ("less than L bytes ... is strongly discouraged as it would decrease the security strength")
KEY_BYTES = hashlib.sha256().digest_size

# The member of the org's declaration that names its fields (PUT /v1/redaction-policy; the hybrid policy pull)
ORG_FIELDS = "manual_redact_fields"

# decision_response.md's remediation details that state the call's value at an envelope field, by remediation type:
# the member that holds the field's path, and the member that holds the value found there
VALUE_AT_FIELD = {
    "threshold": ("field", "current_value"),
    "field_restriction": ("field_ref", "blocked_fields"),
}

_SPEC = "event_format.md §Redaction"


def value_hash(value: Any, key: bytes) -> str:
    """How the gateway records an argument it was not told to record: HMAC-SHA256 under the store's key, over the
    value's canonical form."""
    return HASH_PREFIX + hmac.new(key, canonical_json(value).encode("utf-8"), hashlib.sha256).hexdigest()


def _path(entry: Any, source: str) -> Tuple[str, ...]:
    segments = tuple(entry.split(".")) if isinstance(entry, str) else ()
    if len(segments) < 2 or not all(segments):
        raise ValueError(
            f"{source} entry {entry!r} is not a declared field. A declared field is a member of one of the envelope's "
            f"objects, written as a dotted path such as 'parameters.account_number' or 'target.email'; a top-level "
            f"field is how the record is found, and is never redacted ({_SPEC}).")
    return segments


def _replace(node: Any, segments: Tuple[str, ...], treat: Callable[[Any], Any]) -> None:
    """Replace the value at `segments` under `node` with `treat(value)`, through every item of an array met."""
    if isinstance(node, list):
        for item in node:
            _replace(item, segments, treat)
        return
    if not isinstance(node, dict) or segments[0] not in node:
        return
    if len(segments) == 1:
        node[segments[0]] = treat(node[segments[0]])
    else:
        _replace(node[segments[0]], segments[1:], treat)


def _holds(node: Any, segments: Tuple[str, ...]) -> bool:
    """Whether the envelope holds a value at `segments` under `node`, walked as `_replace` walks it: through objects,
    and through every item of an array met (any item holding one holds it)."""
    if isinstance(node, list):
        return any(_holds(item, segments) for item in node)
    if not isinstance(node, dict) or segments[0] not in node:
        return False
    return len(segments) == 1 or _holds(node[segments[0]], segments[1:])


def _remediations(node: Any) -> Iterator[dict]:
    """Every remediation the decision carries, wherever a `remediation` member sits."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "remediation" and isinstance(value, dict):
                yield value
            yield from _remediations(value)
    elif isinstance(node, list):
        for item in node:
            yield from _remediations(item)


def _redacted(_value: Any) -> str:
    return MARKER


@dataclass(frozen=True)
class Redaction:
    """A store's declaration: the fields it redacts, and, at the gateway, the parameters it records as given.

    `recorded_parameters` is None when parameters are recorded as given (the SDK's default). When it is a mapping
    (`{action: [parameter names]}`), every other member of `parameters` is recorded as `value_hash(value, key)`, under
    the store's `key` (`keyed`)."""

    fields: Tuple[Tuple[str, ...], ...] = ()
    recorded_parameters: Optional[Mapping[str, Tuple[str, ...]]] = field(default=None)
    key: Optional[bytes] = field(default=None, repr=False, compare=False)

    @classmethod
    def declared(cls, fields: Optional[Iterable[str]] = None,
                 recorded_parameters: Optional[Mapping[str, Iterable[str]]] = None, *,
                 source: str = "redact_fields") -> "Redaction":
        """Validate a declaration. Raises ValueError, naming the entry, for a path that is not a declared field."""
        if isinstance(fields, str):
            raise ValueError(f"{source} is a list of field paths, got the string {fields!r} ({_SPEC}).")
        paths = tuple(_path(entry, source) for entry in (fields or ()))
        recorded = None
        if recorded_parameters is not None:
            if not isinstance(recorded_parameters, Mapping):
                raise ValueError(f"recorded_parameters maps an action to the parameter names recorded as given, "
                                 f"got {type(recorded_parameters).__name__} ({_SPEC}).")
            recorded = {}
            for action, names in recorded_parameters.items():
                if isinstance(names, str) or not all(isinstance(n, str) and n for n in (names or ())):
                    raise ValueError(f"recorded_parameters[{action!r}] is a list of parameter names, got {names!r} "
                                     f"({_SPEC}).")
                recorded[action] = tuple(names or ())
        return cls(fields=paths, recorded_parameters=recorded)

    def keyed(self, key: bytes) -> "Redaction":
        """This declaration under the store's value-hash key."""
        if not isinstance(key, bytes) or len(key) < KEY_BYTES:
            raise ValueError(f"The value hash's key is {KEY_BYTES} bytes or more (RFC 2104 §3; {_SPEC}).")
        return replace(self, key=key)

    def joined(self, fields: Iterable[str], *, source: str) -> "Redaction":
        """This declaration with `fields` added: the store redacts each path either declares (row 163(a))."""
        if isinstance(fields, str):
            raise ValueError(f"{source} is a list of field paths, got the string {fields!r} ({_SPEC}).")
        added = tuple(path for path in (_path(entry, source) for entry in fields) if path not in self.fields)
        return replace(self, fields=self.fields + tuple(dict.fromkeys(added))) if added else self

    @property
    def active(self) -> bool:
        return bool(self.fields) or self.recorded_parameters is not None

    def _hash(self, value: Any) -> str:
        return value_hash(value, self.key)

    def _treatment(self, path: str, action: Optional[str]) -> Optional[Callable[[Any], Any]]:
        """How a value found at `path` is recorded: a declared field's (the path is one, lies under one, or holds
        one), a hashed parameter's, or as given (None)."""
        segments = tuple(path.split("."))
        for declared in self.fields:
            n = min(len(declared), len(segments))
            if declared[:n] == segments[:n]:
                return _redacted
        if self.recorded_parameters is not None and segments[0] == "parameters" and (
                len(segments) == 1 or segments[1] not in self.recorded_parameters.get(action, ())):
            return self._hash
        return None

    def records_as_given(self, path: str, action: Optional[str]) -> bool:
        """Whether the store records the value found at `path` as given: not a declared field's, and not, at the
        gateway, a parameter recorded as its hash (telemetry_schema.md "Numeric Parameter Stats", row 216)."""
        return self._treatment(path, action) is None

    def absent(self, envelope: Mapping[str, Any]) -> list:
        """The declared fields at which `envelope` holds no value, in the declaration's order (the store's own, then
        the org's as joined): what the record's `redaction` member names, `{"absent": [...]}` (row 163 (e): "named in
        the record, never skipped silently")."""
        return [".".join(path) for path in self.fields if not _holds(envelope, path)]

    def record(self, envelope: Mapping[str, Any], decision: Mapping[str, Any]) -> Tuple[Any, Any]:
        """The envelope and decision as stored. The inputs are never changed."""
        if not self.active:
            return envelope, decision
        if self.recorded_parameters is not None and self.key is None:
            raise ValueError(f"recorded_parameters hashes each other parameter under the store's key, and this "
                             f"declaration has none: key it with the store's (Redaction.keyed; {_SPEC}).")
        env, dec = copy.deepcopy(dict(envelope)), copy.deepcopy(dict(decision))
        for declared in self.fields:
            _replace(env, declared, _redacted)
        action = env.get("action")
        if self.recorded_parameters is not None and isinstance(env.get("parameters"), dict):
            recorded = self.recorded_parameters.get(action, ())
            env["parameters"] = {name: value if name in recorded or value == MARKER else self._hash(value)
                                 for name, value in env["parameters"].items()}
        for remediation in _remediations(dec):
            members = VALUE_AT_FIELD.get(remediation.get("type"))
            details = remediation.get("details")
            if not members or not isinstance(details, dict) or not isinstance(details.get(members[0]), str):
                continue
            treat = self._treatment(details[members[0]], action)
            if treat is not None and members[1] in details:
                details[members[1]] = treat(details[members[1]])
        return env, dec

