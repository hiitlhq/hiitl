# Changelog — `hiitl` Python package

All notable changes to the Python SDK + evaluator are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-11-18

<!-- Prepared release date: re-date this entry if publication slips. -->

The first release since 0.1.0. The evaluator moves from policy format 1.3 to
2.21 and decision response 1.4 to 1.15 (`docs/specs/policy_format.md` and
`docs/specs/decision_response.md`, Version History), and the package gains the
MCP proxy. Format 2.0 is a schema break: a 0.1.0 policy whose rules set
`enabled` or `mode` is refused on load until it is migrated (see **Removed**).

### Verification

- Latency targets and durable audit writes are unchanged. Structural checks fail
  every build; timing cells assert p95 only under `HIITL_RELEASE_LATENCY=1` in the
  named release environment and record samples otherwise. The release check
  refuses missing, incomplete, unasserted or over-target evidence for its export
  commit. Shared-runner samples remain artifacts, not a release certificate.

### Breaking changes

- **Policy files load when the client is constructed.** A missing, unreadable or
  unparsable supplied file raises `PolicyLoadError` before an envelope exists,
  as in the TypeScript SDK. One-time file setup is paid at construction rather
  than by the first guarded action. A later file-load failure still returns a
  recorded `POLICY_ERROR` decision.
- **Held policy files follow identity, change metadata and the platform clock.**
  A permission change, replacement or edit that preserves mtime causes a reload.
  A reading made within the same timestamp tick is confirmed by content until
  the platform timestamps distinguish a later rewrite. An unchanged file then
  needs no content read during evaluation. A source whose clock cannot be
  observed remains confirmed by content; its directory need not be writable.
- **One-time admission declarations are prepared at construction.** This includes
  the direct core evaluator, decision/audit shapes and every sync channel's shapes before the first
  background cycle. The call's actual admission remains inside its timing.
  Earlier fresh-process measurements and the hand-back's costs are
  retained in tests/conformance/sdk_startup; they are measurements, not limits.

- **Reserved policy markers refuse malformed forms at load.** `$field`, `$declared` and `$uncalibrated` must be the sole key at a position that reads that form. Sibling keys and unsupported positions are refused; nested values gain no new resolution. Envelope-owned keys remain ordinary data.
- **Numeric remedies follow the member type.** A typed numeric member must be a number in its declared range. Text is a remedy only in open data that admits it.

- **New envelopes preserve supplied date-time text when recording and hashing.**
  Python previously re-spelled lowercase `t`/`z`, zero-offset spellings and
  fractions longer than six digits. Policy comparisons, the recorded envelope,
  and its signed/hash form now retain the supplied text; a signature over that
  text verifies. A native aware `datetime` uses its existing JSON form. Windows,
  clocks and dedup still read instants, and old records retain their text and hashes.
  `Envelope.timestamp` and `Principal.verified_at` now expose string-compatible
  values; use `hiitl.core.date_time.read` when an instant is needed. The SDK's
  generated `+00:00` timestamp therefore keeps that spelling instead of becoming `Z`.
- **A referenced `conforms_to` schema follows the same closed declaration as a
  literal.** Unsupported keywords or invalid schema member types now stop an
  unsettled reached rule with the existing policy error instead of being ignored.
  A valid schema's ordinary non-conformance remains a non-match.
- **`conforms_to` reads declared object models as their supplied JSON members.**
  For example, a `cost_estimate` object can now satisfy its parameter schema where
  Python previously treated the model wrapper as a non-match. Its right side also
  accepts the declared field-reference form instead of rejecting it at load.
  An object with a mistyped child still fails conformance.
- **Wrong-kind operands stop an unsettled reached rule with a policy error.**
  Python no longer treats `in` / `not_in` against a referenced string as substring
  tests, or lets `not_contains` succeed on a value that is neither string nor
  array. Numeric operators also refuse booleans and numeric text. Evaluation
  returns `POLICY_ERROR` / `POLICY_EVALUATION_FAILED`, blocked and recorded;
  a decisive sibling condition can still settle the tree in either order.
  Fixed wrong-kind literals are refused at load where the operator declares the
  right-side kind. Absent/null fields and declared placeholders are unchanged.
- **Input types and nulls are enforced as declared.** Files and mappings that
  previously relied on coercion, undefined members or undeclared null values
  can now be refused, including route metadata. The numeric domain and YAML
  reading also change; see Migration notes for the affected inputs and remedies.
- **JSON equality and membership distinguish booleans from numbers.** A policy
  comparison of `true` with `1` no longer matches. Objects compare by their own
  contents regardless of key order, and lists by ordered values; equality and
  membership use the same comparison. The absent/null-field gate and array-left
  subset meaning of `in` are unchanged.
- **A hosted evaluate body outside the numeric domain is refused before an
  envelope exists.** After key and scope checks, it receives the existing located
  422 validation list, not `EVALUATION_FAILED`/500, naming the field and its
  declared type and range, recommending text only where text is admitted.
  Even with a string `action_id`, this refusal leaves no decision or audit record.

- **The `matches` operator is removed.** A policy naming it is refused at load
  (`PolicyLoadError`) at the condition's `operator`, and the refusal names the
  operators to use in its place: `starts_with` or `ends_with` for a prefix or
  suffix, `contains` for a substring, `in` for a set of values. End an allowlist
  prefix at a boundary (`"https://hooks.slack.com/"`, with its slash), so a host
  that only begins with an allowed one is not admitted. The envelope schema's
  `pattern` checks on hiitl's own identifiers are unchanged.

### Added

- **`ENVELOPE_RENAMED`** in the core: each envelope field the schema renamed,
  old name to new (`{"tool_name": "action"}`), read by the refusal and the
  lint.
- **`correlation_id`**, an `evaluate()` option: your own ID tying an action
  to others, such as a request ID, recorded in the envelope as given.
- **`trace_id` from the active OpenTelemetry span.** When `opentelemetry-api`
  is installed, the envelope's `trace_id` is the active span's trace ID (32
  lowercase hex). Without the API, or outside a span, it is unset. The API is
  not a dependency.
- **`fail_mode`**, read from `HIITL_FAIL_MODE`: what a hosted outage answers.
  Its decision is `CONTROL_PLANE_UNAVAILABLE`: under `FAIL_CLOSED` (default)
  not allowed; under `FAIL_OPEN`, opt-in, `allowed` true, its message the
  warning that no policy decided it. Another value is refused with a
  `ConfigurationError` naming the two.
- **The hosted client holds what the service could not take.** An outage's
  decision is recorded in the local store (under `redact_fields`) and pushed,
  oldest first, before the next call is sent. A push the service does not
  answer sends nothing further. A record the service refuses for its own
  content is settled as the sync engine settles it (see Changed); one refused
  for any other reason stays held, with a warning. While the circuit breaker
  is open no call is sent, a push included. A store that cannot write the record answers `BLOCK`
  `AUDIT_WRITE_FAILED`, in either fail mode.
- **`record_result()` during a hosted outage holds the result** and returns
  `{"action_id", "execution_result", "held": True}`. It is pushed after the
  held records; one the service refuses is removed, with an error logged. A
  store that cannot hold it raises `AuditLogError`.
- **`status()` names the hosted circuit breaker**
  (`circuit_breakers: {"hosted": ...}`).
- **MCP proxy: an upstream's secrets by reference.** An upstream's
  `secret_refs` names a variable of the proxy's own environment as
  `env:<NAME>`: for a stdio upstream, one of its environment variables; for
  an SSE upstream, a header's whole value (`Authorization:
  env:MY_INTERNAL_AUTH`). Each is read when the proxy starts, and an unset one
  stops the start, naming it. A name given both as written (`env`, `headers`)
  and by reference is refused; header names compare in any case.

- **The MCP proxy** — `pip install "hiitl[mcp]"` (needs `mcp>=1.30.0,<2.0.0`)
  installs `hiitl-mcp-proxy`, which re-exposes your MCP servers' tools and
  runs every tool call through `evaluate()` before forwarding it.
  `REQUIRE_APPROVAL` / `PAUSE` / `ESCALATE` open a review case and wait for
  the reviewer when the config names `server_url` and `api_key`; without them
  the call is refused with a message saying so. Recipes in `examples/mcp-proxy/`.
- **Rule lifecycle (format 2.0)** — `lifecycle_stage` (`draft`, `staged`,
  `active`, `disabled`, `archived`). Staged rules never bind; what they would
  have decided is on every Decision as `staged_observations` (always a list).
  Rules also take a `scope` (agents, users, environments, and a deterministic
  percentage rollout) and a `valid_from` / `valid_to` window.
- **DENY wins (2.1)** — `KILL_SWITCH` over `BLOCK` over every other decision,
  then priority, then definition order.
- **Rate limits as rules (2.1, 2.2)** — a `RATE_LIMIT` rule carries its
  `rate_limit` window and meters; `metadata.rate_limits` is compiled to such
  rules on load; rule scope `user_action`. A `RATE_LIMIT` decision reports the
  exceeded rule's scope and window, and `rate_limit_rules` lists the matching
  windowed rules.
- **Values only a person can set (2.1, 2.5)** — the placeholders
  `{"$uncalibrated": ...}` and `{"$declared": ...}`. A rule carrying one never
  matches until the value is set.
- **Rule lineage and dependencies (2.1, 2.3)** — `tests` shipped with a rule,
  `suggested_by`, `requirement_citation` (a string or a list), and `waits_on`,
  a rule's unmet dependency.
- **Richer conditions (2.6)** — a field reference as a condition's value
  (`{"$field": "<path>"}`), the `conforms_to` operator over a parameter
  schema, and `in` / `not_in` with an array on the left as subset tests.
- **Sync-route enrichment (2.7)** — `external.<source>.<field>` reads a sync
  route's declared answer fields. The SDK asks the route (`route_client`, an
  `httpx.Client`) and evaluates again with the answer; a route that does not
  answer fails closed (`ROUTE_UNANSWERED`) unless its SLA says `fail_open`. The
  Decision carries `enrichment`, `routes` (each sync route asked, and how it
  answered) and, on `ROUTE`, `route_ref`.
- **Policy lint** (`hiitl.core.lint`) — runs when a policy loads; findings are
  logged as warnings and never block the load.
- **Canonical audit hash** (`hiitl.core.canonical`) — audit content hashes are
  computed over RFC 8785 canonical JSON, identical in the TypeScript SDK.
- **Verified principals** — `HIITL(principal_verifier=fn)` with
  `evaluate(..., principal_token=...)`: `fn(token)` returns the verified
  `{sub, scope | scopes, iss, aud}`; a rejected token means no principal.
  Hosted mode forwards the token. `evaluate(..., requested_scopes=[...])`
  records the scopes a call asks for.
- **`HIITL(cold_start_behavior=...)`** — hybrid mode's choice when no disk
  cache or local policy fallback is available and the initial sync fails or
  times out (TICKET-116):
  - `"warn-and-observe"` (default) — log a WARNING and evaluate the empty
    policy set in the configured mode: `OBSERVE_ALL` observes;
    `RESPECT_POLICY` blocks with `NO_MATCHING_RULE`. Every `Decision` carries
    `cache_status='empty'` until background sync succeeds.
  - `"fail-closed"` — raise `ColdStartError` from the constructor instead of
    continuing. Use when un-policied evaluation must never run.
  - `"observe-silent"` — the 0.1.0 behaviour (log at INFO only). Opt-in; not
    recommended for new code.
- **`Decision.cache_status`** — `Optional[Literal["synced", "from_disk", "empty"]]`,
  stamped on every Decision in hybrid mode: whether the policy came from a
  fresh sync, the on-disk cache, or an empty policy set. Hosted-mode and
  local-mode Decisions leave it `None`.
- **`ColdStartError`** (subclass of `HIITLError`) — raised from `HIITL(...)`
  when `cold_start_behavior='fail-closed'` and the initial sync fails.
- **`SyncCache.cache_status()`** — the per-decision cache status string behind
  `Decision.cache_status`.
- **Top-level error exports** — `RouteLoadError`, `SyncError` and
  `ColdStartError` are importable from `hiitl`, like every other SDK error.

### Changed

- **An object that is neither condition form is refused at its own path.** `{}`,
  or an object setting two of `all_of`, `any_of` and `none_of`, was already
  refused; the refusal is now located at the condition itself and names "Exactly
  one of all_of, any_of, or none_of must be set", as in TypeScript, in place of
  pydantic's union labels.

- **Explicit null in a route is refused wherever the route schema excludes it.**
  Both loaders name the field, including nested members, array items, typed map
  values and typed metadata children. Omitted optional members and their defaults
  retain their existing behavior; arbitrary untyped metadata can still hold null.

- **Escalation context preserves the route's declared shape.** Empty fields and
  summaries and present escalation ladders survive; unset endpoint, label and
  ladder members are absent. The core and SDK retain schema-declared route
  defaults within present parents, with identical context to TypeScript; optional
  absent parents stay absent and Phase 2 fields remain metadata.

- **Licence: Apache-2.0 with NOTICE**, replacing the MIT licence in 0.1.0.
  The package includes the licence and `Copyright 2026 Trevor Foster` notice.

- **The record names its action `action`**, as the envelope does (record
  format 2.0; `tool_name` before). The local store's column is `action`: a
  store written before renames its `tool_name` column when it opens, and
  each record keeps its value, its hash and its sync mark. A record read
  from the store or uploaded carries `action`. Read `action` where you read
  `tool_name`.
- **hiitl sends only over https, loopback included.** `server_url` must be
  an `https` URL naming a host, in every mode; another value is refused when
  the client is constructed, naming it. On your own machine, serve https on
  localhost with a self-signed certificate and trust it with `SSL_CERT_FILE`.
  The same holds for a route's `endpoint` (refused at load), the MCP proxy's
  `server_url` and its SSE upstream `url`, and the scanner's `hiitl_url`
  (refused at config, and before an upload is sent). A URL's host is read as
  written, as the TypeScript SDK reads it: a host holding percent-encoding, a
  label beginning `xn--`, or a name ending in a number that is not a
  dotted-decimal address (`127.1`, `0x7f.1`) is refused, naming it.
- **A route whose `auth` the SDK cannot send is refused at load**, naming
  why: a type other than `bearer_token` or `api_key`, a `secret_ref` that is
  not `env:<NAME>`, or a variable unset or empty in this process. A request
  never goes without the credential its route declares. An `api_key` auth's
  header defaults to `Authorization`, as the route schema says.
- **An outbound route sends the record**, and one declaring `context` is
  refused at load. Its `filters` take their sources' values: `decisions` the
  decision types, `sensitivity` the envelope's sensitivity values; another
  value is refused at load, naming the allowed ones. The filter naming
  actions is `actions`; `tools` is refused at load, naming `actions`.
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
- **A scenario step names its action `action`** (`hiitl.synthetic`). A step's
  envelope takes the members of `evaluate()` that the envelope carries; any
  other, `tool` included, is refused at load, naming the step and the member.
  A scenario refuses an undefined member at any depth, and `run --all` stops
  on a refused scenario, naming it.
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
  read, `review: {"unread": "<resume_token>"}`, and its content hash covers it
  (`AUDIT_FURTHER` gains `review`). In hybrid mode the service reads the case
  when the record is uploaded and refuses it when the case did not let the
  action run. A decision that is not allowed and holds no `resume_token` is
  still `RESULT_ON_UNALLOWED_DECISION`.
- **A policy set holding two rules of one name is refused**, naming the
  name: a rule's `name` is unique within its set.
- **Each component refuses the unread names of its own settings family**,
  through one function, `hiitl.settings.unread_variables`: the SDK its
  `HIITL_SYNC_*` and `HIITL_TELEMETRY_*` names and the MCP proxy its
  `HIITL_MCP_*` names, each naming the names its settings read. The proxy
  reads `HIITL_MCP_CONFIG` and `HIITL_MCP_LOG_LEVEL` through its settings
  model, and refuses a log level Python's `logging` does not define, where
  it was read as `INFO`.
- **`HIITL_SYNC_RL_INTERVAL` is refused when set**, naming the variables a
  setting reads: rate-limit counter sync is not built, so nothing reads it.

- **`record_result()` writes the result.** The local record's hash covers the
  execution result and its redaction, `verify_integrity()` reads both, and the
  upload carries them: `audit_content_hash` joins a record's
  `execution_result`, then its `redaction`, as further terms when the record
  carries them, and a record carrying neither hashes as before. The terms are
  passed by those member names, listed in `hiitl.core.canonical.AUDIT_FURTHER`;
  another name raises `TypeError`. The `LifecycleError` reason
  `RESULT_WRITE_UNAVAILABLE` is gone.
- **A failure inside `evaluate()` is a decision.** An unexpected error answers
  `BLOCK` `EVALUATION_FAILED`, and a store that cannot be read for
  deduplication answers `BLOCK` `AUDIT_READ_FAILED`; both are recorded.
  Before, they raised.
- **Every member of a hosted decision reaches you**, read from the `Decision`
  model, never dropped.
- **`timeout` takes 0.1 to 30 seconds**, in both modes; another value is
  refused.
- **One telemetry family, `HIITL_TELEMETRY_*`**: `HIITL_TELEMETRY_INTERVAL`,
  `HIITL_TELEMETRY_BUFFER_SIZE`, `HIITL_TELEMETRY_SAMPLE_RATE` and
  `HIITL_TELEMETRY_PARAMETER_TOOLS`, each range-checked. The `HIITL_SYNC_`
  names they had are refused, naming the new one.
- **A set `HIITL_SYNC_*` or `HIITL_TELEMETRY_*` variable no setting reads is
  refused** at construction with a `ConfigurationError`: a name an earlier
  release read is refused naming its replacement, and any other naming the
  variables its family's settings read. `HIITL_SYNC_RL_INTERVAL` is among
  them until rate-limit counter sync reads it. A variable set to the empty
  string is not read.
- **A declared parameter sends its count and no mean.** A field in
  `redact_fields` (or the policy's `redaction_policy`) is read when a value is
  counted and again when the telemetry is sent; no sum is held for it.
- **`pydantic-settings>=2.7.0`** (was `>=2.0.0`).
- **One telemetry setting, the spec's.** The level is now the client's
  `telemetry_level` (`HIITL(telemetry_level="off")`), read from
  `HIITL_TELEMETRY_LEVEL`: `full`, `standard` (default), `minimal`, or `off`,
  which sends nothing. `SyncConfig` no longer takes `telemetry_level`, and its
  `HIITL_SYNC_` variable for the level is refused, naming
  `HIITL_TELEMETRY_LEVEL`.
- **MCP proxy: a reviewer's redacted arguments are filled from the call.** A
  review case records the reviewer's `modified_arguments` with each field your
  org declares as `[REDACTED]`. The proxy forwards the call's own value at each
  such path, with the reviewer's other changes. A marked path the call does not
  hold is an error naming it, and nothing is forwarded.
- **`trace_id` takes W3C Trace Context's form** (envelope schema 1.5):
  `Envelope` refuses a `trace_id` other than 32 lowercase hex, naming the
  field. `signature_version` takes only `hmac-sha256-v1`.
- **No version header.** A hosted request no longer sends
  `X-Hiitl-Signature-Version`, and the service no longer reads it. The
  signature's version is the envelope's own `signature_version`
  (`hmac-sha256-v1`), which is signed with the envelope and recorded with it.
  `hiitl.sdk.http_client` no longer defines `SIGNATURE_VERSION_HEADER` or
  `SIGNATURE_VERSION`.
- **No field is ever silently dropped** (envelope schema 1.4, policy format
  2.10, routes 1.3). `Envelope` refuses a field the envelope schema does not
  define, naming it; before, it was dropped. `CostEstimate` takes `tokens`,
  `dollars` and `api_calls`, and `tokens` is a number, read as written. A
  rule's `decision` of `OBSERVE`, `SIGNATURE_INVALID` or
  `CONTROL_PLANE_UNAVAILABLE` (the evaluator's and the control point's) is
  refused, naming the rule. A rule's `scope.environments` takes only `dev`,
  `stage` and `prod`. Every route model refuses a field the route schema does
  not define; `metadata` stays open.

- **Every policy model refuses a field it does not define (2.2)**, naming the
  field, instead of dropping it.
- **Hosted mode** forwards every optional envelope field, and signs the
  request over RFC 8785 canonical JSON. Its `signature_version` is the
  envelope member `hmac-sha256-v1`, signed with the envelope; no signature
  version header is sent or read.
- The cold-start message when neither cache nor a local policy fallback is
  available is logged at **WARNING** by default (was INFO). It names
  the server URL and the elapsed timeout, and how to switch to
  `cold_start_behavior='fail-closed'`.
- The SDK reports its version (`hiitl.__version__`, the `X-HIITL-SDK-Version`
  header, telemetry, the MCP proxy's server info) from one copy,
  `hiitl/_version.py`, which the build also reads. 0.1.0's headers said 0.1.0
  whatever was installed.

### Removed

- **`hiitl.server` is no longer included in the wheel or source distribution.**
  The hosted service is separate from the public SDK package; no `server`
  extra is provided. Use the SDK or MCP proxy for the customer-side control
  point; the old bundled sample server is not a hosted-service deployment.

- **`policy_refs`** leaves the envelope with schema 2.0, with its deprecation
  warning. An envelope carrying it is refused as an undefined field, naming
  it.
- **The `tool_name` alias** leaves the envelope with schema 2.0. An envelope
  carrying `tool_name` is refused as an undefined field; the error names
  `action`, the field it became. The lint reports a policy condition on
  `tool_name` as `UNDEFINED_FIELD`, an error, naming `action`; a policy
  file with one still loads, with the lint's error logged. No call carries
  `tool_name`, so the condition reads an absent field: a comparison on it
  is false, `exists: false` on it matches every call, and a `none_of` over
  it matches unless another of its children does; under `fail_closed` the
  rule blocks with `MISSING_FIELD`. Rewrite each such condition to read
  `action` before upgrading. A path is read as written at every part, so
  `parameters.tool_name` is the parameter of that name, and each part is
  a field the envelope defines or a key the call carries: a model's
  methods (`model_dump`, `__class__`) and a value's attributes
  (`timestamp.year`) are absent, in a path and as a rollout's hash field.
  Send `action`.

- **The rule keys `enabled` and `mode` (format 2.0)** — refused on load with a
  message naming the replacement. Migrate `enabled: false` to
  `lifecycle_stage: disabled`, `enabled: true` to `lifecycle_stage: active`,
  and a per-rule `mode: observe` to `lifecycle_stage: staged`.
- **The `dev` extra.** The test and lint tools are not a dependency of the
  published package.

### Migration notes

- **Forwarding or storing a Pydantic envelope:** use `env.model_dump(exclude_none=True)` (or `env.model_dump(mode="json", exclude_none=True)` for JSON) before `Envelope.model_validate(...)`. The default dump materializes omitted optional fields as `None`; a supplied null still follows the declared input type.

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
- **Route null migration (HTL-41).** Both route loaders now refuse explicit null
  wherever the route schema does not name null, including typed metadata and
  array items. Omit optional fields; retain null only in declared open data.
- Python's own optional SDK arguments still treat `None` as not given; this does
  not erase null values supplied in a file, body or mapping.

- Policies written for 0.1.0: migrate `enabled` / `mode` as above, then re-run
  the policy's tests. Under DENY wins (2.1) a matching `BLOCK` beats a
  higher-priority rule of any other decision, so a policy that relied on
  priority alone can decide differently.
- The default `cold_start_behavior` (`warn-and-observe`) preserves the
  configured evaluation mode on a cold-start failure. A local policy file is
  used first when provided; without cache or fallback, the empty policy set
  observes under `OBSERVE_ALL` and blocks under `RESPECT_POLICY`. The default
  log level is WARNING and `cache_status` reports the cache state. Callers
  who want INFO logging pass `cold_start_behavior='observe-silent'`.

- **Conditions naming `matches`.** Rewrite each one: a pattern anchored at the
  start becomes `starts_with`, ending the prefix at a boundary such as `/`; one
  anchored at the end becomes `ends_with`; an unanchored literal becomes
  `contains`; an alternation of whole values becomes `in`. A pattern none of them
  expresses is read by the caller and declared in the envelope, for example as a
  boolean parameter the policy reads with `equals`.

## [0.1.0] — 2026-03-15 (initial PyPI publish)

Initial release: the core evaluator, SDK, server and synthetic scenario runner
(`hiitl.core`, `hiitl.sdk`, `hiitl.server`, `hiitl.synthetic`), at policy
format 1.3.
