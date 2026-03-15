# Policy Format Specification

**Version**: 1.3
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-02-27

---

## Purpose

This document defines the policy format for HIITL Execution Control Plane. It is the **source of truth** for how policies are structured, evaluated, and composed.

All policy evaluator implementations (TypeScript, Python, and future languages) must conform to this specification. The conformance test suite validates that all implementations produce identical decisions for identical (envelope, policy) inputs.

---

## Design Principles

1. **Simple for basic rules, expressive for complex policies**
2. **Four-layer design** (designed together, implemented incrementally):
   - Layer 1: Rules (atomic conditions and outcomes)
   - Layer 2: Policy sets (collections of rules with evaluation order)
   - Layer 3: Policy hierarchy (composition across scopes) — interface designed in Phase 1, implemented in Phase 2
   - Layer 4: Signal-aware conditions (rules referencing external signals) — interface designed in Phase 1, implemented in Phase 2

3. **Declarative, not imperative** - JSON (primary), YAML (convenience layer)
4. **JSON is the native format** - Policies are JSON objects. YAML support is a thin parsing layer that converts to JSON.
5. **Versioned and immutable** - Once deployed, a policy version never changes
6. **Deterministic evaluation** - Same (envelope, policy) always produces same decision
7. **Explicit composition rules** - Clear precedence, no "smart" merging
8. **Testable** - Policies are code, treat them as such

### Format Priority

**Primary format: JSON**
- Envelopes are JSON
- Decisions are JSON
- Conformance tests are JSON
- Database stores policies as JSON (JSONB in Postgres)
- Evaluator works on JSON objects internally

**YAML support: Convenience layer**
- YAML is friendlier for humans writing policies by hand
- YAML files are parsed and converted to JSON before evaluation
- YAML loader is a thin layer on top of JSON parsing
- Examples below show both formats, but JSON is authoritative

---

## Layer 1: Rules (Phase 1)

A **rule** is the atomic unit of policy. It consists of:
- **Conditions**: When does this rule apply?
- **Decision**: What outcome does it produce?
- **Metadata**: Name, description, reason codes

### Rule Structure (YAML)

```yaml
name: "limit-high-value-payments"
description: "Require approval for payments over $500"
enabled: true
priority: 100

conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "parameters.amount"
      operator: "greater_than"
      value: 500

decision: "REQUIRE_APPROVAL"
reason_code: "HIGH_VALUE_PAYMENT"
route: "finance-review"  # References a route artifact (see docs/specs/routes.md)
metadata:
  sla_hours: 4
  reviewer_role: "finance_approver"
```

### Rule Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique rule identifier within policy set |
| `description` | string | Yes | Human-readable explanation |
| `enabled` | boolean | Yes | Whether rule is active (allows disabling without deleting) |
| `priority` | integer | Yes | Evaluation order (higher priority = evaluated first) |
| `conditions` | object | Yes | Condition tree (see Condition Syntax below) |
| `decision` | string | Yes | Decision outcome (see Valid Decisions below) |
| `reason_code` | string | Yes | Machine-readable reason for decision |
| `route` | string | No | Name of route configuration for escalation decisions (`REQUIRE_APPROVAL`, `PAUSE`, `ESCALATE`). References a separately managed route artifact by name. See `docs/specs/routes.md`. |
| `remediation` | object | No | Structured guidance returned when this rule triggers a BLOCK or RATE_LIMIT. Contains `message`, `suggestion`, `type`, and `details`. See decision_response.md. |
| `metadata` | object | No | Additional data (SLA, reviewer info, etc.) |
| `mode` | string | No | Rule enforcement mode: `"observe"` (log but don't enforce) or `"enforce"` (default). When mode is `"observe"`, matching decisions become OBSERVE with `allowed=true` and `would_be` showing the original decision. |

### Remediation on Rules

The optional `remediation` field on a rule defines the actionable guidance returned to the caller when that rule produces a blocking decision (BLOCK, RATE_LIMIT). Remediation is **only meaningful on blocking rules** — if an ALLOW or SANDBOX rule includes remediation, the evaluator ignores it.

The remediation object has four fields:
- `message` (required) — Human-readable explanation of why the action was blocked
- `suggestion` (required) — Actionable next step for the caller or agent
- `type` (required) — One of: `field_restriction`, `threshold`, `scope`, `rate_limit`, `temporal`, `custom`
- `details` (optional) — Type-specific structured fields. See [decision_response.md](decision_response.md#remediation-types) for the full schema per type.

Example rule with remediation:

```yaml
- name: block-high-value-payments
  description: Block payments over $10,000
  enabled: true
  priority: 100
  conditions:
    all_of:
      - field: parameters.amount
        operator: greater_than
        value: 10000
  decision: BLOCK
  reason_code: AMOUNT_EXCEEDS_LIMIT
  remediation:
    message: "Payment amount exceeds the $10,000 limit."
    suggestion: "Reduce amount to $10,000 or below, or request approval."
    type: threshold
    details:
      threshold: 10000
      max_allowed: 10000
```

When the evaluator matches this rule, the `remediation` object is copied directly to the decision response. The caller (or agent) can read `remediation.message` for a human explanation and `remediation.details` for structured data to self-correct.

### Valid Decisions (Phase 1)

| Decision | Description |
|----------|-------------|
| `ALLOW` | Action is permitted, proceed with execution |
| `OBSERVE` | Action observed but not enforced (produced by evaluator in observe mode, not written in rules). `allowed=true`, `would_be` shows enforce result. |
| `BLOCK` | Action is denied, do not execute |
| `PAUSE` | Action is held for later processing |
| `REQUIRE_APPROVAL` | Action requires human approval before execution |
| `SANDBOX` | Route action to sandbox/non-prod endpoint |
| `RATE_LIMIT` | Action exceeds rate limit, throttle (produced by rate limiter, not by rules — see Rate Limiting below) |
| `KILL_SWITCH` | Action blocked by kill switch (hard stop) |
| `ESCALATE` | Action escalated to higher authority |
| `ROUTE` | Action routed to specific handler/queue |

---

## Condition Syntax

Conditions are expressed as nested JSON/YAML trees. They support:
- Field path references (dot notation for nested fields)
- Comparison operators
- Logical operators (AND, OR, NOT)
- Set membership
- Pattern matching

### Condition Operators

#### Logical Operators

**`all_of`** (AND): All conditions must be true
```yaml
conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "environment"
      operator: "equals"
      value: "prod"
```

**`any_of`** (OR): At least one condition must be true
```yaml
conditions:
  any_of:
    - field: "sensitivity"
      operator: "contains"
      value: "money"
    - field: "sensitivity"
      operator: "contains"
      value: "irreversible"
```

**`none_of`** (NOT): None of the conditions may be true
```yaml
conditions:
  none_of:
    - field: "environment"
      operator: "equals"
      value: "dev"
```

#### Comparison Operators

| Operator | Types | Description |
|----------|-------|-------------|
| `equals` | all | Exact match (case-sensitive for strings) |
| `not_equals` | all | Not equal |
| `greater_than` | number | Numeric > comparison |
| `greater_than_or_equal` | number | Numeric >= comparison |
| `less_than` | number | Numeric < comparison |
| `less_than_or_equal` | number | Numeric <= comparison |
| `contains` | string, array | String substring or array element membership |
| `not_contains` | string, array | Inverse of contains |
| `starts_with` | string | String prefix match |
| `ends_with` | string | String suffix match |
| `matches` | string | Regex match (use sparingly, can be slow) |
| `in` | all | Value is in set (right-hand side is array) |
| `not_in` | all | Value is not in set |
| `exists` | all | Field exists in envelope (value is true/false) |

### Field Path Syntax

Use **dot notation** for nested fields:

| Field Path | Envelope Location |
|------------|-------------------|
| `action` | Top-level field |
| `parameters.amount` | Nested: `envelope.parameters.amount` |
| `target.account_id` | Nested: `envelope.target.account_id` |
| `cost_estimate.dollars` | Nested: `envelope.cost_estimate.dollars` |
| `sensitivity` | Array field (use `contains` operator) |

### Complex Condition Example

```yaml
name: "block-risky-prod-payments"
conditions:
  all_of:
    - field: "environment"
      operator: "equals"
      value: "prod"
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - any_of:
        - field: "parameters.amount"
          operator: "greater_than"
          value: 10000
        - all_of:
            - field: "parameters.amount"
              operator: "greater_than"
              value: 1000
            - field: "confidence"
              operator: "less_than"
              value: 0.8
decision: "REQUIRE_APPROVAL"
reason_code: "RISKY_PAYMENT"
```

**Evaluation**:
- Must be in `prod` environment
- Must be `process_payment` action
- AND (amount > $10,000 OR (amount > $1,000 AND confidence < 0.8))
- → REQUIRE_APPROVAL

---

## Layer 2: Policy Sets (Phase 1)

A **policy set** is a named collection of rules with:
- Version identifier
- Evaluation order
- Scope (org_id, environment)
- Metadata

### Policy Set Structure (YAML)

```yaml
policy_set:
  name: "payments-policy"
  version: "v2.1.0"
  description: "Payment processing controls for production"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  rules:
    - name: "kill-switch-all-payments"
      enabled: false  # Kill switch, disabled by default
      priority: 1000  # Highest priority
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "KILL_SWITCH"
      reason_code: "KILL_SWITCH_ACTIVE"

    - name: "block-payments-from-suspended-agents"
      enabled: true
      priority: 900
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "agent_id"
            operator: "in"
            value: ["agent-123", "agent-456"]  # Suspended agents
      decision: "BLOCK"
      reason_code: "AGENT_SUSPENDED"

    - name: "require-approval-high-value"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"
      route: "finance-review"  # Routes to route artifact
      metadata:
        sla_hours: 4

    - name: "allow-payments"
      enabled: true
      priority: 1  # Lowest priority, default allow
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"

  metadata:
    created_at: "2026-02-01T10:00:00Z"
    created_by: "admin@example.com"
    tags: ["payments", "production", "high-stakes"]

    # Rate limits applied post-evaluation to ALLOW decisions
    rate_limits:
      - scope: "agent_id"
        window: "hour"
        limit: 100
```

### Policy Set Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `policy_set.name` | string | Yes | Policy set identifier |
| `policy_set.version` | string | Yes | Semver version (v{major}.{minor}.{patch}) |
| `policy_set.description` | string | Yes | Human-readable description |
| `policy_set.scope` | object | Yes | Scope where this policy applies |
| `policy_set.rules` | array | Yes | List of rules (evaluated in priority order) |
| `policy_set.metadata` | object | No | Additional data (see Policy Metadata below) |

### Policy Metadata (Shareability & Presentation)

Policies are first-class product artifacts — shareable, forkable, presentable, and gradable. The metadata section supports this:

```yaml
metadata:
  # Identification
  author: "security-team@example.com"
  created_at: "2026-02-01T10:00:00Z"
  updated_at: "2026-02-14T10:00:00Z"

  # Shareability
  tags: ["payments", "production", "high-stakes", "pci-dss"]
  intended_use_case: "Payment processing controls for production AI agents"
  target_agent_types: ["payment-agent", "billing-agent"]

  # Template lineage
  template:
    source: "hiitl/templates/payments-basic"   # Template this was forked from
    source_version: "v1.0.0"                    # Version of the source template
    customizations: ["added-approval-threshold", "added-rate-limit"]

  # Visual rendering hints
  display:
    sections:
      - name: "Safety Controls"
        rules: ["kill-switch-all-payments", "block-payments-from-suspended-agents"]
        severity: "critical"
      - name: "Approval Workflows"
        rules: ["require-approval-high-value"]
        severity: "warning"
      - name: "Default Behavior"
        rules: ["allow-payments"]
        severity: "info"

  # Ecosystem references (compliance mapping)
  compliance_references:
    - standard: "SOC2"
      control_ids: ["CC6.1", "CC6.3"]
    - standard: "PCI-DSS"
      control_ids: ["6.4.1", "6.4.2"]

  # Grading hooks
  grading:
    expected_coverage: 0.85           # Expected percentage of actions covered
    minimum_grade_threshold: "B"       # Minimum acceptable grade
    test_scenario_refs: ["payments-basic", "payments-edge-cases"]
```

#### Metadata Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata.author` | string | No | Who created/maintains this policy |
| `metadata.created_at` | datetime | No | Creation timestamp |
| `metadata.updated_at` | datetime | No | Last modification timestamp |
| `metadata.tags` | array[string] | No | Categorization tags for search/filter |
| `metadata.intended_use_case` | string | No | Human-readable description of intended use case |
| `metadata.target_agent_types` | array[string] | No | Agent types this policy is designed for |
| `metadata.template` | object | No | Template lineage (if forked from a template) |
| `metadata.template.source` | string | No | Template identifier this was forked from |
| `metadata.template.source_version` | string | No | Version of the source template |
| `metadata.template.customizations` | array[string] | No | What was customized from the template |
| `metadata.display` | object | No | Visual rendering hints for UI presentation |
| `metadata.display.sections` | array[object] | No | Logical groupings of rules with severity |
| `metadata.compliance_references` | array[object] | No | External standard references (SOC2, PCI-DSS, EU AI Act, NIST AI RMF) |
| `metadata.grading` | object | No | Grading configuration for policy testing |

#### Template Semantics

Policy templates are pre-built, forkable policies for common use cases. Templates enable:

- **Onboarding acceleration** — developers start from a proven template, not a blank page
- **Distribution mechanism** — users discover ECP through well-designed templates for their use case
- **Best practices encoding** — templates embody best practices for specific domains

When a policy is forked from a template:
1. The `metadata.template.source` field records the template origin
2. The `metadata.template.source_version` records which version was forked
3. The `metadata.template.customizations` array describes what was changed
4. The forked policy is fully independent — changes to the template do not auto-propagate

#### Visual Rendering Requirements

The policy format must support clean presentation in a UI. The `metadata.display` section provides:

- **Section groupings** — rules organized into logical groups (safety, approvals, rate limits, defaults)
- **Severity indicators** — critical, warning, info levels for visual differentiation
- **Human-readable labels** — all rule names and descriptions must be presentable to non-developers

The UI renders policies attractively using these hints. A policy file should look professional when shared, not like raw config.

---

## Evaluation Semantics

### Evaluation Order (Deterministic)

Rules are evaluated in **priority order (highest to lowest)**. The first matching rule produces the decision.

**Exception**: DENY/BLOCK always wins. If any rule produces BLOCK, the action is blocked regardless of other rules.

### Precedence Rules

Fixed evaluation sequence (cannot be reconfigured):

1. **Kill switches** (priority 1000+)
2. **Deny rules / Blocks** (priority 900-999)
3. **Rate limits** (priority 500-899)
4. **Scope enforcement** (priority 400-499)
5. **Threshold checks** (priority 100-399)
6. **Approval requirements** (priority 50-99)
7. **Allow rules** (priority 1-49)

### Conflict Resolution

**Rule**: **DENY wins**.

If multiple rules match and any produces BLOCK, KILL_SWITCH, or other denial decision, the action is blocked.

This is **not configurable**. It is a design invariant.

### Evaluation is Side-Effect Free

Policy evaluation **reads state** (counters, config) but **never mutates it**.

- Counter increments happen **after** evaluation produces an ALLOW decision and the action proceeds
- Rate limit checks **read** the current counter value
- The counter increments **on execution**, not on evaluation

This ensures replay and simulation produce correct results without side effects.

---

## Layer 3: Policy Hierarchy (Interface Design - Phase 1, Implementation - Phase 2)

**Status**: Interface designed in Phase 1 schema, implemented when teams need it.

Policy hierarchy allows composition across scopes:
- **Org defaults** → apply to all agents in org
- **Team/project overrides** → apply to specific teams
- **Agent-specific policies** → apply to individual agents

### Hierarchy Rules (Design)

- More specific scopes can **tighten** constraints (cannot loosen)
- Clear precedence: Agent > Team > Org
- Policy sets at different scopes are **composed**, not replaced
- DENY always wins (even from broader scope)

### Scope Fields (Schema Support)

```yaml
scope:
  org_id: "org_abc123"
  environment: "prod"
  team_id: "team_payments"      # Phase 2
  project_id: "project_checkout" # Phase 2
  agent_id: "payment-agent"      # Phase 2
```

**Phase 1**: Only `org_id` and `environment` are required. Schema supports additional scoping dimensions but they are not implemented yet.

---

## Layer 4: Signal-Aware Conditions (Interface Design - Phase 1, Implementation - Phase 2)

**Status**: Interface designed in Phase 1, full implementation in Phase 2.

Rules can reference **external signal values** pushed into ECP by ecosystem partners.

### Signal Reference Syntax (Design)

```yaml
name: "block-on-high-risk-score"
conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "external.crowdstrike.risk_score"
      operator: "greater_than"
      value: 0.8
decision: "ESCALATE"
reason_code: "HIGH_RISK_SIGNAL"
```

**Field path `external.{source}.{signal_name}`**:
- `external.` prefix indicates signal reference
- `{source}` is the signal source system (crowdstrike, datadog, custom, etc.)
- `{signal_name}` is the signal field

### Signal Availability

Signals are:
- Injected via the **signal ingestion API** (Phase 2)
- Scoped to (org_id, environment, optional agent_id/action)
- Time-limited (TTL - signals expire)
- Versioned (signal schema version)

**Phase 1**: Policy schema supports signal references, but signal ingestion API is not implemented. Policies can be written with signal references for future use.

---

## Policy Versioning & Immutability

### Version Requirements

- All policy sets carry a **version identifier** (semver: `v{major}.{minor}.{patch}`)
- **Deployed versions are immutable** - never modified, only superseded
- **Rollback = activating a previous version**, not editing current version
- Breaking changes require major version bump + migration guide

### Backward Compatibility

- **New optional fields** can be added (minor version bump)
- **Existing fields cannot be removed** (major version bump required)
- **Field types cannot change** (major version bump required)
- **Evaluation semantics changes** require major version bump

### Policy Version in Decisions

Every decision includes the **policy version(s)** used in evaluation. This enables:
- Replay against historical policy version
- Debugging (know exactly what policy applied)
- Audit trail (what policy was in effect when action was evaluated)

---

## Storage

### Local Mode
- Policies loaded from **YAML/JSON files on disk**
- File path: `policies/{org_id}/{environment}/{policy_set_name}.yaml`
- Version = filename or embedded version field

### Hosted Mode
- Policies stored in **database** (PostgreSQL)
- Managed via **API** (CRUD operations)
- Immutable versioning (new version = new row, old row never updated)
- Active version tracked separately (can be changed to activate different version)

**"Policy is code"** means versioned, testable, and reviewable — database-backed versioning with API management achieves this.

---

## Policy Testing & Validation

### Validation Requirements

Before deploying a policy:

1. **Syntax validation**: YAML/JSON is well-formed
2. **Schema validation**: All required fields present, types correct
3. **Condition validation**: Field paths are valid, operators supported
4. **Decision validation**: Decision type is valid enum value
5. **Priority validation**: No duplicate priorities within policy set
6. **Replay simulation**: Test policy against recent traffic (dry-run)

### Policy Testing

Policies are code. Test them:

- **Unit tests**: Given envelope, assert expected decision
- **Integration tests**: Full policy set evaluation
- **Conformance tests**: Language-neutral test suite
- **Replay tests**: Historical envelopes against new policy version

---

## Policy Format Examples

### Example 1: Simple Allow/Deny

```yaml
policy_set:
  name: "dev-environment-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "dev"

  rules:
    - name: "allow-all-in-dev"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "environment"
            operator: "equals"
            value: "dev"
      decision: "ALLOW"
      reason_code: "DEV_ENVIRONMENT"
```

### Example 2: Rate Limiting

Rate limits are configured at the policy set level in `metadata.rate_limits`, not as individual rules.
They are applied post-evaluation to ALLOW decisions only (evaluation is side-effect free).

```yaml
policy_set:
  name: "email-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  rules:
    - name: "allow-emails"
      description: "Allow email sending"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"

  metadata:
    rate_limits:
      - scope: "user_id"
        window: "hour"
        limit: 50
```

When the rate limit is exceeded, the caller receives a `RATE_LIMIT` decision with metadata
including `scope`, `window`, `limit`, `current`, and `reset_at`. Multiple rate limits can
be configured in the array (e.g., 50/hour AND 10/minute); the first exceeded limit triggers.

### Example 3: Sensitive Action Approval

```yaml
- name: "require-approval-for-admin-grants"
  enabled: true
  priority: 200
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "grant_access"
      - field: "parameters.role"
        operator: "in"
        value: ["admin", "superuser", "root"]
  decision: "REQUIRE_APPROVAL"
  reason_code: "ADMIN_PERMISSION_GRANT"
  route: "security-review"
  metadata:
    sla_hours: 2
    reviewer_role: "security_team"
```

### Example 4: Block with Remediation

```yaml
- name: "block-protected-field-access"
  enabled: true
  priority: 800
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "search_users"
      - field: "parameters.fields"
        operator: "contains_any"
        value: ["ssn", "tax_id", "bank_account"]
  decision: "BLOCK"
  reason_code: "PROTECTED_FIELD_ACCESS"
  remediation:
    message: "Query includes protected fields that require elevated permissions."
    suggestion: "Remove protected fields and retry, or escalate to an authorized reviewer."
    type: "field_restriction"
    details:
      blocked_fields:
        ref: "parameters.fields"
        filter: ["ssn", "tax_id", "bank_account"]
      allowed_alternative:
        fields: ["name", "email", "department", "title", "start_date"]
```

When this rule triggers, the decision response includes the `remediation` object with the computed `blocked_fields` and `allowed_alternative`. An agent reading the remediation can remove the protected fields and retry successfully.

### Example 5: Kill Switch

```yaml
- name: "kill-switch-database-deletes"
  enabled: false  # Disabled by default, enabled when incident declared
  priority: 1000
  conditions:
    all_of:
      - field: "operation"
        operator: "equals"
        value: "delete"
      - field: "target.resource_type"
        operator: "equals"
        value: "database"
  decision: "KILL_SWITCH"
  reason_code: "KILL_SWITCH_ACTIVE_DATABASE_DELETES"
```

---

## Implementation Requirements

All policy evaluator implementations must:

1. **Parse YAML/JSON policy files** into internal representation
2. **Validate policy structure** against this specification
3. **Evaluate conditions** deterministically (same envelope + policy = same decision)
4. **Respect priority order** (highest priority first)
5. **Apply precedence rules** (DENY wins, fixed evaluation sequence)
6. **Pass conformance test suite** (language-neutral test cases)
7. **Return decision with metadata** (decision type, reason code, policy version, matched rule)
8. **Be side-effect free** (evaluation does not mutate state)

---

## Conformance Testing

The conformance test suite (`/tests/conformance/`) contains test cases in the format:

```json
{
  "test_name": "high_value_payment_requires_approval",
  "envelope": { /* full envelope JSON */ },
  "policy_set": { /* full policy set */ },
  "expected_decision": {
    "decision": "REQUIRE_APPROVAL",
    "reason_code": "HIGH_VALUE_PAYMENT",
    "matched_rule": "require-approval-high-value",
    "policy_version": "v2.1.0"
  }
}
```

Every evaluator implementation runs the full suite. All must produce identical decisions.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial policy format specification | Phase 0 Setup |
| 1.1 | 2026-02-16 | Added: policy metadata (shareability, templates, visual rendering, ecosystem references, grading hooks), HITL config references on escalation rules, template semantics | Strategic Evolution |
| 1.2 | 2026-02-24 | Renamed hitl_config → route on rules. Added remediation block on rules for BLOCK/RATE_LIMIT decisions. Updated all references from HITL Config Spec to Route Spec. | Strategic Evolution v2 |
| 1.3 | 2026-02-27 | Added rule `mode` field (observe/enforce). Renamed tool_name → action in envelope (backward compat preserved). Added OBSERVE decision type. | TICKET-028.1 |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Field paths referenced in conditions
- [Decision Response Spec](decision_response.md) - Decision output format
- [Route Spec](routes.md) - Route schema (external communication — outbound, inbound, bidirectional)
- [Infrastructure Analysis](../technical/ecp_infrastructure_analysis.md) - Custom evaluator decision

---

**This specification is the source of truth. Implementations follow the spec. If two implementations disagree, the spec decides.**
