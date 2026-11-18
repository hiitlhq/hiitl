"""Read supplied JSON kinds before the existing models coerce or default them.

The model declarations supply structure; independent canonical-source cases hold
those declarations to the format. Omission is not a supplied null. No input is
modified, and open values remain data.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from contextlib import contextmanager
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ValidationError, ValidationInfo, TypeAdapter
from pydantic_core import PydanticCustomError

from hiitl.core.date_time import DateTime

_DATE_TIME = TypeAdapter(DateTime)

from hiitl.core.numeric_domain import NumericDomainError, validate_numeric_domain, admitted_numbers


def _integer(value, info: ValidationInfo):
    validate_numeric_domain(value, shape={'type': 'integer'})
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not value.is_integer())):
        raise ValueError(f'{info.field_name or "<root>"} must be an integer JSON number; booleans and numeric text are not coerced')
    return value


def _number(value, info: ValidationInfo):
    validate_numeric_domain(value, shape={'type': 'number'})
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{info.field_name or "<root>"} must be a JSON number; booleans and numeric text are not coerced')
    return value


JsonInteger = Annotated[int, BeforeValidator(_integer)]
JsonNumber = Annotated[float, BeforeValidator(_number)]


def supplied(value: Any) -> Any:
    """Project owned models without manufacturing their unset optional members."""
    if isinstance(value, BaseModel):
        return {key: supplied(getattr(value, key)) for key in value.model_fields_set} | {
            key: supplied(child) for key, child in (value.model_extra or {}).items()
        }
    if isinstance(value, Mapping):
        return {key: supplied(child) for key, child in value.items()}
    if isinstance(value, list):
        return [supplied(child) for child in value]
    return value


@lru_cache
def model_shape(model: type[BaseModel]) -> dict:
    return model.model_json_schema(by_alias=False)


def input_errors(value: Any, shape: dict, *, partial=False, path=(), check_null=True, numbers_only=False) -> list[dict]:
    """Validate supplied kinds/null, closure and declared scalar/array constraints.

    Optional null branches in a Pydantic schema represent its omission sentinel;
    the three input formats write optional members by omission. An unconstrained
    branch is still unconstrained, including null. Partial applies only to the
    root required list of a shipped-test envelope, never its present children.
    """
    errors = []

    def error(at, current, message, kind='value_error'):
        if kind == 'extra_forbidden':
            name = ''.join(f'[{part}]' if isinstance(part, int) else ('.' if index else '') + part
                           for index, part in enumerate(at)) or '<root>'
            return {'type': PydanticCustomError(kind, f'Extra inputs are not permitted at {name}'),
                    'loc': at, 'input': current}
        name = '.'.join(map(str, at)) or '<root>'
        cause = ValueError(f'{name} {message}')
        return {'type': kind, 'loc': at, 'input': current, 'ctx': {'error': cause}}

    def visit(current, node, at):
        if current is None and (numbers_only or not check_null):
            return []
        if 'x-shape-after' in node:
            # An after-validator's rule (pydantic mode='after', zod refine) reads a node whose own members hold
            remaining = {key: child for key, child in node.items() if key != 'x-shape-after'}
            found = visit(current, remaining, at)
            detail = None if found else node['x-shape-after'](current)
            return found or ([error(at, current, detail)] if detail else [])
        if 'x-shape-refusal' in node:
            detail = node['x-shape-refusal'](current)
            remaining = {key: child for key, child in node.items() if key != 'x-shape-refusal'}
            found = visit(current, remaining, at)
            return ([error(at, current, detail)] if detail else []) + found
        if '$ref' in node:
            target = shape
            for segment in node['$ref'].removeprefix('#/').split('/'):
                target = target[segment.replace('~1', '/').replace('~0', '~')]
            return visit(current, target, at)
        branches = node.get('anyOf', node.get('oneOf'))
        if branches is not None:
            choices = [branch for branch in branches if branch.get('type') != 'null']
            def accepts_kind(branch):
                if '$ref' in branch:
                    resolved = shape
                    for part in branch['$ref'].removeprefix('#/').split('/'):
                        resolved = resolved[part.replace('~1', '/').replace('~0', '~')]
                    return accepts_kind(resolved)
                kind = branch.get('type')
                return kind is None or {
                    'object': isinstance(current, Mapping), 'array': isinstance(current, list),
                    'string': isinstance(current, (str, datetime)), 'boolean': isinstance(current, bool),
                    'integer': isinstance(current, (int, float)) and not isinstance(current, bool),
                    'number': isinstance(current, (int, float)) and not isinstance(current, bool),
                }.get(kind, False)
            matching = [branch for branch in choices if accepts_kind(branch)]
            siblings = {key: child for key, child in node.items() if key not in ('anyOf', 'oneOf')}
            attempts = [visit(current, {**branch, **siblings}, at) for branch in (matching or choices)]
            if any(not attempt for attempt in attempts):
                return []
            # Structural union errors name the actual instance, not Pydantic's
            # generated union-arm label. Prefer the arm closest to the data.
            return min(attempts, key=lambda attempt: (sum(e['type'] == 'extra_forbidden' for e in attempt),
                                                     len(attempt))) if attempts else []
        combined = [item for branch in node.get('allOf', []) for item in visit(current, branch, at)]
        if 'if' in node:
            test = node['if']
            matches = isinstance(current, Mapping) and all(key in current for key in test.get('required', []))
            matches = matches and all(key in current and current[key] == child.get('const')
                                      for key, child in test.get('properties', {}).items())
            branch = node.get('then' if matches else 'else', {})
            combined.extend(visit(current, branch, at))
        kind = node.get('type')
        if numbers_only and kind not in ('number', 'integer'):
            # Decision's scope here is its numeric declarations only: do not
            # introduce unrelated type, null, closure or requiredness changes.
            if isinstance(current, Mapping):
                properties = node.get('properties', {})
                additional = node.get('additionalProperties', {})
                for key, child in current.items():
                    constraint = properties.get(key, additional)
                    if isinstance(constraint, dict):
                        combined.extend(visit(child, constraint, (*at, key)))
            elif isinstance(current, list) and 'items' in node:
                combined.extend(item for index, child in enumerate(current)
                                for item in visit(child, node['items'], (*at, index)))
            return combined
        if kind is None:
            if isinstance(current, Mapping):
                combined.extend(item for key, child in node.get('properties', {}).items() if key in current
                                for item in visit(current[key], child, (*at, key)))
            return combined
        if current is None:
            return [error(at, current, 'must not be null; the declared input type excludes null')]
        numeric = isinstance(current, (int, float)) and not isinstance(current, bool)
        checks = {
            'object': isinstance(current, Mapping), 'array': isinstance(current, list),
            'string': isinstance(current, str) or (node.get('format') == 'date-time' and isinstance(current, datetime)),
            'boolean': isinstance(current, bool), 'number': numeric,
            'integer': numeric and (isinstance(current, int) or (math.isfinite(current) and current.is_integer())),
        }
        if not checks.get(kind, False):
            return [error(at, current, f'must have JSON type {kind}; values are not coerced')]
        found = combined
        if node.get('format') == 'date-time':
            try:
                _DATE_TIME.validate_python(current, context={"field_name": str(at[-1]) if at else "<root>"})
            except ValidationError as cause:
                found.append(error(at, current, str(cause)))
        if kind == 'object':
            properties = node.get('properties', {})
            additional = node.get('additionalProperties', {})
            if not (partial and at == path):
                for key in node.get('required', []):
                    if key not in current:
                        parent = '.'.join(map(str, at)) or '<root>'
                        found.append({'type': PydanticCustomError('missing', f'Field required in {parent}'),
                                      'loc': (*at, key), 'input': current})
            for key, child in current.items():
                if key in properties:
                    found.extend(visit(child, properties[key], (*at, key)))
                elif additional is False:
                    found.append(error((*at, key), child, 'is not defined', 'extra_forbidden'))
                elif isinstance(additional, dict):
                    found.extend(visit(child, additional, (*at, key)))
        elif kind == 'array':
            for index, child in enumerate(current):
                found.extend(visit(child, node.get('items', {}), (*at, index)))
            for keyword, compare in (('minItems', lambda a, b: a < b), ('maxItems', lambda a, b: a > b)):
                if keyword in node and compare(len(current), node[keyword]):
                    found.append(error(at, current, f'violates declared {keyword} {node[keyword]}'))
        elif numeric:
            for keyword, compare in (('minimum', lambda a, b: a < b), ('maximum', lambda a, b: a > b),
                                     ('exclusiveMinimum', lambda a, b: a <= b), ('exclusiveMaximum', lambda a, b: a >= b),
                                     # Pydantic retains Field bounds on a numeric union under these metadata names.
                                     ('ge', lambda a, b: a < b), ('le', lambda a, b: a > b),
                                     ('gt', lambda a, b: a <= b), ('lt', lambda a, b: a >= b)):
                if keyword in node and compare(current, node[keyword]):
                    found.append(error(at, current, f'violates declared {keyword} {node[keyword]}'))
        elif isinstance(current, str):
            for keyword, compare in (('minLength', lambda a, b: a < b), ('maxLength', lambda a, b: a > b)):
                if keyword in node and compare(len(current), node[keyword]):
                    found.append(error(at, current, f'violates declared {keyword} {node[keyword]}'))
            if 'pattern' in node and re.search(node['pattern'], current) is None:
                found.append(error(at, current, f'does not match its declared pattern {node["pattern"]}'))
        if 'enum' in node and current not in node['enum']:
            found.append(error(at, current, f'must be one of {node["enum"]}'))
        if 'const' in node and current != node['const']:
            found.append(error(at, current, f'must be {node["const"]!r}'))
        return found

    errors.extend(visit(supplied(value), shape, path))
    return errors


def validate_input(model: type[BaseModel], value: Any, *, partial=False, path=(), shape=None, check_null=True, numbers_only=False) -> None:
    shape = model_shape(model) if shape is None else shape
    validate_numbers(model.__name__, value, path=path, shape=shape)
    errors = input_errors(value, shape,
                          partial=partial, path=path, check_null=check_null, numbers_only=numbers_only)
    if errors:
        raise ValidationError.from_exception_data(model.__name__, errors)


def validate_numbers(title: str, value: Any, *, path=(), shape=None) -> None:
    try:
        validate_numeric_domain(value, path, shape=shape)
    except NumericDomainError as error:
        raise ValidationError.from_exception_data(title, [
            {'type': 'value_error', 'loc': error.path, 'input': value, 'ctx': {'error': error}},
        ]) from error


@contextmanager
def number_input(model, value, *, shape=None):
    """Admit a whole supplied model before its child readers project/default it."""
    validate_numbers(model.__name__, value, shape=model_shape(model) if shape is None else shape)
    with admitted_numbers():
        yield

