# Event & Audit Format Specification

**Version**: 1.0
**Status**: Phase 0 Specification
**Last Updated**: 2026-02-14

---

## Purpose

This document defines the **event and audit record format** for HIITL Execution Control Plane.

Events are produced for:
- **Audit log** (immutable, append-only record of all actions)
- **Ecosystem outbound** (structured events emitted to observability, GRC, and monitoring platforms via webhooks)

The format is designed with **OpenTelemetry compatibility** in mind (CLAUDE.md Infrastructure Analysis line 103).

---

## Design Principles

Per CLAUDE.md Infrastructure Spec #3 (lines 322-330):

1. **Immutable audit trail** - Append-only, no mutation, no soft-delete
2. **Every attempted action produces a record** - Even if blocked
3. **Structured, not narrative** - Machine-readable JSON with consistent field naming
4. **OTel-compatible** - Maps cleanly to OpenTelemetry spans and events
5. **Filterable** - Support filtering by decision type, tool, sensitivity, envelope fields

---

## Core Event Structure

### Event Schema (JSON)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.ai/schemas/event/v1.json",
  "title": "HIITL Audit Event",
  "description": "Audit record and outbound event format",
  "type": "object",
  "required": [
    "event_id",
    "event_type",
    "timestamp",
    "org_id",
    "environment",
    "action_id",
    "decision"
  ],
  "properties": {
    "event_id": {
      "type": "string",
      "description": "Unique event identifier. Format: evt_{ulid}",
      "pattern": "^evt_[a-zA-Z0-9]{20,}$"
    },
    "event_type": {
      "type": "string",
      "description": "Type of event",
      "enum": [
        "action.evaluated",
        "action.executed",
        "action.failed",
        "action.canceled",
        "action.escalated",
        "action.review_pending",
        "action.review_received",
        "action.resumed",
        "policy.changed",
        "kill_switch.activated",
        "kill_switch.deactivated",
        "control_plane.unavailable",
        "rate_limit.exceeded",
        "signature.invalid"
      ]
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when event occurred"
    },
    "org_id": {
      "type": "string",
      "description": "Organization identifier"
    },
    "environment": {
      "type": "string",
      "enum": ["dev", "stage", "prod"],
      "description": "Environment where event occurred"
    },
    "action_id": {
      "type": "string",
      "description": "Action identifier (from envelope)"
    },
    "idempotency_key": {
      "type": "string",
      "description": "Idempotency key (from envelope)"
    },
    "agent_id": {
      "type": "string",
      "description": "Agent identifier (from envelope)"
    },
    "user_id": {
      "type": "string",
      "description": "User identifier (from envelope)"
    },
    "action": {
      "type": "string",
      "description": "Action name (from envelope)"
    },
    "operation": {
      "type": "string",
      "description": "Operation type (from envelope)"
    },
    "decision": {
      "type": "string",
      "description": "Decision outcome",
      "enum": ["ALLOW", "BLOCK", "PAUSE", "REQUIRE_APPROVAL", "SANDBOX", "RATE_LIMIT", "KILL_SWITCH", "ESCALATE", "ROUTE", "SIGNATURE_INVALID", "CONTROL_PLANE_UNAVAILABLE"]
    },
    "reason_codes": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Reason codes explaining the decision"
    },
    "policy_version": {
      "type": "string",
      "description": "Policy version used in evaluation"
    },
    "matched_rules": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "rule_name": {"type": "string"},
          "policy_set": {"type": "string"},
          "priority": {"type": "integer"}
        }
      },
      "description": "Rules that matched"
    },
    "timing": {
      "type": "object",
      "properties": {
        "ingest_ms": {"type": "number"},
        "evaluation_ms": {"type": "number"},
        "total_ms": {"type": "number"}
      },
      "description": "Timing metadata"
    },
    "envelope": {
      "type": "object",
      "description": "Full or redacted envelope. Redaction per org policy."
    },
    "execution_result": {
      "type": "object",
      "description": "Execution result (if action was executed)",
      "properties": {
        "status": {
          "type": "string",
          "enum": ["succeeded", "failed", "canceled"]
        },
        "error": {"type": "string"},
        "duration_ms": {"type": "number"}
      }
    },
    "trace_id": {
      "type": "string",
      "description": "Distributed tracing trace ID (OTel compatible)"
    },
    "span_id": {
      "type": "string",
      "description": "Distributed tracing span ID (OTel compatible)"
    }
  }
}
```

---

## Event Types

### action.evaluated

**When**: Policy evaluation completed for an action

**Fields**:
- All core fields (event_id, timestamp, org_id, environment, action_id, decision, etc.)
- `envelope` - Full or redacted envelope
- `policy_version` - Policy version used
- `matched_rules` - Rules that produced decision
- `timing` - Evaluation timing

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8I",
  "event_type": "action.evaluated",
  "timestamp": "2026-02-14T12:34:56.789Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "agent_id": "payment-agent",
  "action": "process_payment",
  "operation": "execute",
  "decision": "REQUIRE_APPROVAL",
  "reason_codes": ["HIGH_VALUE_PAYMENT"],
  "policy_version": "v2.1.0",
  "matched_rules": [
    {"rule_name": "require-approval-high-value", "policy_set": "payments-policy", "priority": 100}
  ],
  "timing": {
    "ingest_ms": 0.5,
    "evaluation_ms": 1.2,
    "total_ms": 2.1
  },
  "envelope": {
    "parameters": {
      "amount": 5000,
      "currency": "usd"
    }
  }
}
```

---

### action.executed

**When**: Action was executed (decision was ALLOW or SANDBOX)

**Fields**:
- All fields from `action.evaluated`
- `execution_result` - Execution outcome (status, duration, error if failed)

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8J",
  "event_type": "action.executed",
  "timestamp": "2026-02-14T12:34:58.123Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "agent_id": "payment-agent",
  "action": "process_payment",
  "decision": "ALLOW",
  "execution_result": {
    "status": "succeeded",
    "duration_ms": 145.3
  }
}
```

---

### action.failed

**When**: Action execution failed (after ALLOW decision)

**Fields**:
- All fields from `action.executed`
- `execution_result.error` - Error message

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8K",
  "event_type": "action.failed",
  "timestamp": "2026-02-14T12:34:59.456Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "agent_id": "payment-agent",
  "action": "process_payment",
  "decision": "ALLOW",
  "execution_result": {
    "status": "failed",
    "error": "Payment gateway timeout",
    "duration_ms": 5002.1
  }
}
```

---

### kill_switch.activated

**When**: Kill switch policy rule was activated

**Fields**:
- Core fields
- `kill_switch_metadata` - Which tool/agent/scope was blocked

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8L",
  "event_type": "kill_switch.activated",
  "timestamp": "2026-02-14T12:35:00.000Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "kill_switch_metadata": {
    "rule_name": "kill-switch-all-payments",
    "scope": "tool",
    "action": "process_payment",
    "activated_by": "admin@example.com",
    "reason": "Suspected fraud pattern detected"
  }
}
```

---

### rate_limit.exceeded

**When**: Action exceeded rate limit

**Fields**:
- Core fields
- `rate_limit` - Counter state snapshot

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8M",
  "event_type": "rate_limit.exceeded",
  "timestamp": "2026-02-14T12:35:01.234Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "agent_id": "payment-agent",
  "action": "process_payment",
  "decision": "RATE_LIMIT",
  "rate_limit": {
    "scope": "agent_id",
    "window": "hour",
    "limit": 100,
    "current": 101,
    "reset_at": "2026-02-14T13:00:00Z"
  }
}
```

---

### signature.invalid

**When**: Envelope signature verification failed

**Fields**:
- Core fields
- `error` - Error details

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8N",
  "event_type": "signature.invalid",
  "timestamp": "2026-02-14T12:35:02.345Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "SIGNATURE_INVALID",
  "error": {
    "code": "SIGNATURE_VERIFICATION_FAILED",
    "message": "HMAC signature does not match"
  }
}
```

---

### action.escalated

**When**: Action was escalated to human review (decision was REQUIRE_APPROVAL, PAUSE, or ESCALATE)

**Fields**:
- All core fields
- `route_ref` - Name of the route used for this escalation
- `resume_token` - Token to correlate reviewer response back to this action
- `escalation_context` - What the reviewer will see and can do

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8P",
  "event_type": "action.escalated",
  "timestamp": "2026-02-14T12:34:56.789Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "agent_id": "payment-agent",
  "action": "process_payment",
  "decision": "REQUIRE_APPROVAL",
  "reason_codes": ["HIGH_VALUE_PAYMENT"],
  "route_ref": "finance-review",
  "resume_token": "rtk_01HQZ7B2C3D4E5F6G7H8I9J",
  "escalation_context": {
    "sla_seconds": 14400,
    "timeout_behavior": "escalate",
    "routing_target": "https://hooks.example.com/hiitl/finance-review"
  }
}
```

---

### action.review_pending

**When**: Escalation has been routed to a reviewer and is awaiting response

**Fields**:
- Core fields
- `resume_token` - Correlation token
- `routed_to` - Where the escalation was sent (reviewer identity or queue)

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8Q",
  "event_type": "action.review_pending",
  "timestamp": "2026-02-14T12:34:57.123Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "resume_token": "rtk_01HQZ7B2C3D4E5F6G7H8I9J",
  "routed_to": "finance-team-queue"
}
```

---

### action.review_received

**When**: A reviewer has submitted their response (approve, deny, modify, etc.)

**Fields**:
- Core fields
- `resume_token` - Correlation token
- `review_response` - The reviewer's decision, identity, reasoning, and any modifications

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8R",
  "event_type": "action.review_received",
  "timestamp": "2026-02-14T12:45:00.000Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "resume_token": "rtk_01HQZ7B2C3D4E5F6G7H8I9J",
  "review_response": {
    "decision": "approve",
    "reviewer_id": "user_finance_jane",
    "reason": "Verified with vendor, amount is correct",
    "modifications": null,
    "response_time_ms": 603123
  }
}
```

---

### action.resumed

**When**: A previously paused/escalated action has been resumed or canceled after review

**Fields**:
- Core fields
- `resume_token` - Correlation token
- `resume_outcome` - Whether the action was resumed for execution or canceled

**Example**:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8S",
  "event_type": "action.resumed",
  "timestamp": "2026-02-14T12:45:01.234Z",
  "org_id": "org_abc123",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "resume_token": "rtk_01HQZ7B2C3D4E5F6G7H8I9J",
  "resume_outcome": "execute",
  "review_response": {
    "decision": "approve",
    "reviewer_id": "user_finance_jane"
  }
}
```

---

## OpenTelemetry Compatibility

Per CLAUDE.md Infrastructure Analysis line 103:

Event format is designed to **map cleanly to OpenTelemetry spans and events**.

### OTel Span Mapping

HIITL event → OTel span:

| HIITL Field | OTel Span Field |
|-------------|-----------------|
| `event_id` | `span.id` |
| `trace_id` | `span.trace_id` |
| `timestamp` | `span.start_time` |
| `timing.total_ms` | `span.duration` |
| `event_type` | `span.name` |
| `org_id` | `span.attributes["org.id"]` |
| `agent_id` | `span.attributes["agent.id"]` |
| `action` | `span.attributes["action"]` |
| `decision` | `span.attributes["decision"]` |
| `policy_version` | `span.attributes["policy.version"]` |

### OTel Event Emission (Phase 2)

Phase 2 includes full OTel export:
- Span exporter configured for ECP
- Spans emitted to OTel collectors
- Compatible with Datadog, Honeycomb, New Relic, etc.

Phase 1: Event structure supports OTel mapping but export is via webhooks, not native OTel protocol.

---

## Audit Log Storage

Per CLAUDE.md Infrastructure Spec #3 (lines 322-330):

### Append-Only Requirement

- **No UPDATE or DELETE** on audit log table
- INSERT-only access for application
- Retention policy archives/deletes old records (per org configuration)

### Storage Fields (Database Schema)

```sql
CREATE TABLE audit_log (
  event_id VARCHAR(64) PRIMARY KEY,
  event_type VARCHAR(64) NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL,
  org_id VARCHAR(64) NOT NULL,
  environment VARCHAR(16) NOT NULL,
  action_id VARCHAR(64) NOT NULL,
  idempotency_key VARCHAR(255),
  agent_id VARCHAR(128),
  user_id VARCHAR(128),
  action VARCHAR(128),
  operation VARCHAR(16),
  decision VARCHAR(64) NOT NULL,
  reason_codes JSONB,
  policy_version VARCHAR(64),
  matched_rules JSONB,
  timing JSONB,
  envelope JSONB,
  execution_result JSONB,
  trace_id VARCHAR(128),
  span_id VARCHAR(128),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_audit_org_env_time ON audit_log(org_id, environment, timestamp DESC);
CREATE INDEX idx_audit_action_id ON audit_log(action_id);
CREATE INDEX idx_audit_agent_id ON audit_log(agent_id, timestamp DESC);
CREATE INDEX idx_audit_action ON audit_log(action, timestamp DESC);
CREATE INDEX idx_audit_decision ON audit_log(decision, timestamp DESC);

-- Ensure org_id isolation (row-level security if supported)
-- ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY audit_org_isolation ON audit_log FOR ALL USING (org_id = current_setting('app.org_id'));
```

### Partitioning (for scale)

Time-partitioned by month:
```sql
-- Partition by month for efficient retention
CREATE TABLE audit_log_2026_02 PARTITION OF audit_log
  FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
```

Old partitions can be dropped for retention.

---

## Redaction

Per CLAUDE.md Security Requirements (line 170):

Sensitive parameters must be redactable before audit log storage.

### Redaction Policy

Org-level configuration:
```yaml
redaction_policy:
  mode: "auto"  # auto, manual, none
  auto_redact_patterns:
    - "password"
    - "secret"
    - "api_key"
    - "token"
    - "ssn"
    - "credit_card"
  manual_redact_fields:
    - "parameters.account_number"
    - "target.email"
```

### Redacted Envelope Example

Original:
```json
{
  "parameters": {
    "account_number": "1234567890",
    "amount": 500
  }
}
```

Redacted:
```json
{
  "parameters": {
    "account_number": "[REDACTED]",
    "amount": 500
  }
}
```

**Important**: Redaction happens **after policy evaluation** (evaluation sees full envelope).

---

## Webhook Emission (Outbound Events)

Per CLAUDE.md Ecosystem Integration (lines 375-382):

### Webhook Configuration

Orgs can configure webhook endpoints to receive events:

```yaml
webhooks:
  - name: "datadog-integration"
    url: "https://webhook.site/datadog"
    events: ["action.evaluated", "action.executed", "rate_limit.exceeded"]
    filters:
      decision: ["BLOCK", "KILL_SWITCH", "RATE_LIMIT"]
      environment: ["prod"]
    authentication:
      type: "hmac"
      secret: "webhook_secret_abc123"
    retry:
      max_attempts: 3
      backoff: "exponential"
```

### Webhook Payload

Same format as audit event:
```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7H8I",
  "event_type": "action.evaluated",
  "timestamp": "2026-02-14T12:34:56.789Z",
  ...
}
```

**Webhook signature** (HMAC-SHA256):
```
X-HIITL-Signature: sha256=a1b2c3d4...
```

Customer verifies signature to ensure webhook is from HIITL.

---

## Event Filtering

Webhooks support filtering by:
- `event_type` - Which event types to receive
- `decision` - Which decision outcomes (e.g., only BLOCK and KILL_SWITCH)
- `environment` - Which environments (e.g., only prod)
- `action` - Specific actions
- `agent_id` - Specific agents
- `sensitivity` - Actions with specific sensitivity flags

This prevents sending irrelevant events to consumers.

---

## Retention Policy

Per CLAUDE.md Infrastructure Spec #3 (line 330):

- **Configurable retention per org**
- Default: 7-30 days (free tier)
- Enterprise: configurable, potentially indefinite

### Retention Enforcement

Automated background job:
- Runs daily
- Deletes/archives events older than org's retention window
- Partitioned tables make deletion efficient (DROP PARTITION)

### Export Before Deletion

Orgs can export audit logs before retention window expires:
- Export API: GET `/v1/audit/export?start_date=...&end_date=...`
- Format: JSON lines, CSV
- Large exports streamed (not buffered in memory)

---

## Conformance Testing

Event format validated in test suite:

```json
{
  "test_name": "audit_event_format",
  "envelope": { /* ... */ },
  "policy_set": { /* ... */ },
  "expected_event": {
    "event_type": "action.evaluated",
    "decision": "REQUIRE_APPROVAL",
    "reason_codes": ["HIGH_VALUE_PAYMENT"],
    "policy_version": "v2.1.0"
  }
}
```

All implementations produce events matching specification.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial event format specification | Phase 0 Setup |
| 1.1 | 2026-02-16 | Added: escalation lifecycle events (action.escalated, action.review_pending, action.review_received, action.resumed) with HITL config references | Strategic Evolution |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Source data for events
- [Decision Response Spec](decision_response.md) - Decision metadata included in events
- [Policy Format Spec](policy_format.md) - Policy version tracking
- [Route Spec](routes.md) - Route schema (escalation, routing, SLA)
- [HITL Config Spec](hitl_config.md) - *(Deprecated — replaced by routes.md)*
- [Security Requirements](../security/security_requirements.md) - Redaction requirements
- [CLAUDE.md](../../CLAUDE.md) - Audit trail requirements

---

**This specification is the source of truth for event and audit format.**
