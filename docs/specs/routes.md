# Route Specification

**Version**: 1.0
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-02-24

---

## Purpose

This document defines the **Route** schema — the third core artifact alongside the execution envelope and the policy format. Routes define **how ECP communicates with external systems.**

Routes replace what was previously modeled as separate concepts:
- **HITL configs** (escalation to human reviewers) → bidirectional sync routes with purpose: review
- **Outbound integrations / webhook emission** → outbound async routes with purpose: observability, compliance
- **Signal ingestion** → inbound async routes with purpose: security, policy-management

All external communication — regardless of direction, timing, or purpose — is a **route.**

---

## The Three-Artifact Model

1. **Envelope** — "here's what the agent wants to do"
2. **Policy** — "this action requires approval" → routes to `finance-review`
3. **Route** — "finance-review means: send context to this endpoint, offer approve/deny/modify, SLA is 15 minutes, timeout escalates via the escalation ladder"

The policy doesn't change across deployment phases. Only the route's target changes:
- Phase 1.5: Route points to a customer-managed webhook endpoint
- Phase 2 (Reviewer Cockpit): Route points to HIITL's managed review queue
- Phase 3 (Certified Network): Route points to HIITL's managed reviewer pool

---

## Route Properties

Every route is characterized by three core properties:

### Direction
- `outbound` — ECP sends to external system. ECP initiates.
- `inbound` — External system sends to ECP. External system initiates.
- `bidirectional` — ECP sends context, waits for response. ECP initiates, external system responds.

### Timing
- `async` — Batched, queued, does not block evaluation. Used when evaluation doesn't depend on the route.
- `sync` — On the hot path, evaluation waits for completion. Used when evaluation depends on the route's result.

### Purpose (Labels)
Purpose labels help developers organize and understand their routes. These are descriptive, not enforced categories:
- `observability` — shipping events to monitoring (Datadog, Grafana)
- `compliance` — shipping evidence to GRC platforms (Vanta, Drata) or receiving compliance assessments
- `review` — routing actions to human reviewers or review queues
- `security` — receiving threat signals, activating kill switches, pushing alerts to SIEM
- `policy-management` — receiving policy updates from external policy management systems
- `assessment` — sending context to evaluation services (LLM analysis, risk scoring, compliance APIs)

---

## Common Route Patterns

| Pattern | Direction | Timing | Purpose | Example |
|---------|-----------|--------|---------|---------|
| Ship audit to Datadog | outbound | async | observability | Batch events, ship on schedule |
| Escalate to human reviewer | bidirectional | sync | review | Send context, wait for approve/deny |
| EU AI Act compliance check | bidirectional | sync | assessment, compliance | Send context, get compliant/non-compliant |
| Receive kill switch from security | inbound | async | security | External tool pushes signal, ECP updates state |
| Receive policy from governance platform | inbound | async | policy-management | External system proposes policy update |
| Push evidence to Vanta | outbound | async | compliance | Ship compliance evidence |

---

## Full Schema

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.ai/schemas/route/v1.json",
  "title": "HIITL Route Configuration",
  "description": "Configuration for external communication routes. Routes define how ECP communicates with external systems — outbound (ECP sends), inbound (external sends to ECP), or bidirectional (ECP sends, waits for response).",
  "type": "object",
  "required": ["name", "version", "direction", "timing"],
  "properties": {
    "name": {
      "type": "string",
      "description": "Unique identifier for this route. Referenced by policy rules via the 'route' field.",
      "pattern": "^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
      "examples": ["finance-review", "datadog-audit", "security-signals"]
    },
    "version": {
      "type": "string",
      "description": "Immutable semver version. Once deployed, never modified — only superseded.",
      "pattern": "^v\\d+\\.\\d+\\.\\d+$",
      "examples": ["v1.0.0", "v2.1.0"]
    },
    "description": {
      "type": "string",
      "description": "Human-readable description of this route's purpose."
    },
    "direction": {
      "type": "string",
      "enum": ["outbound", "inbound", "bidirectional"],
      "description": "Communication direction. outbound: ECP sends to external system. inbound: external system sends to ECP. bidirectional: ECP sends context, waits for response."
    },
    "timing": {
      "type": "string",
      "enum": ["async", "sync"],
      "description": "Whether this route blocks evaluation. async: batched/queued, never blocks. sync: on the hot path, evaluation waits for completion."
    },
    "purpose": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["observability", "compliance", "review", "security", "policy-management", "assessment"]
      },
      "minItems": 1,
      "description": "Descriptive labels for what this route is used for. Not enforced — helps developers organize routes."
    },
    "scope": {
      "type": "object",
      "description": "Tenant and environment scope for this route.",
      "required": ["org_id"],
      "properties": {
        "org_id": {
          "type": "string",
          "pattern": "^org_[a-zA-Z0-9]{16,}$",
          "description": "Organization this route belongs to."
        },
        "environment": {
          "type": "string",
          "enum": ["dev", "stage", "prod"],
          "description": "Environment scope. If omitted, route applies to all environments."
        }
      }
    },
    "endpoint": {
      "type": "string",
      "format": "uri",
      "description": "Target URL for outbound/bidirectional routes. For inbound routes, ECP generates the endpoint — use inbound.url instead."
    },
    "auth": {
      "$ref": "#/$defs/auth"
    },
    "protocol": {
      "type": "string",
      "enum": ["http", "grpc", "webhook"],
      "default": "webhook",
      "description": "Transport protocol. Phase 1: webhook only. grpc reserved for future use."
    },
    "context": {
      "$ref": "#/$defs/context"
    },
    "filters": {
      "$ref": "#/$defs/filters"
    },
    "retry": {
      "$ref": "#/$defs/retry"
    },
    "queue": {
      "$ref": "#/$defs/queue"
    },
    "response_schema": {
      "$ref": "#/$defs/response_schema"
    },
    "sla": {
      "$ref": "#/$defs/sla"
    },
    "escalation_ladder": {
      "$ref": "#/$defs/escalation_ladder"
    },
    "correlation": {
      "$ref": "#/$defs/correlation"
    },
    "inbound": {
      "$ref": "#/$defs/inbound"
    },
    "metadata": {
      "type": "object",
      "description": "Additional metadata for organizational use.",
      "properties": {
        "author": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "tags": {"type": "array", "items": {"type": "string"}}
      },
      "additionalProperties": true
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {"direction": {"const": "outbound"}}
      },
      "then": {
        "required": ["endpoint"],
        "properties": {
          "inbound": false,
          "response_schema": false,
          "sla": false,
          "escalation_ladder": false,
          "correlation": false
        }
      }
    },
    {
      "if": {
        "properties": {"direction": {"const": "bidirectional"}}
      },
      "then": {
        "required": ["endpoint", "response_schema", "sla"],
        "properties": {
          "inbound": false
        }
      }
    },
    {
      "if": {
        "properties": {"direction": {"const": "inbound"}}
      },
      "then": {
        "required": ["inbound"],
        "properties": {
          "endpoint": false,
          "context": false,
          "response_schema": false,
          "sla": false,
          "escalation_ladder": false,
          "correlation": false
        }
      }
    }
  ],
  "$defs": {
    "auth": {
      "type": "object",
      "description": "Authentication configuration for outbound/bidirectional requests, or expected auth for inbound requests.",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["api_key", "bearer_token", "hmac_sha256", "mtls", "oauth2"],
          "description": "Authentication method."
        },
        "header": {
          "type": "string",
          "description": "HTTP header name for API key or bearer token auth.",
          "default": "Authorization",
          "examples": ["Authorization", "X-API-Key"]
        },
        "secret_ref": {
          "type": "string",
          "description": "Reference to the secret value. Never stored in plaintext in the route config. References a secret manager key or environment variable.",
          "examples": ["env:DATADOG_API_KEY", "vault:hiitl/routes/datadog/api_key"]
        },
        "hmac_header": {
          "type": "string",
          "description": "For hmac_sha256: HTTP header carrying the HMAC signature.",
          "default": "X-HIITL-Signature"
        }
      },
      "required": ["type", "secret_ref"]
    },
    "context": {
      "type": "object",
      "description": "What data to send on outbound/bidirectional routes. Defines which envelope fields, labels, and additional context are included.",
      "properties": {
        "fields": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["field_path"],
            "properties": {
              "field_path": {
                "type": "string",
                "description": "Dot-notation path into the envelope (e.g., 'parameters.amount', 'agent_id', 'action')."
              },
              "label": {
                "type": "string",
                "description": "Human-readable label for this field. Used in review UIs."
              },
              "format": {
                "type": "string",
                "enum": ["text", "currency", "date", "json", "code", "url"],
                "default": "text",
                "description": "Display format hint for UIs consuming this data."
              }
            }
          },
          "description": "Which envelope fields to include in the outbound payload."
        },
        "include_policy_ref": {
          "type": "boolean",
          "default": true,
          "description": "Include which policy/rule triggered this route in the outbound payload."
        },
        "include_audit_context": {
          "type": "boolean",
          "default": false,
          "description": "Include relevant audit history (recent actions by same agent) in the outbound payload."
        },
        "risk_framing": {
          "type": "object",
          "description": "How to frame the risk/severity for the recipient (human reviewer, compliance system, etc.).",
          "properties": {
            "severity": {
              "type": "string",
              "enum": ["low", "medium", "high", "critical"],
              "description": "Severity level for this escalation."
            },
            "summary": {
              "type": "string",
              "description": "Human-readable risk summary."
            },
            "consequences": {
              "type": "object",
              "properties": {
                "if_approved": {"type": "string", "description": "What happens if the action is approved."},
                "if_denied": {"type": "string", "description": "What happens if the action is denied."}
              }
            }
          }
        }
      }
    },
    "filters": {
      "type": "object",
      "description": "When this route activates. Routes without filters activate for all matching decisions. Filters narrow activation to specific tools, agents, or sensitivity levels.",
      "properties": {
        "decisions": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": ["ALLOW", "BLOCK", "PAUSE", "REQUIRE_APPROVAL", "SANDBOX", "RATE_LIMIT", "KILL_SWITCH", "ESCALATE", "ROUTE"]
          },
          "description": "Activate this route only for specific decision types."
        },
        "tools": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Activate only for specific tool names."
        },
        "agents": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Activate only for specific agent IDs."
        },
        "sensitivity": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": ["money", "identity", "permissions", "regulated", "irreversible"]
          },
          "description": "Activate only for actions with specific sensitivity classifications."
        }
      }
    },
    "retry": {
      "type": "object",
      "description": "Retry configuration for failed outbound/bidirectional deliveries.",
      "properties": {
        "max_attempts": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10,
          "default": 3,
          "description": "Maximum delivery attempts before giving up."
        },
        "backoff": {
          "type": "string",
          "enum": ["exponential", "linear", "fixed"],
          "default": "exponential",
          "description": "Backoff strategy between retries."
        },
        "initial_delay_ms": {
          "type": "integer",
          "minimum": 100,
          "maximum": 60000,
          "default": 1000,
          "description": "Initial delay before first retry (milliseconds)."
        }
      }
    },
    "queue": {
      "type": "object",
      "description": "Batching configuration for async routes. Ignored for sync routes.",
      "properties": {
        "batch_size": {
          "type": "integer",
          "minimum": 1,
          "maximum": 1000,
          "default": 100,
          "description": "Maximum events per batch."
        },
        "flush_interval": {
          "type": "string",
          "pattern": "^\\d+(s|m|h)$",
          "default": "30s",
          "description": "How often to flush the batch (e.g., '30s', '5m', '1h').",
          "examples": ["10s", "30s", "5m"]
        }
      }
    },
    "response_schema": {
      "type": "object",
      "description": "Expected response format for bidirectional routes. Defines what the external system can respond with.",
      "required": ["decision_options"],
      "properties": {
        "decision_options": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": [
              "approve",
              "deny",
              "modify",
              "delegate",
              "request_more_info",
              "conditional_approve",
              "partial_approve"
            ]
          },
          "minItems": 2,
          "description": "Response types available to the external system (e.g., human reviewer)."
        },
        "required_fields": {
          "type": "array",
          "items": {"type": "string"},
          "default": ["decision"],
          "description": "Fields required in every response.",
          "examples": [["decision", "reason"]]
        },
        "optional_fields": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Fields accepted but not required.",
          "examples": [["modifications", "conditions", "notes", "time_bound"]]
        },
        "reason_required_for": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Which decision options require a reason string.",
          "examples": [["deny", "modify"]]
        },
        "modify_constraints": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["field_path", "constraint"],
            "properties": {
              "field_path": {"type": "string", "description": "Dot-notation path to the modifiable field."},
              "constraint": {
                "type": "string",
                "enum": ["reduce_only", "increase_only", "any", "select_from"],
                "description": "What kind of modification is allowed."
              },
              "options": {
                "type": "array",
                "description": "For 'select_from' constraint: the allowed values."
              }
            }
          },
          "description": "Phase 2: Which parameters the reviewer can modify and constraints on modifications."
        }
      }
    },
    "sla": {
      "type": "object",
      "description": "Response time expectations for bidirectional routes. Defines timeout behavior.",
      "required": ["timeout", "timeout_action"],
      "properties": {
        "timeout": {
          "type": "string",
          "pattern": "^\\d+(s|m|h)$",
          "description": "Maximum time to wait for a response (e.g., '30s', '15m', '4h', '24h').",
          "examples": ["30s", "15m", "4h"]
        },
        "timeout_action": {
          "type": "string",
          "enum": ["escalate", "fail_closed", "fail_open", "extend"],
          "description": "What happens when timeout is reached. escalate: route to escalation_ladder. fail_closed: block the action (safe default). fail_open: allow the action with warning. extend: double the timeout once."
        },
        "auto_approve_flag": {
          "type": "boolean",
          "default": false,
          "description": "If timeout_action is fail_open, flag the approval as auto-approved in audit trail."
        }
      }
    },
    "escalation_ladder": {
      "type": "object",
      "description": "Multi-level escalation for bidirectional routes. If the initial target doesn't respond within SLA, route to the next level.",
      "properties": {
        "levels": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["level", "route", "after"],
            "properties": {
              "level": {
                "type": "integer",
                "minimum": 1,
                "description": "Escalation level number (1 = first escalation)."
              },
              "route": {
                "type": "string",
                "description": "Name of the route to escalate to.",
                "pattern": "^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
              },
              "after": {
                "type": "string",
                "pattern": "^\\d+(s|m|h)$",
                "description": "Duration before escalating to this level.",
                "examples": ["15m", "1h", "4h"]
              }
            }
          },
          "description": "Ordered list of escalation targets."
        },
        "max_escalation_depth": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10,
          "description": "Maximum number of escalation levels before final timeout."
        },
        "final_timeout_action": {
          "type": "string",
          "enum": ["fail_closed", "fail_open"],
          "default": "fail_closed",
          "description": "What happens when max escalation depth is reached and no response. fail_closed (block, safe default) or fail_open (allow with warning)."
        }
      }
    },
    "correlation": {
      "type": "object",
      "description": "How request and response are matched for bidirectional routes. ECP includes a resume token in the outbound payload; the responding system echoes it back.",
      "properties": {
        "token_field": {
          "type": "string",
          "default": "resume_token",
          "description": "Field name for the resume/correlation token in both request and response payloads."
        }
      }
    },
    "inbound": {
      "type": "object",
      "description": "Configuration for inbound routes (external systems pushing to ECP).",
      "required": ["permissions"],
      "properties": {
        "url": {
          "type": "string",
          "format": "uri",
          "description": "ECP-provided webhook URL for this route. Generated by ECP, shared with the external system. Read-only — set by the system, not the user.",
          "readOnly": true
        },
        "auth": {
          "type": "object",
          "description": "Route-specific authentication credentials for the external system to use when calling ECP.",
          "properties": {
            "type": {
              "type": "string",
              "enum": ["bearer_token", "hmac_sha256"],
              "description": "Authentication method the external system must use."
            },
            "token_ref": {
              "type": "string",
              "description": "Reference to the generated token. Read-only — set by the system.",
              "readOnly": true
            }
          }
        },
        "payload_mapping": {
          "type": "object",
          "description": "How to extract structured signals from the external system's payload format. Different systems (Datadog, PagerDuty, custom) have different payload structures.",
          "properties": {
            "signal_type": {
              "type": "string",
              "description": "JSONPath or field reference for the signal type (e.g., '$.data.alert_type')."
            },
            "agent_ref": {
              "type": "string",
              "description": "JSONPath for the agent identifier, if applicable (e.g., '$.data.tags.agent_id')."
            },
            "severity": {
              "type": "string",
              "description": "JSONPath for severity/priority (e.g., '$.data.attributes.severity')."
            },
            "metadata": {
              "type": "object",
              "description": "Additional field mappings for route-specific data extraction.",
              "additionalProperties": {"type": "string"}
            }
          }
        },
        "permissions": {
          "type": "object",
          "description": "What this inbound route is authorized to do. Trust is explicit and granular per route.",
          "properties": {
            "can_enforce": {
              "type": "boolean",
              "default": false,
              "description": "Can activate kill switches or enforcement state changes. Use for trusted security monitoring tools."
            },
            "can_propose": {
              "type": "boolean",
              "default": false,
              "description": "Can submit policy change proposals (PR-like review workflow). Use for governance platforms."
            },
            "can_signal": {
              "type": "boolean",
              "default": false,
              "description": "Can push risk signals that policies reference in conditions. Use for eval tools, anomaly detectors."
            },
            "enforce_scope": {
              "type": "array",
              "items": {"type": "string"},
              "description": "If can_enforce is true, limits what enforcement actions are permitted.",
              "examples": [["kill_switch:agent", "kill_switch:tool", "rate_limit"]]
            }
          }
        },
        "acceptance_mode": {
          "type": "string",
          "enum": ["propose", "auto_accept"],
          "default": "propose",
          "description": "For can_propose routes: 'propose' creates a review proposal (PR-like), 'auto_accept' applies immediately. Default is 'propose' for safety."
        }
      }
    }
  }
}
```

---

## Validation Rules

### Common Rules (All Directions)

| Rule | Description |
|------|-------------|
| `name` must be unique per (org_id, environment) | No two active routes in the same scope can share a name. |
| `name` pattern: `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` | Lowercase alphanumeric with hyphens, 3-64 characters, must start and end with alphanumeric. |
| `version` is immutable once deployed | A deployed version is never modified — only superseded by a new version. |
| `purpose` must have at least one label | Every route must declare its purpose. |
| `auth.secret_ref` never contains plaintext secrets | References a secret manager key or environment variable, never the actual secret value. |

### Direction-Specific Required Fields

| Direction | Required Fields | Forbidden Fields |
|-----------|----------------|------------------|
| `outbound` | `endpoint` | `inbound`, `response_schema`, `sla`, `escalation_ladder`, `correlation` |
| `bidirectional` | `endpoint`, `response_schema`, `sla` | `inbound` |
| `inbound` | `inbound.permissions` | `endpoint`, `context`, `response_schema`, `sla`, `escalation_ladder`, `correlation` |

### Timing Constraints

| Constraint | Description |
|------------|-------------|
| `sync` routes must not use `queue` | Sync routes are on the hot path — batching is not applicable. |
| `async` routes should specify `queue` or use defaults | Async routes benefit from batching configuration. Defaults: batch_size=100, flush_interval=30s. |
| `bidirectional` routes are always `sync` | Bidirectional implies waiting for a response — async bidirectional is not currently supported. |
| `outbound` routes can be `async` or `sync` | Async for fire-and-forget (observability, compliance). Sync for real-time assessment (rare). |

### Inbound Permission Rules

| Rule | Description |
|------|-------------|
| At least one permission must be `true` | An inbound route with all permissions `false` has no effect. |
| `enforce_scope` requires `can_enforce: true` | Specifying enforce_scope without can_enforce is invalid. |
| `acceptance_mode` requires `can_propose: true` | Specifying acceptance_mode without can_propose is invalid. |
| `auto_accept` requires explicit opt-in | Default is always `propose`. Auto-accept is for trusted systems only. |

### Escalation Ladder Rules

| Rule | Description |
|------|-------------|
| Levels must be in ascending order | Level numbers must be sequential starting from 1. |
| Referenced routes must exist | Each level's `route` field must reference a valid bidirectional route in the same scope. |
| `after` durations must be increasing | Each level's timeout must be greater than or equal to the previous level's. |
| Self-reference is forbidden | A route's escalation ladder must not reference itself. |

---

## Inbound Route Permissions

Inbound routes have scoped permissions defining what the external system is allowed to do:

| Permission | Description | Example |
|------------|-------------|---------|
| `can_enforce` | Can activate kill switches or enforcement changes | Security monitoring tool |
| `can_propose` | Can submit policy change proposals (PR-like review) | Enterprise governance platform |
| `can_signal` | Can push risk signals that policies reference | Eval tools, anomaly detectors |

`enforce_scope` further limits what enforcement actions are permitted (e.g., `["kill_switch:agent", "rate_limit"]`).

**Acceptance mode** for policy updates: `"propose"` (default, creates review proposal) or `"auto_accept"` (for trusted systems).

---

## How Policies Reference Routes

Policy rules reference routes by name using the `route` field:

```yaml
- name: "require-approval-high-value"
  conditions:
    all_of:
      - field: "parameters.amount"
        operator: "greater_than"
        value: 500
  decision: "REQUIRE_APPROVAL"
  reason_code: "HIGH_VALUE_PAYMENT"
  route: "finance-review"  # References this route by name
```

**Resolution**: When the evaluator produces a `REQUIRE_APPROVAL`, `PAUSE`, or `ESCALATE` decision, the system resolves the named route for the current (org_id, environment) scope and includes the resolved details in the decision response via `route_ref` and `escalation_context`.

**Missing route**: If a rule references a route that doesn't exist, the system:
1. Still produces the decision (REQUIRE_APPROVAL, etc.)
2. Includes the `route_ref` in the response (so the caller knows what was expected)
3. Omits `escalation_context` (no route to resolve)
4. Logs a warning event

**Outbound routes and filters**: Outbound routes are not referenced by individual policy rules. Instead, they use `filters` to activate based on decision type, tool, agent, or sensitivity. An outbound route with `filters.decisions: ["BLOCK"]` fires for every BLOCK decision. This is org-level configuration, not per-rule.

---

## Route Examples

### Example 1: Ship Audit Events to Datadog (Outbound Async)

```yaml
name: "datadog-audit"
version: "v1.0.0"
description: "Ship all audit events to Datadog for monitoring and alerting"
direction: outbound
timing: async
purpose: ["observability"]

scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"

endpoint: "https://http-intake.logs.datadoghq.com/api/v2/logs"
auth:
  type: api_key
  header: "DD-API-KEY"
  secret_ref: "env:DATADOG_API_KEY"
protocol: webhook

context:
  fields:
    - field_path: "action_id"
      label: "Action ID"
    - field_path: "agent_id"
      label: "Agent"
    - field_path: "action"
      label: "Tool"
    - field_path: "parameters"
      label: "Parameters"
      format: json
  include_policy_ref: true
  include_audit_context: false

filters:
  decisions: ["ALLOW", "BLOCK", "RATE_LIMIT", "KILL_SWITCH", "REQUIRE_APPROVAL"]

retry:
  max_attempts: 3
  backoff: exponential
  initial_delay_ms: 1000

queue:
  batch_size: 100
  flush_interval: "30s"

metadata:
  author: "platform-team@acmecorp.com"
  tags: ["monitoring", "datadog", "production"]
```

### Example 2: Escalate to Human Reviewer (Bidirectional Sync)

```yaml
name: "finance-review"
version: "v1.0.0"
description: "Route high-value payments to the finance team for approval"
direction: bidirectional
timing: sync
purpose: ["review"]

scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"

endpoint: "https://hooks.acmecorp.com/hiitl/finance-review"
auth:
  type: hmac_sha256
  secret_ref: "env:HIITL_FINANCE_WEBHOOK_SECRET"
  hmac_header: "X-HIITL-Signature"
protocol: webhook

context:
  fields:
    - field_path: "parameters.amount"
      label: "Transaction Amount"
      format: currency
    - field_path: "parameters.currency"
      label: "Currency"
    - field_path: "target.account_id"
      label: "Target Account"
    - field_path: "agent_id"
      label: "Requesting Agent"
    - field_path: "action"
      label: "Action Type"
  include_policy_ref: true
  include_audit_context: false
  risk_framing:
    severity: "high"
    summary: "High-value payment requires finance team approval"
    consequences:
      if_approved: "Payment will be processed to the target account"
      if_denied: "Payment will be blocked. Agent receives BLOCK decision."

response_schema:
  decision_options: ["approve", "deny"]
  required_fields: ["decision"]
  optional_fields: ["reason", "notes"]
  reason_required_for: ["deny"]

sla:
  timeout: "4h"
  timeout_action: escalate

escalation_ladder:
  levels:
    - level: 1
      route: "senior-finance-review"
      after: "4h"
    - level: 2
      route: "cfo-review"
      after: "2h"
  max_escalation_depth: 2
  final_timeout_action: fail_closed

correlation:
  token_field: "resume_token"

retry:
  max_attempts: 3
  backoff: exponential
  initial_delay_ms: 2000

metadata:
  author: "finance-team@acmecorp.com"
  tags: ["payments", "high-value", "finance"]
```

### Example 3: EU AI Act Compliance Check (Bidirectional Sync)

```yaml
name: "eu-ai-act-check"
version: "v1.0.0"
description: "Send action context to compliance API for EU AI Act evaluation"
direction: bidirectional
timing: sync
purpose: ["assessment", "compliance"]

scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"

endpoint: "https://compliance-api.acmecorp.com/v1/evaluate"
auth:
  type: bearer_token
  header: "Authorization"
  secret_ref: "env:COMPLIANCE_API_TOKEN"
protocol: http

context:
  fields:
    - field_path: "action"
      label: "Action Type"
    - field_path: "parameters"
      label: "Action Parameters"
      format: json
    - field_path: "agent_id"
      label: "Agent"
    - field_path: "sensitivity"
      label: "Sensitivity Classification"
  include_policy_ref: true
  risk_framing:
    severity: "high"
    summary: "Action requires EU AI Act compliance evaluation"

response_schema:
  decision_options: ["approve", "deny"]
  required_fields: ["decision", "reason"]
  optional_fields: ["article_citations", "risk_level", "conditions"]

sla:
  timeout: "30s"
  timeout_action: fail_closed

correlation:
  token_field: "correlation_id"

retry:
  max_attempts: 2
  backoff: fixed
  initial_delay_ms: 500

metadata:
  author: "compliance@acmecorp.com"
  tags: ["eu-ai-act", "regulatory", "compliance"]
```

### Example 4: Receive Kill Switch Signal from Security (Inbound Async)

```yaml
name: "crowdstrike-signals"
version: "v1.0.0"
description: "Receive kill switch and threat signals from CrowdStrike"
direction: inbound
timing: async
purpose: ["security"]

scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"

inbound:
  # url: generated by ECP, e.g. "https://api.hiitl.ai/v1/inbound/org_acmecorp1234567/crowdstrike-signals"
  auth:
    type: hmac_sha256
  payload_mapping:
    signal_type: "$.data.alert_type"
    agent_ref: "$.data.tags.agent_id"
    severity: "$.data.attributes.severity"
    metadata:
      threat_id: "$.data.id"
      description: "$.data.attributes.description"
  permissions:
    can_enforce: true
    can_propose: false
    can_signal: true
    enforce_scope: ["kill_switch:agent", "kill_switch:tool"]
  acceptance_mode: "propose"

metadata:
  author: "security@acmecorp.com"
  tags: ["crowdstrike", "threat-detection", "kill-switch"]
```

### Example 5: Receive Policy from Governance Platform (Inbound Async)

```yaml
name: "governance-policy-sync"
version: "v1.0.0"
description: "Receive policy updates from enterprise governance platform"
direction: inbound
timing: async
purpose: ["policy-management"]

scope:
  org_id: "org_acmecorp1234567"

inbound:
  auth:
    type: bearer_token
  payload_mapping:
    signal_type: "$.event_type"
    metadata:
      policy_name: "$.policy.name"
      policy_version: "$.policy.version"
      policy_content: "$.policy.rules"
      change_reason: "$.metadata.reason"
  permissions:
    can_enforce: false
    can_propose: true
    can_signal: false
  acceptance_mode: "propose"

metadata:
  author: "governance@acmecorp.com"
  tags: ["governance", "policy-sync", "enterprise"]
```

### Example 6: Push Compliance Evidence to Vanta (Outbound Async)

```yaml
name: "vanta-evidence"
version: "v1.0.0"
description: "Ship compliance evidence to Vanta for SOC 2 certification"
direction: outbound
timing: async
purpose: ["compliance"]

scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"

endpoint: "https://api.vanta.com/v1/evidence/ingest"
auth:
  type: bearer_token
  header: "Authorization"
  secret_ref: "env:VANTA_API_TOKEN"
protocol: webhook

context:
  fields:
    - field_path: "action_id"
      label: "Control Evidence ID"
    - field_path: "agent_id"
      label: "Agent"
    - field_path: "action"
      label: "Action Type"
    - field_path: "sensitivity"
      label: "Data Classification"
  include_policy_ref: true
  include_audit_context: false

filters:
  decisions: ["BLOCK", "REQUIRE_APPROVAL", "KILL_SWITCH", "RATE_LIMIT"]
  sensitivity: ["money", "identity", "regulated"]

retry:
  max_attempts: 5
  backoff: exponential
  initial_delay_ms: 2000

queue:
  batch_size: 50
  flush_interval: "5m"

metadata:
  author: "compliance@acmecorp.com"
  tags: ["vanta", "soc2", "compliance-evidence"]
```

---

## Migration from HITL Config

All HITL config concepts map directly to bidirectional sync routes with `purpose: ["review"]`. This section documents the complete field mapping and code changes required.

### Field Mapping

| HITL Config Field | Route Equivalent | Notes |
|-------------------|------------------|-------|
| `name` | `name` | Same semantics — unique identifier referenced by policies. |
| `version` | `version` | Same format (semver). Same immutability guarantee. |
| `description` | `description` | Direct mapping. |
| `scope.org_id` | `scope.org_id` | Same tenant isolation model. |
| `scope.environment` | `scope.environment` | Same values: dev, stage, prod. |
| — | `direction: bidirectional` | New field. All HITL configs become bidirectional routes. |
| — | `timing: sync` | New field. All HITL config escalations are sync (evaluation pauses). |
| — | `purpose: ["review"]` | New field. Labels this as a human review route. |
| `escalation_context.surface_fields` | `context.fields` | Each `{field_path, label, format}` maps directly. |
| `escalation_context.additional_context` | `context.include_audit_context: true` | Phase 2: additional context types (recent_actions, related_actions) map to `include_audit_context`. |
| `escalation_context.risk_framing` | `context.risk_framing` | Same structure: severity, summary, consequences. |
| `response_schema.available_responses` | `response_schema.decision_options` | Renamed field. Same values. |
| `response_schema.modify_constraints` | `response_schema.modify_constraints` | Same structure. |
| `response_schema.required_fields.reason_required_for` | `response_schema.reason_required_for` | Moved up one level — not nested under required_fields. |
| `response_schema.required_fields.notes_optional` | `response_schema.optional_fields: ["notes"]` | Explicit optional field list replaces boolean flag. |
| `routing.target_type` | `protocol` + endpoint structure | `webhook` → `protocol: webhook`. Other target types (managed_queue, user, role) are Phase 2 endpoint variations. |
| `routing.target` | `endpoint` | Direct mapping — the URL of the webhook. |
| `routing.routing_conditions` | (Phase 2) | Dynamic routing based on action content — deferred. |
| `sla.response_time_seconds` | `sla.timeout` | Changed from integer seconds to duration string (e.g., `"4h"`, `"900s"`). |
| `sla.timeout_behavior` | `sla.timeout_action` | Renamed. Values: `escalate` → `escalate`, `auto_deny` → `fail_closed`, `auto_approve` → `fail_open`, `extend` → `extend`. |
| `sla.auto_approve_flag` | `sla.auto_approve_flag` | Same semantics. |
| `escalation_ladder.levels` | `escalation_ladder.levels` | Restructured: `{level, target_type, target, sla_seconds}` → `{level, route, after}`. Each escalation level references another route by name instead of inline target definition. |
| `escalation_ladder.max_escalation_depth` | `escalation_ladder.max_escalation_depth` | Same semantics. |
| `escalation_ladder.final_timeout_behavior` | `escalation_ladder.final_timeout_action` | Renamed. Values: `auto_deny` → `fail_closed`, `auto_approve` → `fail_open`. |
| `metadata` | `metadata` | Same structure. |

### Code References to Rename

| Location | Old | New | Notes |
|----------|-----|-----|-------|
| Policy rules | `hitl_config: "name"` | `route: "name"` | Policy format spec already updated. |
| Decision response | `hitl_config_ref` | `route_ref` | Decision response spec already updated. |
| Python SDK | `HitlConfigLoader` | Route loader (TBD) | TICKET-020.1 renames. |
| TypeScript SDK | `HitlConfigLoader` | Route loader (TBD) | TICKET-020.1 renames. |
| Database | `hitl_configs` table | `routes` table | Requires migration. |
| API endpoints | `/hitl-configs/` | `/routes/` | Server endpoint rename. |
| File paths (local mode) | `hitl_configs/{org}/{env}/` | `routes/{org}/{env}/` | Directory rename. |

### YAML Conversion Example

**Before (HITL Config):**

```yaml
name: "finance-review"
version: "v1.0.0"
scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"
escalation_context:
  surface_fields:
    - field_path: "parameters.amount"
      label: "Transaction Amount"
      format: "currency"
    - field_path: "target.account_id"
      label: "Target Account"
  risk_framing:
    severity: "high"
    summary: "High-value payment requires finance team approval"
response_schema:
  available_responses: ["approve", "deny"]
  required_fields:
    reason_required_for: ["deny"]
    notes_optional: true
routing:
  target_type: "webhook"
  target: "https://hooks.acmecorp.com/hiitl/finance-review"
sla:
  response_time_seconds: 14400
  timeout_behavior: "escalate"
```

**After (Route):**

```yaml
name: "finance-review"
version: "v1.0.0"
direction: bidirectional
timing: sync
purpose: ["review"]
scope:
  org_id: "org_acmecorp1234567"
  environment: "prod"
endpoint: "https://hooks.acmecorp.com/hiitl/finance-review"
auth:
  type: hmac_sha256
  secret_ref: "env:HIITL_FINANCE_WEBHOOK_SECRET"
  hmac_header: "X-HIITL-Signature"
protocol: webhook
context:
  fields:
    - field_path: "parameters.amount"
      label: "Transaction Amount"
      format: currency
    - field_path: "target.account_id"
      label: "Target Account"
  include_policy_ref: true
  risk_framing:
    severity: "high"
    summary: "High-value payment requires finance team approval"
response_schema:
  decision_options: ["approve", "deny"]
  required_fields: ["decision"]
  optional_fields: ["reason", "notes"]
  reason_required_for: ["deny"]
sla:
  timeout: "4h"
  timeout_action: escalate
correlation:
  token_field: "resume_token"
```

**Key changes:**
1. Added `direction`, `timing`, `purpose` (new route properties)
2. Flattened `routing.target` → `endpoint`
3. Added `auth` (explicit authentication — was implicit in HITL config)
4. Renamed `escalation_context.surface_fields` → `context.fields`
5. Renamed `available_responses` → `decision_options`
6. Changed `response_time_seconds: 14400` → `timeout: "4h"` (human-readable duration)
7. Added `correlation` (explicit request/response matching)

---

## Storage

### Local Mode
- Routes stored as YAML/JSON files on disk alongside policies
- File path: `routes/{config_name}.yaml` (org/environment scope from file content or directory structure)

### Hosted Mode
- Routes stored in database (PostgreSQL)
- Same immutable versioning model as policies (new version = new row)
- Managed via API (CRUD operations)
- Active version tracked separately

### Tenant Isolation
- Routes are scoped by (org_id, environment) — same as policies
- Cross-tenant access to routes is a critical severity bug

---

## Phase Implementation Scope

### Phase 1.5 (This Release)

| Capability | Status |
|------------|--------|
| Route schema (this document) | Spec complete |
| Bidirectional sync routes (human review) | Implementation via TICKET-020.x |
| Outbound async routes (webhook emission) | Implementation via TICKET-020.x |
| Policy rules reference `route` by name | Already implemented (policy format v1.2) |
| Decision response includes `route_ref` | Already implemented (decision response v1.2) |

### Phase 2 (Reviewer Cockpit)

| Capability | Status |
|------------|--------|
| Managed bidirectional route target (HIITL review queue) | Planned |
| Inbound async routes (signal ingestion) | Planned |
| `modify`, `delegate`, `request_more_info` response options | Planned |
| Modify constraints on response_schema | Planned |
| Escalation ladder implementation | Planned |
| One-click route templates for common targets | Planned |

### Phase 3 (Certified Network)

| Capability | Status |
|------------|--------|
| Certified reviewer network route target | Planned |
| `partial_approve` response option | Planned |
| Policy suggestion feedback loop | Planned |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-24 | Initial draft — unified route model replacing HITL configs, outbound integrations, and signal ingestion | Strategic Evolution v2 |
| 1.0 | 2026-02-24 | Full JSON Schema. Examples for all 6 common route patterns. Validation rules. Complete migration guide from HITL config. | TICKET-019.1 |

---

## Related Documents

- [Policy Format Spec](policy_format.md) - Rules reference routes via `route` field
- [Decision Response Spec](decision_response.md) - `route_ref` in escalation decisions
- [Event Format Spec](event_format.md) - Outbound route event format
- [HITL Config Spec](hitl_config.md) - *(Deprecated — predecessor to this spec)*
- [Strategic Evolution v2](../product_planning/ecp_strategic_evolution_feb_2026_v2.md) - Section 5: full route model design

---

**This specification is the source of truth for routes. Routes are the third core artifact alongside the envelope schema and policy format.**
