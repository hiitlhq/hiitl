"""Core types for HIITL policy evaluation.

These types are derived from the language-neutral specifications:
- envelope_schema.json
- policy_format.md
- decision_response.md

All types use Pydantic for validation and serialization.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StrictBool, StrictStr, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from hiitl.core.date_time import DateTime, DateText
from hiitl.core.input_types import JsonInteger, JsonNumber, validate_input, number_input
from hiitl.core.numeric_domain import numbers_are_admitted
from hiitl.core.policy_values import validate_policy_values
from hiitl.core.input_declarations import blocked_fields_refusal, policy_shape, retired_rule_refusal


# ============================================================================
# Envelope Types (from envelope_schema.json)
# ============================================================================


# The organisation id's form, as envelope_schema.json states it: one pattern, read by the envelope, a route's scope and
# the SDK's configuration (sync_engine.md §8: "sync requests can only read/write data for the `org_id` associated with
# the `api_key`", so the SDK takes every id the service mints).
ORG_ID_PATTERN = r"^org_[a-zA-Z0-9]{16,}$"

# A version's form (policy_format.md's Policy Set Fields and Version Requirements; routes.md): semver,
# `v{major}.{minor}.{patch}`. One pattern, read by a policy set and a route.
VERSION_PATTERN = r"^v\d+\.\d+\.\d+$"

# The dedup window's default (the security architecture §1.3: "The dedup window is configurable (default: 24
# hours)"), read by the hosted service's setting and each SDK's local store: a repeated idempotency key within it
# returns the first decision (row 143).
DEDUP_WINDOW_SECONDS = 24 * 60 * 60

# The envelope schema's version (envelope_schema.json `$id`, `schema_version`): one fact, read by each SDK's builder,
# the lint's test envelope and the synthetic builders. The model takes this major only and refuses another, naming the
# version read, this one and the migration note, a heading of the envelope's docs page (R-0007: "Migration path
# documented before breaking changes"; no acceptance window, ruled 2026-11-07, row 223).
ENVELOPE_SCHEMA_VERSION = "v2.0"
ENVELOPE_MIGRATION_NOTE = "Migrating from schema 1.x"

# Each field the envelope schema renamed, old name to new (envelope_schema.json 1.1: "Renamed tool_name to action").
# An old name has no alias from 2.0 (gap row 225, ruled 2026-11-08): it is refused as any field the schema does not
# define is, and the refusal names the field it became. The lint names it the same way.
ENVELOPE_RENAMED = {"tool_name": "action"}


def renamed_note(old: str) -> str:
    """The refusal's words for a field the schema renamed."""
    new = ENVELOPE_RENAMED[old]
    return (f"{old} is a field the envelope schema does not define: the schema renamed it {new}, with no alias from "
            f"2.0. Send {new}.")


class Environment(str, Enum):
    """Environment enumeration."""

    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"


class Operation(str, Enum):
    """CRUD operation types."""

    READ = "read"
    WRITE = "write"
    CREATE = "create"
    DELETE = "delete"
    EXECUTE = "execute"
    UPDATE = "update"


class Sensitivity(str, Enum):
    """Sensitivity classifications."""

    MONEY = "money"
    IDENTITY = "identity"
    PERMISSIONS = "permissions"
    REGULATED = "regulated"
    IRREVERSIBLE = "irreversible"
    PII = "pii"
    SENSITIVE_DATA = "sensitive_data"


class CostEstimate(BaseModel):
    """Cost estimate for an action (envelope_schema.json v1.4: closed; `tokens` a number)."""

    tokens: Optional[Union[JsonInteger, JsonNumber]] = Field(None, ge=0)
    dollars: Optional[JsonNumber] = Field(None, ge=0)
    api_calls: Optional[JsonInteger] = Field(None, ge=0)

    model_config = ConfigDict(extra="forbid")


class Principal(BaseModel):
    """The verified principal (envelope_schema.json v1.2 `principal`): the subject and
    scopes of a token a verifier checked (MCP authorization spec 2026-07-28: RFC 9728, RFC 8707). Set only by a
    verifier, never accepted as a free value; distinct from agent_id / user_id / requested_scopes."""

    sub: StrictStr = Field(..., min_length=1, max_length=256)
    scopes: Optional[List[StrictStr]] = None
    iss: Optional[StrictStr] = None
    aud: Optional[StrictStr] = None
    verified_by: Literal["sdk_verifier", "mcp_proxy", "hosted"]
    verified_at: Optional[DateText] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _supplied_input(cls, value):
        validate_input(cls, value)
        return value


class Envelope(BaseModel):
    """Execution envelope - normalized action representation.

    Source of truth: docs/specs/envelope_schema.json
    """

    # Required fields
    schema_version: StrictStr = Field(..., pattern=r"^v[0-9]+\.[0-9]+$")
    org_id: StrictStr = Field(..., pattern=ORG_ID_PATTERN)
    environment: Environment
    agent_id: StrictStr = Field(..., min_length=1, max_length=128)
    action_id: StrictStr = Field(..., pattern=r"^act_[a-zA-Z0-9]{20,}$")
    idempotency_key: StrictStr = Field(..., min_length=1, max_length=255)
    action: StrictStr = Field(..., min_length=1, max_length=128)
    timestamp: DateText
    signature: StrictStr = Field(..., pattern=r"^[a-f0-9]{64}$")

    # Fields with defaults (sparse envelope support)
    operation: Operation = Operation.EXECUTE
    target: Dict[StrictStr, Any] = Field(default_factory=dict)
    parameters: Dict[StrictStr, Any] = Field(default_factory=dict)

    # Optional fields
    agent_instance_id: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    user_id: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    session_id: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    correlation_id: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    trace_id: Optional[StrictStr] = Field(None, pattern=r"^[0-9a-f]{32}$")  # W3C Trace Context's form (schema 1.5, row 210)
    action_type: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    sensitivity: Optional[List[Sensitivity]] = None
    cost_estimate: Optional[CostEstimate] = None
    confidence: Optional[JsonNumber] = Field(None, ge=0.0, le=1.0)
    requested_scopes: Optional[List[StrictStr]] = None
    principal: Optional[Principal] = None  # verified only (A7) — see Principal
    reason: Optional[StrictStr] = Field(None, max_length=500)
    prompt_hash: Optional[StrictStr] = Field(None, min_length=1, max_length=128)
    signature_version: Literal["hmac-sha256-v1"] = "hmac-sha256-v1"  # the schema's enum (row 206)
    metadata: Optional[Dict[StrictStr, Any]] = None

    # No field is ever silently dropped (R-0872): a field the schema does not define is refused, naming it.
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _supplied_input(cls, value):
        validate_input(cls, value)
        return value

    @field_validator("schema_version")
    @classmethod
    def _the_major_taken(cls, v: str) -> str:
        if v.partition(".")[0] != ENVELOPE_SCHEMA_VERSION.partition(".")[0]:
            raise ValueError(
                f"schema_version {v} is refused: this release takes envelope schema {ENVELOPE_SCHEMA_VERSION}, and an "
                f"envelope of another major version is refused, with no acceptance window. Build the envelope at "
                f"{ENVELOPE_SCHEMA_VERSION}; the envelope's docs page, '{ENVELOPE_MIGRATION_NOTE}', names each change.")
        return v

    @model_validator(mode="wrap")
    @classmethod
    def _renamed_names_its_new_name(cls, data, handler):
        """A renamed field is refused where any undefined field is, its error naming the field it became; every other
        error stands as validation gave it (ENVELOPE_RENAMED)."""
        try:
            with number_input(cls, data):
                if isinstance(data, cls):
                    validate_input(cls, data)
                return handler(data)
        except ValidationError as e:
            errors = e.errors(include_url=False)
            if not any(_renamed(err) for err in errors):
                raise
            raise ValidationError.from_exception_data(e.title, [
                {"type": PydanticCustomError("extra_forbidden", renamed_note(err["loc"][0])), "loc": err["loc"],
                 "input": err["input"]} if _renamed(err) else
                {k: err[k] for k in ("type", "loc", "input", "ctx") if k in err} for err in errors]) from None


def _renamed(err) -> bool:
    return err["type"] == "extra_forbidden" and len(err["loc"]) == 1 and err["loc"][0] in ENVELOPE_RENAMED


# ============================================================================
# Policy Types (from policy_format.md)
# ============================================================================


class DecisionType(str, Enum):
    """Valid decision outcomes."""

    ALLOW = "ALLOW"
    OBSERVE = "OBSERVE"
    BLOCK = "BLOCK"
    PAUSE = "PAUSE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    SANDBOX = "SANDBOX"
    RATE_LIMIT = "RATE_LIMIT"
    KILL_SWITCH = "KILL_SWITCH"
    ESCALATE = "ESCALATE"
    ROUTE = "ROUTE"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    CONTROL_PLANE_UNAVAILABLE = "CONTROL_PLANE_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    POLICY_ERROR = "POLICY_ERROR"


# The decisions a rule never writes, each with who produces it (policy_format.md 2.10 "Valid Decisions";
# decision_response.md "Error Decisions"). A rule writes every other DecisionType.
PRODUCED_DECISIONS = {
    "OBSERVE": "the evaluator's own in observe mode; a rule that observes without enforcing is `lifecycle_stage: staged`",
    "SIGNATURE_INVALID": "the control point's, when an envelope's signature does not verify",
    "CONTROL_PLANE_UNAVAILABLE": "the hosted client's, when the hosted service cannot be reached and its fail mode applies",
    "VALIDATION_ERROR": "the control point's, when an envelope fails validation",
    "POLICY_ERROR": "the control point's, when the policy cannot be loaded, parsed or evaluated",
}


class ConditionOperator(str, Enum):
    """Condition comparison operators."""

    # Equality
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"

    # Numeric comparison
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"

    # String/array operations
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    MATCHES = "matches"

    # Set operations
    IN = "in"
    NOT_IN = "not_in"

    # Existence
    EXISTS = "exists"

    # Schema conformance (policy_format.md 2.6 "Parameter schema") — never a regex
    CONFORMS_TO = "conforms_to"


# A field reference as a condition's value: resolved against the same envelope at evaluation (policy_format.md 2.6)
FIELD_REF_KEY = "$field"
_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def field_ref(v: Any) -> Any:
    """The path a field-reference value names (a string, or a placeholder staff will set), else None."""
    if isinstance(v, dict) and set(v) == {FIELD_REF_KEY}:
        return v[FIELD_REF_KEY]
    return None


def schema_error(s: Any) -> Optional[str]:
    """Why `s` is not a parameter schema (policy_format.md 2.6 "Parameter schema"), or None."""
    if not isinstance(s, dict):
        return "a parameter schema is an object"
    extra = set(s) - {"type", "properties", "required", "additionalProperties"}
    if extra:
        return f"a parameter schema takes type, properties, required, additionalProperties — not {sorted(extra)}"
    if s.get("type", "object") != "object":
        return "a parameter schema's type is `object`"
    props = s.get("properties", {})
    if not isinstance(props, dict):
        return "`properties` maps a name to its schema"
    for name, p in props.items():
        if not isinstance(p, dict) or set(p) - {"type"} or ("type" in p and (not isinstance(p["type"], str) or p["type"] not in _SCHEMA_TYPES)):
            return f"property `{name}` is {{}} or {{\"type\": one of {sorted(_SCHEMA_TYPES)}}}"
    req = s.get("required", [])
    if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
        return "`required` is a list of names"
    if not isinstance(s.get("additionalProperties", True), bool):
        return "`additionalProperties` is true or false"
    return None


def conforms(value: Any, schema: dict) -> bool:
    """Whether `value` conforms to the parameter schema: an object, every required name present, no name outside the
    properties when additionalProperties is false, every typed property of its type."""
    if not isinstance(value, dict):
        return False
    props = schema.get("properties", {})
    if any(r not in value for r in schema.get("required", [])):
        return False
    if schema.get("additionalProperties", True) is False and any(k not in props for k in value):
        return False
    checks = {"string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
              "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
              "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
              "array": lambda x: isinstance(x, list), "object": lambda x: isinstance(x, dict)}
    return all(checks[p["type"]](value[k]) for k, p in props.items() if "type" in p and k in value)


from .operator_kinds import literal_kind_ok, OperatorKindError


class Condition(BaseModel):
    """Atomic condition - field comparison. The value is a literal, a typed placeholder, or a field reference
    (policy_format.md 2.6); `conforms_to` takes a parameter schema."""

    field: StrictStr
    operator: ConditionOperator
    value: Any

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode="after")
    def _value_shape(self):
        ref = field_ref(self.value)
        if ref is not None and not (isinstance(ref, str) and ref) and not has_placeholder(ref):
            raise ValueError(f"`{self.field}`: a field reference is {{\"{FIELD_REF_KEY}\": \"<envelope path>\"}}")
        if self.operator in ("exists", ConditionOperator.EXISTS) and ref is not None:
            raise ValueError(f"`{self.field}`: `exists` takes true or false, never a field reference")
        if self.operator in ("conforms_to", ConditionOperator.CONFORMS_TO) and ref is None \
                and not has_placeholder(self.value) and schema_error(self.value):
            raise ValueError(f"`{self.field}` conforms_to: {schema_error(self.value)}")
        if ref is None and not has_placeholder(self.value) and not literal_kind_ok(self.operator, self.value):
            raise OperatorKindError(self.operator, self.field)
        return self


class LogicalCondition(BaseModel):
    """Logical condition - combines multiple conditions.

    Supports:
    - all_of (AND)
    - any_of (OR)
    - none_of (NOT)
    """

    all_of: Optional[List[Union["LogicalCondition", Condition]]] = None
    any_of: Optional[List[Union["LogicalCondition", Condition]]] = None
    none_of: Optional[List[Union["LogicalCondition", Condition]]] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def validate_exactly_one_logical_op(self):
        """Ensure exactly one logical operator is set."""
        set_ops = sum([
            self.all_of is not None,
            self.any_of is not None,
            self.none_of is not None,
        ])
        if set_ops != 1:
            raise ValueError(
                "Exactly one of all_of, any_of, or none_of must be set"
            )
        return self


# Update forward references
LogicalCondition.model_rebuild()


class RemediationType(str, Enum):
    """Remediation type — determines the structure of remediation.details.

    Source of truth: docs/specs/decision_response.md (Remediation Types section)
    """

    FIELD_RESTRICTION = "field_restriction"
    THRESHOLD = "threshold"
    SCOPE = "scope"
    RATE_LIMIT = "rate_limit"
    TEMPORAL = "temporal"
    CUSTOM = "custom"


class Remediation(BaseModel):
    """Structured remediation guidance for BLOCK/RATE_LIMIT decisions.

    Present when ECP successfully enforced a policy (not when ECP itself failed).
    Mutually exclusive with error on Decision.

    Source of truth: docs/specs/decision_response.md (Remediation Types section)
    """

    message: StrictStr  # Human-readable explanation
    suggestion: StrictStr  # Actionable next step
    type: RemediationType
    details: Optional[Dict[StrictStr, Any]] = None  # Type-specific structured fields

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode="after")
    def _blocked_fields_shape(self):
        """A field_restriction's `blocked_fields` is a list, or `{ref, filter}` computed from the call (policy_format.md
        **Remediation on Rules**); any other shape is refused at load, naming it."""
        bf = (self.details or {}).get("blocked_fields") if self.type == "field_restriction" else None
        refusal = blocked_fields_refusal(bf)
        if refusal:
            raise ValueError(refusal)
        return self


class LifecycleStage(str, Enum):
    """Per-rule lifecycle stage.

    Replaces the old `enabled` boolean and `mode` field as the single
    source of truth for whether a rule is evaluated and how it behaves.

    See docs/specs/policy_format.md for full semantics.
    """

    DRAFT = "draft"          # Created, not evaluating yet
    STAGED = "staged"        # Evaluating against live traffic; "would have" only (no enforcement). Block 1B records observations.
    ACTIVE = "active"        # Enforcing. The rule's decision is binding.
    DISABLED = "disabled"    # Explicitly turned off. Visible in UI but skipped by evaluator.
    ARCHIVED = "archived"    # Was once active, superseded by newer version.


class RuleScope(BaseModel):
    """Optional scope filters for a rule.

    All fields optional. Absent = applies to all matching envelopes.

    See docs/specs/policy_format.md for full semantics.
    """

    agents: Optional[List[StrictStr]] = None              # Whitelist of agent_ids
    users: Optional[List[StrictStr]] = None               # Whitelist of user_ids
    environments: Optional[List[Environment]] = None  # Whitelist of the envelope's environment values (2.10)
    percentage: Optional[JsonInteger] = Field(default=None, ge=0, le=100)                # Apply to N% of matching envelopes (0-100)
    rollout_hash_field: Optional[StrictStr] = None        # Envelope field used for deterministic percentage hash (default: action_id)

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @field_validator("percentage", mode="wrap")
    @classmethod
    def _percentage_in_range(cls, value, handler):
        try:
            return handler(value)
        except ValidationError as error:
            if not {item['type'] for item in error.errors()} & {'greater_than_equal', 'less_than_equal'}:
                raise
            bounds = {type(item).__name__: item for item in cls.model_fields['percentage'].metadata}
            raise ValueError(f"scope.percentage must be between {bounds['Ge'].ge} and {bounds['Le'].le} inclusive") from None


PLACEHOLDER_KEY = "$uncalibrated"
# a value only staff can set — declared, never observed (T49; policy_format.md 2.5)
DECLARED_KEY = "$declared"
PLACEHOLDER_KEYS = (PLACEHOLDER_KEY, DECLARED_KEY)


def has_placeholder(x: Any) -> bool:
    """Whether a value carries a typed placeholder — `{"$uncalibrated": "<what observation would set it>"}`
    (policy_format.md "Uncalibrated bounds") or `{"$declared": "<what staff declare>"}` (2.5).
    A rule carrying either never matches."""
    if isinstance(x, dict):
        return any(k in x for k in PLACEHOLDER_KEYS) or any(has_placeholder(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(has_placeholder(v) for v in x)
    if isinstance(x, BaseModel):
        return any(has_placeholder(getattr(x, k)) for k in type(x).model_fields)
    return False


def placeholders(x: Any) -> list:
    """Every typed placeholder a value carries, as `(key, what)` in order."""
    if isinstance(x, BaseModel):
        x = x.model_dump(mode="python")
    if isinstance(x, dict):
        own = [(k, x[k]) for k in PLACEHOLDER_KEYS if k in x]
        return own + [p for v in x.values() for p in placeholders(v)]
    if isinstance(x, (list, tuple)):
        return [p for v in x for p in placeholders(v)]
    return []


def _bound(v: Any, name: str) -> Any:
    if isinstance(v, dict):
        if set(v) != {PLACEHOLDER_KEY} or not isinstance(v[PLACEHOLDER_KEY], str):
            raise ValueError(f"{name}: a bound is an integer or the placeholder "
                             f'{{"{PLACEHOLDER_KEY}": "<what observation would set it>"}}')
        return v
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise ValueError(f"{name} must be a positive integer (or the uncalibrated placeholder)")
    return v


class RateLimitWindow(BaseModel):
    """The window a RATE_LIMIT rule meters (policy_format.md "Rate-limit rules"; R-0852)."""

    limit: Union[JsonInteger, Dict[StrictStr, StrictStr]]
    window_seconds: Union[JsonInteger, Dict[StrictStr, StrictStr]]
    scope: Literal["action", "agent", "user", "org", "user_action"] = "action"

    model_config = ConfigDict(extra="forbid")

    @field_validator("limit")
    @classmethod
    def _limit(cls, v: Any) -> Any:
        return _bound(v, "rate_limit.limit")

    @field_validator("window_seconds")
    @classmethod
    def _window(cls, v: Any) -> Any:
        return _bound(v, "rate_limit.window_seconds")


class RuleTest(BaseModel):
    """A test a rule ships with (policy_format.md "Tests shipped with a rule"): an envelope (required fields filled
    with fixed test values) and what the rule alone must do with it — a decision, or NOT_MATCHED."""

    envelope: Dict[StrictStr, Any]
    expect: StrictStr

    model_config = ConfigDict(extra="forbid")

    @field_validator("expect")
    @classmethod
    def _expect(cls, v: str) -> str:
        ok = {d.value for d in DecisionType} | {"NOT_MATCHED"}
        if v not in ok:
            raise ValueError(f"tests[].expect must be a decision or NOT_MATCHED, got {v!r}")
        return v


class SuggestedBy(BaseModel):
    """Lineage of a rule accepted from a suggestion card (written by accept)."""

    suggestion_id: StrictStr
    source: StrictStr
    atom_id: Optional[StrictStr] = None
    assessment_id: Optional[StrictStr] = None
    action_key: Optional[StrictStr] = None

    model_config = ConfigDict(extra="forbid")


class DeterminationRef(BaseModel):
    assessment_id: StrictStr
    grain: StrictStr
    action_id: Optional[StrictStr] = None

    model_config = ConfigDict(extra="forbid")


class PromptRef(BaseModel):
    file: StrictStr
    line: JsonInteger
    quoted: StrictStr

    model_config = ConfigDict(extra="forbid")


class RequirementCitation(BaseModel):
    """What a rule answers: the requirement and the determination, and/or the prompt line (§9.12)."""

    atom_id: Optional[StrictStr] = None
    standard: Optional[StrictStr] = None
    regulatory_trigger: Optional[StrictStr] = None
    determination: Optional[DeterminationRef] = None
    prompt: Optional[PromptRef] = None

    model_config = ConfigDict(extra="forbid")


class WaitsOn(BaseModel):
    """What a rule's condition reads that the envelope does not yet carry — a promotion gate (policy_format.md 2.3,
    2.5): the configured verifier of a verified claim, an envelope field, or enrichment
    context `external.<source>.<field>` — a sync route's answer (`route`) or hiitl's own record (`hiitl_record`), both
    route-response enrichment (TICKET-046)."""

    kind: Literal["verifier", "envelope_field", "route", "hiitl_record"]
    target: StrictStr

    model_config = ConfigDict(extra="forbid")


class Rule(BaseModel):
    """Policy rule - atomic unit of policy.

    Source of truth: docs/specs/policy_format.md

    Lifecycle: every rule has a `lifecycle_stage`. Only rules in `active` state
    are evaluated for binding decisions. `staged` rules will be evaluated for
    "would have" observations in Block 1B; in Block 1A they are skipped.
    `draft`, `disabled`, and `archived` rules are always skipped.

    Schema break: `enabled` and `mode` fields are removed; `lifecycle_stage`
    is the single field controlling rule behavior.
    """

    name: StrictStr
    description: StrictStr
    priority: JsonInteger
    conditions: Union[LogicalCondition, Condition]
    decision: DecisionType
    reason_code: StrictStr
    lifecycle_stage: LifecycleStage = LifecycleStage.ACTIVE
    scope: Optional[RuleScope] = None
    valid_from: Optional[DateTime] = None
    valid_to: Optional[DateTime] = None
    observation_window_days: JsonInteger = 7   # For staged rules: how long to observe before regression report
    route: Optional[StrictStr] = None        # Route name for escalation decisions
    remediation: Optional[Remediation] = None  # Guidance when this rule blocks
    metadata: Optional[Dict[StrictStr, Any]] = None
    rate_limit: Optional[RateLimitWindow] = None          # RATE_LIMIT rules: the window they meter (R-0852)
    tests: Optional[List[RuleTest]] = None                # shipped tests, run by the lint (C7)
    suggested_by: Optional[SuggestedBy] = None            # lineage, written by accept (B2)
    # one citation, or a list when one rule answers several determinations (folded, §K1)
    requirement_citation: Optional[Union[RequirementCitation, List[RequirementCitation]]] = None
    waits_on: Optional[WaitsOn] = None                    # an unmet dependency: a promotion gate (§K2)

    # No field is dropped (policy_format.md "No field is dropped"; S2): a field this spec does not define is refused.
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def _existing_input(cls, value, handler):
        with number_input(cls, value, shape=policy_shape(cls, Envelope)):
            if isinstance(value, cls):
                validate_input(cls, value, shape=policy_shape(cls, Envelope))
            return handler(value)

    @model_validator(mode="before")
    @classmethod
    def _retired_keys(cls, data: Any) -> Any:
        validate_policy_values(data, role="rule")
        detail = retired_rule_refusal(data)
        if detail:
            raise ValueError(detail)
        validate_input(cls, data, shape=policy_shape(cls, Envelope))
        return data

    @field_validator("decision")
    @classmethod
    def _written_decision(cls, v: Any, info) -> Any:
        d = v.value if hasattr(v, "value") else v
        if d in PRODUCED_DECISIONS:
            written = " | ".join(x.value for x in DecisionType if x.value not in PRODUCED_DECISIONS)
            raise ValueError(f"rule {info.data.get('name')!r}: decision {d} is never written in a rule — it is "
                             f"{PRODUCED_DECISIONS[d]} (policy_format.md 'Valid Decisions'). A rule writes one of "
                             f"{written}.")
        return v

    # Derived once at validation, never serialized: a rule carrying the uncalibrated placeholder never matches
    # (policy_format.md "Uncalibrated bounds"); a windowed RATE_LIMIT rule meters and never binds (R-0852).
    _uncalibrated: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _derive(self):
        self._uncalibrated = has_placeholder(self.conditions) or has_placeholder(self.rate_limit)
        return self

    @property
    def uncalibrated(self) -> bool:
        return self._uncalibrated

    @property
    def meters(self) -> bool:
        d = self.decision.value if hasattr(self.decision, "value") else self.decision
        return d == "RATE_LIMIT" and self.rate_limit is not None


class PolicySetScope(BaseModel):
    """Where a policy set applies (policy_format.md "Scope Fields (Schema Support)"): the organisation and environment
    whose envelopes it governs, each in the envelope's own form, are required; team, project and agent are the schema's
    further dimensions."""

    org_id: StrictStr = Field(..., pattern=ORG_ID_PATTERN)
    environment: Environment
    team_id: Optional[StrictStr] = None
    project_id: Optional[StrictStr] = None
    agent_id: Optional[StrictStr] = None

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class PolicySet(BaseModel):
    """Policy set - collection of rules.

    Source of truth: docs/specs/policy_format.md. Its Policy Set Fields table requires the name, a semver version, a
    description, the scope and the rules (HTL-22 row 165).
    """

    name: StrictStr
    version: StrictStr = Field(..., pattern=VERSION_PATTERN)
    description: StrictStr
    scope: PolicySetScope
    # A rule that reads an envelope path the call does not carry (policy_format.md "A field the call does not carry"):
    # skip it and continue (the default), or decide BLOCK naming the field
    on_missing: Literal["skip", "fail_closed"] = "skip"
    rules: List[Rule]
    metadata: Optional[Dict[StrictStr, Any]] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def _existing_input(cls, value, handler):
        with number_input(cls, value, shape=policy_shape(cls, Envelope)):
            if isinstance(value, cls):
                validate_input(cls, value, shape=policy_shape(cls, Envelope))
            return handler(value)

    @model_validator(mode="before")
    @classmethod
    def _one_rate_window_representation(cls, data: Any) -> Any:
        """T47: the set-level `metadata.rate_limits` compiled to windowed RATE_LIMIT rules on load."""
        from hiitl.core.rate_limits import compile_set_limits
        validate_policy_values(data)
        validate_input(cls, data, shape=policy_shape(cls, Envelope))
        return compile_set_limits(data)

    @model_validator(mode="after")
    def _unique_rule_names(self):
        """policy_format.md, a rule's `name`: "Unique rule identifier within policy set" (row 220). Read after the
        set-level throttles compile, so a compiled rule is held to it, named by the entry it carries."""
        held: Dict[str, List[str]] = {}
        for i, rule in enumerate(self.rules):
            source = (rule.metadata or {}).get("compiled_from")
            path = source.get("path") if isinstance(source, dict) else None
            held.setdefault(rule.name, []).append(f"the rule compiled from {path}" if path else f"rules[{i}]")
        twice = {name: where for name, where in held.items() if len(where) > 1}
        if twice:
            named = "; ".join(f"{name!r} is held by {' and '.join(where)}" for name, where in twice.items())
            raise ValueError(f"{named}. A rule's name is the \"Unique rule identifier within policy set\" "
                             f"(policy_format.md): a lifecycle transition, a kill switch and a review address a rule "
                             f"by it. Give each rule a name of its own.")
        return self


# ============================================================================
# Decision Response Types (from decision_response.md)
# ============================================================================


class Timing(BaseModel):
    """Timing metadata for transparency."""

    ingest_ms: JsonNumber
    evaluation_ms: JsonNumber
    total_ms: JsonNumber


class RateLimit(BaseModel):
    """Rate limit state."""

    scope: str
    window: str
    limit: JsonInteger
    current: JsonInteger
    reset_at: DateTime


class MatchedRule(BaseModel):
    """Rule that matched during evaluation."""

    rule_name: str
    policy_set: str
    priority: JsonInteger


class RateLimitRule(BaseModel):
    """A matching active RATE_LIMIT rule with a window (decision_response.md `rate_limit_rules`): it does not bind;
    the post-evaluation limiter counts it when the binding decision is ALLOW."""

    rule_name: str
    policy_set: str
    priority: JsonInteger
    reason_code: str
    limit: JsonInteger
    window_seconds: JsonInteger
    scope: Literal["action", "agent", "user", "org", "user_action"]
    # The rule's own remediation, details computed from the call; the limiter puts it on the refusal (R-0059).
    remediation: Optional[Remediation] = None


class StagedObservation(BaseModel):
    """A "would have" observation from a staged rule (Block 1B, 9b).

    Staged rules run alongside active rules but never bind a decision.
    Each rule that *would* have produced a decision (or considered binding
    in the would-be sense — first match wins in their staged race) is
    captured here so the regression report can compare the staged
    behavior against what the active rules actually decided.

    Source of truth: docs/specs/decision_response.md (Block 1B addition).
    """

    rule_name: str
    policy_set: str
    priority: JsonInteger
    would_be_decision: DecisionType
    would_be_reason_codes: List[str]
    # Whether this staged rule would have been the *first* match
    # (i.e., it bound the staged-only decision). Useful for the regression
    # report — only the first-match staged rule actually changes the
    # would-have-been outcome; lower-priority staged matches are still
    # informative but don't drive the regression decision.
    would_be_binding: bool

    model_config = ConfigDict(use_enum_values=True)


class MissingField(BaseModel):
    """A rule whose outcome an envelope path the call does not carry left open, skipped rather than read
    (decision_response.md `missing_fields`; policy_format.md "A field the call does not carry")."""

    rule_name: str
    policy_set: str
    field: str


class RouteAsked(BaseModel):
    """A sync route asked in this evaluation (decision_response.md 1.7; policy_format.md 2.7; TICKET-046)."""

    rule_name: str
    route: str
    outcome: Literal["answered", "unanswered", "failed_open"]
    fields: Optional[List[str]] = None  # the answer's declared fields that re-entered
    error: Optional[str] = None  # why there is no answer


class ErrorDetail(BaseModel):
    """Error details for failed evaluations.

    Per decision_response.md spec:
    Errors must include both machine-readable codes and human-readable messages
    to provide helpful guidance to developers.
    """

    code: str  # Machine-readable error code (e.g., "SIGNATURE_INVALID")
    message: str  # Human-readable explanation with actionable guidance


class DecisionMetadata(BaseModel):
    """The fail mode an outage decision applied, and the hosted client's circuit breaker when it was answered
    (decision_response.md, the schema's `metadata`; Example 9). Present on `CONTROL_PLANE_UNAVAILABLE`.

    The fail mode is the hosted client's `fail_mode` setting: FAIL_CLOSED by default, FAIL_OPEN opt-in (Stop B (ii),
    ruled 2026-11-06).
    """

    fail_mode: Literal["FAIL_CLOSED", "FAIL_OPEN"]
    circuit_breaker_state: Literal["closed", "open", "half_open"]  # hiitl.sdk.circuit_breaker.CircuitState

    model_config = ConfigDict(extra="forbid")


class Decision(BaseModel):
    """Decision response after policy evaluation.

    Source of truth: docs/specs/decision_response.md
    """

    action_id: str
    decision: DecisionType
    allowed: bool
    reason_codes: List[str]
    policy_version: str
    timing: Timing
    matched_rules: Optional[List[MatchedRule]] = None
    rate_limit: Optional[RateLimit] = None
    resume_token: Optional[str] = None  # Token to correlate escalation with reviewer response
    route_ref: Optional[str] = None  # Route artifact name from matched rule
    escalation_context: Optional[Dict[str, Any]] = None  # Populated by SDK/server, not evaluator
    envelope_hash: Optional[str] = None  # Tier 1 Security: SHA-256 of evaluated envelope
    error: Optional[ErrorDetail] = None
    remediation: Optional[Remediation] = None  # Guidance for BLOCK/RATE_LIMIT decisions
    would_be: Optional[str] = None  # Original decision type when in OBSERVE mode
    would_be_reason_codes: Optional[List[str]] = None  # Original reason codes when in OBSERVE mode
    # Side-by-side observations from staged rules (Block 1B, 9b). Always
    # a list — empty when no staged rules ran — so consumers can iterate
    # without null-checks. The backend audit writer still stores NULL in
    # the DB for empty lists as a storage optimization.
    staged_observations: List["StagedObservation"] = Field(default_factory=list)
    # Matching windowed RATE_LIMIT rules (R-0852): they meter, never bind. Always a list.
    rate_limit_rules: List[RateLimitRule] = Field(default_factory=list)
    # A sync route's answer re-entering evaluation (policy_format.md 2.7; TICKET-046): the enrichment context the last
    # evaluation read ({source: {field: value}}) and each route asked. Set by the SDK / server's routing loop, never by
    # the caller; the submitted envelope is unchanged.
    enrichment: Optional[Dict[str, Dict[str, Any]]] = None
    routes: Optional[List[RouteAsked]] = None
    # Each rule an absent envelope path left unread and that was skipped (on_missing skip, observe mode, a staged
    # rule), with the field: "never skipped silently". Absent when no read was skipped.
    missing_fields: Optional[List[MissingField]] = None
    # SDK cache state at evaluation time (TICKET-116). Local + hybrid
    # SDKs stamp this on every Decision so callers can detect cold-start
    # / stale-cache situations. Possible values:
    #   "synced"    — policies came from a successful in-process sync
    #   "from_disk" — policies came from disk cache (warm start); no
    #                 successful sync this process yet
    #   "empty"     — no policies in memory; evaluator is OBSERVE_ALL
    # Hosted-mode evaluations leave this None (the server has authority;
    # cache_status doesn't apply). Consumers MAY treat None as "not
    # applicable to this decision."
    cache_status: Optional[Literal["synced", "from_disk", "empty"]] = None
    # The outage decision's fail mode and circuit state (row 174); set by the hosted client, None on every other
    metadata: Optional[DecisionMetadata] = None

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode='wrap')
    @classmethod
    def _numeric_admission(cls, value, handler):
        # Decision's existing optional/output shape is unchanged; only the shared number domain applies.
        if numbers_are_admitted():
            return handler(value)
        shape = policy_shape(cls, Envelope)
        with number_input(cls, value, shape=shape):
            validate_input(cls, value, shape=shape, numbers_only=True)
            return handler(value)

    @property
    def ok(self) -> bool:
        """Alias for allowed. Action is permitted."""
        return self.allowed

    @property
    def blocked(self) -> bool:
        """Action was blocked by policy."""
        return not self.allowed and self.decision in (
            "BLOCK", "KILL_SWITCH", "RATE_LIMIT"
        )

    @property
    def needs_approval(self) -> bool:
        """Action requires human approval or review."""
        return self.decision in ("REQUIRE_APPROVAL", "PAUSE", "ESCALATE")

    @property
    def observed(self) -> bool:
        """Action was observed (OBSERVE mode — not enforced)."""
        return self.decision == "OBSERVE"

    @model_validator(mode='before')
    @classmethod
    def coerce_error_field(cls, data):
        """Coerce error field from string or dict to ErrorDetail.

        Backward compatibility: accepts error as a plain string and wraps it
        in ErrorDetail(code="UNKNOWN", message=str). Also accepts dicts.
        """
        if isinstance(data, dict) and 'error' in data and data['error'] is not None:
            err = data['error']
            if isinstance(err, str):
                data = {**data, 'error': {'code': 'UNKNOWN', 'message': err}}
            elif isinstance(err, dict) and not isinstance(err, ErrorDetail):
                # Pydantic will validate the dict → ErrorDetail conversion
                pass
        return data

    @model_validator(mode='after')
    def validate_error_remediation_exclusive(self):
        """Error and remediation are mutually exclusive.

        error = ECP itself failed. remediation = ECP worked and enforced policy.
        """
        if self.error is not None and self.remediation is not None:
            raise ValueError(
                "Decision cannot have both 'error' and 'remediation'. "
                "'error' indicates ECP failure; 'remediation' indicates "
                "intentional policy enforcement."
            )
        return self
