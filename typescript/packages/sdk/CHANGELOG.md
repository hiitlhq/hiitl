# Changelog

All notable changes to `@hiitl/sdk` will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-11-16

<!-- Prepared release date: re-date this entry if publication slips. -->

Requires `@hiitl/core ^0.2.0`: the evaluator moves from policy format 2.0 to
2.21 (see `@hiitl/core`'s changelog), decision for decision with `hiitl` 0.2.0
on PyPI.

### Breaking changes

- **Reserved policy markers refuse malformed forms at load.** `$field`, `$declared` and `$uncalibrated` must be the sole key at a position that reads that form. Sibling keys and unsupported positions are refused; nested values gain no new resolution. Envelope-owned keys remain ordinary data.
- **Numeric remedies follow the member type.** A typed numeric member must be a number in its declared range. Text is a remedy only in open data that admits it.

- **A referenced `conforms_to` schema follows the same closed declaration as a
  literal.** Unsupported keywords or invalid schema member types now stop an
  unsettled reached rule with the existing policy error instead of being ignored.
  A valid schema's ordinary non-conformance remains a non-match.
- **Wrong-kind operands stop an unsettled reached rule with a policy error.**
  Numeric comparisons no longer convert numeric text or booleans. Wrong-kind
  string/set operands no longer silently fail to match, and `not_contains` no
  longer succeeds on a value that is neither string nor array. The SDK answers
  `POLICY_ERROR` / `POLICY_EVALUATION_FAILED`, blocked and recorded; the core
  raises the typed policy-evaluation failure. A decisive sibling condition can
  still settle the tree in either order. Fixed wrong-kind literals are refused
  at load where the operator declares the right-side kind. Absent/null fields
  and declared placeholders are unchanged.
- **JSON equality and membership compare contents.** Object and list comparisons
  that previously failed by object identity can now match: objects compare their
  own keys and values regardless of key order, lists in order. Booleans and
  numbers remain different kinds. The absent/null-field gate and array-left
  subset meaning of `in` are unchanged.
- **A hosted evaluate body outside the numeric domain is refused before an
  envelope exists.** After key and scope checks, it receives the existing located
  422 validation list, not `EVALUATION_FAILED`/500, naming the field and its
  declared type and range, recommending text only where text is admitted.
  Even with a string `action_id`, this refusal leaves no decision or audit record.
- **Declared input types are enforced across envelopes, policies and routes.**
  Omit an optional field instead of supplying null where its type does not name
  null. Correct wrong types instead of relying on boolean or numeric-text
  coercion. Typed metadata, lineage, remediation and sparse rule-test envelopes
  obey their declared child types; free JSON data remains open. Scope percentage
  is an integer 0–100, and a rate-window limit or duration is a positive integer
  (or its declared placeholder). The legacy set-level rate-limit form is a list.
- **All numbers follow one shared admission domain**, including caller data and
  policy literals; see `docs/specs/sync_engine.md#numeric-domain`. A refusal names
  the path and its declared type and range. It recommends text only where text is admitted. Pass large nanosecond timestamps and
  smallest-unit amounts as text. A reached numeric condition on that text stops
  and blocks with `POLICY_ERROR` / `POLICY_EVALUATION_FAILED`, unless the other
  conditions already settle the rule.
  Tiny fractions may read as zero; the canonical form of admitted numbers and
  existing stored hashes/signatures is unchanged.
- **Policy and route YAML use YAML 1.2 Core scalar resolution.** Plain scalars
  such as `yes`, `on` and `1:20` are strings; use explicit JSON-compatible values
  for booleans and numbers, or quote a value to keep it text. Date-time text
  remains text; explicit timestamp tags remain refused.

- **Typed route metadata refuses explicit null at load.** A refusal names the
  member, including nested array items; a null document names the route root.
  Omission, defaults and arbitrary untyped metadata retain their behavior.

- **Route context takes a parsed route with its defaulted members.** When
  constructing data for `resolveEscalationContext`, use `RouteInput` and
  `RouteSchema.parse()` from `@hiitl/core`; `RouteLoader` already parses its files.

- **Validation schemas use Zod 4.** Exported schema types are Zod 4 types;
  consumers composing them with Zod must migrate their own schemas and error
  handling to Zod 4. Read validation details from `ZodError.issues` (the old
  `.errors` alias is gone). Zod's own diagnostic wording can differ; hiitl's
  declared refusal codes, authored guidance and decision contracts stay the same.

- **Node.js 22 or later is required.** Node 18 and 20 leave the supported
  range. Upgrade Node before installing 0.2.0; the TypeScript packages share
  this requirement. CI covers the maintained Node 22, 24 and 26 lines.

### Security

- **The hosted request signature now covers the whole request.** 0.1.0 signed
  `JSON.stringify(body, Object.keys(body).sort())`; a key array passed as the
  replacer filters every nested object to those top-level names, so the
  signature did not cover the contents of `parameters`, `target` or any other
  nested field. The request is now signed over RFC 8785 canonical JSON
  with the envelope's `signature_version: "hmac-sha256-v1"`, identical
  to the Python SDK and the server; no signature-version header is sent. Upgrade if you use hosted mode with a `signature_key`.

### Added

- **`telemetry_level`**, read from `HIITL_TELEMETRY_LEVEL`: `full`,
  `standard` (default), `minimal`, or `off`, the same setting as the Python
  SDK's. This SDK ships no telemetry collector, so it sends no telemetry at
  any level; the value is checked, and another one throws
  `ConfigurationError` naming the four.
- **`correlation_id`**, an `evaluate()` option: your own ID tying an action
  to others, such as a request ID, recorded in the envelope as given.
- **`trace_id` from the active OpenTelemetry span.** When `@opentelemetry/api`
  is installed, the envelope's `trace_id` is the active span's trace ID (32
  lowercase hex). Without the API, or outside a span, it is unset. The API is
  not a dependency.
- **`fail_mode`**, read from `HIITL_FAIL_MODE`: what a hosted outage answers.
  Its decision is `CONTROL_PLANE_UNAVAILABLE`: under `FAIL_CLOSED` (default)
  not allowed; under `FAIL_OPEN`, opt-in, `allowed` true, its message the
  warning that no policy decided it. Another value throws `ConfigurationError`
  naming the two.
- **The hosted client holds what the service could not take.** An outage's
  decision is recorded in the local store (under `redact_fields`) and pushed,
  oldest first, before the next call is sent. A push the service does not
  answer sends nothing further. A record the service refuses for its own
  content is settled as the sync engine settles it (see Changed); one refused
  for any other reason stays held, with a warning. While the circuit breaker
  is open no call is sent, a push included. A store that cannot write the record answers `BLOCK`
  `AUDIT_WRITE_FAILED`, in either fail mode.
- **`recordResult()` during a hosted outage holds the result** and returns it
  marked `held: true`. It is pushed after the held records; one the service
  refuses is removed, with an error logged. A store that cannot hold it throws
  `AuditLogError`.
- **`status()` names the hosted circuit breaker**
  (`circuit_breakers: { hosted: ... }`).
- **The telemetry settings in `sync_config`**, read from `HIITL_TELEMETRY_*`
  (`INTERVAL`, `BUFFER_SIZE`, `SAMPLE_RATE`, `PARAMETER_TOOLS`) and
  range-checked, the same family as the Python SDK's. With no collector, they
  send nothing.

- **Sync-route enrichment** — a rule's sync route is asked (`route_fetch`
  overrides the `fetch` it uses), and the evaluation runs again with the
  route's answer read as `external.<source>.<field>`; a route that does not
  answer fails closed (`ROUTE_UNANSWERED`) unless its SLA says `fail_open`.
  The Decision carries `enrichment`, `routes` and, on `ROUTE`, `route_ref`.
- **Verified principals** — `new HIITL({ principal_verifier: fn })` with
  `evaluate({ ..., principal_token })`: `fn(token)` returns the verified
  `{sub, scope | scopes, iss, aud}`; a rejected token means no principal.
  Hosted mode forwards the token. `evaluate({ ..., requested_scopes })`
  records the scopes a call asks for.

- **`cold_start_behavior` constructor option** (TICKET-121 — mirrors Python TICKET-116).
  Controls what happens when neither disk cache nor a local policy fallback is
  available and the initial sync to the server times out or fails. Three values:
  - `'warn-and-observe'` (default): log a WARNING and evaluate the empty policy
    set in the configured mode: `OBSERVE_ALL` observes; `RESPECT_POLICY` blocks
    with `NO_MATCHING_RULE`. Every Decision carries `cache_status='empty'`
    until background sync succeeds.
  - `'fail-closed'`: `evaluate()` throws `ColdStartError` instead of running against
    an empty policy set. JS constructors can't be async so the throw happens on the
    first `evaluate()` after the initial sync resolves — not on `new HIITL(...)`
    as in Python.
  - `'observe-silent'`: log at INFO instead of WARNING. Opt-in; not recommended
    for new code.
- **`Decision.cache_status`** — `'synced' | 'from_disk' | 'empty' | null`. Stamped
  by the SDK on every Decision returned in local + hybrid modes. Tells the caller
  whether the policy that produced the Decision came from a fresh sync, the on-disk
  cache, or an empty policy set. Hosted-mode Decisions leave this `null` (the server
  is authoritative; the SDK has no cache to describe).
- **`ColdStartError`** — new exception class (subclasses `HIITLError`). Thrown from
  `evaluate()` (not the constructor) on the first call after a failed cold-start
  sync, only when `cold_start_behavior='fail-closed'`.
- **`SyncCache.cacheStatus()`** — new method returning the per-decision cache
  status string. Internal building block for `Decision.cache_status`.
- **`cache_dir` and `sync_init_timeout` constructor options** — explicit knobs for
  hybrid mode's cache directory and initial-sync timeout (default 10s). Previously
  only configurable via the internal `SyncConfig`.

### Changed

- **Loaded routes now read all schema-declared defaults**, matching Python,
  when the containing object is present. Escalation context retains empty labels,
  summaries, fields and present escalation ladders, including defaulted members;
  unset members are absent. Optional absent parents stay absent, and Phase 2
  fields remain metadata.

- **Licence: Apache-2.0 with NOTICE**, replacing the MIT licence in 0.1.0.
  The package includes the licence and `Copyright 2026 Trevor Foster` notice.

- **Hosted evaluation is an explicit opt-in.** In 0.1.0, `api_key` plus
  `server_url` selected hosted mode. Add `evaluation: 'remote'` alongside
  those settings to preserve hosted evaluation. With an API key and the
  default `sync: true`, omitting that opt-in selects hybrid local evaluation
  with background sync; the URL is the sync target. `sync: false` selects
  local evaluation unless remote evaluation was explicitly selected.
- **Unknown constructor options are refused**, naming the option and any
  replacement. Use the declared snake_case names, such as `api_key` and
  `policy_path`; a misspelled or camelCase option that 0.1.0 silently dropped
  now throws `ConfigurationError`.

- **The record names its action `action`**, as the envelope does (record
  format 2.0; `tool_name` before). The local store's column is `action`: a
  store written before renames its `tool_name` column when it opens, and
  each record keeps its value, its hash and its sync mark. A record read
  from the store or uploaded carries `action`. Read `action` where you read
  `tool_name`.
- **hiitl sends only over https, loopback included.** `server_url` must be
  an `https` URL naming a host, in every mode; another value throws
  `ConfigurationError` when the client is constructed, naming it. On your own
  machine, serve https on localhost with a self-signed certificate and trust
  it with `NODE_EXTRA_CA_CERTS`. A route's `endpoint` is held to the same, and
  refused at load. A URL's host is read as written, as the Python SDK reads
  it: a host holding percent-encoding, a label beginning `xn--`, or a name
  ending in a number that is not a dotted-decimal address (`127.1`,
  `0x7f.1`) is refused, naming it.
- **A route whose `auth` the SDK cannot send is refused at load**, naming
  why: a type other than `bearer_token` or `api_key`, a `secret_ref` that is
  not `env:<NAME>`, or a variable unset or empty in this process. A request
  never goes without the credential its route declares. An `api_key` auth's
  header defaults to `Authorization`, as the route schema says.
- **A kill switch binds from the first evaluation after its tick.** The
  kill-switch tick carries `policy_set`, the active version as far as its
  live switches go. When the version the tick names is not the cached one
  (compared by version string, so a switch edited under its own name pulls
  too), the sync engine pulls that version in the same tick, and until a pull
  lands each `evaluate()` is read against the tick's set first: where one of
  its switches binds, the decision is `KILL_SWITCH` under the version the tick
  names, or, under `fail_closed`, `BLOCK` with `MISSING_FIELD` for a switch
  the call cannot be read against; elsewhere the cached version decides. The
  pull is retried at every tick until one lands, and each miss is logged at
  error, naming both versions.
- **Two calls under one new `idempotency_key` give one evaluation and one
  record.** Within one process, a call holds its key in the audit store from
  the dedup read to the record's write, so a second call under that key
  waits and returns the first call's decision. The store is its file,
  whatever name reaches it: a client through a symbolic or a hard link holds
  the keys a client through its path holds. Two processes writing one audit
  file are not held to it.
- **The value-hash key is beside the file the store's name resolves to.** A
  store opened through a symbolic link reads the key beside the file, where
  SQLite keeps its journal, and makes none beside the link. A store opened
  through a file link before this release made its key beside the link; it now
  reads that key, writes it beside the file and leaves it where it was, so a
  value hashes the same across the upgrade. Keys beside two names of one store
  that differ fail the start, naming each file, and none is chosen.
- **`TIMESTAMP_INVALID` is one of `RECORD_REFUSALS`.** The hosted service
  keeps an uploaded record's `timestamp` as its writer gave it and refuses a
  record whose `timestamp` is not an RFC 3339 date-time; the sync engine
  keeps that record as refused.
- **`RESULT_ALREADY_RECORDED` is one of `RECORD_REFUSALS`.** The hosted
  service records an action's result once, whether it was posted to the
  result API or uploaded from a store: an uploaded result the action already
  holds is a duplicate, and a different one is refused, so the sync engine
  keeps that record as refused and never sends it again.
- **A policy with no `content_hash` is refused** at download, as one whose
  hash differs is (`POLICY_INTEGRITY_VIOLATION`). A cached policy file with
  no hash file beside it is discarded, as a mismatched one is.
- **A record the hosted service refuses for its own content is final.** The
  sync engine keeps it in the local store as written, marks it refused with
  the service's code, logs it at error and never sends it again; the records
  behind it upload in the same drain. The codes are `RECORD_REFUSALS` in the
  core. Every other refusal is retried, as before, a code the SDK does not
  know among them. A store written before gains the mark, empty on each
  record it holds; a record it had synced stays synced, and one still to
  send stays to send.
- **Envelope schema 2.0, a major version.** Envelopes are built at `v2.0`
  (`ENVELOPE_SCHEMA_VERSION`, one constant in the core). An envelope of
  another major version is refused, naming the version it carries, the
  version taken and the migration note; there is no acceptance window.
  Migration: set `schema_version` to `v2.0`; drop `policy_refs`; give
  `trace_id` in W3C Trace Context's form, or move another ID to
  `correlation_id`. Records written before are kept as written.
- **A result for a decision held for review is written in the local store.**
  The store holds no review case, so the record names the review it did not
  read, `review: {"unread": "<resume_token>"}`, and its content hash covers
  it. In hybrid mode the service reads the case when the record is uploaded
  and refuses it when the case did not let the action run.
- **`HIITL_SYNC_RL_INTERVAL` is refused when set**, naming the variables a
  setting reads: rate-limit counter sync is not built, so nothing reads it.

- **`recordResult()` writes the result.** The local record's hash covers the
  execution result and its redaction, `verifyIntegrity()` reads both, and the
  upload carries them. The `LifecycleError` reason `RESULT_WRITE_UNAVAILABLE`
  is gone.
- **A failure inside `evaluate()` is a decision.** An unexpected error answers
  `BLOCK` `EVALUATION_FAILED`, and a store that cannot be read for
  deduplication answers `BLOCK` `AUDIT_READ_FAILED`; both are recorded.
  Before, they threw.
- **Every member `DecisionSchema` declares reaches you** from a hosted
  decision, read from the schema, never dropped.
- **A set `HIITL_SYNC_*` or `HIITL_TELEMETRY_*` variable no setting reads is
  refused** at construction with a `ConfigurationError`: a name an earlier
  release read is refused naming its replacement, and any other naming the
  variables its family's settings read. `HIITL_SYNC_RL_INTERVAL` is among
  them until rate-limit counter sync reads it. A variable set to the empty
  string is not read.
- **`timeout` is in seconds**, as in the Python SDK, and so is
  `HIITL_TIMEOUT`: default 5, range 0.1-30.

  A millisecond value set for 0.1.0, such as 5000, is now refused with a
  `ConfigurationError` that says the unit; divide it by 1000.
- **No version header.** A hosted request no longer sends
  `X-Hiitl-Signature-Version`, and the service no longer reads it. The
  signature's version is the envelope's own `signature_version`
  (`hmac-sha256-v1`), which is signed with the envelope and recorded with it.
- **Updated SQLite dependency:** `better-sqlite3` 13.1.1 replaces the ^9.4
  dependency in published 0.1.0. Its declared runtime is Node 22 or later,
  matching the SDK. The record-format migration is described separately above.
- **`CostEstimate` is the envelope's** (`@hiitl/core`'s type): `tokens`,
  `dollars` and `api_calls`. `usd_cents`, which 0.2.0 declared, never reached
  the envelope; it is now refused with `EnvelopeValidationError`, naming it.
  Use `dollars`.
- **A cached policy is read through the model before it is taken.** One the
  model refuses is skipped with a warning naming the field, and the next
  source decides (the policy file), as in the Python SDK.

- **Hybrid mode is now actually wired (TICKET-121).** In 0.1.0, `new HIITL({ api_key: 'sk_...' })`
  without a `policy_path` threw `ConfigurationError("policy_path is required for hybrid mode")`
  because the SyncEngine wasn't connected to the client constructor. As of this
  release, providing an `api_key` enables hybrid mode (the default):
  the client instantiates `SyncCache` + `SyncEngine`, attempts a cold-start sync
  in the background, and starts the periodic tick loop. `policy_path` becomes an
  optional file-based fallback.
- **Hosted mode** forwards every optional envelope field to the server.
- **Rate limits are rules.** The limiter counts the evaluator's windowed
  `RATE_LIMIT` rules (a policy's `metadata.rate_limits` is compiled to such
  rules on load), and an exceeded limit reports the rule's scope and window.
- **SyncEngine concurrency (TICKET-107).** `stop()` no longer runs a final
  audit drain while a timed-out tick is still draining (two drains could
  upload the same records twice), and a tick that fires while the previous
  one is still running is dropped, not queued; `status().tick_skip_count`
  counts them.
- The `X-HIITL-SDK-Version` header is read from the package's own
  `package.json`. 0.1.0 sent a hard-coded `0.1.0`.

### Removed

- **The `tool_name` alias** leaves the envelope with schema 2.0. No call
  carries `tool_name`, so a policy condition on it reads an absent field: a
  comparison on it is false, `exists: false` on it matches every call, and a
  `none_of` over it matches unless another of its children does; under
  `fail_closed` the rule blocks with `MISSING_FIELD`. Rewrite each such
  condition to read `action` before upgrading. The envelope
  `evaluate()` builds carries `action`, as before; one built elsewhere and
  carrying `tool_name` is refused by `@hiitl/core`'s `EnvelopeSchema`, naming
  `action`.

- **The `RateLimitConfig` type export.** It described `metadata.rate_limits`
  entries, which are now compiled to `RATE_LIMIT` rules; type a rule's window
  with `@hiitl/core`'s `RateLimitWindow`.

### Migration notes

- The default `cold_start_behavior` (`'warn-and-observe'`) allows evaluation
  after a cold-start failure, using the local policy fallback when provided.
  Without cache or fallback it evaluates an empty policy set in the configured
  mode: `OBSERVE_ALL` observes; `RESPECT_POLICY` blocks with `NO_MATCHING_RULE`.
  These decisions carry `cache_status='empty'` until background sync succeeds.
- Callers who want the old fail-fast behavior should pass
  `cold_start_behavior: 'fail-closed'`. The error surface moves from constructor to
  first `evaluate()`: it fails when neither cache nor local fallback can supply
  a policy set.
- `Decision.cache_status` is additive; consumers that don't read it are unaffected.

## [0.1.0] — 2026-05-15

Initial public release of the TypeScript SDK. Mirrors the Python SDK
(`hiitl` on PyPI) and is conformance-validated against the cross-language test
suite. Three deployment modes supported — local, hosted, and hybrid — matching
the Python SDK's architecture exactly.

### Features

- **`HIITL` client** with a single `evaluate()` entry point. Sparse envelopes:
  only `action` is required at the call site; everything else is auto-
  generated or defaulted.
- **Local mode** (zero-config). Construct `new HIITL()` with no arguments and
  every action is observed against an empty policy in `OBSERVE_ALL` mode —
  appropriate for development and the first value moment on a new project.
- **Hybrid mode** (Block 5c-5e in this release). Provide an API key and a
  background sync engine starts:
  - Audit records drain to the hosted backend every 30s.
  - Policies, routes, and kill-switch state pull from the backend on
    independent schedules with ETag-conditional GETs.
  - Per-channel circuit breakers protect against repeated failures.
  - SHA-256 integrity verification on cached policies — a content-hash
    mismatch raises `POLICY_INTEGRITY_VIOLATION` and rejects the download.
  - Optional telemetry upload with 10-minute heartbeats.
- **Hosted mode** (legacy). Every evaluate() makes a network call. Available
  for teams that explicitly opt in to zero local state.
- **`SyncCache`** disk-backed memory cache for warm-start across SDK restarts.
  POSIX-atomic disk writes via `tmp` + `rename`, SHA-256 sidecar verified on
  read, CACHE_STALE warning once per channel beyond a configurable age.
- **`AuditLogger`** — SQLite-backed append-only audit log with content
  hashing, queryable by org / action_id / decision type, and a drain surface
  (`getUnsynced` / `markSynced`) consumed by the sync engine.
- **`RateLimiter`** — sliding-window rate limits with scopes
  (`org`, `user`, `tool`, `user:tool`) computed at evaluation time.
- **`PolicyLoader`** + **`RouteLoader`** — JSON / YAML loading with mtime-
  based caching and helpful error messages.
- **`CircuitBreaker`** exposed for advanced wiring (custom transports, test
  instrumentation).

### Architecture

- Pure ESM (`"type": "module"`).
- Runtime deps: `@hiitl/core`, `better-sqlite3`, `js-yaml`, `zod`.
- 255 tests passing across unit + integration + parity-with-Python coverage.
- Node 18+ (uses built-in `fetch`, `AbortController`, `zlib.gzip`).

### Cross-language parity

- 87 conformance fixtures shared with the Python evaluator. All passing.
- `staged_observations` always emitted as an array (never `undefined`),
  matching Python's `List[StagedObservation]` default. Lets cross-language
  consumers iterate without null-checks.
- Byte-equivalent percentage-rollout bucket assignment: SHA-256 of the
  configured hash field → uint32 big-endian → mod 100.
