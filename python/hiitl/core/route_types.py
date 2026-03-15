"""Route model types for HIITL ECP.

These types are derived from the language-neutral route specification:
- docs/specs/routes.md (JSON Schema)

Routes are the third core artifact alongside envelopes and policies.
They define how ECP communicates with external systems — outbound
(ECP sends), inbound (external sends to ECP), or bidirectional
(ECP sends context, waits for response).

All types use Pydantic for validation and serialization.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ============================================================================
# Enums (from routes.md JSON Schema)
# ============================================================================


class RouteDirection(str, Enum):
    """Communication direction for a route."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BIDIRECTIONAL = "bidirectional"


class RouteTiming(str, Enum):
    """Whether a route blocks evaluation."""

    ASYNC = "async"
    SYNC = "sync"


class RoutePurpose(str, Enum):
    """Descriptive labels for route usage."""

    OBSERVABILITY = "observability"
    COMPLIANCE = "compliance"
    REVIEW = "review"
    SECURITY = "security"
    POLICY_MANAGEMENT = "policy-management"
    ASSESSMENT = "assessment"


class RouteProtocol(str, Enum):
    """Transport protocol."""

    HTTP = "http"
    GRPC = "grpc"
    WEBHOOK = "webhook"


class AuthType(str, Enum):
    """Authentication method for outbound/bidirectional routes."""

    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    HMAC_SHA256 = "hmac_sha256"
    MTLS = "mtls"
    OAUTH2 = "oauth2"


class ContextFieldFormat(str, Enum):
    """Display format hint for context fields."""

    TEXT = "text"
    CURRENCY = "currency"
    DATE = "date"
    JSON = "json"
    CODE = "code"
    URL = "url"


class RiskSeverity(str, Enum):
    """Severity level for risk framing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionOption(str, Enum):
    """Response types available to external systems."""

    APPROVE = "approve"
    DENY = "deny"
    MODIFY = "modify"
    DELEGATE = "delegate"
    REQUEST_MORE_INFO = "request_more_info"
    CONDITIONAL_APPROVE = "conditional_approve"
    PARTIAL_APPROVE = "partial_approve"


class TimeoutAction(str, Enum):
    """What happens when SLA timeout is reached."""

    ESCALATE = "escalate"
    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"
    EXTEND = "extend"


class EscalationFinalAction(str, Enum):
    """What happens when max escalation depth is reached."""

    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"


class BackoffStrategy(str, Enum):
    """Backoff strategy between retries."""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"


class InboundAuthType(str, Enum):
    """Authentication method for inbound routes."""

    BEARER_TOKEN = "bearer_token"
    HMAC_SHA256 = "hmac_sha256"


class InboundAcceptanceMode(str, Enum):
    """Acceptance mode for inbound policy proposals."""

    PROPOSE = "propose"
    AUTO_ACCEPT = "auto_accept"


class ModifyConstraintType(str, Enum):
    """Constraint type for parameter modifications."""

    REDUCE_ONLY = "reduce_only"
    INCREASE_ONLY = "increase_only"
    ANY = "any"
    SELECT_FROM = "select_from"


# ============================================================================
# Sub-Models
# ============================================================================


class RouteScope(BaseModel):
    """Tenant and environment scope for a route."""

    org_id: str = Field(..., pattern=r"^org_[a-zA-Z0-9]{16,}$")
    environment: Optional[str] = Field(
        None, pattern=r"^(dev|stage|prod)$"
    )

    model_config = ConfigDict(use_enum_values=True)


class RouteAuth(BaseModel):
    """Authentication configuration for outbound/bidirectional requests."""

    type: AuthType
    secret_ref: str = Field(
        ...,
        description="Reference to secret value (never plaintext). "
        "Use 'env:VAR_NAME' or 'vault:path/to/secret'."
    )
    header: Optional[str] = Field(
        default="Authorization",
        description="HTTP header name for API key or bearer token auth."
    )
    hmac_header: Optional[str] = Field(
        default="X-HIITL-Signature",
        description="For hmac_sha256: HTTP header carrying the HMAC signature."
    )

    model_config = ConfigDict(use_enum_values=True)


class ContextField(BaseModel):
    """A field to include in outbound/bidirectional payloads."""

    field_path: str = Field(
        ...,
        description="Dot-notation path into the envelope "
        "(e.g., 'parameters.amount', 'agent_id')."
    )
    label: Optional[str] = Field(
        None, description="Human-readable label for this field."
    )
    format: Optional[ContextFieldFormat] = Field(
        default="text",
        description="Display format hint for UIs consuming this data."
    )

    model_config = ConfigDict(use_enum_values=True)


class RiskConsequences(BaseModel):
    """What happens depending on the decision."""

    if_approved: Optional[str] = None
    if_denied: Optional[str] = None


class RiskFraming(BaseModel):
    """How to frame the risk/severity for the recipient."""

    severity: Optional[RiskSeverity] = None
    summary: Optional[str] = None
    consequences: Optional[RiskConsequences] = None

    model_config = ConfigDict(use_enum_values=True)


class RouteContext(BaseModel):
    """What data to send on outbound/bidirectional routes."""

    fields: Optional[List[ContextField]] = None
    include_policy_ref: Optional[bool] = Field(
        default=True,
        description="Include which policy/rule triggered this route."
    )
    include_audit_context: Optional[bool] = Field(
        default=False,
        description="Include relevant audit history."
    )
    risk_framing: Optional[RiskFraming] = None


class RouteFilters(BaseModel):
    """When this route activates. Narrows activation to specific criteria."""

    decisions: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    agents: Optional[List[str]] = None
    sensitivity: Optional[List[str]] = None


class RouteRetry(BaseModel):
    """Retry configuration for failed outbound/bidirectional deliveries."""

    max_attempts: Optional[int] = Field(
        default=3, ge=1, le=10,
        description="Maximum delivery attempts before giving up."
    )
    backoff: Optional[BackoffStrategy] = Field(
        default="exponential",
        description="Backoff strategy between retries."
    )
    initial_delay_ms: Optional[int] = Field(
        default=1000, ge=100, le=60000,
        description="Initial delay before first retry (milliseconds)."
    )

    model_config = ConfigDict(use_enum_values=True)


class RouteQueue(BaseModel):
    """Batching configuration for async routes."""

    batch_size: Optional[int] = Field(
        default=100, ge=1, le=1000,
        description="Maximum events per batch."
    )
    flush_interval: Optional[str] = Field(
        default="30s",
        pattern=r"^\d+(s|m|h)$",
        description="How often to flush the batch (e.g., '30s', '5m', '1h')."
    )


class ModifyConstraint(BaseModel):
    """Constraint on parameter modifications (Phase 2)."""

    field_path: str
    constraint: ModifyConstraintType
    options: Optional[List[Any]] = None

    model_config = ConfigDict(use_enum_values=True)


class RouteResponseSchema(BaseModel):
    """Expected response format for bidirectional routes."""

    decision_options: List[DecisionOption] = Field(
        ..., min_length=2,
        description="Response types available to the external system. "
        "At minimum, must include 'approve' and 'deny'."
    )
    required_fields: Optional[List[str]] = Field(
        default=["decision"],
        description="Fields required in every response."
    )
    optional_fields: Optional[List[str]] = Field(
        None,
        description="Fields accepted but not required."
    )
    reason_required_for: Optional[List[str]] = Field(
        None,
        description="Which decision options require a reason string."
    )
    modify_constraints: Optional[List[ModifyConstraint]] = Field(
        None,
        description="Phase 2: constraints on parameter modifications."
    )

    model_config = ConfigDict(use_enum_values=True)


class RouteSLA(BaseModel):
    """Response time expectations for bidirectional routes."""

    timeout: str = Field(
        ...,
        pattern=r"^\d+(s|m|h)$",
        description="Maximum time to wait for a response "
        "(e.g., '30s', '15m', '4h')."
    )
    timeout_action: TimeoutAction = Field(
        ...,
        description="What happens when timeout is reached."
    )
    auto_approve_flag: Optional[bool] = Field(
        default=False,
        description="If timeout_action is fail_open, flag as auto-approved."
    )

    model_config = ConfigDict(use_enum_values=True)


class EscalationLevel(BaseModel):
    """A single level in an escalation ladder."""

    level: int = Field(..., ge=1, description="Escalation level number.")
    route: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
        description="Name of the route to escalate to."
    )
    after: str = Field(
        ...,
        pattern=r"^\d+(s|m|h)$",
        description="Duration before escalating to this level."
    )


class RouteEscalationLadder(BaseModel):
    """Multi-level escalation for bidirectional routes."""

    levels: Optional[List[EscalationLevel]] = None
    max_escalation_depth: Optional[int] = Field(
        None, ge=1, le=10,
        description="Maximum number of escalation levels."
    )
    final_timeout_action: Optional[EscalationFinalAction] = Field(
        default="fail_closed",
        description="What happens when max escalation depth is reached."
    )

    model_config = ConfigDict(use_enum_values=True)


class RouteCorrelation(BaseModel):
    """How request and response are matched for bidirectional routes."""

    token_field: Optional[str] = Field(
        default="resume_token",
        description="Field name for the resume/correlation token."
    )


class InboundAuth(BaseModel):
    """Authentication for inbound routes."""

    type: Optional[InboundAuthType] = None
    token_ref: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class InboundPayloadMapping(BaseModel):
    """How to extract structured signals from external payloads."""

    signal_type: Optional[str] = None
    agent_ref: Optional[str] = None
    severity: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


class InboundPermissions(BaseModel):
    """What an inbound route is authorized to do."""

    can_enforce: Optional[bool] = Field(
        default=False,
        description="Can activate kill switches."
    )
    can_propose: Optional[bool] = Field(
        default=False,
        description="Can submit policy change proposals."
    )
    can_signal: Optional[bool] = Field(
        default=False,
        description="Can push risk signals."
    )
    enforce_scope: Optional[List[str]] = Field(
        None,
        description="Limits on enforcement actions (requires can_enforce=true)."
    )

    @model_validator(mode='after')
    def validate_permissions(self):
        if not any([self.can_enforce, self.can_propose, self.can_signal]):
            raise ValueError(
                "At least one permission must be true "
                "(can_enforce, can_propose, or can_signal). "
                "An inbound route with all permissions false has no effect."
            )
        if self.enforce_scope and not self.can_enforce:
            raise ValueError(
                "enforce_scope requires can_enforce=true. "
                "Set can_enforce to true or remove enforce_scope."
            )
        return self


class RouteInbound(BaseModel):
    """Configuration for inbound routes (Phase 2)."""

    url: Optional[str] = Field(
        None, description="ECP-provided webhook URL (read-only, set by system)."
    )
    auth: Optional[InboundAuth] = None
    payload_mapping: Optional[InboundPayloadMapping] = None
    permissions: InboundPermissions
    acceptance_mode: Optional[InboundAcceptanceMode] = Field(
        default="propose",
        description="'propose' creates review proposal, 'auto_accept' applies immediately."
    )

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode='after')
    def validate_acceptance_mode(self):
        if self.acceptance_mode == "auto_accept" and not self.permissions.can_propose:
            raise ValueError(
                "acceptance_mode 'auto_accept' requires can_propose=true. "
                "Set can_propose to true or use 'propose' mode."
            )
        return self


# ============================================================================
# Root Model: Route
# ============================================================================


class Route(BaseModel):
    """Route configuration — the third core artifact.

    Routes define how ECP communicates with external systems. They are
    referenced by name from policy rules (via the 'route' field) and
    resolved by the SDK/server after evaluation.

    Source of truth: docs/specs/routes.md

    Direction determines which fields are required/forbidden:
    - outbound: requires endpoint; forbids inbound, response_schema, sla,
      escalation_ladder, correlation
    - bidirectional: requires endpoint, response_schema, sla; forbids inbound;
      requires timing=sync
    - inbound: requires inbound.permissions; forbids endpoint, context,
      response_schema, sla, escalation_ladder, correlation
    """

    # Required fields
    name: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
        description="Unique identifier. Referenced by policy rules via 'route' field."
    )
    version: str = Field(
        ...,
        pattern=r"^v\d+\.\d+\.\d+$",
        description="Immutable semver version (e.g., 'v1.0.0')."
    )
    direction: RouteDirection
    timing: RouteTiming

    # Recommended fields
    description: Optional[str] = None
    purpose: Optional[List[RoutePurpose]] = Field(
        None, min_length=1,
        description="Descriptive labels for what this route is used for."
    )

    # Scope
    scope: Optional[RouteScope] = None

    # Connection
    endpoint: Optional[str] = Field(
        None, description="Target URL for outbound/bidirectional routes."
    )
    auth: Optional[RouteAuth] = None
    protocol: Optional[RouteProtocol] = Field(
        default="webhook", description="Transport protocol."
    )

    # Context
    context: Optional[RouteContext] = None

    # Filters
    filters: Optional[RouteFilters] = None

    # Resilience
    retry: Optional[RouteRetry] = None
    queue: Optional[RouteQueue] = None

    # Response (bidirectional)
    response_schema: Optional[RouteResponseSchema] = None
    sla: Optional[RouteSLA] = None
    escalation_ladder: Optional[RouteEscalationLadder] = None
    correlation: Optional[RouteCorrelation] = None

    # Inbound (Phase 2)
    inbound: Optional[RouteInbound] = None

    # Metadata
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode='after')
    def validate_direction_constraints(self):
        """Enforce direction-specific required and forbidden fields."""
        direction = self.direction
        errors = []

        if direction == "outbound":
            if not self.endpoint:
                errors.append(
                    "outbound routes require 'endpoint'. "
                    "Specify the target URL where ECP sends events."
                )
            forbidden = {
                "inbound": self.inbound,
                "response_schema": self.response_schema,
                "sla": self.sla,
                "escalation_ladder": self.escalation_ladder,
                "correlation": self.correlation,
            }
            for field_name, value in forbidden.items():
                if value is not None:
                    errors.append(
                        f"outbound routes must not have '{field_name}'. "
                        f"Remove it or change direction to 'bidirectional'."
                    )

        elif direction == "bidirectional":
            if not self.endpoint:
                errors.append(
                    "bidirectional routes require 'endpoint'. "
                    "Specify the URL where ECP sends context and waits for response."
                )
            if not self.response_schema:
                errors.append(
                    "bidirectional routes require 'response_schema'. "
                    "Define what the external system can respond with "
                    "(at minimum: decision_options with 'approve' and 'deny')."
                )
            if not self.sla:
                errors.append(
                    "bidirectional routes require 'sla'. "
                    "Define timeout and timeout_action for the response."
                )
            if self.inbound is not None:
                errors.append(
                    "bidirectional routes must not have 'inbound'. "
                    "Use direction 'inbound' for external-to-ECP routes."
                )
            if self.timing != "sync":
                errors.append(
                    "bidirectional routes must use timing 'sync'. "
                    "Bidirectional implies waiting for a response."
                )

        elif direction == "inbound":
            if not self.inbound:
                errors.append(
                    "inbound routes require 'inbound' with permissions. "
                    "Define what the external system is authorized to do."
                )
            forbidden = {
                "endpoint": self.endpoint,
                "context": self.context,
                "response_schema": self.response_schema,
                "sla": self.sla,
                "escalation_ladder": self.escalation_ladder,
                "correlation": self.correlation,
            }
            for field_name, value in forbidden.items():
                if value is not None:
                    errors.append(
                        f"inbound routes must not have '{field_name}'. "
                        f"Remove it or change direction."
                    )

        # Timing constraints
        if self.timing == "sync" and self.queue is not None:
            errors.append(
                "sync routes must not use 'queue'. "
                "Batching is only for async routes."
            )

        if errors:
            raise ValueError(
                "Route validation failed:\n- " + "\n- ".join(errors) + "\n\n"
                "See docs/specs/routes.md for the full schema."
            )

        return self
