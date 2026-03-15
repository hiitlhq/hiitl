# Telemetry Schema Specification

**Version**: 1.0
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-02-26

---

## 1. Purpose & Relationship to Audit

Telemetry and audit serve different purposes:

| | Audit | Telemetry |
|---|---|---|
| **What** | Per-action record with full detail | Pre-aggregated statistical summaries |
| **Granularity** | One record per action | One summary per action per time window |
| **Content** | Envelope, decision, timing, matched rules | Counts, distributions, percentiles |
| **Privacy** | Full action detail (redactable fields) | Aggregated stats (no individual actions recoverable) |
| **Use case** | Compliance, replay, debugging | Dashboard, suggestions, pattern detection |
| **Transport** | Sync engine audit channel | Sync engine telemetry channel |

Telemetry is **not** a second copy of the audit log. It is a compact statistical view of SDK behavior computed client-side and shipped to the hosted service to power the behavior dashboard (TICKET-024.1) and suggestion engine (TICKET-024.2).

### Data Flow

```
SDK Evaluation (per action)
    │
    ├──→ Audit Record (full detail, per-event)
    │        → Audit sync channel → Server audit store
    │
    └──→ Telemetry Collector (SDK-side, in-memory)
             │
             │  Aggregates over time window (default 60s)
             │
             └──→ Telemetry Summary (pre-aggregated)
                      → Telemetry sync channel → Server telemetry store
                                                      │
                                                      ├──→ Behavior Dashboard
                                                      └──→ Suggestion Engine
```

---

## 2. Telemetry Record Schema

A telemetry record represents one aggregation window. The SDK produces one record per sync interval.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hiitl.ai/schemas/telemetry/v1.json",
  "title": "HIITL Telemetry Record",
  "description": "Pre-aggregated SDK telemetry for dashboard and suggestion engine",
  "type": "object",
  "required": [
    "telemetry_version",
    "window_start",
    "window_end",
    "org_id",
    "environment",
    "sdk_version",
    "sdk_language",
    "tool_summaries"
  ],
  "properties": {
    "telemetry_version": {
      "type": "string",
      "const": "1.0",
      "description": "Schema version for forward compatibility"
    },
    "window_start": {
      "type": "string",
      "format": "date-time",
      "description": "Start of the aggregation window (inclusive)"
    },
    "window_end": {
      "type": "string",
      "format": "date-time",
      "description": "End of the aggregation window (exclusive)"
    },
    "org_id": {
      "type": "string",
      "description": "Organization identifier"
    },
    "environment": {
      "type": "string",
      "enum": ["dev", "stage", "prod"]
    },
    "sdk_version": {
      "type": "string",
      "description": "SDK package version (e.g., '1.2.3')"
    },
    "sdk_language": {
      "type": "string",
      "enum": ["python", "typescript"],
      "description": "SDK implementation language"
    },
    "sdk_instance_id": {
      "type": "string",
      "description": "Unique identifier for this SDK instance. Anonymizable via redaction controls."
    },
    "tool_summaries": {
      "type": "array",
      "description": "Per-tool metrics for the aggregation window",
      "items": { "$ref": "#/$defs/tool_summary" }
    },
    "agent_summaries": {
      "type": "array",
      "description": "Per-agent metrics for the aggregation window",
      "items": { "$ref": "#/$defs/agent_summary" }
    },
    "system_metrics": {
      "$ref": "#/$defs/system_metrics",
      "description": "SDK-level operational metrics"
    }
  },
  "$defs": {
    "tool_summary": {
      "type": "object",
      "required": ["action", "action_count", "decision_counts"],
      "properties": {
        "action": {
          "type": "string",
          "description": "Name of the action (e.g., 'process_payment', 'send_email')"
        },
        "action_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Total number of actions evaluated for this tool in the window"
        },
        "decision_counts": {
          "type": "object",
          "description": "Count of each decision type",
          "properties": {
            "ALLOW": { "type": "integer", "minimum": 0 },
            "BLOCK": { "type": "integer", "minimum": 0 },
            "REQUIRE_APPROVAL": { "type": "integer", "minimum": 0 },
            "RATE_LIMIT": { "type": "integer", "minimum": 0 },
            "KILL_SWITCH": { "type": "integer", "minimum": 0 },
            "SANDBOX": { "type": "integer", "minimum": 0 },
            "ESCALATE": { "type": "integer", "minimum": 0 },
            "PAUSE": { "type": "integer", "minimum": 0 },
            "ROUTE": { "type": "integer", "minimum": 0 }
          },
          "additionalProperties": { "type": "integer", "minimum": 0 }
        },
        "latency": {
          "$ref": "#/$defs/latency_stats",
          "description": "Evaluation latency statistics. Omitted at 'minimal' redaction level."
        },
        "operations": {
          "type": "object",
          "description": "Count by operation type (read, write, execute, etc.)",
          "additionalProperties": { "type": "integer", "minimum": 0 }
        },
        "parameter_stats": {
          "type": "array",
          "description": "Aggregated parameter statistics. Omitted at 'minimal' redaction level. Never includes raw values.",
          "items": { "$ref": "#/$defs/parameter_stat" }
        },
        "target_cardinality": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of distinct target resources accessed. Omitted at 'minimal' redaction level."
        },
        "error_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of evaluation errors for this tool"
        },
        "reason_code_counts": {
          "type": "object",
          "description": "Count of each reason code produced",
          "additionalProperties": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "agent_summary": {
      "type": "object",
      "required": ["agent_id", "action_count"],
      "properties": {
        "agent_id": {
          "type": "string",
          "description": "Agent identifier"
        },
        "action_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Total actions evaluated for this agent in the window"
        },
        "tools_used": {
          "type": "array",
          "items": { "type": "string" },
          "description": "List of tool names this agent invoked during the window"
        },
        "decision_counts": {
          "type": "object",
          "description": "Aggregate decision distribution for this agent",
          "additionalProperties": { "type": "integer", "minimum": 0 }
        },
        "distinct_users": {
          "type": "integer",
          "minimum": 0,
          "description": "Count of distinct user_ids (not the IDs themselves). Omitted at 'minimal' redaction level."
        }
      }
    },
    "system_metrics": {
      "type": "object",
      "properties": {
        "uptime_seconds": {
          "type": "number",
          "description": "SDK instance uptime since initialization"
        },
        "total_evaluations": {
          "type": "integer",
          "minimum": 0,
          "description": "Cumulative evaluation count since SDK init"
        },
        "sync_status": {
          "type": "string",
          "enum": ["healthy", "degraded", "disconnected"],
          "description": "Current sync engine health"
        },
        "audit_buffer_usage": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "Fraction of audit buffer capacity used (0.0 to 1.0)"
        },
        "cache_age_seconds": {
          "type": "number",
          "description": "Age of the oldest cached data (policies, routes)"
        },
        "error_counts": {
          "type": "object",
          "description": "Error counts by category",
          "properties": {
            "evaluation_errors": { "type": "integer", "minimum": 0 },
            "sync_errors": { "type": "integer", "minimum": 0 },
            "policy_load_errors": { "type": "integer", "minimum": 0 }
          }
        },
        "active_kill_switches": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of currently active kill switch rules"
        },
        "policy_version": {
          "type": "string",
          "description": "Currently active policy version identifier"
        }
      }
    },
    "latency_stats": {
      "type": "object",
      "description": "Latency distribution statistics in milliseconds",
      "properties": {
        "p50": { "type": "number", "description": "Median latency (ms)" },
        "p95": { "type": "number", "description": "95th percentile (ms)" },
        "p99": { "type": "number", "description": "99th percentile (ms)" },
        "min": { "type": "number", "description": "Minimum observed (ms)" },
        "max": { "type": "number", "description": "Maximum observed (ms)" },
        "mean": { "type": "number", "description": "Arithmetic mean (ms)" }
      }
    },
    "parameter_stat": {
      "type": "object",
      "required": ["parameter_path", "stat_type"],
      "description": "Aggregated statistics for a single parameter. Never contains raw parameter values.",
      "properties": {
        "parameter_path": {
          "type": "string",
          "description": "Dot-notation path to the parameter (e.g., 'amount', 'currency')"
        },
        "stat_type": {
          "type": "string",
          "enum": ["numeric", "categorical"],
          "description": "Whether this parameter has numeric or categorical values"
        },
        "numeric_stats": {
          "type": "object",
          "description": "For numeric parameters only",
          "properties": {
            "min": { "type": "number" },
            "max": { "type": "number" },
            "mean": { "type": "number" },
            "count": { "type": "integer", "minimum": 0 }
          }
        },
        "categorical_stats": {
          "type": "object",
          "description": "For categorical parameters only",
          "properties": {
            "distinct_count": {
              "type": "integer",
              "minimum": 0,
              "description": "Number of distinct values observed"
            },
            "top_values": {
              "type": "array",
              "description": "Most frequent values with counts. Only included at 'full' redaction level.",
              "items": {
                "type": "object",
                "properties": {
                  "value": { "type": "string" },
                  "count": { "type": "integer", "minimum": 0 }
                }
              },
              "maxItems": 10
            }
          }
        }
      }
    }
  }
}
```

---

## 3. Metric Definitions

### 3.1 Action Metrics

Computed per action per aggregation window.

| Metric | Type | Description | Redaction Level |
|--------|------|-------------|-----------------|
| `action` | string | Action identifier | Always |
| `action_count` | integer | Total evaluations | Always |
| `decision_counts` | map | Count per decision type (ALLOW, BLOCK, etc.) | Always |
| `latency` | object | Evaluation latency p50/p95/p99/min/max/mean (ms) | Standard+ |
| `operations` | map | Count per operation type (read, write, execute) | Standard+ |
| `parameter_stats` | array | Per-parameter aggregated statistics | Standard+ |
| `target_cardinality` | integer | Distinct target resources | Standard+ |
| `error_count` | integer | Evaluation errors | Always |
| `reason_code_counts` | map | Count per reason code | Standard+ |

### 3.2 Agent Metrics

Computed per agent per aggregation window.

| Metric | Type | Description | Redaction Level |
|--------|------|-------------|-----------------|
| `agent_id` | string | Agent identifier | Always |
| `action_count` | integer | Total evaluations | Always |
| `tools_used` | array | Tool names invoked | Always |
| `decision_counts` | map | Count per decision type | Always |
| `distinct_users` | integer | Count of unique user_ids | Standard+ |

### 3.3 System Metrics

Computed once per SDK instance per aggregation window.

| Metric | Type | Description | Redaction Level |
|--------|------|-------------|-----------------|
| `uptime_seconds` | number | SDK uptime | Always |
| `total_evaluations` | integer | Cumulative evaluations | Always |
| `sync_status` | enum | Sync engine health | Always |
| `audit_buffer_usage` | number | Buffer capacity fraction (0-1) | Always |
| `cache_age_seconds` | number | Oldest cache entry age | Always |
| `error_counts` | object | Errors by category | Always |
| `active_kill_switches` | integer | Active kill switch count | Always |
| `policy_version` | string | Active policy version | Always |

---

## 4. Privacy Boundaries

### Non-Configurable Boundaries

These are enforced in SDK code. No configuration can override them. Server-side enforcement is a backup — the SDK must never send this data in the first place.

| Data Category | Boundary | Rationale |
|--------------|----------|-----------|
| **Raw prompts / LLM inputs** | Never leave the SDK | Contains user content, potentially sensitive IP, PII. No telemetry use case requires raw prompts. |
| **Full parameter payloads** | Never leave the SDK | May contain credentials, PII, financial data. Only aggregated stats (min/max/mean/cardinality) are shipped. |
| **Raw target identifiers** | Never leave the SDK | Resource IDs may reveal internal architecture or contain embedded PII. Only cardinality counts are shipped. |
| **User PII** | Never without explicit opt-in | User IDs are counted (distinct_users) but never enumerated. Names, emails, etc. are never included. |
| **Raw envelope content** | Never leave via telemetry | Full envelopes are shipped via the audit channel, not telemetry. Telemetry only contains aggregated stats derived from envelopes. |

### Enforcement

Privacy boundaries are enforced at the **aggregation layer** within the SDK. The telemetry collector receives evaluation results and produces only aggregated statistics — it never has access to raw data in a form that could be serialized to the telemetry payload.

Implementation requirement: the telemetry aggregator must accept only pre-computed metrics (counts, sums, min/max), not raw action data. This is a structural guarantee, not just a code-level filter.

---

## 5. Redaction Controls

Redaction controls determine how much detail the SDK includes in telemetry. Three levels are defined:

### Redaction Levels

| Level | Description | Use Case |
|-------|-------------|----------|
| **`full`** | All telemetry including parameter stats and top values | Full dashboard experience, suggestion engine at full capability |
| **`standard`** (default) | All telemetry except categorical top values | Good dashboard experience, most suggestion capabilities |
| **`minimal`** | Tool names, action counts, decision counts only | Maximum privacy, limited dashboard, no parameter-based suggestions |

### Per-Field Inclusion Matrix

| Field | `full` | `standard` | `minimal` |
|-------|--------|------------|-----------|
| `action` | Yes | Yes | Yes |
| `action_count` | Yes | Yes | Yes |
| `decision_counts` | Yes | Yes | Yes |
| `error_count` | Yes | Yes | Yes |
| `latency` (percentiles) | Yes | Yes | No |
| `operations` | Yes | Yes | No |
| `parameter_stats.numeric_stats` | Yes | Yes | No |
| `parameter_stats.categorical_stats.distinct_count` | Yes | Yes | No |
| `parameter_stats.categorical_stats.top_values` | Yes | No | No |
| `target_cardinality` | Yes | Yes | No |
| `reason_code_counts` | Yes | Yes | No |
| `agent_summary.distinct_users` | Yes | Yes | No |
| `system_metrics` (all) | Yes | Yes | Yes |

### Configuration

| Method | Setting |
|--------|---------|
| Constructor option | `telemetry_level: "full" \| "standard" \| "minimal"` |
| Environment variable | `HIITL_TELEMETRY_LEVEL` |
| Default | `"standard"` |

To disable telemetry entirely, set `telemetry_level` to `"off"` (or `HIITL_TELEMETRY_LEVEL=off`). When telemetry is off, the sync engine's telemetry channel is inactive and no telemetry data is collected or buffered.

---

## 6. Aggregation Rules

### Window Alignment

- Aggregation windows align to the telemetry sync interval (default: 60 seconds).
- Each window is a half-open interval: `[window_start, window_end)`.
- An action belongs to the window in which its evaluation completed.
- At each sync interval, the SDK finalizes the current window and ships it.

### Percentile Computation

For latency metrics (p50, p95, p99):

- SDK maintains a sorted reservoir of latency values per tool per window.
- For windows with < 1000 evaluations: exact percentile computation.
- For windows with >= 1000 evaluations: implementations may use t-digest or similar sketch algorithm for memory efficiency.
- All latency values are in milliseconds with up to 3 decimal places of precision.

### Numeric Parameter Stats

For numeric parameters (e.g., `amount`, `quantity`):

- Track `min`, `max`, running sum (for `mean`), and `count`.
- Memory-efficient: O(1) per parameter regardless of action volume.
- The SDK auto-detects numeric parameters by observing JSON number types.

### Categorical Parameter Stats

For non-numeric parameters (e.g., `currency`, `region`):

- Track `distinct_count` using exact counting for small cardinality (< 1000 distinct values) or HyperLogLog for high cardinality.
- `top_values` (only at `full` redaction level): track top 10 most frequent values using a Count-Min Sketch or simple frequency map.
- Maximum tracked categorical parameters per tool: 20 (to bound memory usage).

### Automatic Parameter Discovery

The SDK automatically discovers parameters from the `parameters` field of evaluated envelopes:

- Only top-level keys are tracked (no deep nesting — `parameters.amount` yes, `parameters.details.breakdown.tax` no).
- Parameters seen fewer than 3 times in a window are excluded from the telemetry record (noise reduction).
- Parameter tracking is opt-in per tool via configuration to avoid leaking unexpected field names.

---

## 7. Batching & Transport

### Sync Engine Integration

Telemetry uses the sync engine's telemetry channel as defined in [sync_engine.md Section 2.6](sync_engine.md):

| Property | Value |
|----------|-------|
| Endpoint | `POST /v1/sync/telemetry` |
| Default interval | 60 seconds |
| Compression | gzip for payloads > 1 KB |
| Authentication | Bearer token (same as other sync channels) |

### Payload Structure

Each sync cycle ships one telemetry record (one aggregation window). The payload is the telemetry record JSON object as defined in Section 2.

### Buffering

If the telemetry channel is unavailable (sync engine degraded):

- Telemetry records are buffered in memory (up to 60 records = 1 hour at default interval).
- When the buffer is full, the oldest records are dropped (telemetry is best-effort, unlike audit).
- On sync recovery, buffered records are uploaded oldest-first.
- Telemetry buffer overflow emits a `TELEMETRY_BUFFER_FULL` event locally (not critical — telemetry loss is acceptable).

### Empty Windows

If no evaluations occur during a window, the SDK may either:
- Ship an empty telemetry record (useful for confirming the SDK is alive), or
- Skip the window entirely (bandwidth optimization).

Implementations should ship an empty record at least once every 10 minutes as a heartbeat.

---

## 8. Extensibility

### Schema Versioning

The `telemetry_version` field enables forward compatibility:

- Current version: `"1.0"`
- New metric categories can be added as optional fields in minor version bumps (1.1, 1.2).
- Breaking changes (field removals, type changes) require a major version bump (2.0).
- The server must accept any `telemetry_version` it understands and ignore unknown optional fields.
- The SDK must send its compiled schema version, not a dynamic value.

### Custom Metrics Extension Point

Future versions may support custom metrics via an `extensions` field:

```json
{
  "extensions": {
    "custom_namespace": {
      "metric_name": "metric_value"
    }
  }
}
```

This field is reserved but not implemented in v1.0. Implementations must not use it until the extension mechanism is formally specified.

---

## 9. Server-Side Processing

### Storage

The server stores telemetry records in a time-series-optimized table:

- Partitioned by day for efficient retention management.
- Indexed by `org_id`, `environment`, `window_start` for dashboard queries.
- Secondary index on `action` for action-specific drill-downs.

### Retention

| Tier | Default Retention | Notes |
|------|-------------------|-------|
| Free | 30 days | Sufficient for trend analysis |
| Pro | 90 days | Quarterly patterns visible |
| Enterprise | Configurable (up to 365 days) | Compliance and long-term trending |

### Query API

The server exposes query endpoints for the dashboard (defined in Phase 2):

- Aggregation over time ranges (hourly, daily, weekly rollups)
- Filtering by agent, action, environment
- Comparison across time periods
- Export for external analysis

Endpoint design is deferred to TICKET-024.1 (Behavior Dashboard). The telemetry schema defines the storage format; the dashboard defines the query interface.

---

## Appendix: Relationship to Other Specs

| Spec | Relationship |
|------|-------------|
| [Sync Engine](sync_engine.md) | Telemetry uses the sync engine's telemetry channel for transport |
| [Event Format](event_format.md) | Audit events are per-action; telemetry is pre-aggregated. Both originate from the same evaluation. |
| [Decision Response](decision_response.md) | Timing data in decisions feeds into telemetry latency stats |
| [Envelope Schema](envelope_schema.json) | Parameter field structure determines what parameter_stats can be computed |

## Appendix: Example Telemetry Record

```json
{
  "telemetry_version": "1.0",
  "window_start": "2026-03-15T14:30:00Z",
  "window_end": "2026-03-15T14:31:00Z",
  "org_id": "org_abc123def456ghij",
  "environment": "prod",
  "sdk_version": "1.2.3",
  "sdk_language": "python",
  "sdk_instance_id": "inst_k7m9p2q4",
  "tool_summaries": [
    {
      "action": "process_payment",
      "action_count": 47,
      "decision_counts": {
        "ALLOW": 44,
        "RATE_LIMIT": 2,
        "BLOCK": 1
      },
      "latency": {
        "p50": 0.312,
        "p95": 0.891,
        "p99": 1.234,
        "min": 0.201,
        "max": 1.567,
        "mean": 0.389
      },
      "operations": {
        "execute": 47
      },
      "parameter_stats": [
        {
          "parameter_path": "amount",
          "stat_type": "numeric",
          "numeric_stats": {
            "min": 10.50,
            "max": 847.00,
            "mean": 156.32,
            "count": 47
          }
        },
        {
          "parameter_path": "currency",
          "stat_type": "categorical",
          "categorical_stats": {
            "distinct_count": 3
          }
        }
      ],
      "target_cardinality": 31,
      "error_count": 0,
      "reason_code_counts": {
        "default_allow": 44,
        "rate_limit_exceeded": 2,
        "amount_threshold_exceeded": 1
      }
    },
    {
      "action": "send_email",
      "action_count": 12,
      "decision_counts": {
        "ALLOW": 12
      },
      "latency": {
        "p50": 0.198,
        "p95": 0.445,
        "p99": 0.445,
        "min": 0.132,
        "max": 0.502,
        "mean": 0.231
      },
      "operations": {
        "execute": 12
      },
      "target_cardinality": 8,
      "error_count": 0,
      "reason_code_counts": {
        "default_allow": 12
      }
    }
  ],
  "agent_summaries": [
    {
      "agent_id": "payment-agent",
      "action_count": 47,
      "tools_used": ["process_payment"],
      "decision_counts": {
        "ALLOW": 44,
        "RATE_LIMIT": 2,
        "BLOCK": 1
      },
      "distinct_users": 28
    },
    {
      "agent_id": "notification-agent",
      "action_count": 12,
      "tools_used": ["send_email"],
      "decision_counts": {
        "ALLOW": 12
      },
      "distinct_users": 9
    }
  ],
  "system_metrics": {
    "uptime_seconds": 86423.7,
    "total_evaluations": 15847,
    "sync_status": "healthy",
    "audit_buffer_usage": 0.03,
    "cache_age_seconds": 127.4,
    "error_counts": {
      "evaluation_errors": 0,
      "sync_errors": 0,
      "policy_load_errors": 0
    },
    "active_kill_switches": 0,
    "policy_version": "v2.1.0"
  }
}
```
