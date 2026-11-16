# Route Specification

**Version**: 1.4
**Status**: Phase 1.5 + Block 3b/4a IMPLEMENTED; Phase 2 sections marked deferred
**Last Updated**: 2026-11-14

> **Status (2026-05-13)**: The v1.0 spec described the full target
> architecture as if it were Phase 1.5 baseline. **Reality**: the
> core machinery (three-artifact model, direction, timing, sync
> routes via Postgres job queue + pg_notify/SSE, async outbound
> webhook execution) is built and in production. Several spec
> sections (escalation ladders, retry config at route-level,
> batching, response-schema enforcement, correlation tokens,
> inbound routes) are **deferred to Phase 2+**. Outbound routes and
> their `filters` are built as of HTL-29 row 131 (2026-11-09):
> before it, nothing enqueued an outbound job.
> Each affected section now carries a "🟡 Planned" callout. The
> "Implementation: How Routes Execute" section near the end
> documents the actual Postgres job queue + worker pattern that
> v1.0 didn't cover.

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
- Phase 2 (Reviewer Cockpit): Route points to hiitl's managed review queue
- Phase 3 (Certified Network): Route points to hiitl's managed reviewer pool

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

Every supplied number, including open route metadata, follows the single
[numeric domain](sync_engine.md#numeric-domain) before loading, evaluation or recording.
YAML input follows [the shared scalar reading](policy_format.md#format-priority).

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.com/schemas/route/v1.json",
  "title": "hiitl Route Configuration",
  "description": "Configuration for external communication routes. Routes define how ECP communicates with external systems — outbound (ECP sends), inbound (external sends to ECP), or bidirectional (ECP sends, waits for response).",
  "type": "object",
  "required": ["name", "version", "direction", "timing"],
  "additionalProperties": false,
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
      "additionalProperties": false,
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
      "additionalProperties": false,
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
      "description": "What a bidirectional route sends: which envelope fields, labels, and additional context are included. An outbound route sends the record (\"Outbound routes and filters\", below) and is refused with `context` (HTL-29 row 131; R-0872).",
      "additionalProperties": false,
      "properties": {
        "fields": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["field_path"],
            "additionalProperties": false,
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
          "additionalProperties": false,
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
              "additionalProperties": false,
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
      "description": "Which records an outbound route receives (\"Outbound routes and filters\", below; HTL-29 row 131). A route without filters receives every record of its org and environment. Each key the filter declares narrows: a record passes a key when its value is one the key lists, and passes the filter when it passes every key declared. A key's values are read from their source's own taxonomy, and a value outside it is refused at load, naming the allowed values.",
      "additionalProperties": false,
      "properties": {
        "decisions": {
          "type": "array",
          "items": {"type": "string", "description": "A decision type: a value of decision_response.md's `decision`, the record's `decision_type`."},
          "description": "Receive only records whose `decision_type` is one of these."
        },
        "actions": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Receive only records whose `action` is one of these. The key was `tools`, renamed with no alias (HTL-29 row 241, ruled 2026-11-09): a route naming `filters.tools` is refused at load, naming `filters.actions`."
        },
        "agents": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Receive only records whose `agent_id` is one of these."
        },
        "sensitivity": {
          "type": "array",
          "items": {"$ref": "envelope_schema.json#/properties/sensitivity/items"},
          "description": "Receive only records whose envelope's `sensitivity` holds one of these. The values are the envelope's own; this list used to copy five of its seven."
        }
      }
    },
    "retry": {
      "type": "object",
      "description": "🟡 PARTIALLY BUILT. Retry configuration for failed outbound/bidirectional deliveries. **Today**: the hosted route executor implements exponential backoff with jitter (5s × 2^(attempt-1)) and max 3 attempts — but these values are HARDCODED. The schema accepts and stores `max_attempts`, `backoff`, and `initial_delay_ms`, but the executor doesn't yet read them. Setting `max_attempts: 10` on a route stores the value but the executor still uses 3. Phase 2 work to plumb the config through.",
      "additionalProperties": false,
      "properties": {
        "max_attempts": {
          "type": "integer",
          "$comment": "Numeric admission: sync_engine.md#numeric-domain (one shared declaration).",
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
          "$comment": "Numeric admission: sync_engine.md#numeric-domain (one shared declaration).",
          "minimum": 100,
          "maximum": 60000,
          "default": 1000,
          "description": "Initial delay before first retry (milliseconds)."
        }
      }
    },
    "queue": {
      "type": "object",
      "description": "🟡 PLANNED (Phase 2). Batching configuration for async routes. Ignored for sync routes. **Today**: every async job executes individually as soon as a worker claims it from the queue. No batch accumulation happens. The schema accepts batch_size + flush_interval but the executor doesn't yet aggregate. A route with batch_size=100 currently fires 100 separate webhook calls instead of one batched call. Phase 2 work.",
      "additionalProperties": false,
      "properties": {
        "batch_size": {
          "type": "integer",
          "$comment": "Numeric admission: sync_engine.md#numeric-domain (one shared declaration).",
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
      "description": "🟡 PARTIALLY BUILT. Expected response format for bidirectional routes. Defines what the external system can respond with. **Today**: `decision_options` (approve / deny / modify only) and `reason_required_for` are recognized; the reviewer endpoint accepts these. **modify_constraints and the delegate/request_more_info/partial_approve options are NOT enforced** — a reviewer can submit any JSON and the system accepts it. Schema validation of reviewer responses is Phase 2 work.",
      "required": ["decision_options"],
      "additionalProperties": false,
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
            "additionalProperties": false,
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
      "additionalProperties": false,
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
          "description": "What happens when timeout is reached. escalate and extend: read as fail_closed until escalation ladders are built. fail_closed: block the action (safe default). fail_open: allow the action with warning. A review case records it when opened and takes it when its wait ends (see 'A review case: the route's wait, its timeout, its transitions')."
        }
      }
    },
    "escalation_ladder": {
      "type": "object",
      "description": "🟡 PLANNED (Phase 2). Multi-level escalation for bidirectional routes. If the initial target doesn't respond within SLA, route to the next level. **Today**: not implemented. ReviewCase has a single SLA timeout that defaults to fail_closed (or fail_open if configured per the SLA object). Multi-level cascading — '4h then senior, 2h then CFO' — is Phase 2 work. The schema is stable so future enforcement is backward-compatible; routes can store escalation_ladder values today and they'll activate when implemented.",
      "additionalProperties": false,
      "properties": {
        "levels": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["level", "route", "after"],
            "additionalProperties": false,
            "properties": {
              "level": {
                "type": "integer",
                "$comment": "Numeric admission: sync_engine.md#numeric-domain (one shared declaration).",
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
          "$comment": "Numeric admission: sync_engine.md#numeric-domain (one shared declaration).",
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
      "description": "🟡 PLANNED (Phase 2). How request and response are matched for bidirectional routes. ECP would include a resume token in the outbound payload; the responding system echoes it back. **Today**: ECP does emit a `resume_token` on PAUSE/REQUIRE_APPROVAL/ESCALATE decisions (see decision_response.md), but the bidirectional resume flow uses a different mechanism — the ReviewCase API + SSE — and doesn't require the external system to echo a token back. Token-echo correlation is Phase 2 work for external-webhook bidirectional routes.",
      "additionalProperties": false,
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
      "description": "🟡 PLANNED (Phase 2). Configuration for inbound routes (external systems pushing to ECP). **Today**: schema only. No inbound route execution; no webhook endpoint generation; no permission-gated signal handling. The 'receive kill switch from security' / 'receive policy from governance platform' use cases described in this spec are Phase 2 work.",
      "required": ["permissions"],
      "additionalProperties": false,
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
          "additionalProperties": false,
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
          "additionalProperties": false,
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
          "additionalProperties": false,
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

### Omitted fields and declared defaults

An omitted field whose schema declares a `default` reads that value in both languages when its containing object
is present. This includes fields in a present array item. An optional parent object or array without its own default
stays absent when omitted; its children's defaults do not create it. Explicit values are kept and validated, and
defaults do not waive the containing object's other required fields or the route's direction, timing and permission
rules. Defaults on fields marked Phase 2 remain accepted route metadata; applying them does not implement their
deferred delivery behavior. (HTL-39, gap 272; ruled 2026-11-14.)

### Explicit null and omission

A field supplied as `null` is not omitted. Where this schema's type does not
admit null, both route loaders refuse the value, naming its instance path. This
also applies to typed array items, typed map values and declared typed children
inside an otherwise open object. Where the schema admits null, the value loads;
an untyped free-form value is not made non-null by this rule. Omission and
declared defaults continue to follow the preceding section. (HTL-41, gap 277;
ruled 2026-11-14, before the 0.2.0 publish.)

### Common Rules (All Directions)

| Rule | Description |
|------|-------------|
| `name` must be unique per (org_id, environment) | No two active routes in the same scope can share a name. |
| `name` pattern: `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` | Lowercase alphanumeric with hyphens, 3-64 characters, must start and end with alphanumeric. |
| `version` is immutable once deployed | A deployed version is never modified — only superseded by a new version. |
| `purpose` must have at least one label | Every route must declare its purpose. |
| `auth.secret_ref` never contains plaintext secrets | References a secret manager key or environment variable, never the actual secret value. |
| `endpoint` is an `https` URL | "TLS everywhere. No exceptions." (the security requirements, TLS Requirements). A route whose `endpoint` is not an `https` URL naming a host is refused at load, naming it, in both languages and on the hosted write, and the hosted worker sends to no other. Both languages read the value alike, by its written form: it holds no control character, space or DEL; it is written `https://` and then its host, the scheme in any case; its authority is written in RFC 3986's grammar (§3.2: a userinfo of unreserved, sub-delims, `:` and percent-encoded characters; a host; a port of digits); and the language reads the host and any port written: a bracketed IPv6 address is one, and a port is a number up to 65535, read once by its value, so the zeros that lead it are no digits of the number. The host is a name of unreserved and sub-delims characters, a dotted-decimal IPv4 address, or a bracketed IPv6 address, and it is read as written: a name holds no percent-encoding and no label beginning `xn--`, and a name ending in a number is a dotted-decimal address. The written form decides because the two URL parsers differ where a value does not write its host: the URL Standard's parser reads `https:host` or `https:///host` into a host and strips surrounding spaces, where RFC 3986's names none; it ends the authority at a backslash, which RFC 3986's grammar does not admit; it percent-decodes a name, decodes an IDNA label, and reads a name ending in a number as an IPv4 address in its legacy forms (`127.1`, `0x7f.1`, `2130706433`), where RFC 3986 keeps each as written. One table of written values holds both languages to one answer (tests/conformance/transport/). A send follows no redirect, in both SDKs as in the hosted worker: a redirect names a URL this check did not read, so it is the endpoint's answer, read as any answer that is not a success (sync_engine.md §8). Loopback is no exception: a server on the developer's own machine serves `https` on localhost with a self-signed certificate (sync_engine.md §8). (HTL-29, rows 140 and 236) |
| A route the hosted service sends names no address in hiitl's own network | The hosted service sends from hiitl's network, so a route's `endpoint` reaching that network would let an org's route reach hiitl's own services (the project's "Strict tenant isolation by `org_id`. Cross-tenant data access is a critical bug"; Principle 7). An address is hiitl's own when the IANA special-purpose address registries read it not globally reachable: loopback, link-local, the private ranges, and the rest of those registries. The hosted route write (`POST /v1/routes`, and a suggestion's route on accept) refuses an `endpoint` whose host is such an address, or a name that resolves to one, naming it; a name that does not resolve is stored, and the send reads it again. A name does not resolve when the resolver gives it no address: it knows no such name, its IDNA codec does not encode the name (an empty label, a label over 63 octets), or it answers with no address. An `endpoint` the hosted service's HTTP client reads no URL from, though the https rule reads it, is refused at the write, naming why, and ends its job `failed` at send: a retry would send no differently. At send the worker resolves the host, refuses the job if any address is hiitl's own, naming it, and connects to the address it checked, so a name that resolves differently at send is read where it connects. A refused job ends `failed` and sends nothing; a name that does not resolve at send is retried as any failed send is. The SDKs do not apply this rule: an SDK sends from the customer's network, which is theirs. One validator, beside the https rule (HTL-29, row 236; ruled 2026-11-09) |
| The party that sends reads the `auth` | An outbound or bidirectional route's `auth` is read by the party that sends the request ("How it is sent", below). An SDK reads a `bearer_token` or `api_key` secret from `env:<NAME>`, a variable of its own process, into `header`, which defaults to `Authorization` for both types, as the schema says. A route whose `auth` the SDK cannot send is refused at load, naming why: a reference that is not `env:`, a variable unset or empty, or a type the SDK does not send (`hmac_sha256`, `mtls`, `oauth2`). A request never goes without the credential its route declares: a variable unset after the load is no answer, and the route's `sla.timeout_action` decides (Principle 7; Principle 11; HTL-29, row 140). |
| No field is dropped (R-0872) | A route carries exactly the fields this schema defines, at every level (`additionalProperties: false`); a loader refuses any other, naming it, in both languages. Free-form data goes in `metadata` (the route's, or `inbound.payload_mapping.metadata`), the only open objects. |

### Direction-Specific Required Fields

| Direction | Required Fields | Forbidden Fields |
|-----------|----------------|------------------|
| `outbound` | `endpoint` | `inbound`, `context`, `response_schema`, `sla`, `escalation_ladder`, `correlation` |
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
  description: "Payments over 500 need finance approval"
  priority: 200
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

**Outbound routes and filters**: Outbound routes are not referenced by individual policy rules. Instead, they use `filters` to activate based on decision type, action, agent, or sensitivity. An outbound route with `filters.decisions: ["BLOCK"]` fires for every BLOCK decision. This is org-level configuration, not per-rule.

Built as of HTL-29 row 131 (2026-11-09):
- **When a route fires.** Every record the hosted service writes enqueues one `async` job for each active outbound
  `async` route of the record's org and environment whose `filters` the record passes. A record is written by the
  hosted evaluate, the sync upload's ingest, and the result write. The job is enqueued in the record write's own
  transaction ("Postgres Job Queue", below), so the record and its jobs are written together or not at all.
- **What the filter reads.** It reads the record's own fields: `decision_type`, `action`, `agent_id`, and the
  envelope's `sensitivity`, each as stored. A declared field the org redacts is read as its record holds it.
- **What is sent.** The payload is the record as the audit API reads it, `event_type` included (event_format.md
  "Outbound Events"). An outbound route sends no `context` selection, and one declaring `context` is refused at load
  (Direction-Specific Required Fields).
- **A stored route the core cannot read** is still enqueued, and its job ends `failed` at send, naming the refusal. A
  record is never dropped because its route could not be read, and it is never sent through a route that was not
  read.
- **`filters.actions`** (HTL-29 row 241, ruled 2026-11-09). The key that lists actions is `actions`, the record's
  member's own name. `tools` is refused at load, naming `actions`. A stored route naming `tools` is not rewritten, since
  a route version is immutable once deployed, and its job ends `failed` at send, naming `actions`, as any stored route
  the core cannot read does.
- **Sending.** The worker sends as it sends every job: `https` only, and a route declaring `auth` ends `failed`
  without sending, because the hosted service reads no secret (HTL-29 row 140; "How it is sent").
- **Open (gap row 131's open cells):** an outbound `sync` route, a pure-local SDK's outbound, and a bidirectional
  route's `filters` are not read.

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
  org_id: "org_acmecorp12345678"
  environment: "prod"

endpoint: "https://http-intake.logs.datadoghq.com/api/v2/logs"
auth:
  type: api_key
  header: "DD-API-KEY"
  secret_ref: "env:DATADOG_API_KEY"
protocol: webhook

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
  org_id: "org_acmecorp12345678"
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
  org_id: "org_acmecorp12345678"
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
  org_id: "org_acmecorp12345678"
  environment: "prod"

inbound:
  # url: generated by ECP, e.g. "https://api.hiitl.com/v1/inbound/org_acmecorp12345678/crowdstrike-signals"
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
  org_id: "org_acmecorp12345678"

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
  org_id: "org_acmecorp12345678"
  environment: "prod"

endpoint: "https://api.vanta.com/v1/evidence/ingest"
auth:
  type: bearer_token
  header: "Authorization"
  secret_ref: "env:VANTA_API_TOKEN"
protocol: webhook

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
| `sla.auto_approve_flag` | — (removed in 1.3) | A fail_open timeout is read from the review case's transitions (see "A review case: the route's wait, its timeout, its transitions"). A route file that still carries it is refused, naming it, as any undefined field is (1.3, row 147). |
| `escalation_ladder.levels` | `escalation_ladder.levels` | Restructured: `{level, target_type, target, sla_seconds}` → `{level, route, after}`. Each escalation level references another route by name instead of inline target definition. |
| `escalation_ladder.max_escalation_depth` | `escalation_ladder.max_escalation_depth` | Same semantics. |
| `escalation_ladder.final_timeout_behavior` | `escalation_ladder.final_timeout_action` | Renamed. Values: `auto_deny` → `fail_closed`, `auto_approve` → `fail_open`. |
| `metadata` | `metadata` | Same structure. |

### Code References to Rename

| Location | Old | New | Notes |
|----------|-----|-----|-------|
| Policy rules | `hitl_config: "name"` | `route: "name"` | Policy format spec already updated. |
| Decision response | `hitl_config_ref` | `route_ref` | Decision response spec already updated. |
| Python SDK | `HitlConfigLoader` | `RouteLoader` | Renamed. |
| TypeScript SDK | `HitlConfigLoader` | `RouteLoader` | Renamed. |
| Database | `hitl_configs` table | `routes` table | Requires migration. |
| API endpoints | `/hitl-configs/` | `/routes/` | Server endpoint rename. |
| File paths (local mode) | `hitl_configs/{org}/{env}/` | `routes/{org}/{env}/` | Directory rename. |

### YAML Conversion Example

**Before (HITL Config):**

```yaml
name: "finance-review"
version: "v1.0.0"
scope:
  org_id: "org_acmecorp12345678"
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
  org_id: "org_acmecorp12345678"
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

## Implementation: How Routes Execute

This section documents the actual runtime behavior in the current
codebase. Spec fields are aspirational; this section is descriptive.

### Three-Table Model

Route execution is persisted across these Postgres tables:

| Table | Purpose |
|-------|---------|
| `routes` | The route definition (URL, mode, config). Versioned per (org_id, environment, name). |
| `route_jobs` | One row per route invocation. Holds payload, status, attempts, result/error. The work queue. |
| `review_cases` | One row per PAUSE/REQUIRE_APPROVAL/ESCALATE decision. Linked to the originating `action_id`. Sync routes wait on a row in this table. Holds what the case was opened with, never its outcome. |
| `review_case_transitions` | Append-only. One row per transition of a case (opened, resolved, timed out). The case's status is its latest row. |

`route_jobs` is the unit of work. `review_cases` is the unit of human
collaboration. A bidirectional sync route writes to both.

### Postgres Job Queue

When evaluate() emits a decision that references a route, the API
handler calls `enqueue_route_job(...)` in the **same transaction as the
audit event write**. Losing the queue without losing the audit would be
a durability bug; sharing the transaction guarantees both or neither.
Every record write enqueues its outbound jobs the same way: one per
matching outbound `async` route, before the write commits ("Outbound
routes and filters", above; HTL-29 row 131). The record's insert reads
its routes, in its `RETURNING`, so a record write reads them in no
statement of its own, and each record of a sync upload reads the routes
active at its own write (gap row 190, ruled 2026-11-11: "the outbound
routes read inside the record's statement").

A background worker loop running inside the FastAPI lifespan claims
pending jobs and POSTs their payloads to the route's URL.

**Claim semantics — `SELECT ... FOR UPDATE SKIP LOCKED`:**

```sql
SELECT * FROM route_jobs
 WHERE status = 'pending'
   AND (scheduled_at IS NULL OR scheduled_at <= now())
 ORDER BY created_at ASC
 LIMIT 1
   FOR UPDATE SKIP LOCKED;
```

`SKIP LOCKED` lets multiple worker processes drain in parallel without
contention — each worker grabs a row no other worker has locked. SQLite
(test environment) falls back to a single-worker transactional update
because SKIP LOCKED isn't available there.

**Worker poll cadence:** `WORKER_POLL_INTERVAL_SECONDS = 0.2` (200ms)
between iterations when the queue is empty. The worker yields between
jobs (`await asyncio.sleep(0)`) so the FastAPI event loop stays
responsive.

### Retry Backoff

Failed jobs (HTTP non-2xx, network error, timeout) reset to `pending`
with `scheduled_at` set to a future time. The retry budget is
controlled by `max_attempts` on the job row.

**Backoff formula:** `5s × 2^(attempts - 1)`
— attempt 1 retry waits 5s, attempt 2 retry waits 10s, attempt 3 retry
waits 20s. After `max_attempts` failures the job moves to `abandoned`
(no further retries).

`max_attempts` defaults to **3** and is currently hardcoded at the
enqueue call site. The schema-level `retry.max_attempts` field is
**not yet read by the executor** — see the 🟡 callout on the
`retry` schema above.

### Sync vs Async Modes

`route_jobs.mode` is either `async` or `sync`:

- **`async`** — Fire-and-forget. The calling endpoint returns
  immediately; the worker picks up the job whenever it's next free.
  Used for webhook emission, observability fan-out, signal forwarding.

- **`sync`** — The calling endpoint waits for the job to reach a
  terminal state (`succeeded`/`failed`/`abandoned`) or the caller's
  timeout. `wait_for_job(job_id, timeout_seconds, poll_interval=0.1)`
  polls the row until terminal state or deadline. The same worker
  drains both modes — `sync` is just a scheduling signal to the caller,
  not a separate code path.

**A sync route's answer re-enters evaluation (2026-10-11; TICKET-046 with TICKET-032's sync half;
policy_format.md 2.7 "Enrichment context").**
- **When a route is asked.** A `ROUTE` decision whose rule names a bidirectional route asks that route. The party
  that evaluates asks it: the SDK in local and hybrid mode, the hosted service in hosted mode.
- **What is sent.** The request body is `{route, rule, action, fields}`.
  - `fields` holds the envelope's values at `context.fields`' paths, or the whole envelope when the route names none.
  - `rule` is omitted when `context.include_policy_ref` is false.
- **How it is sent.** The request is POSTed to `endpoint`. With `auth`, the SDK reads a `bearer_token` or `api_key`
  secret from its `secret_ref` (`env:<NAME>`, a variable of its own process) into `auth.header` (Validation Rules, "The
  party that sends reads the `auth`"). The SDK posts directly. The hosted service enqueues a `sync` job and waits on it.
- **The hosted service reads no secret from its own environment (HTL-29; ruled 2026-11-09).** It holds no secret for
  an org, and its own environment holds hiitl's. A hosted job whose route declares `auth` ends `failed` without
  sending, naming why, and a sync route's `sla.timeout_action` decides, as for any route that gave no answer. The
  route write is unchanged: a route declaring `auth` is stored, and the party that sends it reads it. A route the
  hosted service sends takes no credential until an org secret store exists, which is its own block: an org's
  secrets sealed under `SECRETS_ENCRYPTION_KEY`, as a key's signing secret is. A hybrid SDK
  pulls the same route (sync_engine.md §2.3), and an SDK that sends it reads its `auth` in its own process; the
  SDK's routing reads a pulled route once gap row 131's open cell closes (today it reads its route files). By
  the project's "Strict tenant isolation by `org_id`", Principle 7 "Safe-by-default" and `auth.secret_ref` "never
  contains plaintext secrets".
- **The answer.** The answer is the JSON response body. Its declared fields (`response_schema.required_fields` and
  `optional_fields`) re-enter as `external.<route>.<field>`, and the envelope is evaluated again.
- **No answer.** A timeout, a non-2xx response, or a missing required field each fall to `sla.timeout_action`
  (`fail_closed` unless `fail_open`).
- The worker reads the route's `endpoint` (before 2026-10-11 it read a `url` key, which the schema never defined).

### A review case: the route's wait, its timeout, its transitions

**Ruled 2026-11-04 (HTL-20, row 149).** The rule rests on hiitl's infrastructure specification 2, Pause/Approval
Semantics: "decision plane returns state only (no hidden workflow engine), idempotent state transitions, all
transitions auditable". It lives in the MCP gateway, in Routes, in the reviews half of the rule lifecycle, and in
Postgres (proposed architecture).

- **A case has a deadline and a timeout action.**
  - The gateway reads the decision's `escalation_context.timeout` and `escalation_context.timeout_action`. Both SDKs
    copy them there from the route's `sla`.
  - The case's wait is the route's `sla.timeout` when it fits within the gateway's own `review_timeout_seconds`.
    The case then records the route's `timeout_action`.
  - Otherwise the wait is the gateway's own `review_timeout_seconds`, and the case records `fail_closed`. This
    covers a decision with no route `sla`, and a route wait the gateway cannot hold (the gateway's bound is
    coordinated with its MCP client's request timeout).
  - A `timeout_action` belongs to its `timeout`: a shorter wait never takes a route's `fail_open`.
  - The case records `timeout_action` when it is opened and never changes it.
- **A timeout takes the recorded `timeout_action`.**
  - The service appends a `pending → timed_out` transition when the deadline passes with no resolution. This
    happens on the stream, or on a resolve that arrives late.
  - The stream's `timeout` event carries the recorded `timeout_action`.
  - The gateway reads that value as every other `sla` reader does. `fail_open` forwards the original arguments and
    logs a warning. `fail_closed`, `escalate` and `extend` refuse the call and name the action (escalate and extend
    read as fail_closed until escalation ladders are built).
- **Only a recorded timeout is a timeout.** The gateway's own wait can end first: its deadline passes, or the stream
  closes with no event. Then there is no `timed_out` transition to read, so the gateway refuses the call as an
  error. A `fail_open` route never forwards on a timeout the record does not hold.
- **A transition is appended, never written over.**
  - `review_case_transitions` holds one row per transition: `case_id`, `seq`, `from_status`, `to_status`,
    `actor`, `response` and `at`.
  - Rows are numbered from 1 within a case, and `(case_id, seq)` is unique.
  - Rows are appended and never updated or deleted.
  - Opening a case appends `→ pending`. A resolve appends `pending → approved | rejected | modified`. A deadline
    that passes appends `pending → timed_out`.
  - The case's `status`, `reviewer_id`, `reviewer_response` and `resolved_at` are read from its latest transition.
    They are not stored on the case. Every read of a case returns its `transitions`.
- **The resolver is the caller (HTL-29 row 135).** By row 218's ruling read as its class: an identity a record
  attributes is the caller's.
  - A resolve's transition names the authenticated caller as its `actor`, the caller's `AuthContext.key_id`. The
    case's `reviewer_id` is read from it.
  - A body that sends `reviewer_id` is refused as undefined, naming the field (R-0872).
- **Resolving is idempotent.**
  - A resolve repeating the recorded resolution returns 200 and appends nothing. It repeats when the caller, the
    decision and the response are all the same.
  - A different resolution returns 409, naming the recorded one.
  - A resolve after the deadline appends `timed_out` (if it is not yet recorded) and returns 409.
  - Two resolves that race are ordered by the `(case_id, seq)` constraint. The loser re-reads the case and is
    answered from the record.
- **`sla.auto_approve_flag` is removed (1.3).**
  - Its one behaviour was to "flag the approval as auto-approved in audit trail" when `timeout_action` is
    `fail_open`.
  - The record already holds that fact: a `timed_out` transition on a case whose `timeout_action` is `fail_open`.
    A stored flag would be a second copy of a fact the record derives.
  - Its `false` value would leave a fail-open forward unmarked, and "all transitions auditable" rules that out.
  - A route file that still carries the flag is refused, naming it, as any undefined field is (row 147, R-0872
    "no field is ever silently dropped"). Both route models refuse an unknown `sla` key.
- **A refused resolve is not recorded (ruled 2026-11-05).** A refused request is not a transition, so it is not
  recorded, by "all transitions auditable".
  - A refused resolve changes no state. Refusals: a late or conflicting resolve (409), `modified` without
    `modified_arguments` (400), a decision the route does not take (422), a key without `admin` (403), another
    org's case (404).
  - A late resolve finds the deadline passed. The timeout is the transition, appended once, and the resolve adds
    nothing of its own. A reviewer's late answer to a `fail_open` timeout is answered 409 and is not on the record.

### Multi-Worker Coordination via `pg_notify`

The sync case for human review can't be solved by polling alone —
when an operator clicks "approve" in the dashboard, the agent waiting
on the SSE stream needs to wake up *immediately*, not on the next
polling tick.

**Channel:** `pg_notify('review_resolved', case_id)` fires when
`POST /v1/reviews/{case_id}/resolve` commits.

**Per-worker listener:** Each uvicorn worker holds a dedicated asyncpg
connection with `LISTEN review_resolved` open for its lifetime. The
listener connection is **not pooled** — `LISTEN` holds the connection,
and pooling would deadlock when the pool tries to reset it.

**Local pending dict:** Every worker keeps a `dict[case_id,
asyncio.Event]` of cases it has open SSE waiters for. Notifications
broadcast to every worker; each worker checks its local dict and only
wakes the waiter if it owns one. Other workers ignore.

**Atomicity caveat:** `notify()` is called *after* the resolve
transaction commits. There's a brief window where a connecting SSE
client could miss the notification — handled by always re-reading the
case's transitions on SSE connect (resolved-before-connect short-circuits
the wait).

`ReviewNotifier` is the abstraction. Two implementations: `PgNotifier`
(production) and `InProcessNotifier` (tests, single-worker dev).

### SSE Keepalive

`GET /v1/reviews/{case_id}/stream` returns a Server-Sent Events stream
that resolves when the case resolves or times out. SSE connections sit
idle for the case's pending duration — sometimes minutes, sometimes
hours.

**Keepalive cadence:** **30 seconds** — every 30s the stream emits a
`: keepalive\n\n` SSE comment (a spec-recognized no-op). Render's HTTP
layer idle timeout is ~100s; 30s leaves comfortable headroom for retry
and clock skew. Defined as `_SSE_KEEPALIVE_SECONDS = 30` in the reviews
router.

### Outage Behavior

- **Worker down:** Jobs accumulate in `pending`. Sync callers see
  their `wait_for_job` deadline expire and decide fail-open vs
  fail-closed per their own policy.
- **Webhook target down:** Retries with exponential backoff; after
  `max_attempts`, status → `abandoned` with `error` populated. No
  cascading failure — the audit event is already durable.
- **Listener connection dies:** SSE waiters in that worker fall through
  to row-state re-read on the next reconnect. No notifications are
  lost from the database side; only the wake-up signal to in-flight
  waiters is at risk.

### Future Work

The schema fields marked 🟡 above (retry, queue,
response_schema, escalation_ladder, correlation, inbound) require
executor changes before they're load-bearing. The current
implementation honors the *structure* (validates and stores them) but
does not yet enforce the *semantics*.

---

## Phase Implementation Scope

### Phase 1.5 + Block 3b/4a (Shipped)

| Capability | Status |
|------------|--------|
| Route schema (this document) | ✅ Spec complete (v1.1) |
| Bidirectional sync routes (human review via ReviewCase) | ✅ Block 3a/3b |
| Outbound async routes (webhook emission), with `filters` | ✅ HTL-29 row 131 (Block 1B Item 11 built the worker; nothing enqueued an outbound job until row 131) |
| Policy rules reference `route` by name | ✅ Policy format v1.2 |
| Decision response includes `route_ref` | ✅ Decision response v1.2 |
| Postgres job queue + worker pool | ✅ hosted service |
| `pg_notify` / SSE for review notification | ✅ hosted service |
| Sync mode (`wait_for_job`) | ✅ Block 1B Item 11 |
| Exponential retry backoff (hardcoded 3 attempts) | ✅ Block 1B Item 11 |

### Deferred — Schema Defined, Executor Not Yet Honoring

These fields validate and persist today but don't change runtime
behavior. Promoting any of these to load-bearing is a per-field
implementation ticket.

| Capability | Schema | Executor |
|------------|--------|----------|
| `retry.max_attempts` / `retry.backoff` config | Accepted | Hardcoded to 3, 5s × 2^n |
| `queue` (batching, max_batch_size, max_age) | Accepted | Not implemented |
| `response_schema.modify_constraints` | Accepted | Not enforced |
| `escalation_ladder` | Accepted | Not implemented |
| `correlation.resume_token` style | Accepted | Sync routes use ReviewCase API instead |
| `inbound` direction | Accepted | No API surface yet |

### Phase 2+ (Future)

| Capability | Status |
|------------|--------|
| Managed bidirectional route target (hiitl review queue) | Planned |
| Inbound async routes (signal ingestion) | Planned |
| `modify`, `delegate`, `request_more_info` response options | Planned |
| Escalation ladder implementation | Planned |
| Managed routes marketplace + provider adapters | Planned |
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
| 1.1 | 2026-05-13 | Documentation refresh: split schema (aspirational) from executor (built). Added "Implementation: How Routes Execute" section documenting Postgres job queue, `pg_notify`/SSE, sync vs async modes, retry backoff, multi-worker coordination. Marked deferred fields (filters, retry config, queue, modify_constraints, escalation_ladder, correlation, inbound) with 🟡 callouts. Rewrote Phase Implementation Scope to reflect Block 3b/4a shipped state. | Sprint B docs refresh |
| 1.2 | 2026-11-03 | Brought current to the ruled changes: the `RouteLoader` rename, `timeout_action` escalate and extend read as fail_closed, example org_ids match the schema pattern (HTL-17) | CC |
| 1.3 | 2026-11-04 | A review case waits the route's `sla.timeout` and takes its `timeout_action`; resolutions append to `review_case_transitions` and resolving is idempotent; `sla.auto_approve_flag` removed (HTL-20, row 149). Every object the schema defines is closed (`additionalProperties: false`); `metadata` stays the open place. A route naming an undefined field is refused, naming it, a retired `sla.auto_approve_flag` among them (R-0872 swept; HTL-20 row 147) | CC |
| 1.4 | 2026-11-09 | An `endpoint` is an `https` URL, loopback included; the party that sends reads the `auth`, the SDK refusing at load an `auth` it cannot send, naming why, and `header` defaulting to `Authorization` for both types; the hosted service reads no secret from its own environment, and a hosted job whose route declares `auth` fails without sending (HTL-29, row 140 and the finding read with it). A resolve's reviewer is its caller, and a body naming `reviewer_id` is refused as undefined (row 135) | CC |

---

## Related Documents

- [Policy Format Spec](policy_format.md) - Rules reference routes via `route` field
- [Decision Response Spec](decision_response.md) - `route_ref` in escalation decisions
- [Event Format Spec](event_format.md) - Outbound route event format

---

**This specification is the source of truth for routes. Routes are the third core artifact alongside the envelope schema and policy format.**
