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

- **Not a replication protocol.** The sync engine transfers operational data, not a full database replica.
- **Not the evaluator.** Sync populates the cache; the evaluator reads from it. These are separate concerns.

### Note on real-time channels (Block 3b addition)

The SDK's sync engine itself remains a **polling architecture** —
audit batches, policy/route/kill-switch pulls all happen on
independent interval timers. This keeps the engine simple,
firewall-friendly, and bounded in resource use.

**However**, the platform also exposes **real-time channels for
synchronous routes** (Block 3b):

- When `evaluate()` returns PAUSE / REQUIRE_APPROVAL / ESCALATE,
  nothing is queued by the evaluation itself. The caller (typically
  the MCP proxy or a server-side wrapper) opens a review case with
  `POST /v1/reviews` and waits on `GET /v1/reviews/{case_id}/stream`.
- Resolution events propagate via `pg_notify` (Postgres LISTEN/NOTIFY)
  in production, or an in-process notifier in tests / single-process
  dev. Workers holding SSE connections receive notifications and emit
  the resolution event to the waiting client without polling.
- See [`routes.md`](./routes.md#implementation-how-routes-execute) section
  "Implementation: How Routes Execute" for the full mechanics.

This is **adjacent to** the sync engine, not part of it: the SDK does
not initiate or consume SSE streams during normal `evaluate()` calls
(those are zero-network in hybrid mode). SSE is only used by callers
that need to block on a human/external decision, and those callers
typically aren't running inside the agent's hot path.

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
          "action": { "type": ["string", "null"], "description": "The envelope's action (event_format.md 2.0, From 1.x: `tool_name` before; the service reads it from the envelope, never as sent)" },
          "agent_id": { "type": ["string", "null"] },
          "content_hash": { "type": "string", "description": "SHA-256 hash of the record content" },
          "event_type": { "type": "string", "description": "Optional: the record's event, computed from its decision (event_format.md \"Event Types\") and checked by the service" },
          "execution_result": { "type": "object", "description": "On a result record only (event_format.md \"The Lifecycle\"): status, error, duration_ms" },
          "redaction": { "type": "object", "description": "Only where a declared path is absent (event_format.md \"Redaction\"): {\"absent\": [<declared path>, ...]}" }
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
      "description": "Number of records the key's org and environment already hold: a record under an event_id they hold, or a result record whose action already holds its result (Behavior, below)"
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
      "description": "The records the server did not store, each with its code. A record refused for its own content is final: the SDK keeps it as written, marks it refused with the code and never sends it again. Any other refusal is retried (Behavior, below)."
    }
  }
}
```

**Behavior:**
- Server deduplicates by `event_id` within the key's org and environment (HTL-29 row 136): a record whose `event_id`
  they already hold is a duplicate, so uploading the same record twice is safe. A record under an `event_id` that
  another org or environment holds is neither a duplicate nor a refusal: it is checked and stored as any record is,
  and the answer says nothing of the other.
- Server verifies `content_hash` matches the record content. Hash mismatch → record rejected with `CONTENT_HASH_MISMATCH`.
- The record keeps the `timestamp` its writer gave it (HTL-29 row 242, ruled 2026-11-09: "the record keeps its
  writer's `timestamp`; the service's own write is `created_at`", by event_format.md's field table, "When the record
  was written", and the OTel mapping). It is read in the schema's form, `date-time`, by RFC 3339's grammar as
  ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar" states it; the store holds that instant, in UTC.
  A record whose `timestamp` is absent or refused by that reading is rejected with `TIMESTAMP_INVALID`, its message
  naming the element refused, and the server supplies no time of its own for it.
- The record is event_format.md's record. Both SDKs upload it with its `event_type`, computed from its decision. The
  server computes it again and rejects a record whose `event_type` is not the computed one with
  `EVENT_TYPE_MISMATCH`, naming both; a record with no `event_type` is accepted, and no column stores it (HTL-22 row
  150).
- A record carrying `execution_result` (a result record, event_format.md "The Lifecycle") is stored as any record is,
  its hash checked over every term it carries (Stop A, ruled 2026-11-06), and its result is recorded once (gap row 265,
  ruled 2026-11-11: "every writer of a result shares the action's result-once contract, sync ingest included"). Its
  `execution_result` is checked as the result API checks a body, and one that is not an `execution_result` is
  rejected with `RESULT_INVALID`. The server holds the action, by its org, environment and `action_id`, from its read
  of the action's records until the record's write commits, as the result API holds it (event_format.md "The
  Lifecycle", "One step"), and reads them as that API reads them: a different result recorded for the action rejects
  the record with `RESULT_ALREADY_RECORDED`, the API's own code, and the same result already recorded makes the record
  a duplicate, counted in `duplicates` and stored no second time, so a result uploaded again under another `event_id`
  is safe.
- A record carrying `redaction` has it checked as event_format.md states the member, `{"absent": [<declared path>, …]}`:
  an object whose one member, `absent`, is a non-empty list of paths. One in another form is rejected with
  `REDACTION_INVALID`, never stored in part: each further term the server receives is checked against its form (HTL-23,
  row 191's ingest read as a class).
- A result record carrying `review` (event_format.md, a result whose writer holds no review case; row 217, ruled
  2026-11-07) has it checked against its form, `{"unread": <the decision's resume_token>}`: the member the core
  computes for the record's own decision. One in another form, or on a decision that is not held, is rejected with
  `REVIEW_INVALID`. The server then reads the action's review case as the result API reads it and rejects a result
  record whose case did not let the action run with `RESULT_ON_UNALLOWED_DECISION`, by the one rule both cores hold
  (`result_refusal`'s review read): the store names the review unread, and the service, which holds the case, reads it.
- **A refusal of the record's own content is final** (row 224, ruled 2026-11-08: "a record the service refuses for
  its own content stays in the local store as written, marked refused with the service's code, logged at error,
  and not sent again"). `MISSING_EVENT_ID`, `CONTENT_HASH_MISMATCH`, `TIMESTAMP_INVALID`, `RESULT_INVALID`,
  `REDACTION_INVALID`, `REVIEW_INVALID`, `RESULT_ON_UNALLOWED_DECISION`, `EVENT_TYPE_MISMATCH` and
  `RESULT_ALREADY_RECORDED` refuse a record for what it carries, and the server's answer is final, as it is for a held result
  (event_format.md "The Lifecycle": "a refused result is no record and the service's answer is final"). These codes are one table, `RECORD_REFUSALS` in
  `hiitl.core.lifecycle` and `@hiitl/core`, and the server refuses a record's content under no other code. Each SDK
  keeps the refused record in its local store as written, marks it refused with the code (a mark beside the
  record, as `synced` is; the record's content never changes), logs it at error naming the event, the code and the
  message, and never sends it again; the records behind it upload in the same drain.
- **Every other refusal is retried.** `TENANT_MISMATCH` is the record against the caller's key, and a corrected
  key sends it; `INSERT_FAILED` is the server's own write ("Resend it"); a code the SDK does not know is read
  as retryable, never as final (ontology §4.3: a false final is the dangerous direction). The record stays
  unsynced, it is logged at warning, and the drain stops until the next interval.

**The content hash — one canonical serialisation (Trevor, 2026-10-10).**

`content_hash` is the lowercase hex SHA-256 of the UTF-8 bytes of `{event_id}:{C(envelope)}:{C(decision)}`, then
`:{C(execution_result)}` on a record carrying `execution_result`, then `:{C(redaction)}` on a record carrying
`redaction`, then `:{C(review)}` on a record carrying `review` (Trevor, 2026-11-06, Stop A: "each content member a
record carries beyond its envelope and decision joins the hash as a further term in a fixed order"; `review` by row
217, ruled 2026-11-07). A record carrying none of them hashes over the first three terms alone, so every record
written before 1.5 of event_format.md, and every case in `tests/conformance/audit_hash/`, stands.
- `envelope`, `decision`, `execution_result`, `redaction` and `review` are the record's JSON values exactly as
  uploaded.
- `C` is the JSON Canonicalization Scheme (RFC 8785):
  - object keys are sorted by their UTF-16 code units, with no insignificant whitespace;
  - strings escape only `"`, `\` and control characters (`\b \f \n \r \t`, else `\u00xx` lowercase);
  - numbers take their ECMAScript form (`150.0` → `150`, `1e-7`, `1e+21`).
- One implementation per language, read by every writer and every checker:
  - `hiitl.core.canonical` (Python: `canonical_json`, `audit_content_hash`) and `@hiitl/core` (`canonicalJson`,
    `auditContentHash`);
  - the SDKs' local audit, the server's upload check and the hosted audit write.
- Conformance cases (`tests/conformance/audit_hash/`) hash fixed records to the same digest in both languages: one
  with no further term, one with `execution_result`, one with `redaction`, one with both, and a held result carrying
  all three (`review` is carried only beside `execution_result`).
- A record written before this keeps the hash it was written with.
- Successfully uploaded records are marked as synced in the local audit store. They remain in local storage (for local queries) but are excluded from future sync batches.
- A record refused for its own content is marked refused with the server's code, and is excluded from future sync
  batches and from the audit buffer (§7) in the same way: it remains in local storage, as written.

### Numeric domain

**Admission before `C` (Trevor, 2026-11-14, HTL-43 `d82fe0f5`).** This is one rule for every numeric value
in the supplied JSON tree, including open caller data, policy literals, and nested arrays and objects, not only
members declared as integers. A held number must be finite and have absolute value strictly less than `2**53`
(`9007199254740992`). Both SDKs refuse any number at or beyond that magnitude, including exactly representable
values, however it was written. Python checks an arbitrary-size integer before converting it to a floating-point
value. A declared integer must additionally have no fractional part; booleans and numeric text are not coerced
into numbers.

Fractions use their nearest IEEE 754 binary64 value, without a decimal-digit-count restriction. A fraction too
small for binary64 reads as zero; zero and negative zero are admitted. Overflow and non-finite values are refused.
Each check is on the value the SDK holds: there is no separate original-token reader or different numeric contract
for file input and native calls. The SDK cannot recover precision lost before a native value reached it.

This flat magnitude limit is **hiitl's stricter admission rule, not an RFC 8785 serialization limit**. Above it a
JavaScript Number cannot show whether it is the caller's intended value or a rounding of that value; the two SDKs
must nevertheless accept and refuse the same input. hiitl therefore refuses some numbers that `C` could carry.
RFC 8259 §6 and RFC 7493 §2.2 explain the interoperable integer range; RFC 8785 §3.2.2.3 and Appendix B define
the broader serialization and its refusal of non-finite numbers. Their algorithms are not changed by this rule.

Admission is made where a value is supplied, before a conversion or projection can lose a supplied numeric
value (Trevor, 2026-11-15 UTC, HTL-43). A stored record read back for upload, verification or export is not a
supplied tree and is not admitted again. The SDK's held policy is supplied where it is loaded (its policy file
or the disk cache) or received (a policy pull or a kill-switch tick), and is admitted there; each evaluate reads
the held reading, and neither admits it nor rebuilds it from the stored record again (HTL-43 gap 295, 88579bbd
item 4). Old records upload as written, with their content, hash and integrity
unchanged, and the records behind them upload in the same drain. The service's upload check is verification
under `C` too. Admission and `C` are separate calls: admission where a value is supplied, `C` wherever a hash is
computed or verified. A new record is signed and hashed after its input was admitted, so nothing new enters
there. This creates no local refusal code, final mark or new wire code. The existing `RECORD_REFUSALS` and
retry rules remain unchanged. Hosted evaluation's envelope-exists boundary is owned by
[Error Handling](decision_response.md#error-handling), including its numeric refusal before an envelope exists. An out-of-domain value is refused with its exact instance path
(`<root>` for the root). At a typed numeric member the refusal names its declared numeric type and range,
including this shared domain; its remedy is a number within that declaration, not text. Only a member that
admits text (open `parameters`, `target`, `metadata`, or a policy literal) is directed to pass the value as text
(HTL-43 hand-back, 2026-11-16; supersedes the blanket remedy in `d82fe0f5` item 6).
Text remains text; a policy cannot then compare
it as a number: a reached numeric condition that the rest of the call does not settle stops and blocks
with the existing policy error, as policy_format.md **An operand of the wrong kind** declares.
Numeric declarations elsewhere, including the SDK's integer duration, read this one domain.
For admitted values, `C`, the signed form, content-hash terms and bytes remain as specified above. Existing stored
hashes, signatures and records are not rewritten. This changes admission at the SDK and hosted control point's
decision/audit boundaries (system architecture §2, **proposed**), not the canonicalization algorithm.

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
          "content_hash": { "type": "string", "description": "SHA-256 of C(content), C being §2.1's RFC 8785 (below)" },
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
    },
    "redaction_policy": {
      "type": "object",
      "required": ["manual_redact_fields"],
      "properties": {
        "manual_redact_fields": {
          "type": "array",
          "items": { "type": "string" },
          "description": "The org's declared fields (event_format.md §Redaction); [] when none"
        }
      }
    }
  }
}
```

**Behavior:**
- Server returns `304 Not Modified` if the client's ETag matches the current version.
- **The org's redaction declaration rides the policy channel** (HTL-22 row 163(a), ruled by Trevor 2026-11-05 on HTL-20:
  "the hybrid SDK pulls the org's redaction policy"). The SDK redacts the union of it and its own declaration.
  - `redaction_policy` is sent on every 200, with or without policies; the server writes it.
  - The ETag takes the declaration as a term when the org declares a field: `canonical_hash` of the list, beside the
    policies' versions. A change to the declaration changes the tag, so the next pull is a 200. An org that declares
    nothing keeps the tag it had.
  - The SDK refuses a 200 without the member, or with an entry that is not a declared field (`SyncError` on the
    policy channel, naming `redaction_policy`), and keeps the cache it had. An absent member is never read as
    "nothing declared".
  - The cache keeps it in the policy payload, across restarts. The local audit store reads it at each write and
    redacts every path the SDK's own `redact_fields` or the org's list names.
- SDK verifies `content_hash` for each policy before caching. A policy whose `content_hash` is absent, empty, or not the hash of its `content` is refused alike (HTL-29 row 137; the schema above requires the member, and a check that passes when the hash is absent checks nothing). The download is rejected (`SyncError` on the policy channel), the cache keeps what it had, and `POLICY_INTEGRITY_VIOLATION` is logged at error naming the policy and whether its hash was absent or different.
- **The policy content hash — the same canonical serialisation** (by §2.1: "read by every writer and every checker").
  - A policy's `content_hash` is the lowercase hex SHA-256 of the UTF-8 bytes of `C(content)`, `C` being §2.1's RFC 8785.
  - A route configuration's stored `content_hash` takes the same form over its `config`.
  - One function per language computes it, `canonical_hash` in `hiitl.core.canonical` and `canonicalHash` in `@hiitl/core`.
  - Every writer reads it: the policy and route create paths, onboarding's seed and the repair migration.
  - Every checker reads it: the hosted evaluate's integrity check, both SDKs' download check, and the create path's "same version, other content" test.
  - Each integrity checker refuses a policy with no hash as it refuses one whose hash differs: the hosted evaluate fails closed with `POLICY_INTEGRITY_VIOLATION` (row 137).
  - A conformance case (`tests/conformance/policy_hash/`) hashes a fixed policy whose content the older forms serialise differently (a non-ASCII string, an integral float), to the same digest in both languages.
  - A row written in an older form (sorted keys, compact or spaced) is superseded by the repair migration, as every policy write supersedes: a new active row with the same content and version and the canonical hash, plus a change-audit row (`HASH_FORM`). The old row keeps its content and hash; only its active flag is cleared. A row that verifies under no form is left as it is and counted.
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
  "required": ["kill_switches", "policy_set", "server_time"],
  "properties": {
    "policy_set": {
      "type": ["object", "null"],
      "description": "The version the set is read from, as far as its live switches go: a policy set (policy_format.md) holding the version's name, version, description, scope and on_missing, and its rules that are live switches, each as the version holds it. null when the org has no active version"
    },
    "kill_switches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["rule_name", "active", "scope"],
        "properties": {
          "rule_name": { "type": "string" },
          "active": { "const": true },
          "scope": {
            "type": "object",
            "required": ["environment"],
            "properties": {
              "environment": { "type": "string" }
            }
          },
          "activated_at": { "type": "string", "format": "date-time" },
          "activated_by": { "type": "string" },
          "reason": { "type": "string", "description": "The activation's reason, as the activation recorded it" }
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
- **The set is the switches the org's active version makes live (HTL-29 row 131).** A switch is a `KILL_SWITCH` rule,
  and it is live when the evaluator binds it: in the `active` stage, the one stage that binds, and carrying no
  placeholder, since a rule carrying one "never matches" (policy_format.md "Uncalibrated bounds"). The set holds those,
  and only those, so `active` is always `true`. `scope.environment` names the environment the version is the org's active one in. What a switch
  stops is its rule's `conditions`, read in the version and nowhere else. `activated_at`, `activated_by` and `reason`
  are the activation's own record (the rule's `metadata.kill_switch`), present when it holds them. Before, the set held
  every `KILL_SWITCH` rule with its stage as `active`, a `scope` read from keys a rule's `conditions` does not have, and
  a `reason` read from a key the activation does not write.
- **The tick is the change signal; the version is what evaluates.** A switch's activation and its deactivation are
  each a new policy version (policy_format.md: "A version identifies what evaluates"; "Every rule edit writes a new
  version string: a lifecycle transition (stage, promote, rollback, a kill switch's activation)"). On receipt, the SDK
  compares the version the tick names (`policy_set.version`) with its cached version's. "A version string names one
  policy content per organisation and environment" (policy_format.md), so the version, never the switches' names, says
  whether what the SDK holds is what the service holds: a switch edited under its own name is a new version, and is
  pulled as an activation is (HTL-29 condition 2, 2026-11-10). A tick naming no version (no `policy_set`) differs from
  a cached version, since an unread version is never the same one, and agrees only with a cache that holds none. When
  the two differ, the SDK pulls the policy version in the same tick (§2.2, with its integrity check), and the version
  that lands binds from the next evaluation. One function in each core reads a set's live switches
  (`live_kill_switches` / `liveKillSwitches`): the service builds the set with it, and the SDK names them in its logs.
- **Until that pull lands, the version the tick names decides in its switches' scope (ruled 2026-11-09, HTL-29 row
  240).** A kill switch's activation is a policy version (event_format.md: "A kill switch's activation is a new policy
  version"), and the tick carries the version it read as far as its switches go: `policy_set`, the version's name,
  version, description, scope and `on_missing` and its rules that are live switches, each as the version holds it,
  read through the model. After a tick whose version differs, and until a pull lands after it, the SDK evaluates each
  call against `policy_set` first, in its own mode. Where one of its switches binds, the decision is `KILL_SWITCH`
  under the version the tick names and is recorded with that version; it stands, and the cached version is not read.
  Elsewhere the cached version decides. A switch decides a call when the evaluator names it as the binding rule (the
  decision's `matched_rules`), whatever the decision; a call no rule of `policy_set` binds is the cached version's.
  The list itself still decides nothing: what a switch stops is its rule, in the version.
- **The two readings agree wherever a switch binds.** `KILL_SWITCH` is the first class in precedence (policy_format.md
  "Rule Precedence"), so the switch that binds in `policy_set` is the one that binds in the whole version, and the
  decision, its reason, its rule, its remediation and its version are the version's own. What the SDK does not hold is
  not on the decision: the version's staged observations, its metering rules (`rate_limit_rules`, which count only an
  `ALLOW`) and the fields its other rules would name missing.
- **A switch the call cannot read under `fail_closed` blocks the call (ruled 2026-11-10, HTL-29 condition 2).** Under
  `fail_closed` "an active rule the call cannot read decides `BLOCK` with `MISSING_FIELD`" (policy_format.md), and
  Principle 7: "If a failure mode is ambiguous, default to blocking". Where a switch in `policy_set` cannot be read and
  the version's `on_missing` is `fail_closed`, the decision is `BLOCK` with `MISSING_FIELD` and the remediation naming
  the field, under the version the tick names and recorded with it; it stands, and the cached version is not read. The
  version blocks the call too: every rule that can bind ahead of the unread switch is a switch, which `policy_set`
  holds, or one that decides `BLOCK` (a `BLOCK` rule, or another rule the call cannot read). The decision names what
  the SDK holds, the switch and its field. Where a rule of the version that `policy_set` does not carry binds ahead of
  the switch, the version would name that rule; the SDK, not holding it, names the switch, and the decision is `BLOCK`
  either way. Under `OBSERVE_ALL` every set is read as `skip` (policy_format.md), so the switch binds nothing and the
  cached version decides the call.
- **A pull that lands ends the tick's part.** A new version or a 304 is read after the tick, so the cached version is
  the server's as of the pull, and the tick's version is compared with it again at the next tick. A tick read from the
  disk cache at start has had no pull after it until the first one lands, so a restart keeps a switch it named binding
  (Principle 7: "If a failure mode is ambiguous, default to blocking").
- **The pull is retried at every tick until one lands.** It runs past the policy channel's circuit breaker (§7), and
  its outcome is recorded on that breaker. Each miss is logged at error, naming the version the tick names and its
  switches, and the cached version and its switches.
- A switch deactivated in the tick's version keeps binding by the cached version until the pull lands: the cached
  version holds it, and it decides everywhere `policy_set`'s switches do not bind.
- A switch activated between ticks binds from the first evaluation after the next tick: enforcement is delayed by at
  most one kill-switch interval. For stricter requirements, reduce the interval or use hosted mode.
- Before, the SDK read only the pulled version, and a switch whose pull failed did not bind until a pull landed.

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
| **Priority** | Low; payload defined in [telemetry_schema.md](telemetry_schema.md) |

The telemetry channel uses the same transport infrastructure as other sync channels but its payload schema is defined separately in the telemetry schema specification. The Python SDK sends telemetry on this channel; the TypeScript SDK does not yet.

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
- **One upload contract (Trevor, 2026-10-10):** the server decodes a gzip request body (`Content-Encoding: gzip`)
  before it parses it, on every endpoint. A body it cannot decode is refused with `400 INVALID_BODY_ENCODING`.
  The SDKs send what this section says, and the server accepts exactly that.
- **Maximum upload size: 52428800 bytes, decoded** (50 MB). A batch is drawn from the SDK's audit buffer, so this is
  the buffer's own bound (`max_buffer_size_bytes`, §7), and no batch the SDK can hold is refused. A request body
  whose decoded size passes it is refused with `413 BODY_TOO_LARGE`, and a compressed body is never decoded past it.
  This is the one number the server's decoder reads (Trevor, 2026-10-10).
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
        ├── policies.json.sha256
        ├── policies.etag
        ├── routes.json
        ├── routes.json.sha256
        ├── routes.etag
        ├── kill_switches.json
        └── kill_switches.json.sha256
```

Each `.json` file contains the full response payload from the last successful sync. Each `.etag` file contains the ETag value for conditional requests.

### Integrity

Each `.json` file is written with its `.sha256` sidecar, the lowercase hex SHA-256 of the file's bytes. A warm start reads each file against its sidecar. A file whose sidecar is absent, unreadable, or names another hash is discarded, and `CACHE_INTEGRITY_VIOLATION` is logged at error naming which. The SDK then starts as it would without that file (§5). Absent is refused as a mismatch is (HTL-29 row 137). The sidecar is part of the write: a sidecar the SDK could not write fails the write. The in-memory cache stands, and the next successful sync writes both files.

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
2. **Block initialization** until the first policy download completes, with a configurable timeout (default: 10 seconds). The TypeScript SDK runs this first sync in the background and does not block the constructor.
3. **If initial sync succeeds** — populate cache, start background sync, initialization completes.
4. **If initial sync times out** — fall back to local policy files (`policy_path` if configured). Emit `SYNC_INIT_TIMEOUT` event. Start background sync (will retry).
5. **If no local policies and sync fails** — behaviour follows `cold_start_behavior`: `warn-and-observe` (default) logs a warning and evaluates against an empty policy set, in the client's own mode, with `cache_status: "empty"` until a sync succeeds (under `OBSERVE_ALL` every call comes back `OBSERVE`; under `RESPECT_POLICY` every call is blocked with `NO_MATCHING_RULE`); `observe-silent` does the same at INFO; `fail-closed` raises `ColdStartError` (Python: from the constructor; TypeScript: from the first `evaluate()`).

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
- **Precedence**: Server cache > local policy files > empty (evaluated in the client's mode, or `ColdStartError` under `cold_start_behavior: fail-closed`).

### Audit Records — Client Wins

The client is the authoritative source for audit records.

- Audit records are generated locally and uploaded to the server.
- The server deduplicates by `event_id` within the key's org and environment, and a result record by its action's
  result (§2.1). Uploading the same record multiple times is idempotent.
- The server never pushes audit records to the client.
- If upload fails, records remain in the local buffer and are retried. Records are never dropped: a record the
  server refuses for its own content stays in the local store, marked refused, and is not sent again (§2.1).

### Rate Limits — Merge, Then Server Wins

Rate limit counters require special handling because multiple SDK instances may be incrementing counters independently.

1. Client uploads its local counter snapshots.
2. Server merges counters across all instances (sum of increments since last sync, bounded by window).
3. Server returns the merged state.
4. Client replaces local counters with the server's merged values.

Between syncs, each instance only sees its own increments. This means rate limits may undercount in hybrid mode. For strict cross-instance enforcement, use hosted mode.

### Kill Switches — Server Wins, Through the Version

- A tick naming a version other than the cached one pulls the policy version in that tick (§2.4). The pulled version replaces the cached one, as any policy download does: the server wins.
- Active kill switches take effect immediately on the next evaluation — no waiting for any interval or cache refresh.
  Until the pull lands, the version the tick names decides in its switches' scope (§2.4; HTL-29 row 240, ruled
  2026-11-09).

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

The pull a kill-switch tick makes when the version it names is not the cached one is not skipped by an open policy
breaker: it is retried at every tick until one lands, and its outcome is recorded on that breaker (§2.4).

### Graceful Degradation

When sync fails, all channels degrade to local-only operation:

| Channel | Degraded Behavior |
|---------|-------------------|
| Audit Upload | Records accumulate in local buffer. Retried when connectivity returns. |
| Policy Download | Evaluator uses cached policies, except where the switches of a kill-switch tick no pull has followed bind (§2.4). `CACHE_STALE` event emitted when cache exceeds max stale age. |
| Route Download | Evaluator uses cached routes. Same staleness behavior as policies. |
| Kill Switch Polling | The last tick read stands: until a pull lands after it, its switches bind in their scope under the version it names (§2.4). `CACHE_STALE` event emitted. |
| Rate Limit Sync | Local counters used (may undercount). No warning — this is the expected local behavior. |

### Audit Buffer Management

The local audit buffer is bounded to prevent unbounded memory/disk growth:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_buffer_records` | 10,000 | Maximum records in memory buffer |
| `max_buffer_size_bytes` | 50 MB | Maximum total size of buffered records |

The buffer is the local audit store's unsynced records (SQLite, on disk), less any marked refused (§2.1): a
refused record is not sent again, so it is not waiting. When the unsynced backlog reaches either limit:

1. **`BUFFER_FULL` event emitted** — a warning naming the backlog (records and bytes) and both limits. It is emitted once per crossing: the engine re-arms it when the backlog falls below both limits, so a backlog that stays full is said once, not every tick.
2. **Records are never dropped.** New audit records continue to be written to the local store.
3. **On sync recovery** — the unsynced records upload oldest first.

**The hosted client's buffer** (Stop B (i), ruled 2026-11-06: "the pure-hosted client keeps a local audit buffer for
the records the service could not take, pushed when it answers, as hybrid buffers; a hybrid sync outage stays the sync
engine's `SYNC_CIRCUIT_OPEN`"). A pure-hosted client runs no sync engine. Its store is this same local audit store, at
`audit_db_path`, holding only what the service could not take: an outage decision's record, and a result the result
API could not take (event_format.md "The Lifecycle"). It pushes them itself, before its next call is sent: the records
to `POST /v1/sync/audit` in batches of §9's `audit_batch_size` default, oldest first, then the held results to
`POST /v1/actions/{action_id}/result`, oldest first (decision_response.md "Where the error is answered"). Records are
never dropped. A record the service refuses for its own content is settled as the sync engine settles it (§2.1):
marked refused, logged at error and not sent again.

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
| `POLICY_INTEGRITY_VIOLATION` | Error | A downloaded policy's content hash absent or mismatched |
| `CACHE_INTEGRITY_VIOLATION` | Error | A cached file's `.sha256` sidecar absent, unreadable or mismatched; the file is discarded |
| `CONTENT_HASH_MISMATCH` | Error | Audit record hash verification failed on server |

---

## 8. Security

### Transport Security

All sync traffic must use TLS 1.2 or higher. SDK implementations must not allow disabling TLS for sync channels (even in development — use localhost with self-signed certs if needed).

A `server_url` that is not an `https` URL naming a host, read by its written form as routes.md reads an `endpoint` (Validation Rules), is refused when the client is constructed, naming it, in both SDKs (HTL-29, row 140). The class is every URL that carries the `api_key`: the sync target, the hosted client's `server_url`, the gateway's, and the scanner's `hiitl_url`, which its findings upload sends the key to; the scanner refuses it when its settings are read, as a value it would send the key to. Loopback is no exception, by the sentence above.

A send goes only to the URL its check read: **no sender follows a redirect** (HTL-29 review, condition 1). A redirect names a URL the check did not read, so it is the endpoint's answer, not a hop: each sender reads a 3xx as it reads any answer that is not a success, naming its status, and sends nothing to its `Location`. By the sentence above and the security requirements' "TLS everywhere. No exceptions." The class is every sending boundary, each named here: both SDKs' hosted client, sync client and hybrid route send; the gateway's review client; the scanner's findings upload; and the hosted service's route worker (routes.md, rows 140 and 236) and email provider. The gateway's SSE upstream is the `mcp` library's to send: from `mcp` 1.30 it follows a redirect only within the endpoint's origin, the scheme, host and port the check read, whatever its client's setting, and the gateway requires that version (`mcp` 1.29 follows any).

### Authentication

- Sync uses the same `api_key` as hosted mode, passed as a Bearer token.
- **Every sync channel takes the `evaluate` scope** (Trevor, 2026-11-04). That covers the audit upload, the policy and route downloads, kill switch polling and telemetry (§2), so the agent runtime's own key syncs. An audit upload submits what was evaluated, and a download reads what the in-process evaluator binds. By the security architecture's scopes (§1.5): `evaluate` "can submit envelopes for evaluation, receive decisions", and `admin` "Cannot submit envelopes for evaluation (separation of duties)". A key without `evaluate` (or `full`) is refused with `403`.
- The server validates that the `api_key` is authorized for the claimed `org_id` and `environment`.
- Unauthorized requests receive `401 Unauthorized`. Mismatched org/environment receives `403 Forbidden`.

### Tenant Isolation

- The server enforces that sync requests can only read/write data for the `org_id` associated with the `api_key`.
- Cross-tenant data leakage through sync channels is a critical severity bug.

### Content Integrity

- **Audit records**: Content hash (SHA-256) is computed by the SDK at write time and verified by the server on upload.
- **Policies**: Content hash is computed by the server and verified by the SDK on download. Hash absent or mismatched → policy rejected, `POLICY_INTEGRITY_VIOLATION` emitted (§2.2).
- **Kill switches and routes**: Integrity is implied by TLS transport security. Explicit content hashing may be added in a future version if required.

### Credential Handling

- `api_key` must never be logged, cached to disk, or included in error messages.
- Sync event payloads must not include the `api_key` or any authentication credentials.

---

## 9. Configuration

All sync parameters are configurable via constructor options (`sync_config` in both SDKs), with environment variable overrides; both SDKs read each variable below but one. Rate-limit counter sync is not built (gap row 131), so no setting reads `HIITL_SYNC_RL_INTERVAL`, and, set, it is refused as the paragraph after the table states, naming it.

### Configuration Table

| Parameter | Constructor Option | Environment Variable | Default | Description |
|-----------|-------------------|---------------------|---------|-------------|
| Cache directory | `cache_dir` | `HIITL_CACHE_DIR` | `~/.hiitl/cache/` | Disk cache location |
| Audit sync interval | `audit_sync_interval` | `HIITL_SYNC_AUDIT_INTERVAL` | `30` (seconds) | How often audit records are uploaded |
| Policy sync interval | `policy_sync_interval` | `HIITL_SYNC_POLICY_INTERVAL` | `300` (seconds) | How often policies are refreshed |
| Route sync interval | `route_sync_interval` | `HIITL_SYNC_ROUTE_INTERVAL` | `300` (seconds) | How often routes are refreshed |
| Kill switch poll interval | `kill_switch_poll_interval` | `HIITL_SYNC_KS_INTERVAL` | `30` (seconds) | How often kill switches are polled |
| Rate limit sync interval | `rate_limit_sync_interval` | `HIITL_SYNC_RL_INTERVAL` | none: not read (gap row 131) | Rate-limit counter sync is not built (gap row 131), so no setting reads it. The variable, set, is refused as the paragraph after the table states, naming the names the family's settings read; the constructor option is refused as an undefined option, naming it (row 221, ruled 2026-11-07 as built) |
| Audit batch size | `audit_batch_size` | `HIITL_SYNC_AUDIT_BATCH` | `100` | Max records per audit upload |
| Max buffer records | `max_buffer_records` | `HIITL_SYNC_MAX_BUFFER` | `10000` | Max audit records in memory |
| Max buffer size | `max_buffer_size_bytes` | `HIITL_SYNC_MAX_BUFFER_BYTES` | `52428800` (50 MB) | Max total buffer size |
| Init timeout | `sync_init_timeout` | `HIITL_SYNC_INIT_TIMEOUT` | `10` (seconds) | Cold start sync timeout |
| Circuit breaker threshold | `circuit_breaker_threshold` | `HIITL_SYNC_CB_THRESHOLD` | `5` | Failures before circuit opens |
| Circuit breaker reset | `circuit_breaker_reset` | `HIITL_SYNC_CB_RESET` | `60` (seconds) | Time before half-open probe |
| Max cache stale age | `max_cache_stale_age` | `HIITL_SYNC_MAX_STALE` | `86400` (24 hours) | Max age before `CACHE_STALE` warning |
| Sync request timeout | `sync_timeout` | `HIITL_SYNC_TIMEOUT` | `10` (seconds) | HTTP timeout for each sync request |
| Sync request retries | `sync_max_retries` | `HIITL_SYNC_MAX_RETRIES` | `3` | Retry attempts for a sync request |

A set `HIITL_SYNC_*` variable that no setting reads is refused when the client is constructed
(`ConfigurationError`), naming the variable and the names a setting reads, or, for a name an earlier release read, its
replacement (telemetry_schema.md §5, "Names earlier releases read"). Ruled 2026-11-06 (row 207): "a set `HIITL_*`
variable no setting reads is refused at construction, naming its replacement", by Principle 11 and the ontology's
§4.3. A variable left set from an earlier release is never ignored silently.

Each component refuses the unread names of its own families, and only those (row 222, ruled 2026-11-07): "each
component refuses the unread names of its own families (the gateway `HIITL_MCP_*`, the scanner `HIITL_SCAN_*`) … The
SDK holds no copy of another component's settings (one representation per fact)". The SDK's families are
`HIITL_SYNC_*` and `HIITL_TELEMETRY_*`; the gateway's is `HIITL_MCP_*` (its settings model; its README, "CLI"); the scanner's is
`HIITL_SCAN_*` (its settings models, its spend ceiling among them). One function reads them all (`hiitl.settings.unread_variables`): each component
passes its own families and the names its own settings models read, so the list of names a component reads is its
settings models, and nowhere else. A setting's value that does not parse is refused naming it, never read as another value: the
gateway's log level is a name Python's `logging` defines, and the scanner's ceiling a positive number (a ceiling read as
off lets spend run without a word).

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
| [Telemetry Schema](telemetry_schema.md) | Telemetry channel payload |
