"""Core types for HIITL policy evaluation.

These types are derived from the language-neutral specifications:
- envelope_schema.json
- policy_format.md
- decision_response.md

All types use Pydantic for validation and serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ============================================================================
# Envelope Types (from envelope_schema.json)
# ============================================================================


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
    """Cost estimate for an action."""

    tokens: Optional[int] = Field(None, ge=0)
    dollars: Optional[float] = Field(None, ge=0)
    api_calls: Optional[int] = Field(None, ge=0)


class Envelope(BaseModel):
    """Execution envelope - normalized action representation.

    Source of truth: specs/envelope_schema.json
    """

    # Required fields
    schema_version: str = Field(..., pattern=r"^v[0-9]+\.[0-9]+$")
    org_id: str = Field(..., pattern=r"^org_[a-zA-Z0-9]{16,}$")
    environment: Environment
    agent_id: str = Field(..., min_length=1, max_length=128)
    action_id: str = Field(..., pattern=r"^act_[a-zA-Z0-9]{20,}$")
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    action: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime
    signature: str = Field(..., pattern=r"^[a-f0-9]{64}$")

    # Fields with defaults (sparse envelope support)
    operation: Operation = Operation.EXECUTE
    target: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)

    # Optional fields
    agent_instance_id: Optional[str] = Field(None, min_length=1, max_length=128)
    user_id: Optional[str] = Field(None, min_length=1, max_length=128)
    session_id: Optional[str] = Field(None, min_length=1, max_length=128)
    correlation_id: Optional[str] = Field(None, min_length=1, max_length=128)
    trace_id: Optional[str] = Field(None, min_length=1, max_length=128)
    action_type: Optional[str] = Field(None, min_length=1, max_length=128)
    sensitivity: Optional[List[Sensitivity]] = None
    cost_estimate: Optional[CostEstimate] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    requested_scopes: Optional[List[str]] = None
    reason: Optional[str] = Field(None, max_length=500)
    prompt_hash: Optional[str] = Field(None, min_length=1, max_length=128)
    policy_refs: Optional[List[str]] = None
    signature_version: Optional[str] = "hmac-sha256-v1"
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode='before')
    @classmethod
    def handle_tool_name_compat(cls, data):
        """Accept tool_name as alias for action (backward compatibility)."""
        if isinstance(data, dict) and 'tool_name' in data and 'action' not in data:
            data = {**data}
            data['action'] = data.pop('tool_name')
        return data


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


class Condition(BaseModel):
    """Atomic condition - field comparison."""

    field: str
    operator: ConditionOperator
    value: Any

    model_config = ConfigDict(use_enum_values=True)


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

    message: str  # Human-readable explanation
    suggestion: str  # Actionable next step
    type: RemediationType
    details: Optional[Dict[str, Any]] = None  # Type-specific structured fields

    model_config = ConfigDict(use_enum_values=True)


class Rule(BaseModel):
    """Policy rule - atomic unit of policy.

    Source of truth: docs/specs/policy_format.md
    """

    name: str
    description: str
    enabled: bool
    priority: int
    conditions: Union[LogicalCondition, Condition]
    decision: DecisionType
    reason_code: str
    route: Optional[str] = None  # Route name for escalation decisions
    remediation: Optional[Remediation] = None  # Guidance when this rule blocks
    metadata: Optional[Dict[str, Any]] = None
    mode: Literal["observe", "enforce"] = "enforce"

    model_config = ConfigDict(use_enum_values=True)


class PolicySet(BaseModel):
    """Policy set - collection of rules.

    Source of truth: docs/specs/policy_format.md
    """

    name: str
    version: str
    description: Optional[str] = None
    scope: Optional[Dict[str, str]] = None  # org_id, environment
    rules: List[Rule]
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# Decision Response Types (from decision_response.md)
# ============================================================================


class Timing(BaseModel):
    """Timing metadata for transparency."""

    ingest_ms: float
    evaluation_ms: float
    total_ms: float


class RateLimit(BaseModel):
    """Rate limit state."""

    scope: str
    window: str
    limit: int
    current: int
    reset_at: datetime


class ApprovalMetadata(BaseModel):
    """Approval workflow metadata."""

    approval_id: str
    sla_hours: Optional[float] = None
    reviewer_role: Optional[str] = None
    resume_url: Optional[str] = None


class SandboxMetadata(BaseModel):
    """Sandbox routing metadata."""

    sandbox_endpoint: str
    sandbox_environment: Optional[str] = None


class MatchedRule(BaseModel):
    """Rule that matched during evaluation."""

    rule_name: str
    policy_set: str
    priority: int


class ErrorDetail(BaseModel):
    """Error details for failed evaluations.

    Per decision_response.md spec and CLAUDE.md principle #11:
    Errors must include both machine-readable codes and human-readable messages
    to provide helpful guidance to developers.
    """

    code: str  # Machine-readable error code (e.g., "SIGNATURE_INVALID")
    message: str  # Human-readable explanation with actionable guidance


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
    approval_metadata: Optional[ApprovalMetadata] = None
    sandbox_metadata: Optional[SandboxMetadata] = None
    resume_token: Optional[str] = None  # Token to correlate escalation with reviewer response
    route_ref: Optional[str] = None  # Route artifact name from matched rule
    escalation_context: Optional[Dict[str, Any]] = None  # Populated by SDK/server, not evaluator
    envelope_hash: Optional[str] = None  # Tier 1 Security: SHA-256 of evaluated envelope
    error: Optional[ErrorDetail] = None
    remediation: Optional[Remediation] = None  # Guidance for BLOCK/RATE_LIMIT decisions
    would_be: Optional[str] = None  # Original decision type when in OBSERVE mode
    would_be_reason_codes: Optional[List[str]] = None  # Original reason codes when in OBSERVE mode

    model_config = ConfigDict(use_enum_values=True)

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
