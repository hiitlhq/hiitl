# Decision Response Specification

**Version**: 1.15
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-11-08

---

## Purpose

This document defines the **decision response** format returned by hiitl Execution Control Plane after policy evaluation.

The decision response is what the SDK caller receives. It must contain:
- The decision outcome (allow, block, pause, etc.)
- Reason codes explaining why
- Timing metadata (for transparency)
- Policy version used (for audit and replay)
- Counter state (for rate limits)
- Any additional metadata needed for the caller to act

All SDK implementations (TypeScript, Python, and future languages) must conform to this specification.

Every numeric value admitted through this format, including each integer member and open data, follows
[the single numeric domain](sync_engine.md#numeric-domain). This is admission before evaluation, signing,
hashing or recording; existing stored records, hashes and signatures remain as written.

---

## Design Principles

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
  "$id": "https://hiitl.com/schemas/decision-response/v1.json",
  "title": "hiitl Decision Response",
  "description": "Response returned after policy evaluation",
  "type": "object",
  "required": [
    "action_id",
    "decision",
    "reason_codes",
    "policy_version",
    "timing",
    "allowed",
    "staged_observations"
  ],
  "properties": {
    "action_id": {
      "type": "string",
      "description": "Echo of the action_id from the envelope. For correlation. Under a repeated idempotency_key, the first action's: the decision is the first one (row 143)."
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
        "CONTROL_PLANE_UNAVAILABLE",
        "VALIDATION_ERROR",
        "POLICY_ERROR"
      ],
      "description": "The decision outcome"
    },
    "allowed": {
      "type": "boolean",
      "description": "Convenience boolean: true if decision is ALLOW, SANDBOX or OBSERVE, false otherwise"
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
          "priority": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain."}
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
          "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "description": "Time spent ingesting and validating envelope (milliseconds)"
        },
        "evaluation_ms": {
          "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "description": "Time spent in policy evaluation (milliseconds)"
        },
        "total_ms": {
          "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "description": "Total request latency (milliseconds)"
        }
      }
    },
    "rate_limit": {
      "type": "object",
      "description": "Counter state (see Rate Limit Counter State). Present on a RATE_LIMIT decision (the exceeded window), and on a decision the limiter counted (the window with the least headroom left). Absent when no windowed rule matched.",
      "properties": {
        "scope": {"type": "string", "description": "The window's rule's scope: action, agent, user, org or user_action (policy_format.md Rate-limit rules)"},
        "window": {"type": "string", "description": "The window's rule's window, as `<window_seconds>s` (e.g. `3600s`)"},
        "limit": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Maximum allowed in window"},
        "current": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Count in the window, this call included when the limiter counted it"},
        "reset_at": {"type": "string", "format": "date-time", "description": "When the oldest call in the window leaves it, freeing a slot"}
      }
    },
    "rate_limit_rules": {
      "type": "array",
      "description": "Active RATE_LIMIT rules with a window that matched (policy_format.md Rate-limit rules). They do not bind; the post-evaluation limiter counts each in its window when the binding decision is ALLOW. Empty when none matched.",
      "items": {
        "type": "object",
        "required": ["rule_name", "policy_set", "priority", "reason_code", "limit", "window_seconds", "scope"],
        "properties": {
          "rule_name": {"type": "string"},
          "policy_set": {"type": "string"},
          "priority": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain."},
          "reason_code": {"type": "string", "description": "The rule's own reason code. An exceeded window's decision carries RATE_LIMIT_EXCEEDED and names the rule in matched_rules (T47)"},
          "remediation": {"$ref": "#/properties/remediation", "description": "The rule's remediation, its call-computed details resolved (policy_format.md Remediation on Rules). Absent when the rule has none. The limiter returns it, with a rate_limit remediation's counter state filled, when the window is exceeded"},
          "limit": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain."},
          "window_seconds": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain."},
          "scope": {"type": "string", "enum": ["action", "agent", "user", "org", "user_action"]}
        }
      }
    },
    "resume_token": {
      "type": "string",
      "description": "Token to correlate the reviewer's response back to the paused action. Present for REQUIRE_APPROVAL, PAUSE, and ESCALATE decisions. Used by the caller to resume or cancel the action after review."
    },
    "route_ref": {
      "type": "string",
      "description": "Name of the route artifact used for this escalation. References the route that defines how external communication works for this action (escalation context, response schema, SLA, routing target). Present for REQUIRE_APPROVAL, PAUSE, and ESCALATE decisions, and for ROUTE (the sync route the rule asks; policy_format.md 2.7). Formerly 'hitl_config_ref'."
    },
    "enrichment": {
      "type": "object",
      "description": "The enrichment context the last evaluation read (policy_format.md 2.7, TICKET-046): {source: {field: value}} — each sync route's declared answer fields under the route's name. Present when a route answered. Set by hiitl from the route's answer, never by the caller; the submitted envelope is unchanged.",
      "additionalProperties": {"type": "object"}
    },
    "routes": {
      "type": "array",
      "description": "Each sync route asked in this evaluation, in order (policy_format.md 2.7). Present when a ROUTE rule bound.",
      "items": {
        "type": "object",
        "required": ["rule_name", "route", "outcome"],
        "properties": {
          "rule_name": {"type": "string", "description": "The ROUTE rule that asked"},
          "route": {"type": "string", "description": "The route asked (the enrichment source)"},
          "outcome": {"type": "string", "enum": ["answered", "unanswered", "failed_open"], "description": "answered: its declared fields re-entered; unanswered: no answer, the decision stays ROUTE (fail closed, ROUTE_UNANSWERED); failed_open: no answer, the route's SLA says fail_open, so it counts as answered with no fields"},
          "fields": {"type": "array", "items": {"type": "string"}, "description": "The answer's fields that re-entered"},
          "error": {"type": "string", "description": "Why there is no answer (timeout, error response, missing required field)"}
        }
      }
    },
    "missing_fields": {
      "type": "array",
      "description": "Each rule the evaluation read whose outcome a field the call does not carry left open, and did not bind by its set's `on_missing: fail_closed`: it was skipped and flagged (policy_format.md \"A field the call does not carry\"; HTL-22 row 176). In the order the rules were read, then each rule's conditions; each field once per rule. Present when a rule was skipped; absent otherwise.",
      "items": {
        "type": "object",
        "required": ["rule_name", "policy_set", "field"],
        "properties": {
          "rule_name": {"type": "string", "description": "The rule that could not be read"},
          "policy_set": {"type": "string", "description": "Its policy set"},
          "field": {"type": "string", "description": "The envelope path the call does not carry"}
        }
      }
    },
    "escalation_context": {
      "type": "object",
      "description": "The route the binding rule names (`route_ref`), flattened for the caller (routes.md): where the review goes, how long it has, what the reviewer can answer and what the reviewer sees. Present for REQUIRE_APPROVAL, PAUSE and ESCALATE decisions whose route the SDK or the service loaded. Each property is the route field it names, in that field's shape (routes.md); a property whose route field is unset is absent.",
      "properties": {
        "endpoint": {"type": "string", "description": "The route's `endpoint`"},
        "protocol": {"type": "string", "description": "The route's `protocol`"},
        "timeout": {"type": "string", "description": "The route's `sla.timeout`, a duration such as \"4h\""},
        "timeout_action": {"type": "string", "description": "The route's `sla.timeout_action`: what happens when the review is not answered in time"},
        "decision_options": {"type": "array", "items": {"type": "string"}, "description": "The route's `response_schema.decision_options`: what the reviewer can answer"},
        "fields": {"type": "array", "items": {"type": "object"}, "description": "The route's `context.fields`, each `{field_path, label, format}`: what the reviewer sees"},
        "severity": {"type": "string", "description": "The route's `context.risk_framing.severity`"},
        "summary": {"type": "string", "description": "The route's `context.risk_framing.summary`"},
        "escalation_ladder": {"type": "object", "description": "The route's `escalation_ladder`: `levels`, `max_escalation_depth`, `final_timeout_action`"},
        "token_field": {"type": "string", "description": "The route's `correlation.token_field`: the field the resume token travels in"}
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
    "staged_observations": {
      "type": "array",
      "description": "Side-by-side observations from rules in lifecycle_stage='staged' (Block 1B). Each staged rule that matched during evaluation contributes one entry — the rule did NOT bind the decision, but the evaluator recorded what it would have decided so regression reports can compare staged vs active behavior. **ALWAYS present** — emitted as an empty array `[]` when no staged rules matched, never omitted, never `null`/`undefined`. This is a load-bearing contract: consumers iterate the array directly (`for (const obs of decision.staged_observations)`) without null-checks. Cross-language conformance fixtures in `tests/conformance/cases/lifecycle/` validate this guarantee on every evaluation.",
      "items": {
        "type": "object",
        "required": ["rule_name", "policy_set", "priority", "would_be_decision", "would_be_reason_codes", "would_be_binding"],
        "properties": {
          "rule_name": {"type": "string"},
          "policy_set": {"type": "string"},
          "priority": {"type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain."},
          "would_be_decision": {
            "type": "string",
            "description": "What this staged rule's decision would have been if it were active.",
            "enum": ["ALLOW", "BLOCK", "PAUSE", "REQUIRE_APPROVAL", "SANDBOX", "RATE_LIMIT", "KILL_SWITCH", "ESCALATE", "ROUTE", "OBSERVE"]
          },
          "would_be_reason_codes": {
            "type": "array",
            "items": {"type": "string"}
          },
          "would_be_binding": {
            "type": "boolean",
            "description": "True if this is the highest-priority staged match — i.e., this is the rule that would have BOUND the would-be decision had it been active. Lower-priority staged matches are still informative for regression analysis but did not drive the would-be outcome."
          }
        }
      }
    },
    "envelope_hash": {
      "type": "string",
      "description": "SHA-256 of the envelope as evaluated, over its signed form (hiitl.core.canonical envelope_hash; @hiitl/core envelopeHash): the caller recomputes it from the envelope it sent. Present in every mode (row 134)."
    },
    "cache_status": {
      "type": "string",
      "enum": ["synced", "from_disk", "empty"],
      "description": "Hybrid mode only: where the evaluator's policies came from. synced: a sync completed in this process. from_disk: the disk cache, before any sync. empty: no policies, so the call was evaluated as OBSERVE_ALL. Absent in local and hosted mode."
    },
    "error": {
      "type": "object",
      "description": "Error details. Present on an error decision (the envelope could not be evaluated; `code` is the decision) and on a BLOCK the control point itself answered (`code` is its cause: `RATE_LIMIT_SERVICE_ERROR`, `AUDIT_WRITE_FAILED`). Mutually exclusive with 'remediation'. Error means something went wrong with ECP itself; remediation means ECP successfully enforced a policy.",
      "properties": {
        "code": {"type": "string", "description": "Error code: the error decision itself (Examples 8 and 9), or the cause of a BLOCK the control point answered"},
        "message": {"type": "string", "description": "Human-readable error message"}
      }
    },
    "metadata": {
      "type": "object",
      "description": "Present on CONTROL_PLANE_UNAVAILABLE: the fail mode the outage applied, and the hosted client's circuit breaker after the call (Example 9). Absent on every other decision.",
      "properties": {
        "fail_mode": {"type": "string", "enum": ["FAIL_CLOSED", "FAIL_OPEN"], "description": "The fail mode applied, the hosted client's `fail_mode` setting: FAIL_CLOSED (the default) answers `allowed` false; FAIL_OPEN, opt-in, answers `allowed` true with its warning in `error.message`, logged and recorded (Error Handling)"},
        "circuit_breaker_state": {"type": "string", "enum": ["closed", "open", "half_open"], "description": "The hosted client's circuit breaker after the call: closed, open (calls fail fast and are not sent), or half_open (the next call is a probe)"}
      },
      "required": ["fail_mode", "circuit_breaker_state"],
      "additionalProperties": false
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
| `ROUTE` | `false` | A sync route was asked and has not answered (`ROUTE_UNANSWERED`), or the rule's route is not a sync route | Do not execute; the route's answer, once it re-enters, decides (policy_format.md 2.7) |

### Error Decisions

| Decision | Description | Typical Caller Action |
|----------|-------------|----------------------|
| `SIGNATURE_INVALID` | Envelope signature verification failed | Fix SDK signature, do not retry |
| `CONTROL_PLANE_UNAVAILABLE` | ECP is unreachable, fail mode applied | Read `allowed`: false under FAIL_CLOSED (do not execute), true under FAIL_OPEN (execute; the warning is logged and recorded) |
| `VALIDATION_ERROR` | The envelope is not one the control point admits: a field the schema refuses, another org's or environment's envelope, a timestamp outside the window | Correct the envelope, send a new one |
| `POLICY_ERROR` | The policy could not be had or evaluated: none active, not found, unreadable, not a policy set the format admits, its stored hash does not match, or the evaluator failed on it | Do not execute; correct or publish the policy |

Every error decision has `allowed: false`, `error.code` equal to the decision and its cause as the one reason code (see Error Handling). The one `allowed: true` is `CONTROL_PLANE_UNAVAILABLE` under `FAIL_OPEN`, which a caller opts into (Stop B (ii), ruled 2026-11-06).

---

## Response Examples

### Example 1: ALLOW

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "ALLOW",
  "allowed": true,
  "reason_codes": ["DEFAULT_ALLOW"],
  "staged_observations": [],
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
  "staged_observations": [],
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
  "staged_observations": [],
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
  "staged_observations": [],
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
    "endpoint": "https://hooks.example.com/hiitl/finance-review",
    "protocol": "webhook",
    "timeout": "4h",
    "timeout_action": "escalate",
    "decision_options": ["approve", "deny", "modify"],
    "fields": [
      {"field_path": "parameters.amount", "label": "Payment amount", "format": "currency"},
      {"field_path": "target.account_id", "label": "Account", "format": "text"}
    ],
    "token_field": "resume_token"
  }
}
```

**Caller action**:
1. Do not execute immediately
2. Use `resume_token` to correlate this escalation with the reviewer's response
3. The review goes to `escalation_context.endpoint`; the reviewer sees `fields` and answers one of `decision_options` within `timeout`
4. Resume execution after approval granted using `resume_token`

---

### Example 5: RATE_LIMIT

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "RATE_LIMIT",
  "allowed": false,
  "reason_codes": ["RATE_LIMIT_EXCEEDED"],
  "staged_observations": [],
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
    "scope": "agent",
    "window": "3600s",
    "limit": 100,
    "current": 100,
    "reset_at": "2026-02-14T14:00:00Z"
  },
  "remediation": {
    "message": "Payments are limited to 100 per agent per hour.",
    "suggestion": "Retry after reset_at, or spread payments across the hour.",
    "type": "rate_limit",
    "details": {
      "scope": "agent",
      "window": "3600s",
      "limit": 100,
      "current": 100,
      "reset_at": "2026-02-14T14:00:00Z"
    }
  },
  "rate_limit_rules": [
    {
      "rule_name": "rate-limit-payments-per-agent",
      "policy_set": "payments-policy",
      "priority": 50,
      "reason_code": "PAYMENT_RATE_EXCEEDED",
      "limit": 100,
      "window_seconds": 3600,
      "scope": "agent",
      "remediation": {
        "message": "Payments are limited to 100 per agent per hour.",
        "suggestion": "Retry after reset_at, or spread payments across the hour.",
        "type": "rate_limit"
      }
    }
  ]
}
```

The `remediation` is the rule's own, its details filled from the exceeded window's counter state; the call was counted
in no window (see **Rate Limit Counter State**).

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
  "staged_observations": [],
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
  "staged_observations": [],
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
  }
}
```

**Caller action**:
1. Execute the action against the caller's sandbox target, not production (the decision names no sandbox endpoint: which target is the sandbox is the caller's own configuration)
2. Flag execution as sandbox in logs

---

### Example 8: SIGNATURE_INVALID (Error)

```json
{
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGHIJK",
  "decision": "SIGNATURE_INVALID",
  "allowed": false,
  "reason_codes": ["ENVELOPE_SIGNATURE_VERIFICATION_FAILED"],
  "staged_observations": [],
  "matched_rules": [],
  "policy_version": "",
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
  "staged_observations": [],
  "matched_rules": [],
  "policy_version": "",
  "timing": {
    "ingest_ms": 0.0,
    "evaluation_ms": 0.0,
    "total_ms": 5000.0
  },
  "error": {
    "code": "CONTROL_PLANE_UNAVAILABLE",
    "message": "The hosted service did not answer within the timeout on any attempt, so the action was not evaluated and is not allowed (fail-closed). Do not execute it; check the service's status and the client's timeout and max_retries; the cause is in the log."
  },
  "metadata": {
    "fail_mode": "FAIL_CLOSED",
    "circuit_breaker_state": "open"
  }
}
```

**Caller action**:
1. If `fail_mode` is `FAIL_CLOSED` (`allowed` false): Do not execute (fail safe)
2. If `fail_mode` is `FAIL_OPEN` (`allowed` true, opt-in): Execute; the hosted client logs the warning and records the decision (fail permissive)
3. Alert operations team (ECP unavailable)
4. Circuit breaker is open - subsequent calls will fail fast

Under `FAIL_OPEN` the same outage answers `"allowed": true`, `"metadata": {"fail_mode": "FAIL_OPEN", …}`, and an
`error.message` that says the action was allowed unevaluated because the client is configured to fail open.

---

## Remediation Types

Remediation provides structured, actionable guidance when a policy intentionally blocks an action. The `remediation.type` field determines the schema of `remediation.details`.

### Invariant: Error vs Remediation

A decision **MUST NOT** include both `error` and `remediation`:
- **`error`** = ECP itself failed (signature invalid, control plane unavailable, policy parse error). The action was not evaluated.
- **`remediation`** = ECP worked correctly and intentionally blocked the action by policy. The action was evaluated and denied.

If `error` is present, `remediation` MUST be absent, and vice versa. Implementations enforce this at the type level.

### Computed details

A rule's remediation is returned with the details that state a fact of the call computed from the call, so the caller
can "actually consume and use the policy to refine and proceed with the adjusted tool call" (R-0059). The rule states
where the fact is, never its value (policy_format.md **Remediation on Rules**):

| Type | Field | Computed as |
|------|-------|-------------|
| `field_restriction` | `blocked_fields`, written `{ref, filter}` | the envelope's values at `ref` that are in `filter`, in the envelope's order, each once; `field_ref` is `ref` |
| `threshold` | `current_value` | the envelope's value at `field`, when `field` is given |
| `temporal` | `current_time` | the envelope's `timestamp` |
| `rate_limit` | `limit`, `current`, `reset_at`, `scope`, `window` | the exceeded window's counter state |

A detail written as a value is returned as written. Two details are not yet computed: `temporal.next_allowed_at` (no
evaluator reads a time window) and `scope.current_scope` (no envelope field states the caller's scope); each is
returned as the rule writes it. *(HTL-20, row 146.)*

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
| `limit` | `integer` | Maximum allowed in window; [shared numeric domain](sync_engine.md#numeric-domain) |
| `current` | `integer` | Current count in window; [shared numeric domain](sync_engine.md#numeric-domain) |
| `reset_at` | `string (date-time)` | When the counter resets |
| `scope` | `string` | The exceeded rule's scope (action, agent, user, org, user_action) |
| `window` | `string` | The exceeded rule's window, `<window_seconds>s` |

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
      "scope": "agent",
      "window": "3600s"
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

**Every decision response includes timing metadata**. Developers must never wonder "is this slowing me down?"

**Timing fields**:
- `ingest_ms` - Time to validate envelope, check signature, extract org_id
- `evaluation_ms` - Time spent in policy evaluation engine
- `total_ms` - Full round-trip latency (includes network if hosted mode)

The clock starts where `evaluate()` starts, in each core and each SDK, so the admission of the call's own tree
(sync_engine.md **Numeric domain**) is counted in `ingest_ms` and `total_ms`. In an SDK, `ingest_ms` runs from its
`evaluate()` through the envelope's signature check (the list above), and the evaluator's own ingest is added to it
(HTL-43 gap 303, ruled `b88dd3e3`).

**Latency targets**:
- **Typical core evaluation**: < 1ms for typical policies.
- **Hybrid mode** (default): Microsecond evaluation (in-process, no I/O)
- **Pure local mode**: Single-digit milliseconds (< 10ms)
- **Pure hosted mode**: Low tens of milliseconds (< 50ms, region-dependent)

If evaluation or round-trip latency exceeds its applicable target consistently, it's a performance bug.

---

## Policy Version Inclusion (Auditability)

**Every decision includes the policy version** used in evaluation.

**Why**:
- Enables **replay**: Re-evaluate historical envelope against the policy that was active at the time
- Enables **debugging**: Know exactly what policy produced this decision
- Enables **audit trail**: Record shows what policy was in effect when action was evaluated

**Format**: Semver string (e.g., `"v2.1.0"`)

If multiple policy sets were evaluated (hierarchy), include all versions:
```jsonc
"policy_versions": [
  {"scope": "org", "version": "v1.0.0"},
  {"scope": "agent", "version": "v2.1.0"}
]
```

---

## Rate Limit Counter State

**Decision includes counter state** when rate limit is checked.

**Why**:
- Caller can make **informed retry decisions**
- Caller knows how close they are to limit (can throttle proactively)
- Transparent - no hidden state

**Fields**:
- `scope` - What is being rate-limited: the window's rule's scope (action, agent, user, org, user_action)
- `window` - The window's rule's window, `<window_seconds>s`
- `limit` - Maximum allowed in window
- `current` - Count in the window, this call included when the limiter counted it
- `reset_at` - RFC 3339 date-time (ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar") when the oldest call in the window leaves it

**Even when decision is ALLOW**, include rate_limit: every decision the limiter counted carries it (R-0008: "Decisions
must include current counter state snapshot"). Its window is the one with the least headroom left (`limit − current`;
on a tie, the first listed), because that is the limit the caller reaches first. No bound for "approaching" is defined,
so none is applied: a caller reads its headroom from `limit` and `current`. *(HTL-20, row 146.)*
```json
{
  "decision": "ALLOW",
  "allowed": true,
  "rate_limit": {
    "scope": "agent",
    "window": "3600s",
    "limit": 100,
    "current": 95,
    "reset_at": "2026-02-14T14:00:00Z"
  }
}
```

This allows caller to proactively throttle before hitting limit.

**Rate-limit rules.** A matching active `RATE_LIMIT` rule with a window is listed in `rate_limit_rules`, with its
`reason_code` and `remediation`. It does not bind. When the binding decision is `ALLOW`, the limiter reads every listed
window (key `rule:<name>:<scope key>`) before it counts any. When one is exceeded, the response is `RATE_LIMIT` with
`reason_codes: ["RATE_LIMIT_EXCEEDED"]`, `matched_rules` naming the rule, `rate_limit` carrying its counter state (`scope`
is the rule's scope, `window` its `window_seconds` as `"<n>s"`), and `remediation` the rule's own, a `rate_limit`
remediation's details being that counter state. The call is then counted in no window. The reason code is
`RATE_LIMIT_EXCEEDED` for every windowed rule: `matched_rules` names the rule (T47), and the rule's own `reason_code` is
in `rate_limit_rules[].reason_code`. Under `OBSERVE_ALL` the refusal comes back `OBSERVE` with `would_be: RATE_LIMIT`. A
limiter that fails is `BLOCK` / `RATE_LIMIT_SERVICE_ERROR` with an `error`, never an `ALLOW`; under `OBSERVE_ALL` that
block is observed, the `error` kept (policy_format.md **Rate-limit rules**, "In either mode"; HTL-20, row 132).

---

## A Field the Call Does Not Carry

A rule reads the envelope paths its conditions name. When a path the call does not carry leaves the rule's outcome
open, the rule's set decides what happens by its `on_missing` (policy_format.md **A field the call does not carry**;
HTL-22 row 176):

- **`skip`** (the default): the rule is read as an absent field has always been read, and is named in
  `missing_fields`. The decision is the one it was before `on_missing` existed.
- **`fail_closed`**: the rule decides `BLOCK` with `reason_codes: ["MISSING_FIELD"]`, `matched_rules` naming the rule,
  and a `custom` remediation whose `details.fields` lists the paths the call must carry. It contends at the rule's
  own priority in the `BLOCK` class (policy_format.md **Rule Precedence**), so a matching `KILL_SWITCH`, or a matching
  `BLOCK` of higher priority, binds over it.

Under `OBSERVE_ALL`, and for a staged rule, the rule is skipped and flagged whatever its set says.
`observe()` keeps `missing_fields`. An absent `external.*` field is not counted: it is the enrichment context, not the
envelope.

```json
{
  "decision": "BLOCK",
  "allowed": false,
  "reason_codes": ["MISSING_FIELD"],
  "matched_rules": [
    {"rule_name": "approve_large_payments", "policy_set": "payments_policy", "priority": 200}
  ],
  "remediation": {
    "message": "Rule 'approve_large_payments' in policy set 'payments_policy' reads parameters.amount, which the call does not carry, and the set's on_missing is fail_closed.",
    "suggestion": "Add parameters.amount to the call and evaluate it again.",
    "type": "custom",
    "details": {"fields": ["parameters.amount"]}
  },
  "staged_observations": []
}
```

The same call under `skip` is decided by the next rule, and carries:

```json
{
  "missing_fields": [
    {"rule_name": "approve_large_payments", "policy_set": "payments_policy", "field": "parameters.amount"}
  ]
}
```

---

## SDK Ergonomics

The decision response is designed to be **easy to use** in SDK code.

### Python Example (evaluate() — primary API)

```python
result = hiitl.evaluate(
    "process_payment",
    parameters={"amount": 500, "currency": "usd"}
)

if result.ok:
    actually_process_payment(...)
elif result.blocked:
    if result.remediation:
        print(result.remediation.message)
        # "Payment amount exceeds the $10,000 limit. Reduce or request approval."
elif result.needs_approval:
    send_to_review(resume_token=result.resume_token, route=result.route_ref)
```

### Python Example (evaluate() — full control)

```python
decision = hiitl.evaluate(
    "process_payment",
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
        wait_until(decision.rate_limit.reset_at)
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
  action: 'process_payment',
  parameters: { amount: 500, currency: 'usd' },
});

if (result.allowed) {
  await actuallyProcessPayment(...);
} else if (result.decision === 'BLOCK') {
  console.log(result.remediation?.message);
} else if (result.decision === 'REQUIRE_APPROVAL') {
  await sendToReview({ resume_token: result.resume_token, route: result.route_ref });
}
```

---

## Conformance Testing

Decision response format is validated in the conformance test suite:

```jsonc
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

**All errors produce structured decision responses.**

Never return generic 500 errors without a decision response body.

**Error decisions**:
- `SIGNATURE_INVALID` - Envelope signature verification failed (`ENVELOPE_SIGNATURE_MISSING`, `ENVELOPE_SIGNATURE_VERIFICATION_FAILED`, `SIGNATURE_VERSION_UNSUPPORTED`)
- `CONTROL_PLANE_UNAVAILABLE` - ECP is unreachable: every attempt timed out (`CONTROL_PLANE_TIMEOUT`), no connection, or a transient status on the last attempt that the service did not answer, carrying no decision and not the service's error format (`CONTROL_PLANE_UNREACHABLE`), or the circuit breaker is open and the call was not sent (`CIRCUIT_BREAKER_OPEN`)
- `VALIDATION_ERROR` - Envelope failed schema validation (`ENVELOPE_VALIDATION_ERROR`), or is not this key's to send (`TENANT_MISMATCH`, `TIMESTAMP_OUT_OF_WINDOW`), or carries a principal token the org has no verifier for (`PRINCIPAL_VERIFIER_NOT_CONFIGURED`, row 194, ruled 2026-11-06: the envelope exists, so it is read after the envelope as the service's other refusals are, with one record)
- `POLICY_ERROR` - Policy evaluation failed (misconfigured policy): `POLICY_NOT_FOUND`, `POLICY_LOAD_FAILED`, `POLICY_VALIDATION_ERROR`, `POLICY_INTEGRITY_VIOLATION`, `POLICY_EVALUATION_FAILED`

**Error response includes**:
- `allowed` - `false`, but for `CONTROL_PLANE_UNAVAILABLE` under `FAIL_OPEN` (below)
- `error.code` - Machine-readable error code: the decision (Examples 8 and 9)
- `error.message` - Human-readable explanation: what happened and what to do. It is authored for the cause, never a caught exception's text; the cause is logged where it was caught
- `reason_codes` - The cause, one reason code (e.g., `["ENVELOPE_SIGNATURE_VERIFICATION_FAILED"]`)

**Audit requirement**: Even error decisions produce audit records. The hosted service records a refused envelope under the API key's org and environment, never the envelope's own claim. No decision carrying `error` is the first decision under an `idempotency_key`: `error` means ECP itself failed and the action was not evaluated (above), so its retry is. That is each error decision, and each `BLOCK` the control point answers with `error` (`EVALUATION_FAILED`, `AUDIT_READ_FAILED`, `RATE_LIMIT_SERVICE_ERROR`; row 193).

**Where the error is answered**:
- **The hosted service** answers an error decision as the response body, with the HTTP status its cause declares: 403 for `ENVELOPE_SIGNATURE_MISSING`, `ENVELOPE_SIGNATURE_VERIFICATION_FAILED`, `TENANT_MISMATCH` and `TIMESTAMP_OUT_OF_WINDOW`; 400 for `SIGNATURE_VERSION_UNSUPPORTED`, `POLICY_VALIDATION_ERROR` and `PRINCIPAL_VERIFIER_NOT_CONFIGURED`; 422 for `ENVELOPE_VALIDATION_ERROR`; 404 for `POLICY_NOT_FOUND`; 500 for `POLICY_INTEGRITY_VIOLATION`, `POLICY_EVALUATION_FAILED`, and the BLOCKs the control point answers below (`EVALUATION_FAILED`, `AUDIT_READ_FAILED`, `AUDIT_WRITE_FAILED`). A request that is no envelope at all is answered before one exists, with no decision and no record: a missing or unknown API key (401), a key without the `evaluate` scope (403), a body that is not a JSON object, has no string `action_id`, or carries a number outside the [Numeric domain](sync_engine.md#numeric-domain) (FastAPI's existing located 422 list, naming the field and the remedy for its declared kind, by Numeric domain). **A body outside the Numeric domain is no envelope yet. This is the one refused request carrying a string `action_id` that leaves no audit record at the service.**
- **The caller is read before the request's shape** (row 203, ruled 2026-11-06: "The caller is read before the request's shape, one order across the service; row 147's query refusal is re-anchored to match", by this order and Tier 1's keys: an unauthenticated caller learns nothing of the shape). On every endpoint of the service: the key (401), then its scope (403), then the request's shape (an undefined query parameter, a body the endpoint does not declare, a body that is not JSON, the 422 list).
- **The SDKs** return the error decision from `evaluate()` and record it. They raise a typed hiitl error only before the envelope exists (a configuration they cannot use, an envelope they cannot build). Both hosted clients read a decision body on any status as the decision, every member the decision model declares (row 204, ruled 2026-11-06: the clients' lists are generated from the model, never written by hand, by R-0872 "no field is ever silently dropped").
- **An outage** is answered by the hosted client, since the service is what cannot be reached: `CONTROL_PLANE_UNAVAILABLE` with `metadata` `{fail_mode, circuit_breaker_state}` (Example 9). What an outage is (row 199, ruled 2026-11-06 as built): no answer within the timeout on any attempt, no connection, or a transient status on the last attempt that carries no decision and is not the service's error format (a gateway's page); a transient status whose body is the service's error format is the service's answer, raised as the service's error. Each hosted client holds a circuit breaker, the sync engine's `CircuitBreaker` at its own defaults (row 198, ruled 2026-11-06: no setting until a caller needs one, by "new things must earn their place"). An outage counts against it, and any answer from the service closes it; once it is open, a call is not sent and fails fast until the reset interval passes, when one call probes. `status()` names its state in both SDKs, as it names the sync engine's (`circuit_breakers.hosted`, by "no silent degradation"). In hybrid and local mode an outage meets only sync, and evaluation is unchanged: a hybrid sync outage stays the sync engine's `SYNC_CIRCUIT_OPEN`.
- **The fail mode (Stop B (ii), ruled 2026-11-06):** "a `fail_mode` setting on the hosted client, `FAIL_CLOSED` by default, `FAIL_OPEN` opt-in, under which the outage decision is `allowed` true with its warning recorded", by R-0002's "Configurable fail mode: FAIL_CLOSED (default) or FAIL_OPEN" and the error-handling rule's "Fail-open is opt-in and must be explicitly configured". Under `FAIL_OPEN` the outage decision is `CONTROL_PLANE_UNAVAILABLE` with `allowed` true, its cause the one reason code, `error.code` the decision, and an `error.message` that is the warning: the action was allowed without being evaluated, because the client is configured to fail open. The client logs it at warning and records it. Every other error decision is `allowed` false in either mode.
- **The outage's record (Stop B (i), ruled 2026-11-06):** "the pure-hosted client keeps a local audit buffer for the records the service could not take, pushed when it answers, as hybrid buffers", by Principle 6 ("Every attempted action produces a durable record") and R-0002's "structured CONTROL_PLANE_UNAVAILABLE audit event". The hosted client writes the outage decision's record (the envelope it built and the decision, under the SDK's `redact_fields`) to its local audit store at `audit_db_path`, as local and hybrid do (event_format.md "Where it is held"). Before it sends its next call it pushes what it holds, oldest first: the records to `POST /v1/sync/audit` in batches of the sync engine's `audit_batch_size` default (sync_engine.md §2.1 and §9; the `evaluate` scope the hosted key holds already takes it), then each held result to `POST /v1/actions/{action_id}/result` (event_format.md "The Lifecycle"). A push the service does not answer leaves everything held, and the call is answered as the same outage without a further send, so an outage never doubles a call's latency. A record whose push the service refuses (`errors` in §2.1's response) is settled as the sync engine settles it, by the one step both share (sync_engine.md §2.1; row 224, ruled 2026-11-08): one refused for its own content is kept as written, marked refused with the code, logged at error and never sent again; one refused for any other reason stays held, never dropped, and is logged at warning; the client pushes again when it next holds a record or result, or when it is next constructed, so a refused record is not re-sent before every call. A record the store itself cannot write is `AUDIT_WRITE_FAILED`, as everywhere: the action is `BLOCK` in either fail mode. A result the store cannot hold is the one typed error the result write raises (row 200).
- **The hosted client's settings.** Each is a constructor option, read from its variable when not given, in both SDKs:

| Setting | Option | Variable | Default | Range |
|---------|--------|----------|---------|-------|
| Request timeout | `timeout` | `HIITL_TIMEOUT` | `5` (seconds) | 0.1–30 seconds (row 209, ruled 2026-11-06: "One timeout range in both SDKs, 0.1 to 30 seconds, declared in the spec; Python takes it", the bound Trevor's declaration, the TypeScript SDK's adopted) |
| Retries | `max_retries` | `HIITL_MAX_RETRIES` | `3` | 0–10 |
| Fail mode | `fail_mode` | `HIITL_FAIL_MODE` | `FAIL_CLOSED` | `FAIL_CLOSED`, `FAIL_OPEN` |

A value outside its range is refused when the client is constructed (`ConfigurationError`), naming the range.

**A record that cannot be written**: the action is `BLOCK` with `error.code` and the reason `AUDIT_WRITE_FAILED`, in every mode and never observed ("Audit write failures in fail-closed mode must block the action", Infrastructure spec 3). It is the one error answer with no record, because the record is what failed; the hosted service answers it with status 500. A limiter that cannot be read is `BLOCK` with `RATE_LIMIT_SERVICE_ERROR` (Rate Limit Counter State), its message authored and the cause logged.

**A failure the path does not name (row 193, ruled 2026-11-06):** "once an envelope exists, an unexpected failure on the evaluate path is `BLOCK`, fail-closed, with `error.code` and an authored message, its record written where the store answers; the same for a failed dedup read in both SDKs", by this section's "Never return generic 500 errors without a decision response body" and Principle 7. Once the envelope exists under **Where the error is answered** above:
- an exception the evaluate path does not raise as its own is `BLOCK` with `error.code` and the one reason code `EVALUATION_FAILED`;
- a dedup read that fails (the store could not be read to find the first decision under the envelope's `idempotency_key`) is `BLOCK` with `AUDIT_READ_FAILED`, in the hosted service and in both SDKs.

Each message is authored for its cause, and the cause is logged where it was caught. Its record is written where the store answers; a store that does not answer leaves no record, and the failure to write it is logged (the action was refused already). The hosted service answers either with status 500 and the decision as its body. Neither is ever the first decision under its `idempotency_key`.

---

## Versioning

**Decision response schema version**: `v1.0`

**Backward compatibility**:
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
| 1.5 | 2026-10-08 | Added `rate_limit_rules` (matching windowed RATE_LIMIT rules; they meter, never bind). DENY wins as ruled (policy_format.md Rule Precedence). | T-130 |
| 1.6 | 2026-10-08 | One rate-window representation (T47): a `RATE_LIMIT` decision's `rate_limit` reports the exceeded rule's scope and window (`<n>s`), and `matched_rules` names the rule — the set-level `metadata.rate_limits` is compiled to rules on load; scope `user_action` added. | T-130 follow-up |
| 1.7 | 2026-10-11 | A `ROUTE` decision carries its rule's `route` as `route_ref`; `enrichment` (the context the last evaluation read) and `routes` (each sync route asked: rule, route, answered / unanswered / failed_open) — a sync route's answer re-entering evaluation (policy_format.md 2.7; TICKET-046). | TICKET-046 |
| 1.8 | 2026-11-03 | Brought current to the ruled changes: `allowed` includes OBSERVE, `route_ref`, `envelope_hash` and `cache_status`, `staged_observations` in every example, evaluate() examples use `action` (HTL-17) | CC |
| 1.9 | 2026-11-04 | HTL-20. Row 134 with row 127: `envelope_hash` is present in every mode and is the one function's hash of the envelope's signed form, so the caller recomputes it from what it sent. Rows 132 and 146: rate limits as ruled: the limiter reads every window before it counts any, so a refused call is counted in none; every decision the limiter counted carries `rate_limit` (the window with the least headroom; R-0008); a `RATE_LIMIT` decision carries the rule's own remediation with its counter state, and `rate_limit_rules[]` carries each rule's `reason_code` and `remediation`; under `OBSERVE_ALL` a refusal is `OBSERVE` / `would_be: RATE_LIMIT`; a limiter that fails is `BLOCK` / `RATE_LIMIT_SERVICE_ERROR`. Computed remediation details (`blocked_fields` from `{ref, filter}`, `threshold.current_value`, `temporal.current_time`). Row 143: a call under a repeated `idempotency_key` returns the first decision, its `action_id` the first action's; the hosted response carries `action_id`, as the schema requires. | CC |
| 1.10 | 2026-11-04 | Declared, never produced, walked down (row 146, HTL-20): `approval_metadata` and `sandbox_metadata` leave the schema (no evaluator, SDK or service sets them); `escalation_context` restated to the shape both SDKs and the service emit, each property the route field it names (routes.md) | CC |
| 1.11 | 2026-11-05 | A field the call does not carry (HTL-22 row 176): under a set's `on_missing: fail_closed` a rule it leaves open decides `BLOCK` / `MISSING_FIELD` with a `custom` remediation naming the fields; `missing_fields` names each rule skipped and flagged (under `skip`, `OBSERVE_ALL` and the staged lane) | CC |
| 1.12 | 2026-11-05 | HTL-22 rows 145-D6 and 159: an error is a decision. `VALIDATION_ERROR` and `POLICY_ERROR` join the enum and the Error Decisions table; each error decision carries `error.code` equal to the decision and its cause as the one reason code, with an authored message (never a caught exception's text); the hosted service answers it as the body with its HTTP status and records it under the key's org; the SDKs return it and raise only before the envelope exists; a record that cannot be written is `BLOCK` / `AUDIT_WRITE_FAILED`. | CC |
| 1.13 | 2026-11-05 | HTL-22 row 174, under `FAIL_CLOSED`: an outage is a decision. Each hosted client answers `CONTROL_PLANE_UNAVAILABLE`, with its cause as the one reason code (`CONTROL_PLANE_TIMEOUT`, `CONTROL_PLANE_UNREACHABLE`, `CIRCUIT_BREAKER_OPEN`) and an authored message, behind a circuit breaker. `metadata` is restated as the outage decision's `fail_mode` and `circuit_breaker_state`. The outage record and `FAIL_OPEN` wait (Stop B). | CC |
| 1.14 | 2026-11-06 | HTL-23, Trevor's rulings of 2026-11-06. Stop B: the hosted client records its outage decision in a local store and pushes it when the service answers (i), and takes `fail_mode`, `FAIL_CLOSED` by default, `FAIL_OPEN` opt-in with the decision `allowed` true and its warning recorded (ii); `status()` names the hosted breaker (row 198); the hosted settings table, with one timeout range of 0.1 to 30 seconds in both SDKs (row 209). Row 193: an unexpected failure once the envelope exists is `BLOCK` / `EVALUATION_FAILED`, a failed dedup read `BLOCK` / `AUDIT_READ_FAILED`. Row 194: `PRINCIPAL_VERIFIER_NOT_CONFIGURED` is a `VALIDATION_ERROR` (400) with one record. Row 203: the caller is read before the request's shape on every endpoint. Row 204: the hosted clients read every member the decision model declares. | CC |
| 1.15 | 2026-11-08 | HTL-27 row 224, as ruled 2026-11-08: a record the hosted client's push is refused for its own content is settled as the sync engine settles it (sync_engine.md §2.1), kept as written, marked refused, logged at error and never sent again; any other refusal stays held, at warning. | CC |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Input to policy evaluation
- [Policy Format Spec](policy_format.md) - Policy evaluation semantics
- [Route Spec](routes.md) - Route schema (external communication — outbound, inbound, bidirectional)
- [Event Format Spec](event_format.md) - Audit record format

---

**This specification is the source of truth. Implementations follow the spec.**
