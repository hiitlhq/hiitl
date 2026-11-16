"""Reserved policy values: policy_format.md#reserved-policy-values (88579bbd).

This reader admits existing forms; it never resolves a new position. A caller's
Envelope is not a policy and does not pass this reader.
"""
from __future__ import annotations
import json
from collections.abc import Mapping
from pydantic import BaseModel, ValidationError

MARKERS = frozenset(('$field', '$declared', '$uncalibrated'))


def validate_policy_values(value, *, role='policy', path=()):
    if isinstance(value, BaseModel):
        value = {k: getattr(value, k) for k in value.model_fields_set}
    if isinstance(value, Mapping):
        keys = MARKERS.intersection(value)
        if keys:
            allowed = ({'$field', '$declared', '$uncalibrated'} if role == 'operand'
                       else {'$declared', '$uncalibrated'} if role == 'placeholder'
                       else {'$declared'} if role == 'reference'
                       else {'$uncalibrated'} if role == 'bound' else set())
            if len(value) != 1 or not keys.issubset(allowed):
                location = '<root>' + ''.join('[' + json.dumps(p) + ']' for p in path)
                cause = ValueError(f'Reserved policy marker at {location}: {", ".join(sorted(keys))} must be the sole key at a position that reads that form. Remove sibling keys or move the form to a supported position.')
                raise ValidationError.from_exception_data('Policy values', [
                    {'type': 'value_error', 'loc': at, 'input': value, 'ctx': {'error': cause}}
                    for at in [path, *((*path, key) for key in value)]
                ])
            key = next(iter(keys))
            validate_policy_values(value[key], role='reference' if key == '$field' else 'data', path=(*path, key))
            return
        for key, child in value.items():
            next_role = 'data'
            if role == 'policy' and key == 'rules': next_role = 'rules'
            elif role == 'policy' and key == 'metadata': next_role = 'metadata'
            elif role == 'metadata' and key == 'rate_limits': next_role = 'windows'
            elif role == 'rule' and key == 'metadata': next_role = 'rule_metadata'
            elif role == 'rule_metadata' and key == 'compiled_from': next_role = 'provenance'
            elif role == 'provenance' and key == 'entry': next_role = 'window'
            elif role == 'rule' and key == 'conditions': next_role = 'condition'
            elif role == 'rule' and key == 'rate_limit': next_role = 'window'
            elif role == 'window' and key in ('limit', 'window_seconds'): next_role = 'bound'
            elif role == 'condition' and key in ('all_of', 'any_of', 'none_of'): next_role = 'conditions'
            elif role == 'condition' and key == 'value': next_role = 'operand'
            elif role in ('operand', 'placeholder'): next_role = 'placeholder'
            validate_policy_values(child, role=next_role, path=(*path, key))
    elif isinstance(value, (list, tuple)):
        child_role = {'rules': 'rule', 'conditions': 'condition', 'windows': 'window',
                      'operand': 'placeholder', 'placeholder': 'placeholder'}.get(role, 'data')
        for index, child in enumerate(value):
            validate_policy_values(child, role=child_role, path=(*path, index))
