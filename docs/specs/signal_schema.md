# Signal Ingestion Schema Specification

**Version**: 1.0
**Status**: Phase 0 Interface Design (Implementation in Phase 2)
**Last Updated**: 2026-02-14

---

## Purpose

This document defines the **signal schema** for external systems to push risk signals, anomaly flags, compliance state changes, and eval metrics into HIITL Execution Control Plane.

**Signal ingestion is a core integration surface** (CLAUDE.md line 109). It enables ecosystem partners (security platforms, eval tools, monitoring systems) to inform ECP's policy decisions at runtime.

**Phase 1**: Interface designed, policy format supports signal references
**Phase 2**: Full implementation of signal ingestion API

---

## What Are Signals?

**Signals** are external data points that inform policy evaluation.

Examples:
- Security platform (CrowdStrike) detects elevated risk score for an agent
- Eval tool (Braintrust) reports model drift above threshold
- Monitoring system (Datadog) signals system under load
- Compliance system flags regulatory restriction
- Custom system reports business metric threshold

Signals are:
- **Pushed into ECP** by external systems (not pulled)
- **Time-limited** (TTL - signals expire)
- **Scoped** to org, environment, and optionally agent/tool
- **Referenced in policy conditions** (Layer 4 of policy format)

---

## Signal vs. Envelope Context

**Envelope context** (envelope.confidence, envelope.sensitivity):
- Submitted by the agent/SDK at action time
- Part of the action request
- Agent's self-reported context

**Signals**:
- Pushed by external systems independent of actions
- Cached and available to policy evaluator
- External, authoritative sources (security vendors, eval platforms)

Policies can reference both.

---

## Signal Schema (JSON)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.ai/schemas/signal/v1.json",
  "title": "HIITL Signal",
  "description": "External signal pushed into ECP for policy evaluation",
  "type": "object",
  "required": [
    "signal_id",
    "source",
    "signal_type",
    "value",
    "scope",
    "timestamp",
    "ttl_seconds"
  ],
  "properties": {
    "signal_id": {
      "type": "string",
      "description": "Unique signal identifier. Format: sig_{ulid}",
      "pattern": "^sig_[a-zA-Z0-9]{20,}$"
    },
    "source": {
      "type": "string",
      "description": "Signal source system identifier",
      "examples": ["crowdstrike", "datadog", "braintrust", "custom"]
    },
    "signal_type": {
      "type": "string",
      "description": "Type of signal within source system",
      "examples": ["risk_score", "anomaly_detected", "model_drift", "system_load", "compliance_flag"]
    },
    "value": {
      "description": "Signal value. Type depends on signal_type.",
      "oneOf": [
        {"type": "number"},
        {"type": "string"},
        {"type": "boolean"},
        {"type": "object"}
      ]
    },
    "scope": {
      "type": "object",
      "description": "Scope where this signal applies",
      "required": ["org_id", "environment"],
      "properties": {
        "org_id": {"type": "string", "description": "Organization this signal applies to"},
        "environment": {"type": "string", "enum": ["dev", "stage", "prod"], "description": "Environment"},
        "agent_id": {"type": "string", "description": "Optional: specific agent"},
        "action": {"type": "string", "description": "Optional: specific action"}
      }
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when signal was generated"
    },
    "ttl_seconds": {
      "type": "integer",
      "description": "Time-to-live in seconds. Signal expires after this duration.",
      "minimum": 1,
      "maximum": 86400
    },
    "metadata": {
      "type": "object",
      "description": "Additional metadata from source system",
      "additionalProperties": true
    }
  }
}
```

---

## Signal Examples

### Example 1: Security Risk Score (CrowdStrike)

```json
{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8I",
  "source": "crowdstrike",
  "signal_type": "risk_score",
  "value": 0.85,
  "scope": {
    "org_id": "org_abc123",
    "environment": "prod",
    "agent_id": "payment-agent"
  },
  "timestamp": "2026-02-14T12:30:00Z",
  "ttl_seconds": 300,
  "metadata": {
    "detection_type": "behavioral_anomaly",
    "confidence": 0.92
  }
}
```

**Policy usage**:
```yaml
conditions:
  all_of:
    - field: "external.crowdstrike.risk_score"
      operator: "greater_than"
      value: 0.8
decision: "ESCALATE"
```

---

### Example 2: Model Drift (Braintrust)

```json
{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8J",
  "source": "braintrust",
  "signal_type": "model_drift",
  "value": true,
  "scope": {
    "org_id": "org_abc123",
    "environment": "prod",
    "agent_id": "customer-service-agent"
  },
  "timestamp": "2026-02-14T12:35:00Z",
  "ttl_seconds": 3600,
  "metadata": {
    "drift_metric": "accuracy",
    "baseline": 0.95,
    "current": 0.82
  }
}
```

**Policy usage**:
```yaml
conditions:
  all_of:
    - field: "external.braintrust.model_drift"
      operator: "equals"
      value: true
decision: "PAUSE"
reason_code: "MODEL_DRIFT_DETECTED"
```

---

### Example 3: System Load (Datadog)

```json
{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8K",
  "source": "datadog",
  "signal_type": "system_load",
  "value": {
    "cpu_percent": 85,
    "memory_percent": 90
  },
  "scope": {
    "org_id": "org_abc123",
    "environment": "prod"
  },
  "timestamp": "2026-02-14T12:40:00Z",
  "ttl_seconds": 60,
  "metadata": {
    "alert_level": "warning"
  }
}
```

**Policy usage**:
```yaml
conditions:
  all_of:
    - field: "external.datadog.system_load.cpu_percent"
      operator: "greater_than"
      value: 80
decision: "RATE_LIMIT"
metadata:
  rate_limit:
    window: "minute"
    limit: 10  # Reduce limit during high load
```

---

### Example 4: Compliance Flag (Custom System)

```json
{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8L",
  "source": "compliance-system",
  "signal_type": "regulatory_restriction",
  "value": "GDPR_DATA_FREEZE",
  "scope": {
    "org_id": "org_abc123",
    "environment": "prod",
    "action": "export_user_data"
  },
  "timestamp": "2026-02-14T12:45:00Z",
  "ttl_seconds": 86400,
  "metadata": {
    "jurisdiction": "EU",
    "restriction_reason": "Regulatory investigation active"
  }
}
```

**Policy usage**:
```yaml
conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "export_user_data"
    - field: "external.compliance-system.regulatory_restriction"
      operator: "exists"
      value: true
decision: "BLOCK"
reason_code: "REGULATORY_RESTRICTION_ACTIVE"
```

---

## Signal Lifecycle

### 1. Signal Ingestion (Phase 2 Implementation)

External system pushes signal via Signal Ingestion API:

```http
POST /v1/signals/ingest
Authorization: Bearer {service_token}
Content-Type: application/json

{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8I",
  "source": "crowdstrike",
  "signal_type": "risk_score",
  "value": 0.85,
  "scope": {
    "org_id": "org_abc123",
    "environment": "prod",
    "agent_id": "payment-agent"
  },
  "timestamp": "2026-02-14T12:30:00Z",
  "ttl_seconds": 300
}
```

Response:
```json
{
  "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8I",
  "status": "accepted",
  "expires_at": "2026-02-14T12:35:00Z"
}
```

### 2. Signal Storage

Signals stored in fast key-value store (Redis or equivalent):

**Key**: `signal:{org_id}:{environment}:{source}:{signal_type}:{scope_key}`

**Value**: Signal JSON

**TTL**: `ttl_seconds` (auto-expires)

**Scope key**:
- Global: `*` (no agent/tool specified)
- Agent-specific: `agent:{agent_id}`
- Action-specific: `action:{action}`

### 3. Signal Lookup During Evaluation

Policy references signal: `external.crowdstrike.risk_score`

Evaluator:
1. Parses field path: `external.{source}.{signal_type}`
2. Looks up signal: `signal:{org_id}:{env}:crowdstrike:risk_score:{scope_key}`
3. Tries scopes in order: agent-specific → tool-specific → global
4. Returns signal value (or null if not found/expired)
5. Evaluates condition with signal value

### 4. Signal Expiration

Signals auto-expire after `ttl_seconds`. Expired signals return null in policy evaluation.

**Why TTL is required**:
- Signals represent point-in-time state
- Stale signals lead to incorrect decisions
- External systems must refresh signals to keep them active

---

## Signal Scoping

Signals can apply at different scopes:

| Scope | Example | Policy Match |
|-------|---------|--------------|
| **Org + Environment** (Global) | System-wide load signal | Applies to all actions in org+env |
| **Org + Environment + Agent** | Risk score for specific agent | Applies to actions from that agent |
| **Org + Environment + Tool** | Compliance flag for specific tool | Applies to actions using that tool |

**Precedence**: Most specific scope wins.

Example:
- Signal A: `org_abc123 / prod / * → risk_score = 0.5` (global)
- Signal B: `org_abc123 / prod / agent:payment-agent → risk_score = 0.9` (agent-specific)

Action from `payment-agent` → uses Signal B (0.9)
Action from `other-agent` → uses Signal A (0.5)

---

## Signal Authentication

Signal ingestion uses **service-to-service authentication** (separate from developer API keys).

**Service tokens**:
- Issued per source system (e.g., CrowdStrike gets one token per org)
- Scoped to allowed signal sources (CrowdStrike token can only submit `source: "crowdstrike"` signals)
- Rotatable
- Different permission model (write signals, not evaluate actions)

**API endpoint security**:
```http
POST /v1/signals/ingest
Authorization: Bearer {service_token}
```

Validation:
1. Service token validated
2. Org extracted from token
3. Signal `scope.org_id` must match token's org
4. Signal `source` must match token's allowed sources
5. Rate limited (prevent abuse)

---

## Policy References to Signals (Layer 4)

Per Policy Format Spec (Layer 4):

### Field Path Syntax

```yaml
field: "external.{source}.{signal_type}"
```

Nested signal values:
```yaml
field: "external.datadog.system_load.cpu_percent"
```

### Condition Examples

**Numeric signal**:
```yaml
- field: "external.crowdstrike.risk_score"
  operator: "greater_than"
  value: 0.8
```

**Boolean signal**:
```yaml
- field: "external.braintrust.model_drift"
  operator: "equals"
  value: true
```

**String signal**:
```yaml
- field: "external.compliance-system.regulatory_restriction"
  operator: "in"
  value: ["GDPR_DATA_FREEZE", "CCPA_DATA_FREEZE"]
```

**Signal existence check**:
```yaml
- field: "external.datadog.incident_mode"
  operator: "exists"
  value: true
```

### Handling Missing Signals

If signal doesn't exist or has expired:
- Condition evaluates to `false` (does not match)
- Policy continues to next rule
- No error thrown

**Policy design tip**: Use signal existence checks when signal absence is meaningful:
```yaml
# Only apply rule if signal exists
all_of:
  - field: "external.crowdstrike.risk_score"
    operator: "exists"
    value: true
  - field: "external.crowdstrike.risk_score"
    operator: "greater_than"
    value: 0.8
```

---

## Signal Management API (Phase 2)

### Ingest Signal
```http
POST /v1/signals/ingest
```

### List Active Signals
```http
GET /v1/signals?org_id={org_id}&environment={env}
```

Response:
```json
{
  "signals": [
    {
      "signal_id": "sig_01HQZ8A1B2C3D4E5F6G7H8I",
      "source": "crowdstrike",
      "signal_type": "risk_score",
      "value": 0.85,
      "scope": {"org_id": "org_abc123", "environment": "prod", "agent_id": "payment-agent"},
      "expires_at": "2026-02-14T12:35:00Z"
    }
  ]
}
```

### Delete Signal (Manual Expiration)
```http
DELETE /v1/signals/{signal_id}
```

---

## Ecosystem Integration

### Security Platforms (CrowdStrike, Wiz, Palo Alto)

**Signal types**:
- `risk_score` - Numeric risk score (0.0-1.0)
- `anomaly_detected` - Boolean flag
- `threat_level` - String (low, medium, high, critical)

**Use case**: Block or escalate actions when security platform detects elevated risk.

### Observability Platforms (Datadog, Honeycomb, New Relic)

**Signal types**:
- `system_load` - Object with CPU, memory, etc.
- `incident_mode` - Boolean flag
- `error_rate` - Numeric percentage

**Use case**: Throttle actions during incidents or high load.

### Eval Tools (Braintrust, Weights & Biases)

**Signal types**:
- `model_drift` - Boolean flag
- `accuracy_drop` - Numeric percentage
- `eval_failure` - Boolean flag

**Use case**: Pause or sandbox actions when model quality degrades.

### GRC Platforms (Vanta, Drata, OneTrust)

**Signal types**:
- `compliance_flag` - String (regulation type)
- `audit_mode` - Boolean flag
- `policy_violation` - String (violation type)

**Use case**: Block actions that violate compliance policies.

---

## Signal Schema Versioning

**Signal schema version**: `v1.0`

**Backward compatibility**:
- New signal types can be added
- New source systems can be added
- Signal value structure can extend (add optional fields)
- Existing signal types cannot change structure (breaking)

**Migration**: If signal structure must change, use new signal_type name (e.g., `risk_score_v2`).

---

## Testing

### Signal Injection for Tests

Test harness can inject signals directly:
```python
# Test setup
test_signal = {
    "signal_id": "sig_test_123",
    "source": "crowdstrike",
    "signal_type": "risk_score",
    "value": 0.9,
    "scope": {"org_id": "org_test", "environment": "dev"},
    "timestamp": "2026-02-14T12:00:00Z",
    "ttl_seconds": 300
}
signal_store.inject(test_signal)

# Test evaluation
envelope = create_test_envelope(...)
decision = evaluator.evaluate(envelope, policy_set)
assert decision.decision == "ESCALATE"
```

### Conformance Tests

Signal-aware policy conformance tests:
```json
{
  "test_name": "escalate_on_high_risk_score",
  "envelope": { /* ... */ },
  "policy_set": { /* policy with external signal reference */ },
  "signals": [
    {
      "source": "crowdstrike",
      "signal_type": "risk_score",
      "value": 0.9,
      "scope": {"org_id": "org_test", "environment": "dev"}
    }
  ],
  "expected_decision": {
    "decision": "ESCALATE",
    "reason_code": "HIGH_RISK_SIGNAL"
  }
}
```

---

## Phase 1 vs. Phase 2

**Phase 1** (Interface Design):
- Signal schema defined
- Policy format supports signal references (`external.{source}.{signal_type}`)
- Policies can be written with signal references (will evaluate to null until signals exist)
- No signal ingestion API yet

**Phase 2** (Implementation):
- Signal ingestion API implemented
- Signal storage (Redis or equivalent)
- Service-to-service authentication
- Signal lookup during evaluation
- Signal management API (list, delete)
- Ecosystem partner integrations

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial signal schema specification (interface design) | Phase 0 Setup |

---

## Related Documents

- [Policy Format Spec](policy_format.md) - Layer 4: Signal-aware conditions
- [CLAUDE.md](../CLAUDE.md) - Ecosystem Integration Design (lines 367-391)
- [Infrastructure Analysis](../technical/ecp_infrastructure_analysis.md) - Integration surfaces

---

**This specification defines the interface for signal ingestion. Phase 2 implements the full API.**
