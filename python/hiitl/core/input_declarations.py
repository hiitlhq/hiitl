"""Typed children of otherwise open input objects, from the owning format tables.

These models describe supplied members only. Validation does not replace the
caller dictionaries with models, add defaults, or discard their other keys.
"""
from copy import deepcopy
from functools import lru_cache
from typing import Annotated, Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from hiitl.core.date_time import DateTime


class OpenObject(BaseModel):
    model_config = ConfigDict(extra='allow')


class PolicyTemplate(OpenObject):
    source: Optional[str] = None
    source_version: Optional[str] = None
    customizations: Optional[list[str]] = None


class PolicyDisplay(OpenObject):
    sections: Optional[list[dict[str, Any]]] = None


class UncalibratedBound(BaseModel):
    value: str = Field(alias='$uncalibrated')
    model_config = ConfigDict(extra='forbid')


PositiveInteger = Annotated[int, Field(gt=0)]


class LegacyRateLimit(BaseModel):
    """policy_format.md, the set-level compilation table."""
    scope: Optional[str] = None
    window: Optional[str] = None
    limit: Optional[Union[PositiveInteger, UncalibratedBound]] = None
    window_seconds: Optional[Union[PositiveInteger, UncalibratedBound]] = None
    model_config = ConfigDict(extra='forbid')


class PolicyMetadata(OpenObject):
    """policy_format.md Metadata Fields; datetime is a written string."""
    author: Optional[str] = None
    created_at: Optional[DateTime] = None
    updated_at: Optional[DateTime] = None
    tags: Optional[list[str]] = None
    intended_use_case: Optional[str] = None
    target_agent_types: Optional[list[str]] = None
    template: Optional[PolicyTemplate] = None
    display: Optional[PolicyDisplay] = None
    compliance_references: Optional[list[dict[str, Any]]] = None
    grading: Optional[dict[str, Any]] = None
    rate_limits: Optional[list[LegacyRateLimit]] = None


class RouteMetadata(OpenObject):
    """routes.md metadata properties, with other metadata still open."""
    author: Optional[str] = None
    created_at: Optional[DateTime] = None
    tags: Optional[list[str]] = None


class ComputedBlockedFields(BaseModel):
    ref: str
    filter: list[Any]
    model_config = ConfigDict(extra='forbid')


class FieldRestrictionDetails(OpenObject):
    blocked_fields: Optional[Union[list[str], ComputedBlockedFields]] = None
    allowed_fields: Optional[list[str]] = None
    field_ref: Optional[str] = None


class ThresholdDetails(OpenObject):
    threshold: Optional[float] = None
    current_value: Optional[float] = None
    max_allowed: Optional[float] = None
    field: Optional[str] = None


class ScopeDetails(OpenObject):
    required_scope: Optional[str] = None
    current_scope: Optional[str] = None
    allowed_scopes: Optional[list[str]] = None
    scope_type: Optional[str] = None


class RateLimitDetails(OpenObject):
    limit: Optional[int] = None
    current: Optional[int] = None
    reset_at: Optional[DateTime] = None
    scope: Optional[str] = None
    window: Optional[str] = None


class TemporalDetails(OpenObject):
    allowed_window: Optional[dict[str, Any]] = None
    timezone: Optional[str] = None
    next_allowed_at: Optional[DateTime] = None
    current_time: Optional[str] = None


DETAILS = {
    'field_restriction': FieldRestrictionDetails, 'threshold': ThresholdDetails,
    'scope': ScopeDetails, 'rate_limit': RateLimitDetails, 'temporal': TemporalDetails,
}


def retired_rule_refusal(data):
    """The existing migration guidance for the rule's retired lifecycle fields."""
    if isinstance(data, dict):
        for key in ("enabled", "mode"):
            if key in data:
                return (
                    f"rule {data.get('name')!r}: `{key}` was replaced by `lifecycle_stage` (draft | staged | active "
                    f"| disabled | archived) — `enabled: false` is `lifecycle_stage: disabled`, `enabled: true` the "
                    f"default `active`, per-rule observe `staged`. The key is refused rather than ignored: ignoring "
                    f"`enabled: false` ran disabled rules, kill switches among them, live.")
    return None


def envelope_renamed_refusal(data):
    """A shipped test envelope uses the envelope's own migration guidance."""
    from .types import ENVELOPE_RENAMED, renamed_note
    if isinstance(data, dict):
        notes = [renamed_note(old) for old in ENVELOPE_RENAMED if old in data]
        return "; ".join(notes) or None
    return None


def blocked_fields_refusal(value):
    """The existing row-146 remediation shape explanation, also used before coercion."""
    if value is None or isinstance(value, list):
        return None
    if (isinstance(value, dict) and set(value) == {'ref', 'filter'} and isinstance(value['ref'], str)
            and value['ref'] and isinstance(value['filter'], list)
            and all(isinstance(member, str) for member in value['filter'])):
        return None
    json_type = {str: 'string', int: 'number', float: 'number', bool: 'boolean'}.get(type(value), type(value).__name__)
    shape = f'an object with keys {sorted(value)}' if isinstance(value, dict) else f'a {json_type}'
    return (f'remediation.details.blocked_fields is {shape}. A field_restriction\'s blocked_fields is either a list '
            'of field names, copied as written, or {ref, filter}: `ref` the envelope path whose values are '
            'checked (a non-empty string), `filter` the list of blocked values (strings), computed from the call '
            '(policy_format.md "Remediation on Rules").')


@lru_cache
def policy_shape(model, envelope_model):
    """Join the existing model declarations to their open typed child declarations."""
    shape = deepcopy(model.model_json_schema())
    definitions = shape.setdefault('$defs', {})

    def embed(declaration):
        fragment = deepcopy(declaration.model_json_schema())
        definitions.update(fragment.pop('$defs', {}))
        return fragment

    def node(declaration):
        return shape if model.__name__ == declaration else definitions.get(declaration)

    if (rule := node('Rule')) is not None:
        rule['x-shape-refusal'] = retired_rule_refusal
    if (policy := node('PolicySet')) is not None:
        policy['properties']['metadata'] = embed(PolicyMetadata)
    if (test := node('RuleTest')) is not None:
        partial = embed(envelope_model)
        partial.pop('required', None)
        partial['x-shape-refusal'] = envelope_renamed_refusal
        test['properties']['envelope'] = partial
    if (window := node('RateLimitWindow')) is not None:
        bound = {'anyOf': [{'type': 'integer', 'exclusiveMinimum': 0}, embed(UncalibratedBound)]}
        window['properties']['limit'] = deepcopy(bound)
        window['properties']['window_seconds'] = deepcopy(bound)
    if (remediation := node('Remediation')) is not None:
        remediation['allOf'] = []
        for name, declaration in DETAILS.items():
            details = embed(declaration)
            if declaration is FieldRestrictionDetails:
                details['properties']['blocked_fields']['x-shape-refusal'] = blocked_fields_refusal
            remediation['allOf'].append({
                'if': {'properties': {'type': {'const': name}}, 'required': ['type']},
                'then': {'properties': {'details': details}},
            })
    if (logical := node('LogicalCondition')) is not None:
        logical['x-shape-after'] = logical_sets_refusal
    if (condition := node('Condition')) is not None:
        declared = {'type': 'object', 'properties': {'$declared': {'type': 'string'}},
                    'required': ['$declared'], 'additionalProperties': False}
        operand = {'allOf': [
            {'if': {'required': [key]}, 'then': {'properties': {key: child}, 'additionalProperties': False}}
            for key, child in (
                ('$uncalibrated', {'type': 'string'}), ('$declared', {'type': 'string'}),
                ('$field', {'anyOf': [{'type': 'string'}, declared]}),
            )
        ]}
        condition['properties']['value'] = operand
        condition['x-shape-refusal'] = condition_operand_refusal
        property_shape = {'type': 'object', 'properties': {'type': {'type': 'string'}},
                          'additionalProperties': False}
        parameter = {'type': 'object', 'properties': {
            'type': {'type': 'string'}, 'properties': {'type': 'object', 'additionalProperties': property_shape},
            'required': {'type': 'array', 'items': {'type': 'string'}},
            'additionalProperties': {'type': 'boolean'},
        }, 'additionalProperties': False}
        condition.setdefault('allOf', []).append({
            'if': {'properties': {'operator': {'const': 'conforms_to'}}, 'required': ['operator']},
            'then': {'properties': {'value': {'anyOf': [parameter, {
                'type': 'object', 'properties': {'$field': {'anyOf': [{'type': 'string'}, declared]}},
                'required': ['$field'], 'additionalProperties': False,
            }]}}},
        })
    return shape



LOGICAL_SETS = ('all_of', 'any_of', 'none_of')


def logical_sets_refusal(value):
    """A logical condition sets exactly one of its three sets (policy_format.md "Exactly one set"). The model reads it
    after its own members hold, and the input walker reads it the same way (`x-shape-after`)."""
    if not isinstance(value, dict) or sum(value.get(name) is not None for name in LOGICAL_SETS) == 1:
        return None
    return 'Exactly one of all_of, any_of, or none_of must be set'


def condition_operand_refusal(value):
    """Name operator/path before the generic supplied-kind reader; references remain references."""
    from .operator_kinds import literal_kind_ok, OperatorKindError
    from .types import field_ref, has_placeholder
    if not isinstance(value, dict) or 'operator' not in value or 'value' not in value:
        return None
    if field_ref(value['value']) is None and not has_placeholder(value['value']) and not literal_kind_ok(value['operator'], value['value']):
        return str(OperatorKindError(value['operator'], value.get('field', '<field>')))
    return None
