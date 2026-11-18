"""The one held-number admission rule (sync_engine.md#numeric-domain)."""
from __future__ import annotations
import json
import math
from collections.abc import Mapping
from typing import Any
from pydantic import BaseModel
from contextlib import contextmanager
from contextvars import ContextVar

# The declared binary64 interoperable magnitude; SDKs read this helper, not a copied bound.
NUMERIC_BOUND = 2 ** 53
_ADMITTED = ContextVar('hiitl_numbers_admitted', default=False)


def numbers_are_admitted() -> bool:
    return _ADMITTED.get()


def copy_supplied_input(value):
    """Own the JSON containers before callbacks can change the caller's copy."""
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    if isinstance(value, Mapping):
        return {key: copy_supplied_input(child) for key, child in value.items()}
    if isinstance(value, list):
        return [copy_supplied_input(child) for child in value]
    if isinstance(value, tuple):
        return tuple(copy_supplied_input(child) for child in value)
    return value


@contextmanager
def admitted_numbers():
    """An owned reader/producer consuming input this synchronous call admitted.

    This scope never spans a transport, user callback, or another public call.
    Externally supplied mutable models are admitted afresh at each entry.
    """
    token = _ADMITTED.set(True)
    try:
        yield
    finally:
        _ADMITTED.reset(token)

def numeric_declaration(shape: dict, path: tuple[str | int, ...], value=None) -> dict | None:
    """Read owning fields and subtype declarations only when an input is refused."""
    def member(current, key):
        if isinstance(current, BaseModel):
            return getattr(current, key, None)
        if isinstance(current, Mapping):
            return current.get(key)
        if isinstance(current, (list, tuple)) and isinstance(key, int) and key < len(current):
            return current[key]
        return None

    def matches(current, condition):
        if 'const' in condition and current != condition['const']:
            return False
        keys = current.model_fields_set if isinstance(current, BaseModel) else current if isinstance(current, Mapping) else ()
        if any(key not in keys for key in condition.get('required', [])):
            return False
        return all(key not in keys or matches(member(current, key), child)
                   for key, child in condition.get('properties', {}).items())

    def branch_fits(node, current):
        if not isinstance(node, dict):
            return node is not False
        if '$ref' in node:
            target = shape
            for part in node['$ref'].removeprefix('#/').split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
            return branch_fits(target, current)
        if node.get('type') == 'object':
            if not isinstance(current, (Mapping, BaseModel)):
                return False
            keys = current.model_fields_set if isinstance(current, BaseModel) else current.keys()
            if node.get('additionalProperties') is False and set(keys) - node.get('properties', {}).keys():
                return False
        elif node.get('type') == 'array' and not isinstance(current, (list, tuple)):
            return False
        elif node.get('type') == 'null' and current is not None:
            return False
        elif node.get('type') == 'string' and not isinstance(current, str):
            return False
        elif node.get('type') == 'boolean' and not isinstance(current, bool):
            return False
        elif node.get('type') in ('integer', 'number') and (isinstance(current, bool) or not isinstance(current, (int, float))):
            return False
        return matches(current, node)

    def read(node, remaining, current):
        if node is False:
            return {'forbidden': True}
        if not isinstance(node, dict):
            return None
        if '$ref' in node:
            target = shape
            for part in node['$ref'].removeprefix('#/').split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
            return read(target, remaining, current)
        for branch in node.get('allOf', []):
            found = read(branch, remaining, current)
            if found is not None:
                return found
        if 'if' in node:
            chosen = node.get('then' if matches(current, node['if']) else 'else', {})
            found = read(chosen, remaining, current)
            if found is not None:
                return found
        branches = node.get('anyOf', node.get('oneOf', []))
        branches = [branch for branch in branches if branch_fits(branch, current)] or branches
        choices = [found for branch in branches
                   if (found := read(branch, remaining, current)) is not None]
        if choices:
            # integer | number admits fractions: report the declared number domain.
            found = next((choice for choice in choices if choice.get('type') == 'number'),
                         next((choice for choice in choices if choice.get('type') == 'integer'),
                              next((choice for choice in choices if choice.get('type') not in (None, 'null')), choices[0])))
            return {**found, **{k: v for k, v in node.items() if k in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'ge', 'le', 'gt', 'lt')}}
        if not remaining:
            return node if 'type' in node else None
        key, *rest = remaining
        child = node.get('items', {}) if isinstance(key, int) else node.get('properties', {}).get(key, node.get('additionalProperties', {}))
        return read(child, rest, member(current, key))
    return read(shape, path, value)


class NumericDomainError(ValueError):
    def __init__(self, path: tuple[str | int, ...], declaration: dict | None = None):
        self.path = path
        location = '<root>' + ''.join('[' + json.dumps(p, ensure_ascii=False) + ']' for p in path)
        if declaration and declaration.get('forbidden'):
            message = f'Numeric value at {location} is outside the shared domain; this member is not declared. Remove the undeclared member.'
        elif declaration and declaration.get('type') not in ('integer', 'number'):
            kind = declaration['type']
            message = f'Numeric value at {location} is outside the shared domain; this member requires a JSON {kind}. Supply a value matching its declaration.'
        elif declaration:
            kind = declaration['type']
            bounds = []
            for key, relation in (('minimum', '>='), ('maximum', '<='), ('exclusiveMinimum', '>'), ('exclusiveMaximum', '<'),
                                  ('ge', '>='), ('le', '<='), ('gt', '>'), ('lt', '<')):
                if key in declaration:
                    bounds.append(f'{relation} {declaration[key]:g}')
            limits = (' and ' + ', '.join(bounds)) if bounds else ''
            message = f'Numeric value at {location} must be a JSON {kind}, finite with magnitude below {NUMERIC_BOUND}{limits}; supply a JSON {kind} within this declared range.'
        else:
            message = f'Numeric value at {location} must be finite with magnitude below {NUMERIC_BOUND}; pass the value as text instead.'
        super().__init__(message)

def validate_numeric_domain(value: Any, path: tuple[str | int, ...] = (), *, shape: dict | None = None) -> None:
    """Check every supplied number without coercing, filtering or copying JSON data."""
    if numbers_are_admitted():
        return
    try:
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            # Check Python's integer while it is exact; float(value) may overflow or round.
            if abs(value) >= NUMERIC_BOUND:
                raise NumericDomainError(path)
        elif isinstance(value, float):
            if not math.isfinite(value) or abs(value) >= NUMERIC_BOUND:
                raise NumericDomainError(path)
        elif isinstance(value, BaseModel):
            for key in value.model_fields_set - (value.model_extra or {}).keys():
                validate_numeric_domain(getattr(value, key), (*path, key))
            for key, member in (value.model_extra or {}).items():
                validate_numeric_domain(member, (*path, key))
        elif isinstance(value, Mapping):
            for key, member in value.items():
                validate_numeric_domain(member, (*path, key))
        elif isinstance(value, (list, tuple)):
            for index, member in enumerate(value):
                validate_numeric_domain(member, (*path, index))
    except NumericDomainError as error:
        declaration = numeric_declaration(shape, error.path[len(path):], value) if shape else None
        if declaration:
            raise NumericDomainError(error.path, declaration) from error
        raise
