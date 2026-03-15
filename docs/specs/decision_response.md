# Decision Response Specification

**Version**: 1.4
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-02-27

---

## Purpose

This document defines the **decision response** format returned by HIITL Execution Control Plane after policy evaluation.

The decision response is what the SDK caller receives. It must contain:
- The decision outcome (allow, block, pause, etc.)
- Reason codes explaining why
- Timing metadata (for transparency)
- Policy version used (for audit and replay)
- Counter state (for rate limits)
- Any additional metadata needed for the caller to act

All SDK implementations (TypeScript, Python, and future languages) must conform to this specification.

---

## Design Principles

Per CLAUDE.md:

1. **Deterministic** - Same (envelope, policy) always produces same decision
2. **Transparent** - Include timing metadata so developers can measure latency impact
3. **Auditable** - Include policy version and reason codes for debugging
4. **Actionable** - Include sufficient context for caller to handle decision (e.g., counter state for rate limits)
5. **Language-neutral** - Defined as a spec, serializable to/from JSON

---

## Decision Response Structure

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.ai/schemas/decision-response/v1.json",
  "title": "HIITL Decision Response",
  "description": "Response returned after policy evaluation",
  "type": "object",
  "required": [
    "action_id",
    "decision",
    "reason_codes",
    "policy_version",
    "timing",
    "allowed"
  ],
  "properties": {
    "action_id": {
      "type": "string",
      "description": "Echo of the action_id from the envelope. For correlation."
    },
    "decision": {
      "type": "string",
      "enum": [
        "ALLOW",
        "OBSERVE",
        "BLOCK",
        "PAUSE",
        "REQUIRE_APPROVAL",
        "SANDBOX",
        "RATE_LIMIT",
        "KILL_SWITCH",
        "ESCALATE",
        "ROUTE",
        "SIGNATURE_INVALID",
        "CONTROL_PLANE_UNAVAILABLE"
      ],
      "description": "The decision outcome"
    },
    "allowed": {
      "type": "boolean",
      "description": "Convenience boolean: true if decision is ALLOW or SANDBOX, false otherwise"
    },
    "reason_codes": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Machine-readable reason codes explaining the decision"
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
      "description": "Rules that matched and contributed to the decision"
    },
    "policy_version": {
      "type": "string",
      "description": "Version of the policy set used for evaluation. Enables replay and audit."
    },
    "timing": {
      "type": "object",
      "required": ["ingest_ms", "evaluation_ms", "total_ms"],
      "properties": {
        "ingest_ms": {
          "type": "number",
          "description": "Time spent ingesting and validating envelope (milliseconds)"
        },
        "evaluation_ms": {
          "type": "number",
          "description": "Time spent in policy evaluation (milliseconds)"
        },
        "total_ms": {
          "type": "number",
          "description": "Total request latency (milliseconds)"
        }
      }
    },
    "rate_limit": {
      "type": "object",
      "description": "Rate limit state. Present if decision is RATE_LIMIT or if approaching limit.",
      "properties": {
        "scope": {"type": "string", "description": "Rate limit scope (agent_id, user_id, etc.)"},
        "window": {"type": "string", "description": "Time window (minute, hour, day)"},
        "limit": {"type": "integer", "description": "Maximum allowed in window"},
        "current": {"type": "integer", "description": "Current count in window"},
        "reset_at": {"type": "string", "format": "date-time", "description": "When counter resets"}
      }
    },
    "resume_token": {
      "type": "string",
      "description": "Token to correlate the reviewer's response back to the paused action. Present for REQUIRE_APPROVAL, PAUSE, and ESCALATE decisions. Used by the caller to resume or cancel the action after review."
    },
    "route_ref": {
      "type": "string",
      "description": "Name of the route artifact used for this escalation. References the route that defines how external communication works for this action (escalation context, response schema, SLA, routing target). Present for REQUIRE_APPROVAL, PAUSE, and ESCALATE decisions. Formerly 'hitl_config_ref'."
    },
    "escalation_context": {
      "type": "object",
      "description": "Context for the escalation workflow. Present for REQUIRE_APPROVAL, PAUSE, and ESCALATE decisions. Provides the caller with information about the escalation process.",
      "properties": {
        "sla_seconds": {"type": "integer", "description": "Expected response time in seconds"},
        "timeout_behavior": {"type": "string", "enum": ["escalate", "auto_deny", "auto_approve", "extend"], "description": "What happens if SLA is exceeded"},
        "available_responses": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Response types available to the reviewer (e.g., approve, deny, modify)"
        },
        "routing_target": {"type": "string", "description": "Where the escalation is routed (webhook URL, queue name, role)"},
        "resume_url": {"type": "string", "description": "URL to resume execution after approval (hosted mode)"}
      }
    },
    "approval_metadata": {
      "type": "object",
      "description": "Legacy approval workflow metadata. Present if decision is REQUIRE_APPROVAL. Prefer resume_token + hitl_config_ref + escalation_context for new integrations.",
      "properties": {
        "approval_id": {"type": "string", "description": "Unique identifier for this approval request"},
        "sla_hours": {"type": "number", "description": "Expected SLA for approval (hours)"},
        "reviewer_role": {"type": "string", "description": "Role required to approve"},
        "resume_url": {"type": "string", "description": "URL to resume execution after approval"}
      }
    },
    "sandbox_metadata": {
      "type": "object",
      "description": "Sandbox routing metadata. Present if decision is SANDBOX.",
      "properties": {
        "sandbox_endpoint": {"type": "string", "description": "Sandbox endpoint to route to"},
        "sandbox_environment": {"type": "string", "description": "Sandbox environment name"}
      }
    },
    "remediation": {
      "type": "object",
      "description": "Structured, actionable guidance for BLOCK and RATE_LIMIT decisions. Present only when the evaluation succeeded and the action was intentionally blocked by policy. Mutually exclusive with 'error' (error means ECP itself failed; remediation means ECP worked correctly and enforced a policy). See 'Remediation Types' section below for type-specific details schemas.",
      "required": ["message", "suggestion", "type"],
      "properties": {
        "message": {"type": "string", "description": "Human-readable explanation of why the action was blocked"},
        "suggestion": {"type": "string", "description": "Actionable next step for the caller or agent"},
        "type": {
          "type": "string",
          "enum": ["field_restriction", "threshold", "scope", "rate_limit", "temporal", "custom"],
          "description": "Remediation type — determines the structure of the details object"
        },
        "details": {
          "type": "object",
          "description": "Type-specific structured fields. Schema depends on remediation type — see 'Remediation Types' section.",
          "additionalProperties": true
        }
      }
    },
    "would_be": {
      "type": "string",
      "description": "Original decision type when in OBSERVE mode. Shows what enforce mode would have decided. Present only when decision is OBSERVE.",
      "enum": ["ALLOW", "BLOCK", "PAUSE", "REQUIRE_APPROVAL", "SANDBOX", "RATE_LIMIT", "KILL_SWITCH", "ESCALATE", "ROUTE"]
    },
    "would_be_reason_codes": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Original reason codes when in OBSERVE mode. Shows the reason codes that enforce mode would have returned. Present only when decision is OBSERVE."
    },
    "error": {
      "type": "object",
      "description": "Error details. Present if evaluation failed (ECP internal error). Mutually exclusive with 'remediation'. Error means something went wrong with ECP itself; remediation means ECP successfully enforced a policy.",
      "properties": {
        "code": {"type": "string", "description": "Error code"},
        "message": {"type": "string", "description": "Human-readable error message"}
      }
    },
    "metadata": {
      "type": "object",
      "description": "Additional metadata from policy evaluation",
      "additionalProperties": true
    }
  }
}
```

---

## Decision Types

### Core Decisions (Phase 1)

| Decision | `allowed` | Description | Typical Caller Action |
|----------|-----------|-------------|----------------------|
| `ALLOW` | `true` | Action is permitted | Execute the action |
| `OBSERVE` | `true` | Action observed (not enforced). `would_be` shows enforce result | Execute the action, review `would_be` for what enforcement would do |
| `BLOCK` | `false` | Action is denied by policy | Do not execute, log reason |
| `PAUSE` | `false` | Action is held for later processing | Store for later, poll for resolution |
| `REQUIRE_APPROVAL` | `false` | Action requires human approval | Route to approval queue, wait for decision |
| `SANDBOX` | `true` | Route to sandbox/non-prod endpoint | Execute but use sandbox environment |
| `RATE_LIMIT` | `false` | Action exceeds rate limit | Backoff and retry after `reset_at` |
| `KILL_SWITCH` | `false` | Action blocked by kill switch (hard stop) | Do not execute, alert ops team |
| `ESCALATE` | `false` | Action escalated to higher authority | Route to escalation queue |
| `ROUTE` | `false` | Action routed to specific handler | Send to specific queue/handler |

### Error Decisions

| Decision | Description | Typical Caller Action |
|----------|-------------|----------------------|
| `SIGNATURE_INVALID` | Envelope signature verification failed | Fix SDK signature, do not retry |
| `CONTROL_PLANE_UNAVAILABLE` | ECP is unreachable, fail mode applied | Check fail mode (FAIL_CLOSED: block, FAIL_OPEN: allow with warning) |

---

## Response Examples

### Example 1: ALLOW

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "ALLOW",
  "allowed": true,
  "reason_codes": ["DEFAULT_ALLOW"],
  "matched_rules": [
    {
      "rule_name": "allow-payments",
      "policy_set": "payments-policy",
      "priority": 1
    }
  ],
  "policy_version": "v2.1.0",
  "timing": {
    "ingest_ms": 0.5,
    "evaluation_ms": 1.2,
    "total_ms": 2.1
  }
}
```

**Caller action**: Execute the action.

---

### Example 2: OBSERVE (would-be BLOCK)

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "OBSERVE",
  "allowed": true,
  "reason_codes": ["OBSERVED"],
  "would_be": "BLOCK",
  "would_be_reason_codes": ["AMOUNT_EXCEEDS_LIMIT"],
  "matched_rules": [
    {
      "rule_name": "block-high-value-payments",
      "policy_set": "payments-policy",
      "priority": 900
    }
  ],
  "policy_version": "v2.1.0",
  "timing": {
    "ingest_ms": 0.4,
    "evaluation_ms": 0.9,
    "total_ms": 1.7
  }
}
```

**Caller action**: Execute the action (OBSERVE mode does not enforce). Review `would_be` to see what enforcement would have done. Use this to validate policies before enabling enforcement.

---

### Example 3: BLOCK (with remediation)

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "BLOCK",
  "allowed": false,
  "reason_codes": ["AMOUNT_EXCEEDS_LIMIT"],
  "matched_rules": [
    {
      "rule_name": "block-high-value-payments",
      "policy_set": "payments-policy",
      "priority": 900
    }
  ],
  "policy_version": "v2.1.0",
  "timing": {
    "ingest_ms": 0.4,
    "evaluation_ms": 0.9,
    "total_ms": 1.7
  },
  "remediation": {
    "message": "Payment amount of $15,000 exceeds the $10,000 limit.",
    "suggestion": "Reduce amount to $10,000 or below, or request approval for higher amounts.",
    "type": "threshold",
    "details": {
      "threshold": 10000,
      "current_value": 15000,
      "max_allowed": 10000
    }
  }
}
```

**Caller action**: Do not execute. Read `remediation.message` for human-readable explanation. Agent can use `remediation.details` to self-correct and retry (e.g., reduce amount).

---

### Example 4: REQUIRE_APPROVAL

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "REQUIRE_APPROVAL",
  "allowed": false,
  "reason_codes": ["HIGH_VALUE_PAYMENT"],
  "matched_rules": [
    {
      "rule_name": "require-approval-high-value",
      "policy_set": "payments-policy",
      "priority": 100
    }
  ],
  "policy_version": "v2.1.0",
  "timing": {
    "ingest_ms": 0.5,
    "evaluation_ms": 1.1,
    "total_ms": 2.0
  },
  "resume_token": "rtk_01HQZ7B2C3D4E5F6G7H8I9J",
  "route_ref": "finance-review",
  "escalation_context": {
    "sla_seconds": 14400,
    "timeout_behavior": "escalate",
    "available_responses": ["approve", "deny", "modify"],
    "routing_target": "https://hooks.example.com/hiitl/finance-review",
    "resume_url": "https://api.hiitl.ai/v1/actions/act_01HQZ6X8Z9P5ABCDEFGHIJK/resume"
  }
}
```

**Caller action**:
1. Do not execute immediately
2. Use `resume_token` to correlate this escalation with the reviewer's response
3. Route to the target specified in `escalation_context.routing_target` (webhook, queue, or internal handler)
4. Wait for reviewer response (poll `resume_url` or receive webhook callback)
5. Resume execution after approval granted using `resume_token`

---

### Example 5: RATE_LIMIT

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "RATE_LIMIT",
  "allowed": false,
  "reason_codes": ["RATE_LIMIT_EXCEEDED"],
  "matched_rules": [
    {
      "rule_name": "rate-limit-payments-per-agent",
      "policy_set": "payments-policy",
      "priority": 50
    }
  ],
  "policy_version": "v2.1.0",
  "timing": {
    "ingest_ms": 0.4,
    "evaluation_ms": 0.8,
    "total_ms": 1.5
  },
  "rate_limit": {
    "scope": "agent_id",
    "window": "hour",
    "limit": 100,
    "current": 100,
    "reset_at": "2026-02-14T14:00:00Z"
  }
}
```

**Caller action**:
1. Do not execute
2. Wait until `reset_at` or implement exponential backoff
3. Retry after rate limit window resets

**SDK helper**: Provide `wait_until_reset()` method that sleeps until `reset_at`.

---

### Example 6: KILL_SWITCH

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "KILL_SWITCH",
  "allowed": false,
  "reason_codes": ["KILL_SWITCH_ACTIVE_DATABASE_DELETES"],
  "matched_rules": [
    {
      "rule_name": "kill-switch-database-deletes",
      "policy_set": "global-kill-switches",
      "priority": 1000
    }
  ],
  "policy_version": "v1.0.0",
  "timing": {
    "ingest_ms": 0.3,
    "evaluation_ms": 0.5,
    "total_ms": 1.0
  }
}
```

**Caller action**:
1. Do not execute
2. Alert operations team (kill switch activated)
3. Do not retry (kill switch is intentional block)

---

### Example 7: SANDBOX

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "SANDBOX",
  "allowed": true,
  "reason_codes": ["SANDBOX_MODE_ENABLED"],
  "matched_rules": [
    {
      "rule_name": "sandbox-all-payments-in-dev",
      "policy_set": "dev-policy",
      "priority": 10
    }
  ],
  "policy_version": "v1.0.0",
  "timing": {
    "ingest_ms": 0.4,
    "evaluation_ms": 0.7,
    "total_ms": 1.3
  },
  "sandbox_metadata": {
    "sandbox_endpoint": "https://sandbox-api.stripe.com",
    "sandbox_environment": "test"
  }
}
```

**Caller action**:
1. Execute the action
2. BUT use `sandbox_endpoint` instead of production endpoint
3. Flag execution as sandbox in logs

---

### Example 8: SIGNATURE_INVALID (Error)

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "SIGNATURE_INVALID",
  "allowed": false,
  "reason_codes": ["ENVELOPE_SIGNATURE_VERIFICATION_FAILED"],
  "matched_rules": [],
  "policy_version": null,
  "timing": {
    "ingest_ms": 0.2,
    "evaluation_ms": 0.0,
    "total_ms": 0.3
  },
  "error": {
    "code": "SIGNATURE_INVALID",
    "message": "Envelope signature verification failed. Possible tampering or incorrect secret key."
  }
}
```

**Caller action**:
1. Do not execute
2. Check SDK configuration (is secret key correct?)
3. Investigate potential envelope tampering
4. Do not retry with same envelope (signature will still fail)

---

### Example 9: CONTROL_PLANE_UNAVAILABLE (Outage)

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "CONTROL_PLANE_UNAVAILABLE",
  "allowed": false,
  "reason_codes": ["CONTROL_PLANE_TIMEOUT"],
  "matched_rules": [],
  "policy_version": null,
  "timing": {
    "ingest_ms": 0.0,
    "evaluation_ms": 0.0,
    "total_ms": 5000.0
  },
  "error": {
    "code": "CONTROL_PLANE_UNAVAILABLE",
    "message": "ECP control plane is unreachable. Fail-closed mode applied."
  },
  "metadata": {
    "fail_mode": "FAIL_CLOSED",
    "circuit_breaker_state": "open"
  }
}
```

**Caller action**:
1. If `fail_mode` is `FAIL_CLOSED`: Do not execute (fail safe)
2. If `fail_mode` is `FAIL_OPEN`: Execute with warning logged (fail permissive)
3. Alert operations team (ECP unavailable)
4. Circuit breaker is open - subsequent calls will fail fast

---

## Remediation Types

Remediation provides structured, actionable guidance when a policy intentionally blocks an action. The `remediation.type` field determines the schema of `remediation.details`.

### Invariant: Error vs Remediation

A decision **MUST NOT** include both `error` and `remediation`:
- **`error`** = ECP itself failed (signature invalid, control plane unavailable, policy parse error). The action was not evaluated.
- **`remediation`** = ECP worked correctly and intentionally blocked the action by policy. The action was evaluated and denied.

If `error` is present, `remediation` MUST be absent, and vice versa. Implementations enforce this at the type level.

### Type: `field_restriction`

Blocked because specific fields or values are restricted.

**Details schema:**
| Field | Type | Description |
|-------|------|-------------|
| `blocked_fields` | `string[]` | Fields that caused the block |
| `allowed_fields` | `string[]` | Fields that are permitted |
| `field_ref` | `string` | Envelope field path containing restricted values |

```json
{
  "remediation": {
    "message": "Query includes protected fields that require elevated permissions.",
    "suggestion": "Remove 'ssn' and 'tax_id' from requested fields, or escalate to an authorized reviewer.",
    "type": "field_restriction",
    "details": {
      "blocked_fields": ["ssn", "tax_id"],
      "allowed_fields": ["name", "email", "department", "title"],
      "field_ref": "parameters.fields"
    }
  }
}
```

### Type: `threshold`

Blocked because a numeric value exceeds a configured limit.

**Details schema:**
| Field | Type | Description |
|-------|------|-------------|
| `threshold` | `number` | The limit that was exceeded |
| `current_value` | `number` | The value the action attempted |
| `max_allowed` | `number` | Maximum permitted value |
| `field` | `string` | Envelope field path that exceeded the threshold |

```json
{
  "remediation": {
    "message": "Payment amount of $15,000 exceeds the $10,000 limit.",
    "suggestion": "Reduce amount to $10,000 or below, or request approval for higher amounts.",
    "type": "threshold",
    "details": {
      "threshold": 10000,
      "current_value": 15000,
      "max_allowed": 10000,
      "field": "parameters.amount"
    }
  }
}
```

### Type: `scope`

Blocked because the action is outside the permitted scope.

**Details schema:**
| Field | Type | Description |
|-------|------|-------------|
| `required_scope` | `string` | Permission or scope needed |
| `current_scope` | `string` | What the caller currently has |
| `allowed_scopes` | `string[]` | All scopes that would satisfy the requirement |
| `scope_type` | `string` | Type of scope (e.g., "tool", "operation", "environment") |

```json
{
  "remediation": {
    "message": "This tool requires 'finance:write' scope.",
    "suggestion": "Request 'finance:write' scope, or use a tool within your current permissions.",
    "type": "scope",
    "details": {
      "required_scope": "finance:write",
      "current_scope": "finance:read",
      "allowed_scopes": ["finance:write", "finance:admin"],
      "scope_type": "tool"
    }
  }
}
```

### Type: `rate_limit`

Blocked because the rate limit was exceeded.

**Details schema:**
| Field | Type | Description |
|-------|------|-------------|
| `limit` | `integer` | Maximum allowed in window |
| `current` | `integer` | Current count in window |
| `reset_at` | `string (date-time)` | When the counter resets |
| `scope` | `string` | Rate limit scope (agent_id, user_id, etc.) |
| `window` | `string` | Time window (minute, hour, day) |

```json
{
  "remediation": {
    "message": "Rate limit exceeded: 100 actions per hour.",
    "suggestion": "Wait until 14:00 UTC when the rate limit window resets, or reduce action frequency.",
    "type": "rate_limit",
    "details": {
      "limit": 100,
      "current": 100,
      "reset_at": "2026-02-14T14:00:00Z",
      "scope": "agent_id",
      "window": "hour"
    }
  }
}
```

### Type: `temporal`

Blocked because the action was attempted outside an allowed time window.

**Details schema:**
| Field | Type | Description |
|-------|------|-------------|
| `allowed_window` | `object` | Time window when action is permitted (`start`, `end`) |
| `timezone` | `string` | Timezone for the window |
| `next_allowed_at` | `string (date-time)` | Earliest time the action can succeed |
| `current_time` | `string` | When the action was attempted |

```json
{
  "remediation": {
    "message": "Bulk data exports are only permitted between 02:00-06:00 UTC.",
    "suggestion": "Retry after 02:00 UTC, or request an exception for off-hours exports.",
    "type": "temporal",
    "details": {
      "allowed_window": {"start": "02:00", "end": "06:00"},
      "timezone": "UTC",
      "next_allowed_at": "2026-02-15T02:00:00Z",
      "current_time": "2026-02-14T15:30:00Z"
    }
  }
}
```

### Type: `custom`

Free-form remediation for policy-specific guidance that doesn't fit the standard types.

**Details schema:** Any valid JSON object (`additionalProperties: true`).

```json
{
  "remediation": {
    "message": "Action blocked by compliance policy CP-2024-07.",
    "suggestion": "Contact compliance@example.com for policy exception.",
    "type": "custom",
    "details": {
      "policy_ref": "CP-2024-07",
      "contact": "compliance@example.com",
      "documentation_url": "https://internal.example.com/compliance/cp-2024-07"
    }
  }
}
```

---

## Timing Metadata (Transparency)

Per CLAUDE.md line 411:

**Every decision response includes timing metadata**. Developers must never wonder "is this slowing me down?"

**Timing fields**:
- `ingest_ms` - Time to validate envelope, check signature, extract org_id
- `evaluation_ms` - Time spent in policy evaluation engine
- `total_ms` - Full round-trip latency (includes network if hosted mode)

**Latency targets**:
- **Hybrid mode** (default): Microsecond evaluation (in-process, no I/O)
- **Pure local mode**: Single-digit milliseconds (< 10ms)
- **Pure hosted mode**: Low tens of milliseconds (< 50ms, region-dependent)

If `total_ms` exceeds these targets consistently, it's a performance bug.

---

## Policy Version Inclusion (Auditability)

Per CLAUDE.md line 336:

**Every decision includes the policy version** used in evaluation.

**Why**:
- Enables **replay**: Re-evaluate historical envelope against the policy that was active at the time
- Enables **debugging**: Know exactly what policy produced this decision
- Enables **audit trail**: Record shows what policy was in effect when action was evaluated

**Format**: Semver string (e.g., `"v2.1.0"`)

If multiple policy sets were evaluated (hierarchy), include all versions:
```json
"policy_versions": [
  {"scope": "org", "version": "v1.0.0"},
  {"scope": "agent", "version": "v2.1.0"}
]
```

---

## Rate Limit Counter State

Per CLAUDE.md Infrastructure Spec #6 (line 354):

**Decision includes counter state** when rate limit is checked.

**Why**:
- Caller can make **informed retry decisions**
- Caller knows how close they are to limit (can throttle proactively)
- Transparent - no hidden state

**Fields**:
- `scope` - What is being rate-limited (agent_id, user_id, action, etc.)
- `window` - Time window (minute, hour, day)
- `limit` - Maximum allowed in window
- `current` - Current count in window
- `reset_at` - ISO 8601 timestamp when counter resets

**Even when decision is ALLOW**, include rate_limit if approaching limit:
```json
{
  "decision": "ALLOW",
  "allowed": true,
  "rate_limit": {
    "scope": "agent_id",
    "window": "hour",
    "limit": 100,
    "current": 95,
    "reset_at": "2026-02-14T14:00:00Z"
  }
}
```

This allows caller to proactively throttle before hitting limit.

---

## SDK Ergonomics

The decision response is designed to be **easy to use** in SDK code.

### Python Example (evaluate() — primary API)

```python
result = hiitl.evaluate(
    tool="process_payment",
    parameters={"amount": 500, "currency": "usd"}
)

if result.ok:
    actually_process_payment(...)
elif result.blocked:
    print(result.remediation.message)
    # "Payment amount exceeds the $10,000 limit. Reduce or request approval."
elif result.needs_approval:
    send_to_review(resume_token=result.resume_token, route=result.route_ref)
```

### Python Example (evaluate() — full control)

```python
decision = hiitl.evaluate(
    tool="process_payment",
    operation="execute",
    target={"account_id": "acct_123"},
    parameters={"amount": 500}
)

if decision.allowed:
    result = actually_execute_action(...)
else:
    if decision.decision == "REQUIRE_APPROVAL":
        send_to_review(
            resume_token=decision.resume_token,
            route=decision.route_ref,
            context=decision.escalation_context
        )
    elif decision.decision == "RATE_LIMIT":
        wait_until(decision.rate_limit["reset_at"])
        retry()
    elif decision.decision == "KILL_SWITCH":
        alert_ops("Kill switch active", decision.reason_codes)
    else:
        if decision.remediation:
            log.warning(f"Blocked: {decision.remediation.message}")
        else:
            log.warning(f"Action blocked: {decision.reason_codes}")
```

### TypeScript Example

```typescript
const result = await hiitl.evaluate({
  tool: 'process_payment',
  parameters: { amount: 500, currency: 'usd' },
});

if (result.ok) {
  await actuallyProcessPayment(...);
} else if (result.blocked) {
  console.log(result.remediation?.message);
} else if (result.needsApproval) {
  await sendToReview({ resumeToken: result.resumeToken, route: result.routeRef });
}
```

---

## Conformance Testing

Decision response format is validated in the conformance test suite:

```json
{
  "test_name": "high_value_payment_requires_approval",
  "envelope": { /* ... */ },
  "policy_set": { /* ... */ },
  "expected_decision": {
    "decision": "REQUIRE_APPROVAL",
    "allowed": false,
    "reason_codes": ["HIGH_VALUE_PAYMENT"],
    "matched_rules": [{"rule_name": "require-approval-high-value"}],
    "policy_version": "v2.1.0"
  }
}
```

All evaluator implementations must produce decision responses matching the expected format.

---

## Error Handling

**All errors produce structured decision responses** (CLAUDE.md line 496).

Never return generic 500 errors without a decision response body.

**Error decisions**:
- `SIGNATURE_INVALID` - Envelope signature verification failed
- `CONTROL_PLANE_UNAVAILABLE` - ECP is unreachable (circuit breaker, timeout)
- `VALIDATION_ERROR` - Envelope failed schema validation
- `POLICY_ERROR` - Policy evaluation failed (misconfigured policy)

**Error response includes**:
- `error.code` - Machine-readable error code
- `error.message` - Human-readable explanation
- `reason_codes` - Reason codes (e.g., `["SIGNATURE_VERIFICATION_FAILED"]`)

**Audit requirement**: Even error decisions produce audit records (CLAUDE.md line 496).

---

## Versioning

**Decision response schema version**: `v1.0`

**Backward compatibility** (CLAUDE.md lines 341-346):
- New optional fields may be added (minor version bump)
- Existing fields cannot be removed (major version bump)
- Field types cannot change (major version bump)

**Migration path**: If breaking changes required, document migration guide before implementation.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial decision response specification | Phase 0 Setup |
| 1.1 | 2026-02-16 | Added: resume_token, hitl_config_ref, escalation_context fields for escalation decisions | Strategic Evolution |
| 1.2 | 2026-02-24 | Renamed hitl_config_ref → route_ref. Added remediation object for BLOCK/RATE_LIMIT decisions. Clarified error vs remediation distinction (mutually exclusive). Added SDK usage examples using evaluate(). | Strategic Evolution v2 |
| 1.3 | 2026-02-26 | Formalized type-specific remediation schemas for all 6 types (field_restriction, threshold, scope, rate_limit, temporal, custom). Added Remediation Types section with examples. Formalized error vs remediation invariant. Made message/suggestion/type required on remediation. | TICKET-019.2 |
| 1.4 | 2026-02-27 | Added OBSERVE decision type with would_be/would_be_reason_codes fields. Supports observe-before-enforce progressive rollout. | TICKET-028.1 |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Input to policy evaluation
- [Policy Format Spec](policy_format.md) - Policy evaluation semantics
- [Route Spec](routes.md) - Route schema (external communication — outbound, inbound, bidirectional)
- [Event Format Spec](event_format.md) - Audit record format
- [CLAUDE.md](../../CLAUDE.md) - Design principles and requirements

---

**This specification is the source of truth. Implementations follow the spec.**
