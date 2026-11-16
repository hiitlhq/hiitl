# Telemetry Schema Specification

**Version**: 2.0
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-11-15 (HTL-43: numeric per-record refusal, §7; 2026-11-09, HTL-30: percentile interpolation, §6; 2026-11-06, HTL-23: rows 207, 208 and 216, the telemetry family and the names earlier releases read, §5; 2026-11-04, HTL-20: rows 142 and 146; 2.0 removes fields, §8)

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

Every numeric value admitted through this format, including each integer member and open data, follows
[the single numeric domain](sync_engine.md#numeric-domain). This is admission before evaluation, signing,
hashing or recording; existing stored records, hashes and signatures remain as written.

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
  "$id": "https://hiitl.com/schemas/telemetry/v2.json",
  "title": "hiitl Telemetry Record",
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
      "const": "2.0",
      "description": "Schema version for forward compatibility"
    },
    "window_start": {
      "type": "string",
      "format": "date-time",
      "description": "Start of the aggregation window (inclusive); an RFC 3339 date-time, read as ecp_evaluate_spec.md \"A date-time is read by RFC 3339's grammar\" states"
    },
    "window_end": {
      "type": "string",
      "format": "date-time",
      "description": "End of the aggregation window (exclusive); an RFC 3339 date-time, read as ecp_evaluate_spec.md \"A date-time is read by RFC 3339's grammar\" states"
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
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "minimum": 0,
          "description": "Total number of actions evaluated for this tool in the window"
        },
        "decision_counts": {
          "type": "object",
          "description": "Count of each decision type",
          "properties": {
            "ALLOW": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "BLOCK": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "REQUIRE_APPROVAL": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "RATE_LIMIT": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "KILL_SWITCH": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "SANDBOX": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "ESCALATE": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "PAUSE": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "ROUTE": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 },
            "OBSERVE": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 }
          },
          "additionalProperties": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 }
        },
        "latency": {
          "$ref": "#/$defs/latency_stats",
          "description": "Evaluation latency statistics. Omitted at 'minimal' redaction level."
        },
        "operations": {
          "type": "object",
          "description": "Count by operation type (read, write, execute, etc.)",
          "additionalProperties": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 }
        },
        "parameter_stats": {
          "type": "array",
          "description": "Counts per parameter, only for an action named in telemetry_parameter_tools (§6). Omitted at 'minimal' redaction level. Never includes a raw value (§4).",
          "items": { "$ref": "#/$defs/parameter_stat" }
        },
        "target_cardinality": {
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "minimum": 0,
          "description": "Number of distinct target resources accessed. Omitted at 'minimal' redaction level."
        },
        "error_count": {
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "minimum": 0,
          "description": "Number of evaluation errors for this tool"
        },
        "reason_code_counts": {
          "type": "object",
          "description": "Count of each reason code produced",
          "additionalProperties": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 }
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
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
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
          "additionalProperties": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0 }
        },
        "distinct_users": {
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "minimum": 0,
          "description": "Count of distinct user_ids (not the IDs themselves). Omitted at 'minimal' redaction level."
        }
      }
    },
    "system_metrics": {
      "type": "object",
      "properties": {
        "uptime_seconds": {
          "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "description": "SDK instance uptime since initialization"
        },
        "total_evaluations": {
          "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
          "minimum": 0,
          "description": "Cumulative evaluation count since SDK init"
        },
        "error_counts": {
          "type": "object",
          "description": "Cumulative error counts by category since SDK init",
          "required": ["evaluation_errors", "telemetry_errors"],
          "properties": {
            "evaluation_errors": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0, "description": "Decisions that carried an error" },
            "telemetry_errors": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0, "description": "Evaluations the collector failed to record" }
          }
        }
      }
    },
    "latency_stats": {
      "type": "object",
      "description": "Latency distribution statistics in milliseconds",
      "properties": {
        "p50": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Median latency (ms)" },
        "p95": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "95th percentile (ms)" },
        "p99": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "99th percentile (ms)" },
        "min": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Minimum observed (ms)" },
        "max": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Maximum observed (ms)" },
        "mean": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Arithmetic mean (ms)" }
      }
    },
    "parameter_stat": {
      "type": "object",
      "required": ["parameter_path", "stat_type"],
      "description": "Counts for a single parameter. Never contains a raw parameter value: no observed value, minimum, maximum or most-frequent value (§4).",
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
          "required": ["count"],
          "properties": {
            "count": { "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "minimum": 0, "description": "Evaluations in which the parameter held a number" },
            "mean": { "type": "number", "$comment": "Numeric admission: sync_engine.md#numeric-domain.", "description": "Only at 'full', and only when the values seen are not all one value (a mean of one value is that value)" }
          }
        },
        "categorical_stats": {
          "type": "object",
          "description": "For categorical parameters only",
          "properties": {
            "distinct_count": {
              "type": "integer", "$comment": "Numeric admission: sync_engine.md#numeric-domain.",
              "minimum": 0,
              "description": "Number of distinct values observed (counted by digest; no value is kept)"
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
| `parameter_stats` | array | Per-parameter counts, for an action named in `telemetry_parameter_tools` (§6) | Standard+ |
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
| `error_counts` | object | `evaluation_errors`, `telemetry_errors` | Always |

`sdk_instance_id` and the system metrics `sync_status`, `audit_buffer_usage`, `cache_age_seconds`, `active_kill_switches` and `policy_version` (and the error categories `sync_errors`, `policy_load_errors`) were declared in 1.0 and never produced. Neither the rulings register nor the design conversation rules on them, so 2.0 states what is built and they leave the schema and the service's model (HTL-20, row 146, 2026-11-04; a field declared and never produced is a claim nothing keeps). A later minor version may add any of them as an optional field (§8) when something produces it.

---

## 4. Privacy Boundaries

### Non-Configurable Boundaries

These are enforced in SDK code. No configuration can override them. Server-side enforcement is a backup — the SDK must never send this data in the first place.

| Data Category | Boundary | Rationale |
|--------------|----------|-----------|
| **Raw prompts / LLM inputs** | Never leave the SDK | Contains user content, potentially sensitive IP, PII. No telemetry use case requires raw prompts. |
| **Full parameter payloads** | Never leave the SDK | May contain credentials, PII, financial data. No raw parameter value leaves at any level: an observed value, a minimum, a maximum and a most-frequent value are each a raw value. What leaves is counts, and at `full` a mean over values that are not all one value. |
| **Raw target identifiers** | Never leave the SDK | Resource IDs may reveal internal architecture or contain embedded PII. Only cardinality counts are shipped. |
| **User PII** | Never without explicit opt-in | User IDs are counted (distinct_users) but never enumerated. Names, emails, etc. are never included. |
| **Raw envelope content** | Never leave via telemetry | Full envelopes are shipped via the audit channel, not telemetry. Telemetry only contains aggregated stats derived from envelopes. |

**Ruled 2026-11-04 (Trevor, HTL-20 row 142): no raw value leaves in telemetry at any level; the default sends counts only.** The rule rests on this table's "Full parameter payloads — Never leave the SDK" and "Names, emails, etc. are never included", §6's "Parameter tracking is opt-in per tool via configuration to avoid leaking unexpected field names", and hiitl's design principle "ECP evaluates declared facts, not raw content". It replaces the 1.0 text that sent each numeric parameter's min and max at `standard` and categorical `top_values` at `full`, which contradicted this table. "Counts only" governs what is derived from the envelope; latency is the SDK's own timing and stays at `standard`. Box: the SDK, its sync engine's telemetry channel.

The TypeScript SDK has no telemetry collector: its sync engine accepts a `TelemetryCollectorSink` and the client passes none, so it sends no telemetry. Nothing here requires one; a TypeScript collector, when built, is held to this section.

### Enforcement

Privacy boundaries are enforced at the **aggregation layer** within the SDK. The telemetry collector receives evaluation results and produces only aggregated statistics — it never has access to raw data in a form that could be serialized to the telemetry payload.

Implementation requirement: the telemetry aggregator keeps only counts, digests, and at `full` a running sum, never a raw value: distinct values are counted by digest, no minimum, maximum or frequency table of values is kept, and a parameter's sum exists only at `full`, where its mean is sent. This is a structural guarantee, not just a code-level filter.

---

## 5. Redaction Controls

Redaction controls determine how much detail the SDK includes in telemetry. Three levels are defined, plus `off`:

### Redaction Levels

| Level | Description | Use Case |
|-------|-------------|----------|
| **`full`** | Everything `standard` sends, plus each tracked numeric parameter's mean (§6) | Suggestion engine with a sense of parameter scale |
| **`standard`** (default) | Counts: per action its decision, operation and reason-code counts, latency, target cardinality, and for a tracked action each parameter's count (numeric) or distinct count (categorical); per agent its counts and distinct users | Dashboard, count-based suggestions |
| **`minimal`** | Per action and per agent: action and decision counts only | Maximum privacy, limited dashboard, no parameter-based suggestions |

No level sends a raw parameter value (§4).

### Per-Field Inclusion Matrix

| Field | `full` | `standard` | `minimal` |
|-------|--------|------------|-----------|
| `action` | Yes | Yes | Yes |
| `action_count` | Yes | Yes | Yes |
| `decision_counts` | Yes | Yes | Yes |
| `error_count` | Yes | Yes | Yes |
| `latency` (percentiles) | Yes | Yes | No |
| `operations` | Yes | Yes | No |
| `parameter_stats.numeric_stats.count` (tracked actions, §6) | Yes | Yes | No |
| `parameter_stats.numeric_stats.mean` (tracked actions; values not all one value) | Yes | No | No |
| `parameter_stats.categorical_stats.distinct_count` (tracked actions) | Yes | Yes | No |
| `target_cardinality` | Yes | Yes | No |
| `reason_code_counts` | Yes | Yes | No |
| `agent_summary` (`agent_id`, `action_count`, `tools_used`, `decision_counts`) | Yes | Yes | Yes |
| `agent_summary.distinct_users` | Yes | Yes | No |
| `system_metrics` (all) | Yes | Yes | Yes |

### Configuration

| Method | Setting |
|--------|---------|
| Constructor option | `telemetry_level: "full" \| "standard" \| "minimal" \| "off"` |
| Environment variable | `HIITL_TELEMETRY_LEVEL` |
| Default | `"standard"` |

**The telemetry family (ruled 2026-11-06, row 208):** "One telemetry family: the spec names the interval, buffer size,
sample rate and parameter tools as `HIITL_TELEMETRY_*` beside `HIITL_TELEMETRY_LEVEL` (spec before cells), both SDKs
read them, and the stale `HIITL_SYNC_TELEMETRY_*` names are refused under row 207". It rests on row 172's ruling (one
telemetry setting, the client's) and "one representation per fact". Every telemetry setting is read under one of these
names, in both SDKs:

| Setting | Constructor option | Environment variable | Default | Range |
|---------|-------------------|---------------------|---------|-------|
| Level | `telemetry_level` | `HIITL_TELEMETRY_LEVEL` | `"standard"` | `full`, `standard`, `minimal`, `off` |
| Interval | `sync_config.telemetry_sync_interval` | `HIITL_TELEMETRY_INTERVAL` | `60` (seconds) | 5–3600 |
| Buffer size | `sync_config.telemetry_buffer_size` | `HIITL_TELEMETRY_BUFFER_SIZE` | `60` (records) | 10–1000 |
| Sample rate | `sync_config.telemetry_sample_rate` | `HIITL_TELEMETRY_SAMPLE_RATE` | `1.0` | 0–1: the fraction of evaluations whose parameter and target details are counted |
| Parameter tools | `sync_config.telemetry_parameter_tools` | `HIITL_TELEMETRY_PARAMETER_TOOLS` (a JSON list) | `[]` | the actions whose parameters are counted (§6, "Parameter Discovery") |

A value outside its range is refused with `ConfigurationError`, naming the range. The TypeScript SDK reads and checks
each, and, shipping no collector, sends nothing at any value.

**Names earlier releases read.** A set variable an earlier release read and this one does not is refused when the
client is constructed (`ConfigurationError`), naming its replacement (row 207, ruled 2026-11-06: "a set `HIITL_*`
variable no setting reads is refused at construction, naming its replacement"). Both SDKs read this table:

| Earlier name | Replacement |
|--------------|-------------|
| `HIITL_SYNC_TELEMETRY_LEVEL` | `HIITL_TELEMETRY_LEVEL` |
| `HIITL_SYNC_TELEMETRY_SYNC_INTERVAL` | `HIITL_TELEMETRY_INTERVAL` |
| `HIITL_SYNC_TELEMETRY_BUFFER_SIZE` | `HIITL_TELEMETRY_BUFFER_SIZE` |
| `HIITL_SYNC_TELEMETRY_SAMPLE_RATE` | `HIITL_TELEMETRY_SAMPLE_RATE` |
| `HIITL_SYNC_TELEMETRY_PARAMETER_TOOLS` | `HIITL_TELEMETRY_PARAMETER_TOOLS` |

A set `HIITL_TELEMETRY_*` variable that neither table names is refused the same way, naming the family's variables.

To disable telemetry entirely, set `telemetry_level` to `"off"` (or `HIITL_TELEMETRY_LEVEL=off`). When telemetry is off, the sync engine's telemetry channel is inactive and no telemetry data is collected or buffered.

The level is a setting of the client, in both SDKs: `HIITL(telemetry_level=...)` in Python, `new HIITL({ telemetry_level })` in TypeScript, and `HIITL_TELEMETRY_LEVEL` for either. It is not one of the sync engine's settings (`sync_config`), and no `HIITL_SYNC_` variable sets it. A value outside the four is refused with `ConfigurationError`, naming them. The TypeScript SDK ships no collector, so it sends no telemetry at any level.

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

**Ruled 2026-11-09 (Trevor, HTL-30):** all three percentiles use linear interpolation at
`(n - 1) * p` in the sorted sample, then round to three decimal places (`p` is 0.50, 0.95 or 0.99).
At an integral position take that sample; between positions interpolate between their two values. A singleton
returns its only value, and repeated values retain their multiplicity. This makes `p50` the median already named
by `latency_stats`: an even sample takes the mean of its two middle values. It does not take the upper middle
value. The convention also governs any permitted approximation's target. Box: the SDK's telemetry collector.
This resolves the convention left unstated by the original exact-percentile
sentence; it changes no privacy boundary or schema field.

### Numeric Parameter Stats

For numeric parameters (e.g., `amount`, `quantity`):

- Track `count`. At `full` only, also a running sum (for `mean`) and a digest of the first value, so the mean is sent only when the values are not all one value.
- A parameter the store does not record as given (a declared field, or at the gateway a parameter recorded as its
  hash, event_format.md "Redaction") contributes its `count` and no `mean` at any level (row 216, ruled 2026-11-06: "a
  declared field contributes its count and no mean, by the declaration read at every place a value leaves"). The
  collector reads the store's declaration as the store applies it, the org's included.
- No minimum or maximum is tracked: each is one observed value.
- Memory-efficient: O(1) per parameter regardless of action volume.
- The SDK detects numeric parameters by observing JSON number types.

### Categorical Parameter Stats

For non-numeric parameters (e.g., `currency`, `region`):

- Track `distinct_count` by counting digests of the values; the value itself is never held.
- No most-frequent values are kept or sent.
- Maximum tracked parameters per tool: 20 (to bound memory usage).

### Parameter Discovery

Parameter tracking is opt-in per tool via configuration to avoid leaking unexpected field names. The SDK tracks the parameters of an action only when the action is named in `telemetry_parameter_tools` (`sync_config.telemetry_parameter_tools`, environment `HIITL_TELEMETRY_PARAMETER_TOOLS` as a JSON list, §5). The default names none, so by default no parameter name or count leaves the SDK. For a named action, the SDK discovers parameters from the `parameters` field of evaluated envelopes:

- Only top-level keys are tracked (no deep nesting — `parameters.amount` yes, `parameters.details.breakdown.tax` no).
- Parameters seen fewer than 3 times in a window are excluded from the telemetry record (noise reduction).

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

Each sync cycle ships every pending record: the payload is `{"records": [<telemetry record>, …], "sdk_version": "<version>"}`, at most as many records as the buffer holds (`telemetry_buffer_size`: 60 by default, from 10 to 1000).

### Per-record response

The upload retains its per-record answer: HTTP `200` with `accepted` and `errors`.
Each error carries the original zero-based record `index`, a `code` naming the
cause, and a `message`. After the existing tenant check, the service reads every
number in the complete supplied record, including unknown optional members,
before reading timestamps, calculating totals or projecting stored members.
A record outside [the numeric domain](sync_engine.md#numeric-domain) is refused
with `NUMERIC_DOMAIN_INVALID`; its message names the exact instance path within
that record (`<root>` for its root) and directs the caller to pass the value as
text. The refused record is not stored or counted as accepted. Other records in
the batch continue through the existing checks and storage path, in either order.

This retains the existing telemetry partial-batch answer, with no audit
`RECORD_REFUSALS` entry, retry mechanism or local final mark. Existing tenant and
timestamp refusals retain their codes and messages. By Trevor's `fc00ed9a`
(2026-11-15), "The other records in the batch go through," and the Numeric domain's
admission before projection; proposed system architecture §2 hosted ingest and
audit/ops telemetry.

### Buffering

If the telemetry channel is unavailable (sync engine degraded):

- Telemetry records are buffered in memory, up to `telemetry_buffer_size` records (60 by default: 1 hour at the default interval).
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

- Current version: `"2.0"` (2026-11-04): removed the numeric `min` and `max`, categorical `top_values`, `sdk_instance_id`, and the system metrics never produced (rows 142 and 146).
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

A record at `standard` from an SDK whose `telemetry_parameter_tools` names `process_payment`:

```json
{
  "telemetry_version": "2.0",
  "window_start": "2026-03-15T14:30:00Z",
  "window_end": "2026-03-15T14:31:00Z",
  "org_id": "org_abc123def456ghij",
  "environment": "prod",
  "sdk_version": "1.2.3",
  "sdk_language": "python",
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
    "error_counts": {
      "evaluation_errors": 0,
      "telemetry_errors": 0
    }
  }
}
```
