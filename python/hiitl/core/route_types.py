"""Route model types for HIITL ECP.

These types are derived from the language-neutral route specification:
- docs/specs/routes.md (JSON Schema)

Routes are the third core artifact alongside envelopes and policies.
They define how ECP communicates with external systems — outbound
(ECP sends), inbound (external sends to ECP), or bidirectional
(ECP sends context, waits for response).

All types use Pydantic for validation and serialization. Every one refuses a field the spec does not define, naming it
(routes.md 1.3: no field is ever silently dropped, R-0872); `metadata` is the one open object.
"""

from copy import deepcopy
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, model_validator
from hiitl.core.input_types import JsonInteger, JsonNumber, supplied, validate_input
from hiitl.core.input_declarations import RouteMetadata

from hiitl.core.route_nulls import forbidden_nulls
from hiitl.core.transport import https_refusal
from hiitl.core.types import ORG_ID_PATTERN, VERSION_PATTERN, DecisionType, Sensitivity


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

    org_id: StrictStr = Field(..., pattern=ORG_ID_PATTERN)
    environment: Optional[StrictStr] = Field(
        None, pattern=r"^(dev|stage|prod)$"
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteAuth(BaseModel):
    """Authentication configuration for outbound/bidirectional requests."""

    type: AuthType
    secret_ref: StrictStr = Field(
        ...,
        description="Reference to secret value (never plaintext). "
        "Use 'env:VAR_NAME' or 'vault:path/to/secret'."
    )
    header: Optional[StrictStr] = Field(
        default="Authorization",
        description="HTTP header name for API key or bearer token auth."
    )
    hmac_header: Optional[StrictStr] = Field(
        default="X-HIITL-Signature",
        description="For hmac_sha256: HTTP header carrying the HMAC signature."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class ContextField(BaseModel):
    """A field to include in outbound/bidirectional payloads."""

    field_path: StrictStr = Field(
        ...,
        description="Dot-notation path into the envelope "
        "(e.g., 'parameters.amount', 'agent_id')."
    )
    label: Optional[StrictStr] = Field(
        None, description="Human-readable label for this field."
    )
    format: Optional[ContextFieldFormat] = Field(
        default="text",
        description="Display format hint for UIs consuming this data."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RiskConsequences(BaseModel):
    """What happens depending on the decision."""

    if_approved: Optional[StrictStr] = None
    if_denied: Optional[StrictStr] = None

    model_config = ConfigDict(extra="forbid")


class RiskFraming(BaseModel):
    """How to frame the risk/severity for the recipient."""

    severity: Optional[RiskSeverity] = None
    summary: Optional[StrictStr] = None
    consequences: Optional[RiskConsequences] = None

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteContext(BaseModel):
    """What a bidirectional route sends. An outbound route sends the record and is refused with `context` (routes.md
    "Outbound routes and filters"; HTL-29 row 131)."""

    fields: Optional[List[ContextField]] = None
    include_policy_ref: Optional[StrictBool] = Field(
        default=True,
        description="Include which policy/rule triggered this route."
    )
    include_audit_context: Optional[StrictBool] = Field(
        default=False,
        description="Include relevant audit history."
    )
    risk_framing: Optional[RiskFraming] = None

    model_config = ConfigDict(extra="forbid")


# Each filter key the route format renamed, old name to new (HTL-29 row 241, ruled 2026-11-09: "the route filter's key
# is `actions`; `tools` is refused at load naming `actions`"). An old name is refused as any key the filter does not
# define is, naming the key it became. A stored route is not rewritten (routes.md "immutable once deployed"): its job
# fails at send the same way, through the worker's read of the route.
FILTER_RENAMED = {"tools": "actions"}


def filter_renamed_refusal(data: Any) -> Optional[str]:
    """One migration explanation for the direct filter and its enclosing route."""
    renamed = [old for old in FILTER_RENAMED if isinstance(data, dict) and old in data]
    if renamed:
        return "; ".join(
            f"filters.{old} is a key the route format does not define: it was renamed filters.{FILTER_RENAMED[old]}, "
            f"with no alias. Write filters.{FILTER_RENAMED[old]}" for old in renamed)
    return None


@lru_cache
def _route_input_shape(model):
    """Retain filter migration guidance before the enclosing closure check."""
    shape = deepcopy(model.model_json_schema())
    shape["properties"]["filters"]["x-shape-refusal"] = filter_renamed_refusal
    metadata = deepcopy(RouteMetadata.model_json_schema())
    shape.setdefault('$defs', {}).update(metadata.pop('$defs', {}))
    shape['properties']['metadata'] = metadata
    return shape


class RouteFilters(BaseModel):
    """Which records an outbound route receives (routes.md "Outbound routes and filters"; HTL-29 row 131): a record
    passes a key when its value is one the key lists, and the filter when it passes every key declared. Each key's
    values are its source's own: `decisions` the decision type, `actions` the record's action, `sensitivity` the
    envelope's sensitivity values; another is refused at load, naming the allowed ones. `routing.FILTER_READS` reads
    each key from the record."""

    decisions: Optional[List[DecisionType]] = None
    actions: Optional[List[StrictStr]] = None
    agents: Optional[List[StrictStr]] = None
    sensitivity: Optional[List[Sensitivity]] = None

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _renamed_names_its_new_name(cls, data: Any) -> Any:
        detail = filter_renamed_refusal(data)
        if detail:
            raise ValueError(detail)
        return data


class RouteRetry(BaseModel):
    """Retry configuration for failed outbound/bidirectional deliveries."""

    max_attempts: Optional[JsonInteger] = Field(
        default=3, ge=1, le=10,
        description="Maximum delivery attempts before giving up."
    )
    backoff: Optional[BackoffStrategy] = Field(
        default="exponential",
        description="Backoff strategy between retries."
    )
    initial_delay_ms: Optional[JsonInteger] = Field(
        default=1000, ge=100, le=60000,
        description="Initial delay before first retry (milliseconds)."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteQueue(BaseModel):
    """Batching configuration for async routes."""

    batch_size: Optional[JsonInteger] = Field(
        default=100, ge=1, le=1000,
        description="Maximum events per batch."
    )
    flush_interval: Optional[StrictStr] = Field(
        default="30s",
        pattern=r"^\d+(s|m|h)$",
        description="How often to flush the batch (e.g., '30s', '5m', '1h')."
    )

    model_config = ConfigDict(extra="forbid")


class ModifyConstraint(BaseModel):
    """Constraint on parameter modifications (Phase 2)."""

    field_path: StrictStr
    constraint: ModifyConstraintType
    options: Optional[List[Any]] = None

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteResponseSchema(BaseModel):
    """Expected response format for bidirectional routes."""

    decision_options: List[DecisionOption] = Field(
        ..., min_length=2,
        description="Response types available to the external system. "
        "At minimum, must include 'approve' and 'deny'."
    )
    required_fields: Optional[List[StrictStr]] = Field(
        default=["decision"],
        description="Fields required in every response."
    )
    optional_fields: Optional[List[StrictStr]] = Field(
        None,
        description="Fields accepted but not required."
    )
    reason_required_for: Optional[List[StrictStr]] = Field(
        None,
        description="Which decision options require a reason string."
    )
    modify_constraints: Optional[List[ModifyConstraint]] = Field(
        None,
        description="Phase 2: constraints on parameter modifications."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteSLA(BaseModel):
    """Response time expectations for bidirectional routes."""

    timeout: StrictStr = Field(
        ...,
        pattern=r"^\d+(s|m|h)$",
        description="Maximum time to wait for a response "
        "(e.g., '30s', '15m', '4h')."
    )
    timeout_action: TimeoutAction = Field(
        ...,
        description="What happens when timeout is reached."
    )
    # `auto_approve_flag` was removed in routes.md 1.3 (HTL-20, row 149): a
    # fail_open timeout is read from the review case's transitions. A route
    # file that still carries it is refused, naming it, as any undefined field is (row 147).

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class EscalationLevel(BaseModel):
    """A single level in an escalation ladder."""

    level: JsonInteger = Field(..., ge=1, description="Escalation level number.")
    route: StrictStr = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
        description="Name of the route to escalate to."
    )
    after: StrictStr = Field(
        ...,
        pattern=r"^\d+(s|m|h)$",
        description="Duration before escalating to this level."
    )

    model_config = ConfigDict(extra="forbid")


class RouteEscalationLadder(BaseModel):
    """Multi-level escalation for bidirectional routes."""

    levels: Optional[List[EscalationLevel]] = None
    max_escalation_depth: Optional[JsonInteger] = Field(
        None, ge=1, le=10,
        description="Maximum number of escalation levels."
    )
    final_timeout_action: Optional[EscalationFinalAction] = Field(
        default="fail_closed",
        description="What happens when max escalation depth is reached."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class RouteCorrelation(BaseModel):
    """How request and response are matched for bidirectional routes."""

    token_field: Optional[StrictStr] = Field(
        default="resume_token",
        description="Field name for the resume/correlation token."
    )

    model_config = ConfigDict(extra="forbid")


class InboundAuth(BaseModel):
    """Authentication for inbound routes."""

    type: Optional[InboundAuthType] = None
    token_ref: Optional[StrictStr] = None

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class InboundPayloadMapping(BaseModel):
    """How to extract structured signals from external payloads."""

    signal_type: Optional[StrictStr] = None
    agent_ref: Optional[StrictStr] = None
    severity: Optional[StrictStr] = None
    metadata: Optional[Dict[StrictStr, StrictStr]] = None

    model_config = ConfigDict(extra="forbid")


class InboundPermissions(BaseModel):
    """What an inbound route is authorized to do."""

    can_enforce: Optional[StrictBool] = Field(
        default=False,
        description="Can activate kill switches."
    )
    can_propose: Optional[StrictBool] = Field(
        default=False,
        description="Can submit policy change proposals."
    )
    can_signal: Optional[StrictBool] = Field(
        default=False,
        description="Can push risk signals."
    )
    enforce_scope: Optional[List[StrictStr]] = Field(
        None,
        description="Limits on enforcement actions (requires can_enforce=true)."
    )

    model_config = ConfigDict(extra="forbid")

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

    url: Optional[StrictStr] = Field(
        None, description="ECP-provided webhook URL (read-only, set by system)."
    )
    auth: Optional[InboundAuth] = None
    payload_mapping: Optional[InboundPayloadMapping] = None
    permissions: InboundPermissions
    acceptance_mode: Optional[InboundAcceptanceMode] = Field(
        default="propose",
        description="'propose' creates review proposal, 'auto_accept' applies immediately."
    )

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

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
    - outbound: requires endpoint; forbids inbound, context, response_schema,
      sla, escalation_ladder, correlation
    - bidirectional: requires endpoint, response_schema, sla; forbids inbound;
      requires timing=sync
    - inbound: requires inbound.permissions; forbids endpoint, context,
      response_schema, sla, escalation_ladder, correlation
    """

    # Required fields
    name: StrictStr = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
        description="Unique identifier. Referenced by policy rules via 'route' field."
    )
    version: StrictStr = Field(
        ...,
        pattern=VERSION_PATTERN,
        description="Immutable semver version (e.g., 'v1.0.0')."
    )
    direction: RouteDirection
    timing: RouteTiming

    # Recommended fields
    description: Optional[StrictStr] = None
    purpose: Optional[List[RoutePurpose]] = Field(
        None, min_length=1,
        description="Descriptive labels for what this route is used for."
    )

    # Scope
    scope: Optional[RouteScope] = None

    # Connection
    endpoint: Optional[StrictStr] = Field(
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
    metadata: Optional[Dict[StrictStr, Any]] = None

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    @model_validator(mode='wrap')
    @classmethod
    def validate_existing_input(cls, value, handler):
        if isinstance(value, cls):
            cls.validate_explicit_nulls(value)
        return handler(value)

    @model_validator(mode='before')
    @classmethod
    def validate_explicit_nulls(cls, value):
        """A supplied null is not omission where routes.md excludes null."""
        # The existing source-generated null reader remains the null producer;
        # this pass adds non-null kinds/bounds and the open metadata's typed children.
        validate_input(cls, value, shape=_route_input_shape(cls), check_null=False)
        raw = supplied(value)
        if isinstance(raw, dict) and 'metadata' in raw:
            validate_input(RouteMetadata, raw['metadata'], path=('metadata',), check_null=False)
        paths = forbidden_nulls(value)
        if paths:
            errors = []
            for path in paths:
                name = '.'.join(map(str, path)) or '<root>'
                error = ValueError(f"{name} must not be null; routes.md excludes null at this location")
                errors.append({'type': 'value_error', 'loc': path, 'input': None, 'ctx': {'error': error}})
            raise ValidationError.from_exception_data(cls.__name__, errors)
        return value

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
            if self.context is not None:
                errors.append(
                    "outbound routes must not have 'context': an outbound route sends the record as the audit API "
                    "reads it, never a selection of its fields (routes.md \"Outbound routes and filters\"). Remove "
                    "it, or change direction to 'bidirectional' to send a selection and wait for an answer."
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

        # routes.md Validation Rules, "`endpoint` is an `https` URL" (row 140)
        refusal = https_refusal(self.endpoint, f"route '{self.name}' endpoint") if self.endpoint else None
        if refusal:
            errors.append(refusal)

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


def resolve_escalation_context(route: Route) -> Dict[str, Any]:
    """Resolve a Route into an escalation_context dict for the decision.

    Extracts the key fields from the typed Route model and returns a
    flattened escalation_context suitable for the Decision object.

    The output includes:
    - timeout: SLA timeout duration (e.g., "4h")
    - timeout_action: What happens on timeout
    - decision_options: What the reviewer can do
    - endpoint: Where the escalation goes
    - protocol: Transport protocol
    - fields: What envelope fields the reviewer sees
    - severity: Risk severity (if specified)
    - summary: Risk summary (if specified)
    - escalation_ladder: Multi-level escalation config (if present)
    - token_field: Correlation token field name (if present)

    Args:
        route: Validated Route model

    Returns:
        Flattened escalation_context dict for the Decision
    """
    context: Dict[str, Any] = {}
    if route.endpoint is not None:
        context["endpoint"] = route.endpoint
    if route.protocol is not None:
        context["protocol"] = route.protocol

    # SLA fields
    if route.sla:
        context["timeout"] = route.sla.timeout
        context["timeout_action"] = route.sla.timeout_action

    # Response schema
    if route.response_schema:
        context["decision_options"] = list(route.response_schema.decision_options)

    # Context fields
    if route.context and route.context.fields is not None:
        context["fields"] = [
            f.model_dump(mode="json", exclude_none=True)
            for f in route.context.fields
        ]

    # Risk framing
    if route.context and route.context.risk_framing:
        rf = route.context.risk_framing
        if rf.severity is not None:
            context["severity"] = rf.severity
        if rf.summary is not None:
            context["summary"] = rf.summary

    # Escalation ladder
    if route.escalation_ladder is not None:
        context["escalation_ladder"] = route.escalation_ladder.model_dump(mode="json", exclude_none=True)

    # Correlation
    if route.correlation:
        context["token_field"] = route.correlation.token_field

    return context
