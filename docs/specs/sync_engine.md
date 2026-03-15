# Sync Engine Protocol Specification

**Version**: 1.0
**Status**: Phase 1.5 Specification
**Last Updated**: 2026-02-26

---

## 1. Purpose & Architecture

The sync engine enables **hybrid mode** — local policy evaluation with background synchronization to the hosted service. It bridges the gap between pure local mode (no network, file-based policies) and hosted mode (server-side evaluation).

**Core invariant: evaluation is never blocked by sync.** All synchronization happens asynchronously in the background. The evaluator always uses locally-cached data. If the cache is stale or sync fails, evaluation continues with local state.

### Data Flow

```
┌─────────────────────────────────────────────────┐
│                  SDK (Hybrid Mode)               │
│                                                  │
│  ┌──────────┐    ┌──────────┐    ┌───────────┐  │
│  │ Evaluator │───>│  Audit   │    │   Cache   │  │
│  │  (local)  │    │  Buffer  │    │  (disk)   │  │
│  └─────┬─────┘    └────┬─────┘    └─────┬─────┘  │
│        │               │                │        │
│        │ reads         │ push           │ pull   │
│        ▼               ▼                ▼        │
│  ┌──────────────────────────────────────────┐    │
│  │            Sync Engine (background)       │    │
│  └────────────────────┬─────────────────────┘    │
└───────────────────────┼──────────────────────────┘
                        │ HTTPS
                        ▼
              ┌──────────────────┐
              │  Hosted Service  │
              │   (server API)   │
              └──────────────────┘
```

### Non-Goals

- **Not real-time streaming.** Sync uses polling intervals and batch uploads, not WebSockets or SSE.
- **Not a replication protocol.** The sync engine transfers operational data, not a full database replica.
- **Not the evaluator.** Sync populates the cache; the evaluator reads from it. These are separate concerns.

---

## 2. Sync Channels

Each data type flows through a dedicated **sync channel** with its own direction, interval, and endpoint.

### 2.1 Audit Upload

Uploads locally-produced audit records to the hosted service.

| Property | Value |
|----------|-------|
| **Direction** | Local → Server |
| **Endpoint** | `POST /v1/sync/audit` |
| **Default Interval** | 30 seconds |
| **Batch Size** | Up to 100 records per request |
| **Priority** | Critical — audit records must never be lost |

**Payload schema:**

```json
{
  "type": "object",
  "required": ["records", "sdk_version", "sync_sequence"],
  "properties": {
    "records": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["event_id", "timestamp", "org_id", "environment", "action_id", "envelope", "decision", "policy_version", "decision_type", "content_hash"],
        "properties": {
          "event_id": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" },
          "org_id": { "type": "string" },
          "environment": { "type": "string", "enum": ["dev", "stage", "prod"] },
          "action_id": { "type": "string" },
          "envelope": { "type": "object" },
          "decision": { "type": "object" },
          "policy_version": { "type": "string" },
          "decision_type": { "type": "string" },
          "action": { "type": "string" },
          "agent_id": { "type": "string" },
          "content_hash": { "type": "string", "description": "SHA-256 hash of the record content" }
        }
      },
      "maxItems": 100
    },
    "sdk_version": { "type": "string" },
    "sync_sequence": {
      "type": "integer",
      "description": "Monotonically increasing sequence number for ordering sync batches"
    }
  }
}
```

**Response schema:**

```json
{
  "type": "object",
  "required": ["accepted", "duplicates"],
  "properties": {
    "accepted": {
      "type": "integer",
      "description": "Number of new records stored"
    },
    "duplicates": {
      "type": "integer",
      "description": "Number of records already present (deduplicated by event_id)"
    },
    "errors": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "event_id": { "type": "string" },
          "code": { "type": "string" },
          "message": { "type": "string" }
        }
      },
      "description": "Records that failed validation. SDK should retain and retry."
    }
  }
}
```

**Behavior:**
- Server deduplicates by `event_id`. Uploading the same record twice is safe.
- Server verifies `content_hash` matches the record content. Hash mismatch → record rejected with `CONTENT_HASH_MISMATCH`.
- Successfully uploaded records are marked as synced in the local audit store. They remain in local storage (for local queries) but are excluded from future sync batches.

### 2.2 Policy Download

Downloads the current active policy set from the hosted service.

| Property | Value |
|----------|-------|
| **Direction** | Server → Local |
| **Endpoint** | `GET /v1/sync/policies` |
| **Default Interval** | 5 minutes |
| **Priority** | Critical — stale policies mean stale enforcement |

**Request headers:**
- `If-None-Match: "{etag}"` — conditional request to avoid re-downloading unchanged policies

**Response schema:**

```json
{
  "type": "object",
  "required": ["policies", "version", "etag"],
  "properties": {
    "policies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["policy_id", "name", "version", "content", "content_hash"],
        "properties": {
          "policy_id": { "type": "string" },
          "name": { "type": "string" },
          "version": { "type": "string" },
          "content": { "type": "object", "description": "Full policy set in JSON format" },
          "content_hash": { "type": "string", "description": "SHA-256 hash of content" },
          "active": { "type": "boolean" },
          "updated_at": { "type": "string", "format": "date-time" }
        }
      }
    },
    "version": {
      "type": "string",
      "description": "Composite version identifier for the entire policy bundle"
    },
    "etag": {
      "type": "string",
      "description": "Opaque version tag for conditional requests"
    }
  }
}
```

**Behavior:**
- Server returns `304 Not Modified` if the client's ETag matches the current version.
- SDK verifies `content_hash` for each policy before caching. Hash mismatch → policy rejected, `POLICY_INTEGRITY_VIOLATION` event emitted.
- On successful download, SDK atomically replaces the policy cache (write new file, then rename — no partial states).
- The evaluator reads from the cache. It is not aware of sync operations.

### 2.3 Route Download

Downloads active route configurations from the hosted service.

| Property | Value |
|----------|-------|
| **Direction** | Server → Local |
| **Endpoint** | `GET /v1/sync/routes` |
| **Default Interval** | 5 minutes |
| **Priority** | High |

**Request headers:**
- `If-None-Match: "{etag}"` — conditional request

**Response schema:**

```json
{
  "type": "object",
  "required": ["routes", "etag"],
  "properties": {
    "routes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "config"],
        "properties": {
          "name": { "type": "string" },
          "config": { "type": "object", "description": "Route configuration per routes.md spec" },
          "updated_at": { "type": "string", "format": "date-time" }
        }
      }
    },
    "etag": { "type": "string" }
  }
}
```

**Behavior:**
- Same ETag/conditional semantics as policy download.
- Atomic cache replacement on update.

### 2.4 Kill Switch Polling

Polls for active kill switch rules. Kill switches are safety-critical and poll at a higher frequency.

| Property | Value |
|----------|-------|
| **Direction** | Server → Local |
| **Endpoint** | `GET /v1/sync/kill-switches` |
| **Default Interval** | 30 seconds |
| **Priority** | High — kill switches are safety-critical |

**Response schema:**

```json
{
  "type": "object",
  "required": ["kill_switches", "server_time"],
  "properties": {
    "kill_switches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["rule_name", "active", "scope"],
        "properties": {
          "rule_name": { "type": "string" },
          "active": { "type": "boolean" },
          "scope": {
            "type": "object",
            "properties": {
              "action": { "type": "string" },
              "agent_id": { "type": "string" },
              "environment": { "type": "string" }
            }
          },
          "activated_at": { "type": "string", "format": "date-time" },
          "activated_by": { "type": "string" },
          "reason": { "type": "string" }
        }
      }
    },
    "server_time": {
      "type": "string",
      "format": "date-time",
      "description": "Server timestamp for clock drift detection"
    }
  }
}
```

**Behavior:**
- No conditional requests — kill switches always return the full active set (small payload).
- On receipt, SDK immediately replaces the local kill switch state. No merge — server is authoritative.
- If a kill switch is activated between polls, enforcement is delayed by at most one polling interval. For stricter requirements, reduce the polling interval or use hosted mode.

### 2.5 Rate Limit Sync

Synchronizes rate limit counter state between local instances and the server.

| Property | Value |
|----------|-------|
| **Direction** | Bidirectional |
| **Endpoint** | `POST /v1/sync/rate-limits` |
| **Default Interval** | 60 seconds |
| **Priority** | Medium — local counters are sufficient for most use cases |

**Request schema (client → server):**

```json
{
  "type": "object",
  "required": ["counters", "client_time"],
  "properties": {
    "counters": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["scope", "window_type", "window_size_seconds", "current_count", "window_start"],
        "properties": {
          "scope": {
            "type": "object",
            "description": "Rate limit scope identifiers (org_id, agent_id, user_id, action)",
            "properties": {
              "org_id": { "type": "string" },
              "agent_id": { "type": "string" },
              "user_id": { "type": "string" },
              "action": { "type": "string" }
            }
          },
          "window_type": { "type": "string", "enum": ["sliding", "fixed"] },
          "window_size_seconds": { "type": "integer" },
          "current_count": { "type": "integer" },
          "window_start": { "type": "string", "format": "date-time" }
        }
      }
    },
    "client_time": { "type": "string", "format": "date-time" }
  }
}
```

**Response schema (server → client):**

```json
{
  "type": "object",
  "required": ["counters", "server_time"],
  "properties": {
    "counters": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["scope", "merged_count", "window_start"],
        "properties": {
          "scope": { "type": "object" },
          "merged_count": {
            "type": "integer",
            "description": "Server-computed merged count across all SDK instances"
          },
          "window_start": { "type": "string", "format": "date-time" }
        }
      }
    },
    "server_time": { "type": "string", "format": "date-time" }
  }
}
```

**Behavior:**
- Client uploads its local counter snapshots. Server merges across all SDK instances sharing the same org/environment.
- Client replaces its local counters with the server's merged state.
- Between syncs, local counters may undercount (each instance only sees its own actions). This is acceptable for non-critical rate limiting.
- For strict enforcement across instances, use hosted mode (server-side evaluation with shared counters).

### 2.6 Telemetry Upload

Uploads SDK telemetry to the hosted service.

| Property | Value |
|----------|-------|
| **Direction** | Local → Server |
| **Endpoint** | `POST /v1/sync/telemetry` |
| **Default Interval** | 60 seconds |
| **Priority** | Deferred — schema defined by TICKET-019.4 |

The telemetry channel uses the same transport infrastructure as other sync channels but its payload schema is defined separately in the telemetry schema specification. This channel is not implemented until TICKET-019.4 is complete.

---

## 3. Wire Protocol

### Transport

- **Protocol**: JSON over HTTPS. TLS required — no plaintext HTTP.
- **Content-Type**: `application/json`
- **Character encoding**: UTF-8

### Authentication

All sync requests include:

```
Authorization: Bearer {api_key}
X-HIITL-Org-Id: {org_id}
X-HIITL-Environment: {environment}
X-HIITL-SDK-Version: {sdk_version}
X-HIITL-SDK-Language: python|typescript
```

The server validates that the `api_key` is authorized for the specified `org_id` and `environment`. Mismatches result in `403 Forbidden`.

### Compression

- Requests with body > 1 KB should be compressed with gzip.
- Set `Content-Encoding: gzip` header when compressing.
- Server always accepts uncompressed requests (compression is optional but recommended).
- Server responses use `Content-Encoding: gzip` when the client sends `Accept-Encoding: gzip`.

### Batching

Each channel defines a maximum batch size. When more data is available than fits in one batch:

1. Send the first batch.
2. On success, send the next batch immediately (no interval wait).
3. Continue until the buffer is drained or an error occurs.
4. On error, stop the drain and resume at the next scheduled interval.

### Request ID

Every sync request includes a unique request ID for tracing:

```
X-Request-Id: {uuid}
```

---

## 4. Caching Strategy

### Cache Location

Configurable via `cache_dir` constructor parameter or `HIITL_CACHE_DIR` environment variable.

**Default**: `~/.hiitl/cache/`

### Cache Structure

```
{cache_dir}/
└── {org_id}/
    └── {environment}/
        ├── policies.json
        ├── policies.etag
        ├── routes.json
        ├── routes.etag
        └── kill_switches.json
```

Each `.json` file contains the full response payload from the last successful sync. Each `.etag` file contains the ETag value for conditional requests.

### TTL and Freshness

| Channel | Default TTL | Max Stale Age | Behavior When Stale |
|---------|-------------|---------------|---------------------|
| Policies | 5 minutes | 24 hours | Warn, continue using cached data |
| Routes | 5 minutes | 24 hours | Warn, continue using cached data |
| Kill Switches | 30 seconds | 5 minutes | Warn, continue using cached data |

- **TTL**: How long before the next background refresh is triggered.
- **Max stale age**: How long cached data can be used before the SDK emits a `CACHE_STALE` warning event. Even beyond max stale age, the SDK continues using cached data — it never blocks evaluation.

### Atomic Writes

Cache updates use atomic write-then-rename to prevent partial reads:

1. Write new content to a temporary file (`{filename}.tmp`)
2. Rename temporary file to the target filename (atomic on POSIX)

---

## 5. Startup Behavior

### Cold Start (No Disk Cache)

When the SDK starts in hybrid mode with no existing disk cache:

1. **Attempt initial sync** — download policies, routes, and kill switches from the server.
2. **Block initialization** until the first policy download completes, with a configurable timeout (default: 10 seconds).
3. **If initial sync succeeds** — populate cache, start background sync, initialization completes.
4. **If initial sync times out** — fall back to local policy files (`policy_path` if configured). Emit `SYNC_INIT_TIMEOUT` event. Start background sync (will retry).
5. **If no local policies and sync fails** — initialization fails with a clear error: "No policies available. Provide policy_path for local fallback or ensure server connectivity."

### Warm Start (Disk Cache Exists)

When the SDK starts and valid disk cache is present:

1. **Load disk cache immediately** — policies, routes, kill switches from `{cache_dir}/{org_id}/{environment}/`.
2. **Check cache age** — if within TTL, use directly. If stale but within max stale age, use with info log. If beyond max stale age, use with warning.
3. **Start background sync** — first sync fires immediately (not waiting for the interval).
4. **Initialization completes immediately** — does not block on server connectivity.

### Hot Start (Already Running)

When the sync engine is already running (e.g., SDK instance reused):

- No-op. Background sync continues on its existing schedule.

---

## 6. Conflict Resolution

### Policies and Routes — Server Wins

The server is the authoritative source for policies and routes in hybrid mode.

- On download, the server's version **completely replaces** the local cache.
- There is no merge. If the server has a different set of policies than the local cache, the server's set is used.
- Local policy files (`policy_path`) are only used as a fallback when the server is unreachable and no cache exists.
- **Precedence**: Server cache > local policy files > empty (fail-closed if no policies available).

### Audit Records — Client Wins

The client is the authoritative source for audit records.

- Audit records are generated locally and uploaded to the server.
- The server deduplicates by `event_id`. Uploading the same record multiple times is idempotent.
- The server never pushes audit records to the client.
- If upload fails, records remain in the local buffer and are retried. Records are never dropped.

### Rate Limits — Merge, Then Server Wins

Rate limit counters require special handling because multiple SDK instances may be incrementing counters independently.

1. Client uploads its local counter snapshots.
2. Server merges counters across all instances (sum of increments since last sync, bounded by window).
3. Server returns the merged state.
4. Client replaces local counters with the server's merged values.

Between syncs, each instance only sees its own increments. This means rate limits may undercount in hybrid mode. For strict cross-instance enforcement, use hosted mode.

### Kill Switches — Server Wins, Immediate Effect

- On download, the server's kill switch state **completely replaces** local state.
- Active kill switches take effect immediately on the next evaluation — no waiting for any interval or cache refresh.

---

## 7. Error Handling & Resilience

### Retry Strategy

All sync channels use exponential backoff with jitter on failure:

| Attempt | Base Delay | With Jitter (range) |
|---------|-----------|---------------------|
| 1 | 1s | 0.5s – 1.5s |
| 2 | 2s | 1.0s – 3.0s |
| 3 | 4s | 2.0s – 6.0s |
| 4 | 8s | 4.0s – 12.0s |
| 5+ | 60s (max) | 30s – 90s |

Jitter formula: `delay * (0.5 + random() * 1.0)`

### Circuit Breaker

Each sync channel has an independent circuit breaker:

| State | Behavior |
|-------|----------|
| **Closed** (normal) | Sync operates normally |
| **Open** (failed) | Sync attempts are skipped. Transitions after 5 consecutive failures. |
| **Half-Open** (probing) | After 60 seconds in open state, allow one sync attempt. Success → closed. Failure → open. |

Circuit breaker state transitions emit structured events (`SYNC_CIRCUIT_OPEN`, `SYNC_CIRCUIT_HALF_OPEN`, `SYNC_CIRCUIT_CLOSED`).

### Graceful Degradation

When sync fails, all channels degrade to local-only operation:

| Channel | Degraded Behavior |
|---------|-------------------|
| Audit Upload | Records accumulate in local buffer. Retried when connectivity returns. |
| Policy Download | Evaluator uses cached policies. `CACHE_STALE` event emitted when cache exceeds max stale age. |
| Route Download | Evaluator uses cached routes. Same staleness behavior as policies. |
| Kill Switch Polling | Uses last known kill switch state. `CACHE_STALE` event emitted. |
| Rate Limit Sync | Local counters used (may undercount). No warning — this is the expected local behavior. |

### Audit Buffer Management

The local audit buffer is bounded to prevent unbounded memory/disk growth:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_buffer_records` | 10,000 | Maximum records in memory buffer |
| `max_buffer_size_bytes` | 50 MB | Maximum total size of buffered records |

When the buffer is full:

1. **Disk spillover** — oldest unsynced records are flushed to a spillover file (`{cache_dir}/{org_id}/{environment}/audit_overflow.jsonl`).
2. **`BUFFER_FULL` event emitted** — warns that the audit buffer has hit its limit.
3. **Records are never dropped.** New audit records continue to be written. The buffer expands to disk as needed.
4. **On sync recovery** — spillover records are uploaded first (oldest-first ordering), then memory buffer.

### Structured Sync Events

The sync engine emits the following structured events (logged locally and included in telemetry when available):

| Event | Severity | Trigger |
|-------|----------|---------|
| `SYNC_STARTED` | Info | Sync engine initialized |
| `SYNC_COMPLETED` | Debug | A sync cycle completed successfully |
| `SYNC_FAILED` | Warning | A sync attempt failed (before circuit opens) |
| `SYNC_CIRCUIT_OPEN` | Error | Circuit breaker opened after consecutive failures |
| `SYNC_CIRCUIT_HALF_OPEN` | Info | Circuit breaker probing |
| `SYNC_CIRCUIT_CLOSED` | Info | Circuit breaker recovered |
| `SYNC_INIT_TIMEOUT` | Warning | Initial sync timed out during cold start |
| `CACHE_STALE` | Warning | Cached data exceeds max stale age |
| `BUFFER_FULL` | Warning | Audit buffer hit capacity, spilling to disk |
| `POLICY_INTEGRITY_VIOLATION` | Error | Policy content hash mismatch |
| `CONTENT_HASH_MISMATCH` | Error | Audit record hash verification failed on server |

---

## 8. Security

### Transport Security

All sync traffic must use TLS 1.2 or higher. SDK implementations must not allow disabling TLS for sync channels (even in development — use localhost with self-signed certs if needed).

### Authentication

- Sync uses the same `api_key` as hosted mode, passed as a Bearer token.
- The server validates that the `api_key` is authorized for the claimed `org_id` and `environment`.
- Unauthorized requests receive `401 Unauthorized`. Mismatched org/environment receives `403 Forbidden`.

### Tenant Isolation

- The server enforces that sync requests can only read/write data for the `org_id` associated with the `api_key`.
- Cross-tenant data leakage through sync channels is a critical severity bug.

### Content Integrity

- **Audit records**: Content hash (SHA-256) is computed by the SDK at write time and verified by the server on upload.
- **Policies**: Content hash is computed by the server and verified by the SDK on download. Hash mismatch → policy rejected, `POLICY_INTEGRITY_VIOLATION` emitted.
- **Kill switches and routes**: Integrity is implied by TLS transport security. Explicit content hashing may be added in a future version if required.

### Credential Handling

- `api_key` must never be logged, cached to disk, or included in error messages.
- Sync event payloads must not include the `api_key` or any authentication credentials.

---

## 9. Configuration

All sync parameters are configurable via constructor options, with environment variable overrides.

### Configuration Table

| Parameter | Constructor Option | Environment Variable | Default | Description |
|-----------|-------------------|---------------------|---------|-------------|
| Cache directory | `cache_dir` | `HIITL_CACHE_DIR` | `~/.hiitl/cache/` | Disk cache location |
| Audit sync interval | `audit_sync_interval` | `HIITL_SYNC_AUDIT_INTERVAL` | `30` (seconds) | How often audit records are uploaded |
| Policy sync interval | `policy_sync_interval` | `HIITL_SYNC_POLICY_INTERVAL` | `300` (seconds) | How often policies are refreshed |
| Route sync interval | `route_sync_interval` | `HIITL_SYNC_ROUTE_INTERVAL` | `300` (seconds) | How often routes are refreshed |
| Kill switch poll interval | `kill_switch_poll_interval` | `HIITL_SYNC_KS_INTERVAL` | `30` (seconds) | How often kill switches are polled |
| Rate limit sync interval | `rate_limit_sync_interval` | `HIITL_SYNC_RL_INTERVAL` | `60` (seconds) | How often rate limit counters sync |
| Audit batch size | `audit_batch_size` | `HIITL_SYNC_AUDIT_BATCH` | `100` | Max records per audit upload |
| Max buffer records | `max_buffer_records` | `HIITL_SYNC_MAX_BUFFER` | `10000` | Max audit records in memory |
| Max buffer size | `max_buffer_size_bytes` | `HIITL_SYNC_MAX_BUFFER_BYTES` | `52428800` (50 MB) | Max total buffer size |
| Init timeout | `sync_init_timeout` | `HIITL_SYNC_INIT_TIMEOUT` | `10` (seconds) | Cold start sync timeout |
| Circuit breaker threshold | `circuit_breaker_threshold` | `HIITL_SYNC_CB_THRESHOLD` | `5` | Failures before circuit opens |
| Circuit breaker reset | `circuit_breaker_reset` | `HIITL_SYNC_CB_RESET` | `60` (seconds) | Time before half-open probe |
| Max cache stale age | `max_cache_stale_age` | `HIITL_SYNC_MAX_STALE` | `86400` (24 hours) | Max age before `CACHE_STALE` warning |

### Precedence

1. Constructor option (highest priority)
2. Environment variable
3. Default value (lowest priority)

---

## 10. Performance Targets

### Evaluation Path

Sync must add **zero latency** to the evaluation hot path. All sync operations run in background threads/tasks. The evaluator reads from in-memory cache — it is never blocked by a sync operation.

### Sync Overhead

| Metric | Target |
|--------|--------|
| Background thread/task memory | < 10 MB per SDK instance |
| Audit upload latency (per batch) | < 500 ms (p95) |
| Policy download latency | < 200 ms (p95) |
| Cache read latency | < 1 ms (from disk) |
| Disk cache size | < 10 MB for typical deployment |

### Throughput

| Metric | Target |
|--------|--------|
| Audit upload throughput | 100 records/batch, up to 3 batches/second during drain |
| Sustained audit rate | 10,000 records/hour without buffer growth |
| Concurrent sync channels | All channels operate independently and concurrently |

---

## 11. Implementation Sequencing

The sync engine is implemented incrementally across Phase 2:

| Phase | Channels | Rationale |
|-------|----------|-----------|
| **2a** | Audit upload + Policy download + Route download | Core value: centralized audit visibility + server-managed policies |
| **2b** | Kill switch polling | Safety-critical: enables remote emergency stops |
| **2c** | Rate limit sync | Cross-instance rate limiting (complex, nice-to-have) |
| **2d** | Telemetry upload | Powers dashboard and analytics (depends on TICKET-019.4) |

Each phase is independently useful. Phase 2a alone replaces the "log: sync will be available in a future release" message with working synchronization.

---

## Appendix: Relationship to Other Specs

| Spec | Relationship |
|------|-------------|
| [Event Format](event_format.md) | Audit records uploaded via sync conform to the event format spec |
| [Decision Response](decision_response.md) | Decisions included in audit records follow this format |
| [Policy Format](policy_format.md) | Policies downloaded via sync conform to the policy format spec |
| [Routes](routes.md) | Routes downloaded via sync conform to the route schema |
| [Envelope Schema](envelope_schema.json) | Envelopes included in audit records conform to this schema |
| Telemetry Schema (TICKET-019.4) | Telemetry channel payload defined by this future spec |
