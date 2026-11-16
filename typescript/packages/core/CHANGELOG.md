# Changelog

All notable changes to `@hiitl/core` will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-11-16

<!-- Prepared release date: re-date this entry if publication slips. -->

The evaluator moves from policy format 2.0 to 2.21 and decision response 1.4 to
1.15 (`docs/specs/policy_format.md` and `docs/specs/decision_response.md`,
Version History), decision for decision with the Python evaluator in `hiitl`
0.2.0.

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

- **Typed route metadata refuses explicit null.** The route schema's declared
  metadata members and array items now enforce its null boundary, like the other
  typed route fields. Omission, defaults and arbitrary untyped metadata remain.

- **Parsed route types include defaulted members.** Code constructing a `Route`
  with omitted defaults should describe its authored data as `RouteInput`, then
  pass it through `RouteSchema.parse()` to obtain the parsed `Route`.

- **Validation schemas use Zod 4.** Exported schema types are Zod 4 types;
  consumers composing them with Zod must migrate their own schemas and error
  handling to Zod 4. Read validation details from `ZodError.issues` (the old
  `.errors` alias is gone). Zod's own diagnostic wording can differ; hiitl's
  declared refusal codes, authored guidance and decision contracts stay the same.

- **Node.js 22 or later is required.** Node 18 and 20 leave the supported
  range. Upgrade Node before installing 0.2.0; the TypeScript packages share
  this requirement. CI covers the maintained Node 22, 24 and 26 lines.

### Added

- **`liveKillSwitches(policy)`**: the kill switches a policy version makes
  live, the one reading the sync engine and the hosted service compare a
  tick's switch names with.
- **`httpsRefusal(url, field)`**: why a URL is not one hiitl sends to, or
  `null`.
- **`DecisionTypeSchema` and `SensitivitySchema`** are exported, as the
  sources a route filter's values are read from.
- `CostEstimate` (type) and `PRODUCED_DECISIONS`, the decisions a rule never
  writes, each with what produces it.
- `RECORD_REFUSALS`, the codes under which the hosted service refuses an
  audit record for its own content; its answer is final. `TIMESTAMP_INVALID`
  is one: a record whose `timestamp` is not an RFC 3339 date-time.
  `RESULT_ALREADY_RECORDED` is one: an uploaded result whose action holds a
  different one.
- **`resultConflict(lifecycle, result)`**: `RESULT_ALREADY_RECORDED` when the
  action holds a result other than `result`, or `null`; `resultRefusal`
  reads it, and the hosted service's sync ingest reads the Python core's.
- `ENVELOPE_RENAMED` and `renamedNote(old)`: each envelope field the schema
  renamed, old name to new (`{ tool_name: 'action' }`), and the refusal's
  words for it.

- **DENY wins (2.1)** — `KILL_SWITCH` over `BLOCK` over every other decision,
  then priority, then definition order.
- **Rate limits as rules (2.1, 2.2)** — a `RATE_LIMIT` rule carries its
  `rate_limit` window; `metadata.rate_limits` is compiled to such rules on
  load; rule scope `user_action`. The Decision lists the matching windowed
  rules as `rate_limit_rules` (always an array).
- **Values only a person can set (2.1, 2.5)** — the placeholders
  `{"$uncalibrated": ...}` and `{"$declared": ...}`. A rule carrying one never
  matches until the value is set.
- **Rule lineage and dependencies (2.1, 2.3)** — `tests` shipped with a rule,
  `suggested_by`, `requirement_citation` (a string or a list), and `waits_on`.
- **Richer conditions (2.6)** — a field reference as a condition's value
  (`{"$field": "<path>"}`), the `conforms_to` operator over a parameter
  schema, and `in` / `not_in` with an array on the left as subset tests.
- **Enrichment (2.7)** — `evaluate(envelope, policy, mode, enrichment)` takes a
  sync route's answers, read as `external.<source>.<field>`; a `ROUTE` rule
  whose route has answered does not match again. The Decision carries
  `enrichment`, `routes` and, on `ROUTE`, `route_ref`.
- **New exports** — `Enrichment`, `routing` (the sync-route helpers the SDK
  uses), `RateLimitRule`, `RateLimitWindow`, `Principal` and `PrincipalSchema`,
  `hasPlaceholder`, `PLACEHOLDER_KEY`, `DECLARED_KEY`, `FIELD_REF_KEY`,
  `fieldRef`, `conforms`, `schemaError`, and `canonicalJson` /
  `auditContentHash` (RFC 8785 canonical JSON, identical to the Python SDK's).

### Changed

- **Omitted route fields now read their declared defaults.** The TypeScript core
  applies every default in `docs/specs/routes.md` when the containing object is
  present, matching Python. Optional absent parents stay absent; explicit values
  remain unchanged. Phase 2 fields remain metadata.

- **Licence: Apache-2.0 with NOTICE**, replacing the MIT licence in 0.1.0.
  The package includes the licence and `Copyright 2026 Trevor Foster` notice.

- **A route's `endpoint` must be an `https` URL naming a host**, loopback
  included, and is refused at load, naming it (`httpsRefusal`, the one
  check every sender reads). Its host is read as written, as the Python core
  reads it: a host holding percent-encoding, a label beginning `xn--`, or a
  name ending in a number that is not a dotted-decimal address (`127.1`,
  `0x7f.1`, `2130706433`) is refused.
- **An outbound route sends the record**, and one declaring `context` is
  refused. Its `filters` take their sources' values: `decisions` the
  `DecisionTypeSchema` values, `sensitivity` the `SensitivitySchema` values;
  another value is refused, naming the allowed ones. The filter naming
  actions is `actions`; a route naming `tools` is refused, `FILTER_RENAMED`,
  naming `actions`.
- **`authHeaders` never sends a request without the credential its route
  declares.** `authRefusal(route)` names why the process cannot send it (a
  type other than `bearer_token` or `api_key`, a `secret_ref` that is not
  `env:<NAME>`, an unset or empty variable); `authHeaders` then throws
  `RouteUnanswered` with that reason, and the route's SLA decides. An
  `api_key` auth's header defaults to `Authorization`.
- **Envelope schema 2.0, a major version.** Envelopes are built at `v2.0`
  (`ENVELOPE_SCHEMA_VERSION`, one constant in the core). An envelope of
  another major version is refused, naming the version it carries, the
  version taken and the migration note; there is no acceptance window.
  Migration: set `schema_version` to `v2.0`; drop `policy_refs`; give
  `trace_id` in W3C Trace Context's form, or move another ID to
  `correlation_id`. Records written before are kept as written.
- **A result for a decision held for review, where the writer holds no
  case.** `resultRefusal` takes the review as the writer holds it; a store
  that holds no case passes `UNREAD`, and a held decision (one carrying a
  `resume_token`) is then not refused. `unreadReview(decision)` is the
  record's `review` member, `{"unread": "<resume_token>"}`, and
  `AUDIT_FURTHER` gains `review`, hashed after `redaction`.
- **`PolicySetSchema` refuses two rules of one name**, naming the name.

- **An audit record's content hash covers its result and its redaction.**
  `auditContentHash` joins the record's `execution_result`, then its
  `redaction`, as further terms when the record carries them; a record
  carrying neither hashes as before. The terms are passed by those member
  names, listed in the exported `AUDIT_FURTHER`; another name throws
  `TypeError`.
- **`trace_id` takes W3C Trace Context's form** (envelope schema 1.5):
  `EnvelopeSchema` refuses a `trace_id` other than 32 lowercase hex, naming
  the field. `signature_version` takes only `hmac-sha256-v1`.
- **`resultRefusal` reads the action's review.** A decision held for review
  (one carrying a `resume_token`) takes a result when its review let it
  execute: approved, modified, or timed out under `fail_open`. A denied or
  pending review, or a timeout under `fail_closed`, is
  `RESULT_ON_UNALLOWED_DECISION`.
- **A failure once the envelope exists is a decision.** `errorBlock` answers
  `BLOCK` with `error.code` its cause (`EVALUATION_FAILED`,
  `AUDIT_READ_FAILED`), and `outage` takes the client's `fail_mode`: under
  `FAIL_OPEN` the decision is `allowed` true, its message the warning. The
  reason `RESULT_WRITE_UNAVAILABLE` is gone.
- **No field is ever silently dropped** (envelope schema 1.4, policy format
  2.10, routes 1.3). `EnvelopeSchema` refuses a field the envelope schema does
  not define, naming it; before, it was dropped. `cost_estimate` takes
  `tokens`, `dollars` and `api_calls`, and `tokens` is a number, read as
  written. A rule's `decision` of `OBSERVE`, `SIGNATURE_INVALID` or
  `CONTROL_PLANE_UNAVAILABLE` (the evaluator's and the control point's) is
  refused, naming the rule. A rule's `scope.environments` takes only `dev`,
  `stage` and `prod`. Every route object refuses a field the route schema does
  not define; `metadata` stays open.

- **Every policy schema refuses a field it does not define (2.2)** instead of
  dropping it; the retired rule keys `enabled` and `mode` are refused naming
  `lifecycle_stage`.
- `Decision.staged_observations` is typed as always present (an array,
  possibly empty), matching what the evaluator has always returned.
- Precedence: under DENY wins a matching `BLOCK` beats a higher-priority rule
  of any other decision. 0.1.0 returned the first match by priority, so a
  policy that relied on priority alone can decide differently; re-run its
  tests.

### Removed

- **`policy_refs`** leaves `EnvelopeSchema` with schema 2.0, with its
  deprecation warning. An envelope carrying it is refused as an undefined
  field, naming it.
- **The `tool_name` alias** leaves `EnvelopeSchema` with schema 2.0. An
  envelope carrying `tool_name` is refused as an undefined key; the issue's
  message names `action`, the field it became. `resolveFieldPath` reads a
  path as written at every part, each part a member the object holds as
  data: `parameters.tool_name` is the parameter of that name, and an
  inherited name (`constructor`, `toString`, `__proto__`) is absent, as
  are an array's index and `length` (an array is read whole, by
  `contains` or `in`). `conforms_to`, a rollout's hash field, a
  set-level rate limit's scope and window, and a route's context paths,
  answer fields and `env:` secret read names the same way. No
  call carries `tool_name`, so a condition on it reads an absent field: a
  comparison on it is false, `exists: false` on it matches every call, and
  a `none_of` over it matches unless another of its children does; under
  `fail_closed` the rule blocks with `MISSING_FIELD`. Rewrite each such
  condition to read `action`. Send `action`.

- The package no longer ships `dist/scanner/`. Those files were never
  importable: the package's `exports` map opens only its index.

## [0.1.0] — 2026-05-15

Initial public release of the TypeScript policy evaluator. Mirrors the Python
evaluator in `hiitl` on PyPI; conformance-validated against an 87-case cross-
language test suite.

### Features

- **Deterministic policy evaluation**. Same envelope + policy → same decision,
  always. Side-effect free. Sub-millisecond evaluation for typical policies.
- **Decision types**: ALLOW, BLOCK, PAUSE, SANDBOX, ROUTE, RATE_LIMIT, ESCALATE,
  REQUIRE_APPROVAL, KILL_SWITCH, OBSERVE.
- **Per-rule lifecycle**: `active` (binding), `staged` (observation-only),
  `draft` / `disabled` / `archived` (skipped).
- **Side-by-side staged-rule observations**. Every evaluation returns a
  `staged_observations` array (possibly empty) describing what staged rules
  would have decided — fuel for regression reports during the
  observe → stage → enforce lifecycle.
- **Scope filters**: per-rule whitelist on `agents` / `users` / `environments`,
  plus deterministic SHA-256 percentage rollout with a configurable hash field.
- **Temporal validity**: `valid_from` / `valid_to` windows on rules.
- **Remediation on BLOCK / RATE_LIMIT**: structured guidance returned with
  blocking decisions so calling agents can self-correct.
- **OBSERVE mode**: wrap blocking decisions in OBSERVE so policies can be tested
  against live traffic before enforcement.
- **Atomic conditions**: 14 operators including `equals`, `greater_than`,
  `contains`, `matches` (regex), `exists`, etc.
- **Logical conditions**: `all_of`, `any_of`, `none_of` with short-circuit
  evaluation.

### Architecture

- Pure ESM (`"type": "module"`).
- Zero runtime dependencies beyond `zod` for schema validation.
- 256 tests passing (180 unit + 76 conformance shared with the Python
  evaluator).
- Node 18+ supported (uses `crypto.createHash` and `performance.now`).

### Docs

- Full API documentation lives in source JSDoc comments — published types
  available via `@hiitl/core`.
- Conformance test fixtures shipped separately at
  https://github.com/hiitlhq/hiitl/tree/main/tests/conformance.
