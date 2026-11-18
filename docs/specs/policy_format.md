# Policy Format Specification

**Version**: 2.23
**Status**: Wave 9 Block 1A Specification
**Last Updated**: 2026-11-17

---

## Purpose

This document defines the policy format for hiitl Execution Control Plane. It is the **source of truth** for how policies are structured, evaluated, and composed.

All policy evaluator implementations (TypeScript, Python, and future languages) must conform to this specification. The conformance test suite validates that all implementations produce identical decisions for identical (envelope, policy) inputs.

An optional field is written by leaving it out; null is a value only where a type names it.

Every number in a policy, including a literal or open metadata value, follows the shared
[numeric domain](sync_engine.md#numeric-domain). Boolean and numeric text are not coerced
to a typed number. The domain is checked on the value held by the SDK; ordinary fractional
rounding is not a separate policy grammar.

---

## Design Principles

1. **Simple for basic rules, expressive for complex policies**
2. **Four-layer design** (designed together, implemented incrementally):
   - Layer 1: Rules (atomic conditions and outcomes)
   - Layer 2: Policy sets (collections of rules with evaluation order)
   - Layer 3: Policy hierarchy (composition across scopes) — interface designed in Phase 1, implemented in Phase 2
   - Layer 4: Signal-aware conditions (rules referencing external signals) — interface designed in Phase 1, implemented in Phase 2

3. **Declarative, not imperative** - JSON (primary), YAML (convenience layer)
4. **JSON is the native format** - Policies are JSON objects. YAML support is a thin parsing layer that converts to JSON.
5. **Versioned and immutable** - Once deployed, a policy version never changes
6. **Deterministic evaluation** - Same (envelope, policy) always produces same decision
7. **Explicit composition rules** - Clear precedence, no "smart" merging
8. **Testable** - Policies are code, treat them as such

### Format Priority

**Primary format: JSON**
- Envelopes are JSON
- Decisions are JSON
- Conformance tests are JSON
- Database stores policies as JSON (JSONB in Postgres)
- Evaluator works on JSON objects internally

**YAML support: Convenience layer**
- YAML is friendlier for humans writing policies by hand
- YAML files are parsed and converted to JSON before evaluation
- YAML loader is a thin layer on top of JSON parsing
- Examples below show both formats, but JSON is authoritative

**One YAML scalar reading (Trevor, HTL-29 `ca60f1ae`, brought forward by HTL-43).** Both SDKs' policy and
route loaders resolve scalars by [YAML 1.2 Core schema §10.3](https://yaml.org/spec/1.2.2/#103-core-schema),
not by their libraries' differing defaults. The declaration's null, boolean, integer and floating-point forms
resolve to those JSON value kinds; an unmatched plain scalar and a quoted scalar remain strings. A date-time
written in YAML remains the string written; an explicit timestamp tag is refused. The shared conformance
table covers each scalar-resolution class through both policy and route loaders. Parsed numeric values then
follow [the shared numeric domain](sync_engine.md#numeric-domain), including its refusal of non-finite values.
This is the same input reading in the customer SDKs and Routes (system architecture §2, **proposed**).

---

## Layer 1: Rules (Phase 1)

A **rule** is the atomic unit of policy. It consists of:
- **Conditions**: When does this rule apply?
- **Decision**: What outcome does it produce?
- **Metadata**: Name, description, reason codes

### Rule Structure (YAML)

```yaml
name: "limit-high-value-payments"
description: "Require approval for payments over $500"
priority: 100
lifecycle_stage: "active"            # active = enforcing; staged = observation-only; see below

conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "parameters.amount"
      operator: "greater_than"
      value: 500

decision: "REQUIRE_APPROVAL"
reason_code: "HIGH_VALUE_PAYMENT"
route: "finance-review"               # References a route artifact (see docs/specs/routes.md)
scope:                                # Optional — applies to all if absent
  environments: ["prod"]
  percentage: 100
metadata:
  sla_hours: 4
  reviewer_role: "finance_approver"
```

### Rule Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique rule identifier within policy set. A set holding two rules of one name does not load: each core model refuses it, naming the name (row 220, ruled 2026-11-07), after a set's `metadata.rate_limits` are compiled to rules, so a compiled rule is held to it too |
| `description` | string | Yes | Human-readable explanation |
| `priority` | integer | Yes | Evaluation order (higher priority = evaluated first); [shared numeric domain](sync_engine.md#numeric-domain) |
| `conditions` | object | Yes | Condition tree (see Condition Syntax below) |
| `decision` | string | Yes | Decision outcome (see Valid Decisions below) |
| `reason_code` | string | Yes | Machine-readable reason for decision |
| `lifecycle_stage` | string | No (default `active`) | One of `draft`, `staged`, `active`, `disabled`, `archived`. See Lifecycle Stages below. |
| `scope` | object | No | Optional whitelist filters and percentage rollout. See Scope below. |
| `valid_from` | string (date-time) | No | RFC 3339 date-time, read as ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar" states. If set, rule is skipped before this time. |
| `valid_to` | string (date-time) | No | RFC 3339 date-time, read as ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar" states. If set, rule is skipped after this time. |
| `observation_window_days` | integer | No (default `7`) | For staged rules: how long the evaluator observes before producing a regression report; [shared numeric domain](sync_engine.md#numeric-domain). |
| `route` | string | No | Name of route configuration for escalation decisions (`REQUIRE_APPROVAL`, `PAUSE`, `ESCALATE`) and for `ROUTE` (a sync route asked for its answer; 2.7). References a separately managed route artifact by name. See `docs/specs/routes.md`. |
| `remediation` | object | No | Structured guidance returned when this rule triggers a BLOCK or RATE_LIMIT. Contains `message`, `suggestion`, `type`, and `details`. See decision_response.md. |
| `metadata` | object | No | Additional data (SLA, reviewer info, etc.) |
| `rate_limit` | object | No | `RATE_LIMIT` rules only: the window the rule meters — `{limit, window_seconds, scope}`. See **Rate-limit rules**. |
| `tests` | array | No | Envelopes the rule ships with and what it must do with each — `[{envelope, expect}]`. Run by the lint. See **Tests shipped with a rule**. |
| `suggested_by` | object | No | Lineage of a rule accepted from a suggestion card — `{suggestion_id, source, atom_id, assessment_id, action_key}`. Written by accept, never by hand. |
| `requirement_citation` | object or array | No | What the rule answers — `{atom_id, standard, regulatory_trigger, determination: {assessment_id, grain, action_id}, prompt: {file, line, quoted}}`; a list of them when one rule answers several determinations (a generated rule folded from identical skeletons). Written by accept. |
| `waits_on` | object | No | What the rule's condition reads that the envelope does not yet carry — `{kind: verifier, target: principal}` (a gate on a verified claim waits on the configured verifier), `{kind: envelope_field, target: <field path>}`, `{kind: route, target: external.<source>.<field>}` (a sync route's answer read by the rule — met when a record of an action the rule binds carries that field in its enrichment context; 2.7, see **Enrichment context**) or `{kind: hiitl_record, target: TICKET-046}` (hiitl's own record as an enrichment source, `external.hiitl.<field>` — the same grammar; nothing writes that source yet, so it is never met). *(2.4's `session` kind was removed in 2.5.)* A rule carrying one is not promoted until the dependency is met (`RULE_DEPENDENCY_UNMET`); see **Tests shipped with a rule** for the other promotion gates. |

### Lineage and dependency field types

These child types are the shared declarations of both SDKs, stated here as ruled in HTL-43
(Trevor, 2026-11-14; HTL-41 `13d5d855`). Requiredness below applies within a present parent:
the optional `suggested_by`, `requirement_citation` and `waits_on` parents may be absent.
Each object in these tables is closed, including `determination` and `prompt`; an undefined
member is refused, naming it, under **No field is dropped** below. Box: the customer's SDKs
and the hosted policy writer, system architecture §2 (**proposed**).

#### Suggested-by fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `suggested_by.suggestion_id` | string | Yes | The accepted suggestion's identifier |
| `suggested_by.source` | string | Yes | The suggestion's source |
| `suggested_by.atom_id` | string | No | The source atom's identifier |
| `suggested_by.assessment_id` | string | No | The source assessment's identifier |
| `suggested_by.action_key` | string | No | The action the suggestion concerns |

#### Requirement-citation fields

`requirement_citation` is one citation object or an array of citation objects. Every array
element has the same closed object type and the same child declarations as a single citation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `requirement_citation.atom_id` | string | No | The cited atom's identifier |
| `requirement_citation.standard` | string | No | The cited standard |
| `requirement_citation.regulatory_trigger` | string | No | The cited regulatory trigger |
| `requirement_citation.determination` | object | No | The determination answered by the rule |
| `requirement_citation.determination.assessment_id` | string | Yes | The determination's assessment |
| `requirement_citation.determination.grain` | string | Yes | The determination's grain |
| `requirement_citation.determination.action_id` | string | No | The determination's action, when it names one |
| `requirement_citation.prompt` | object | No | The prompt passage answered by the rule |
| `requirement_citation.prompt.file` | string | Yes | The prompt's file |
| `requirement_citation.prompt.line` | integer | Yes | The prompt's line; [shared numeric domain](sync_engine.md#numeric-domain) |
| `requirement_citation.prompt.quoted` | string | Yes | The quoted passage |

#### Waits-on fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `waits_on.kind` | string | Yes | One of `verifier`, `envelope_field`, `route`, `hiitl_record` |
| `waits_on.target` | string | Yes | The dependency's target, in the form described in Rule Fields |

> **Block 1A schema break.** The previous `enabled: boolean` and `mode: "observe" | "enforce"` fields are removed. Both are replaced by `lifecycle_stage`. There is no deprecation period — clean break, no users yet.

**No field is dropped** (2026-10-08; R-0864 S2). A rule, a policy set, a condition, a scope, a remediation, a rate-limit
window, a shipped test and the lineage objects carry exactly the fields this spec defines; a loader that meets any
other field refuses the policy with a message naming it. `enabled` and `mode` are refused with their own message:
`enabled: false` is `lifecycle_stage: disabled` (and `enabled: true` is the default, `active`) — refused rather than
ignored, because ignoring `enabled: false` ran disabled rules — kill switches among them — live. Free-form data goes in
`metadata`.

### Lifecycle Stages

Each rule carries a `lifecycle_stage` that controls whether and how it is evaluated. Policy-level batch operations ("stage this policy," "activate this policy") set the stage on every rule; per-rule overrides exist for the advanced path.

| Stage | Behavior |
|-------|----------|
| `draft` | Created but not evaluating. Default for newly generated rules (from suggestions, scanner findings, etc.). |
| `staged` | Evaluating against live traffic in observation mode — records "would have" decisions in the Decision's `staged_observations` (and the audit record) without enforcing. Accumulates regression data for the configurable `observation_window_days`. |
| `active` | Enforcing. The rule's decision is binding. |
| `disabled` | Explicitly turned off. Visible in the UI (you can see what you chose NOT to enforce and why), but the evaluator skips it. |
| `archived` | Was once active, now superseded by a newer version. |

Transitions:
- `draft → staged` (begin observation)
- `staged → active` (promote after regression data confirms readiness)
- `staged → draft` (pull back for redesign)
- `active → disabled` (explicitly turn off)
- `active → archived` (superseded by new version)
- `disabled → draft` (reconsider)
- Any state → `archived` (cleanup)
- Auto-rollback: `active → staged` — demoted on error rate; not `disabled`, so the team can fix the rule rather than recreate it.

**Refinement — an accepted rule is editable** (Trevor, 2026-10-11; `observe_mode_concept_spec.md` "Refinement loop"):
- An edit to a `staged` or `active` rule writes a new policy version. In it the edited rule lands `staged` as a rule of
  its own, beside the unchanged rule it refines. That rule keeps binding.
  - The refinement is named `<name>~r<n>`, with n the next refinement of that rule, and `metadata.refines` names the
    rule it refines.
- The refinement observes, and it needs its own regression report. A report records the body of the rule it read (the
  canonical hash of every field but `lifecycle_stage`), and the promotion gate passes a rule only on a ready report for
  its body as it stands. A report on an earlier body, or one written before reports recorded it, passes nothing
  (HTL-22 row 162).
- Then it is either:
  - **promoted** (`staged → active`): it joins the rule it refines, both bind, and DENY wins; or
  - **merged**: its body replaces the refined rule's, under that rule's name and stage, in a new version, and the
    refinement goes `archived`.
- Through the review surface the edit is a judgment event (T49: a bound it sets is declared).
- No decision changes until a promote or a merge, and every step is a version.

**A set written through the create path** (HTL-20, row 138; `observe_mode_concept_spec.md`: "No policy goes from
recommended to enforced in one step"). `POST /v1/policies` writes a whole set. No rule in it reaches `active` by being
written:

- The set is loaded through the same model the SDKs load it with. A set that does not load is refused with 400
  `POLICY_VALIDATION_ERROR` and the loader's message. A retired `enabled` or `mode` key is one such set, and its message
  names `lifecycle_stage`.
- A rule's **body** is every field but `lifecycle_stage`. A rule written `active` that the current active set does not
  already hold `active` with the same body must pass the promotion gate, the same gate as `staged → active`, which
  includes a ready regression report for its body. If the gate refuses it, it lands `staged`, and the response lists it under `held`
  with the gate's code and message. It is then promoted like any staged rule.
- A rule the current set holds `staged` or `active`, written with a changed body, is an edit to that rule. It is written
  as that rule's refinement (above), beside the unchanged rule, which keeps its stage. The response lists it under
  `refined`. If the current set already holds a refinement of that rule with the same body, that refinement is kept and
  not written again, so writing the same file twice writes the same set.
- Any other rule lands as written: it is new or unchanged, and `draft`, `staged`, `disabled` and `archived` do not bind.
- Rules the current set holds that the written set does not name leave the set: the write replaces it.
- A written set whose content is a stored version's (the same canonical hash) is that version posted again (HTL-22
  row 162; Principle 8, a deployed version is never modified). It is written as stored, each rule at its stored stage,
  and the staging above does not apply. Its change record's `change_type` is `ROLLBACK`; a single rule's rollback stays
  `RULE_ROLLBACK` (R-0850).
- A set that, as it would be written, allows no action (the lint's `ALWAYS_BLOCK`) is refused with 422 `ALWAYS_BLOCK`
  when the current set allowed some, or there is none (H5, "accept never leaves a set that allows nothing", read as
  every write; HTL-22 row 162). The details carry the lint's findings and the rules the gate held `staged`, and nothing
  is written. A current set that already allows nothing is the operator's: the lint reports it, and the write is not
  refused.
- **A first create** (row 201, ruled 2026-11-06: "a first create into an environment with no set carries the
  onboarding default, as accept does, by H5"). A write into an environment with no current set is written with the
  onboarding default after its own rules, as an accept into such an environment is: the default is `ALLOW` at priority
  0 and `active`, so the set allows every action while the gate holds the written rules `staged`, and they observe. A
  written set that already holds a rule with the default's content carries it once. The `ALWAYS_BLOCK` check above
  reads the set as written with the default.
- **The set as it would be written** (row 220, ruled 2026-11-07: "a first create whose rule takes the onboarding
  default's name is refused 422", by "Unique rule identifier within policy set" and row 147's class). The set the write
  would store, with the onboarding default and each refinement (`<name>~r<n>`), is loaded through the same model
  before the `ALWAYS_BLOCK` check. One that does not load is refused with 422 `POLICY_VALIDATION_ERROR` and the
  loader's message, naming the rule, and nothing is written. A written rule that takes the default's name with other
  content is one such set. The code is the loader's in both cases, and the status says which set did not load: 400,
  the set the request carries; 422, the set the write would store, the set `ALWAYS_BLOCK` is read on.
- **Every write loads what it stores** (row 220's class). The one writer of a version, the repository's create, loads
  the set it stores through the same model and refuses one that does not load (422 `POLICY_VALIDATION_ERROR`,
  nothing written), so the create, accept, the lifecycle transitions, a kill switch's activation and the onboarding seed store
  only a set the SDKs load. Accept reads its own refusal first (422 `SUGGESTION_RULE_LINT_ERROR`, its lint loading
  the set the accept would write).
- The onboarding seed and the lifecycle transitions do not use this path. The seed's `observe_all` rule is written
  `active`.

### Scope

Optional per-rule scope filters. All fields optional. Absent = applies to all matching envelopes.

```yaml
scope:
  agents: ["bot-1", "bot-2"]        # whitelist of agent_ids
  users: ["user_123"]                # whitelist of user_ids
  environments: ["stage", "prod"]  # whitelist of the envelope's environment values: dev | stage | prod
  percentage: 10                     # apply to 10% of matching envelopes
  rollout_hash_field: "action_id"    # envelope field used for deterministic hash; default: action_id
```

`environments` takes the envelope's own `environment` values (`dev`, `stage`, `prod`; envelope_schema.json); any other value could never match, so a loader refuses it, naming it (2.10; R-0881).

`scope.percentage` is an optional integer from 0 through 100 inclusive, subject to the
[shared numeric domain](sync_engine.md#numeric-domain). This states the type and bounds
both SDKs already hold (Trevor, HTL-43 `1c1611da`, 2026-11-14); omission still means no
percentage filter. Boolean and numeric text are not an integer.

The percentage check is deterministic: SHA-256 of the configured hash field, truncated to 32 bits, mod 100. Same envelope = same bucket = same decision. If the configured hash field is absent from the envelope (a field the envelope holds as data, as a path's part is:
2.17), the rule is skipped with a logged warning.

### Evaluator Evaluation Order

For each rule (in priority-descending order), the evaluator checks in this order before applying the rule's decision:

1. **Lifecycle stage** — skip unless `lifecycle_stage == "active"`; `staged` rules are evaluated separately and reported in `staged_observations`, never binding.
2. **Temporal validity** — skip if `valid_from` is set and `now < valid_from`, or if `valid_to` is set and `now > valid_to`.
3. **Scope environments** — skip if `scope.environments` is set and the envelope's environment isn't in the list.
4. **Scope agents** — skip if `scope.agents` is set and the envelope's `agent_id` isn't in the list.
5. **Scope users** — skip if `scope.users` is set and the envelope's `user_id` isn't in the list.
6. **Percentage rollout** — skip if `scope.percentage` is set and the deterministic hash bucket ≥ percentage.
7. **Conditions** — evaluate the condition tree. A condition on an envelope path the call does not carry is read by the set's `on_missing` (see **A field the call does not carry** under Evaluation Semantics).
8. **Apply** — the rules that pass 1–7 contend by precedence (see **Rule Precedence — DENY wins** under Evaluation Semantics); the binding rule's `decision` and `reason_code` are returned.

If no rules match, the evaluator returns `BLOCK` with `reason_code: NO_MATCHING_RULE` (safe default).

### Remediation on Rules

The optional `remediation` field on a rule defines the actionable guidance returned to the caller when that rule produces a blocking decision (BLOCK, RATE_LIMIT). Remediation is **only meaningful on blocking rules** — if an ALLOW or SANDBOX rule includes remediation, the evaluator ignores it.

The remediation object has four fields:
- `message` (required) — Human-readable explanation of why the action was blocked
- `suggestion` (required) — Actionable next step for the caller or agent
- `type` (required) — One of: `field_restriction`, `threshold`, `scope`, `rate_limit`, `temporal`, `custom`
- `details` (optional) — Type-specific structured fields. See [decision_response.md](decision_response.md#remediation-types) for the full schema per type.

Example rule with remediation:

```yaml
- name: block-high-value-payments
  description: Block payments over $10,000
  lifecycle_stage: "active"
  priority: 100
  conditions:
    all_of:
      - field: parameters.amount
        operator: greater_than
        value: 10000
  decision: BLOCK
  reason_code: AMOUNT_EXCEEDS_LIMIT
  remediation:
    message: "Payment amount exceeds the $10,000 limit."
    suggestion: "Reduce amount to $10,000 or below, or request approval."
    type: threshold
    details:
      threshold: 10000
      max_allowed: 10000
```

When the evaluator matches this rule, the `remediation` object is copied to the decision response, with the details below computed from the call. The caller (or agent) can read `remediation.message` for a human explanation and `remediation.details` for structured data to self-correct.

**A detail that states a fact of the call is computed from the call** (HTL-20, row 146; R-0059: the agent can "actually
consume and use the policy to refine and proceed with the adjusted tool call"). The author cannot know, when the rule is
written, what a call will carry, so these fields are filled when the decision is made and a remediation never states a
value from another call. Every other field is copied as written.

| Type | Field | Computed as |
|---|---|---|
| `field_restriction` | `blocked_fields` written as `{ref, filter}` | the values at `ref` in the envelope that are in `filter`, in the envelope's order, each once (a single value reads as a list of one; nothing at `ref` gives `[]`). `field_ref` is set to `ref`. A list is copied as written. Any other shape is refused at load, with the shape. |
| `threshold` | `current_value`, when `field` is given | the envelope's value at `field` (absent when the envelope has none there) |
| `temporal` | `current_time` | the envelope's `timestamp` |
| `rate_limit` | `limit`, `current`, `reset_at`, `scope`, `window` | the exceeded window's counter state, filled by the limiter (see **Rate-limit rules**) |

### Rate-limit rules (A3; ruled 2026-10-08, R-0852)

A `RATE_LIMIT` rule carries its window on the rule — one representation, so a card that proposes a limit is one rule:

The numeric `limit` and `window_seconds` members are positive integers, each subject to
the [shared numeric domain](sync_engine.md#numeric-domain), or the typed `$uncalibrated`
placeholder declared below. Both members are required in a present rule window. This
states the shared SDK bounds (Trevor, HTL-43 `1c1611da`, 2026-11-14); the legacy set-level
form still uses its explicitly declared compilation defaults.

```yaml
- name: limit-refunds
  description: At most 20 refunds an hour per agent
  priority: 600
  conditions: {field: action, operator: equals, value: issue_refund}
  decision: RATE_LIMIT
  reason_code: REFUND_RATE
  rate_limit: {limit: 20, window_seconds: 3600, scope: agent}   # scope: action (default) | agent | user | org | user_action
```

Evaluation stays side-effect free. An **active** `RATE_LIMIT` rule with a window that matches **does not bind**: the
evaluator lists it in the decision's `rate_limit_rules`, with its `reason_code` and its `remediation`, and walks on; the
binding decision comes from the other rules. When that decision is `ALLOW`, the post-evaluation limiter (hosted service
and both SDKs) reads each listed rule's window under the key `rule:<name>:<scope key>`, within the call's org and environment (a
`dev` call spends no `prod` counter; HTL-29 row 136), **before it counts any**:

- **One is exceeded:** the decision is `RATE_LIMIT` / `RATE_LIMIT_EXCEEDED`. `matched_rules` names the first exceeded
  rule in listed order, `rate_limit` carries that window's counter state (the rule's scope, its window as
  `<window_seconds>s`), and `remediation` is the rule's own (a `rate_limit` remediation's details are that counter
  state; see **Remediation on Rules**). The call is counted in **no** window: it did not proceed (**Evaluation is
  Side-Effect Free**).
- **None is exceeded:** the call is counted in every window, and the `ALLOW` carries in `rate_limit` the counter state
  of the window with the least headroom left (decision_response.md **Rate Limit Counter State**).

**The read and the count are one step** (HTL-29 row 160; R-0008, "Counters must be atomic and resilient to retries").
Two calls in flight at once under one key are counted as if one came first, so at a window's last slot one is counted
and the other is `RATE_LIMIT`, on any number of service instances. The hosted service takes a transaction-scoped
Postgres advisory lock on each key the call will read (its environment and key), in sorted order and before it reads
any, and holds them until the transaction that writes the call's record ends; a second call under one of those keys
waits, and its read sees the first call's count. The sorted order means no two calls each wait on a key the other holds. The Python
SDK reads and counts under its limiter's lock; TypeScript reads and counts in one synchronous step. The service's SQLite
backend is the single-process test and development double, as for the route job queue (routes.md **Postgres Job
Queue**). It holds each key within its process, by a lock its engine's sessions share, so two calls in flight at once in
its one process are counted as if one came first. Two processes on one SQLite file share no hold (HTL-29 review,
condition 4).

The reason code is `RATE_LIMIT_EXCEEDED` for every windowed rule: one representation, in which `matched_rules` names the
rule (T47), and the rule's own `reason_code` is read in `rate_limit_rules[].reason_code`. A **staged** windowed rule is
observed with `would_be_binding: false` — it meters; it never binds. A `RATE_LIMIT` rule **without** a window is a block
on the calls it matches (the lint reports `RATE_LIMIT_NO_WINDOW`). Scope `user_action` counts per user and action (one
counter for each pair).

**In either mode** (HTL-20, row 132). Under `OBSERVE_ALL` nothing is blocked (ecp_evaluate_spec.md **Observe Mode**:
"Any other decision comes back as `OBSERVE` with `would_be` set to it"). A call past a limit comes back `OBSERVE` with
`would_be: RATE_LIMIT`, the rule in `matched_rules` and the counter state in `rate_limit`, as a kill switch is observed.
The counters count what enforcing would count: a call enforcing would refuse is counted in no window, so each `would_be`
is what enforcing the same calls would have decided. A limiter that fails (it raises, or its store cannot be read) never
lets the call through as an `ALLOW`, because an ambiguous failure blocks (safe by default). The decision is `BLOCK` with
`reason_codes: ["RATE_LIMIT_SERVICE_ERROR"]` and an `error` naming the failure, in the hosted service and both SDKs
alike. Under `OBSERVE_ALL` that block is observed (`would_be: BLOCK`, the `error` kept: the call was not metered).

**One representation: the rule's** (Trevor, T47, 2026-10-08). A set's `metadata.rate_limits` — the earlier set-level
throttle — is **compiled to rules when the set is loaded**, by the policy-set model in every language, so evaluators,
lint and limiters read rules only. Entry *i* becomes the active rule `metadata.rate_limits[i]`: priority 0, condition
`action exists` (every envelope), decision `RATE_LIMIT`, reason code `RATE_LIMIT_EXCEEDED`, and `rate_limit` from the
entry —

| entry | rule |
|---|---|
| `scope: org` (the default) | `scope: org` |
| `scope: agent_id` / `agent` | `scope: agent` |
| `scope: user` / `user_id` | `scope: user` |
| `scope: tool` / `org:tool` | `scope: action` |
| `scope: user:tool` | `scope: user_action` |
| `window_seconds: n`, or `window: second / minute / hour (the default) / day` | `window_seconds: n` / 1 / 60 / 3600 / 86400 |
| `limit: n` (default 1000) | `limit: n` |

— and leaves `metadata`, carried on its rule as `metadata.compiled_from` (`{path, entry}`): nothing is dropped. Any other
key, scope or window name is refused at load with the allowed values. New policies write the rule; the lint reports
`RATE_LIMIT_BOTH_FORMS` on a set that carries both.

### Uncalibrated bounds (C6)

A generated rule whose bound has no record yet — no constant in the code that reaches the action, no observed traffic —
carries a **typed placeholder** where the value would be: `{"$uncalibrated": "<what observation would set it>"}` (in a
condition's `value`, or in a `rate_limit` field). The [reserved value forms](#reserved-policy-values) rule applies. A rule carrying a placeholder **never matches** in either evaluator,
so it can never bind and is never observed (a placeholder cannot be replayed); the lint reports `UNCALIBRATED`; it can
be accepted and staged, and **cannot be promoted** until the bound is set — a changed bound is a new policy version.

### Tests shipped with a rule (C7)

```yaml
tests:
  - envelope: {action: issue_refund, parameters: {amount: 900}}
    expect: BLOCK            # a decision, or NOT_MATCHED
  - envelope: {action: issue_refund, parameters: {amount: 40}}
    expect: NOT_MATCHED
```

Each test is evaluated against the rule alone, as active (required envelope fields are filled with fixed test values).
A failing test is the lint's `TEST_FAILED` (error): the rule cannot be accepted, edited into place or promoted.

### Valid Decisions (Phase 1)

| Decision | Description |
|----------|-------------|
| `ALLOW` | Action is permitted, proceed with execution |
| `OBSERVE` | Action observed but not enforced (produced by evaluator in observe mode, not written in rules). `allowed=true`, `would_be` shows enforce result. |
| `BLOCK` | Action is denied, do not execute |
| `PAUSE` | Action is held for later processing |
| `REQUIRE_APPROVAL` | Action requires human approval before execution |
| `SANDBOX` | Route action to sandbox/non-prod endpoint |
| `RATE_LIMIT` | Action exceeds rate limit, throttle. Produced by the post-evaluation limiter — from a policy set's `metadata.rate_limits` or from a `RATE_LIMIT` rule's window (see **Rate-limit rules**); a `RATE_LIMIT` rule without a window blocks the calls it matches |
| `KILL_SWITCH` | Action blocked by kill switch (hard stop) |
| `ESCALATE` | Action escalated to higher authority |
| `ROUTE` | A sync route was asked and has not answered; its answer, once it re-enters, decides (Enrichment context) |

A rule's `decision` is one of these other than `OBSERVE`. `OBSERVE` is the evaluator's own in observe mode, and the error decisions `SIGNATURE_INVALID`, `CONTROL_PLANE_UNAVAILABLE`, `VALIDATION_ERROR` and `POLICY_ERROR` are the control point's (decision_response.md, Error Decisions); none is written in a rule, and a loader refuses each, naming the rule (2.10; R-0881).

---

## Condition Syntax

Conditions are expressed as nested JSON/YAML trees. They support:
- Field path references (dot notation for nested fields)
- Comparison operators
- Logical operators (AND, OR, NOT)
- Set membership
- String prefix, suffix and substring tests

### Condition Operators

#### Logical Operators

**`all_of`** (AND): All conditions must be true
```yaml
conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "environment"
      operator: "equals"
      value: "prod"
```

**`any_of`** (OR): At least one condition must be true
```yaml
conditions:
  any_of:
    - field: "sensitivity"
      operator: "contains"
      value: "money"
    - field: "sensitivity"
      operator: "contains"
      value: "irreversible"
```

**`none_of`** (NOT): None of the conditions may be true
```yaml
conditions:
  none_of:
    - field: "environment"
      operator: "equals"
      value: "dev"
```

**Exactly one set (HTL-45 `d0640d7a`, gap 322).** A logical condition sets exactly one of `all_of`, `any_of` and `none_of`. An object that sets none of them, such as `{}`, or more than one is neither form of condition. Both loaders refuse it at load at the condition's own path, naming "Exactly one of all_of, any_of, or none_of must be set". Each reads that rule once the object's own members hold, as its model's after-validator does (pydantic's `mode='after'`, zod's `refine`), so an object with a malformed member is refused at that member. Proposed system architecture §2: SDK/ingest (both loaders).

#### Comparison Operators

**JSON-value comparison (Trevor, 2026-11-15 UTC, HTL-43).** Equality compares the
six JSON kinds by their values: null, boolean, number, string, array and object.
Different kinds never equal; in particular, a boolean and a number are different
kinds. Admitted numbers compare by the value held, strings case-sensitively, arrays
by their ordered values, and objects by their own keys and recursively compared
values regardless of key order. Array membership uses this same comparison. One
implementation per language is read by every equality or membership operator.
For a date-time member's comparison value, see ecp_evaluate_spec.md **A date-time
is read by RFC 3339's grammar**, including its native Python case.
This does not change the declared absent/null-field gate, the string-substring
meaning of `contains`, or the array-left subset meaning stated below. Proposed
system architecture §2: SDK decision plane.

| Operator | Types | Description |
|----------|-------|-------------|
| `equals` | all | Exact match by JSON-value comparison above |
| `not_equals` | all | Inverse of JSON-value equality above |
| `greater_than` | number | Numeric > comparison |
| `greater_than_or_equal` | number | Numeric >= comparison |
| `less_than` | number | Numeric < comparison |
| `less_than_or_equal` | number | Numeric <= comparison |
| `contains` | string, array | String substring or array membership by JSON-value comparison above |
| `not_contains` | string, array | Inverse of contains, using the same JSON-value comparison above |
| `starts_with` | string | String prefix match |
| `ends_with` | string | String suffix match |
| `in` | all | Value is in set (right-hand side is array), using JSON-value comparison above |
| `not_in` | all | Inverse of in, using the same JSON-value comparison above |
| `exists` | all | Field exists in envelope (value is true/false) |
| `conforms_to` | object | The field's value conforms to a parameter schema (2.6; see **Parameter schema**) — never a regex |

**`matches` is removed (Trevor, 2026-11-17, HTL-45 `8613a7bc`; R-0173).** A policy naming `matches` is refused at load by the refusal for an operator this table does not have, which names every operator above, among them the operators to use in its place: `starts_with`, `ends_with`, `contains` and `in`.

**A condition carries its `value` (HTL-45 `d0640d7a`, gap 322).** Every operator in the table reads a right-hand side, so an atomic condition's `field`, `operator` and `value` are all required; `exists` takes `true` or `false`. Both loaders refuse a condition without `value` at load at its `value` path, by the refusal for a missing required member that a set without `scope` also gets. A policy is JSON, which has no `undefined`, so in TypeScript a condition whose `value` is set to `undefined` is the same condition as one without it, and is refused the same way. Through 2.22 TypeScript admitted one: its `equals` then never matched and its `not_equals` always did, so a rule with no `value` loaded and never fired, or fired on every call, while Python refused the same policy. A rule that silently never fires is refused at load (gap 287), by Principle 7, "If a failure mode is ambiguous, default to blocking," and by the project's rule, "Both evaluators must produce identical decisions for identical inputs." Proposed system architecture §2: SDK/ingest (both loaders).

**An operand of the wrong kind (Trevor, 2026-11-15, HTL-43 `fc00ed9a`).**
Both operands must fit the kinds the operator declares above, whether read from a
field, a referenced field or a literal. Numbers exclude booleans and numeric text;
string operations take strings; string `contains` / `not_contains` take a string
on the right, while their array form takes any JSON value. Equality keeps the
different-kind comparison declared above. For `conforms_to`, the right operand
must be the **Parameter schema** declared below, including its allowed keywords
and member types: a field reference is compared exactly as a literal would be,
as the reference sentence below declares. A fixed literal of the wrong kind is
refused at policy load where the operator alone declares its right-side kind;
field references and the declared `$declared` / `$uncalibrated` placeholders keep
their existing forms and reading.

At evaluation, a wrong-kind value stops the evaluation only when the rest of the
call does not settle that rule's condition tree. Reach is the existing sentence
under **A field the call does not carry**: a false child settles `all_of`, a true
child settles `any_of` or `none_of`. A mismatch in a tree its other children settle
stops nothing, whichever order the conditions are written in. An unresolved,
reached mismatch answers the existing `POLICY_ERROR` / `POLICY_EVALUATION_FAILED`,
blocked and recorded under decision_response.md **Error Handling**. Its authored
message names the operator and field (and referenced field, where present), not
the supplied value or a caught exception's text. Correct the operand or policy to
use the declared kind. The absent-field reading and null gate are unchanged;
`on_missing` does not read a supplied value of the wrong kind. This follows
Principle 7, "If a failure mode is ambiguous, default to blocking," in the proposed
system architecture §2 SDK decision plane.

**An array on the left of `in` / `not_in`** (2.6): `in` holds when every element of the array is in the set (a
subset); `not_in` when not every element is. A scalar on the left is unchanged.

<a id="reserved-policy-values"></a>

**Reserved value forms (HTL-43, Trevor 2026-11-16, gap 287).** `$field`, `$declared` and
`$uncalibrated` are reserved throughout a policy's values. A marker is its form only as the sole key,
at a position that reads that form. These positions include a set's `metadata.rate_limits[i]` entry
and its declared copy on the compiled rule at `metadata.compiled_from.entry`: both are checked by
the source entry's form rules, including a sole-key `$uncalibrated` in a bound. The exact source
entry stays as provenance; its copy gains no evaluation or resolution. A marker beside another key,
or at any other position, refuses the
policy at load through the loader's existing load refusal. A nested position that does not read a form
does not gain resolution. These keys in a caller's own envelope data remain data, kept and compared.
This supersedes the reserved-form deferral in `1c1611da` item 3 only; computed-filter and outer-wrapper
grammar remain open. It acts at policy admission in the proposed system architecture §2 SDK validation plane.

**A field reference as the value** (2.6): `{"$field": "<path>"}` in place of a literal — resolved against the same
envelope at evaluation (or, for an `external.*` path, the evaluation's enrichment context — 2.7, TICKET-046),
then compared exactly as a literal would be; every operator accepts it where the types fit (`not_in` against an array
the envelope carries, `equals` against a field of the same type, …). A reference that resolves to nothing makes the
condition false, like an absent field (`exists` excepted, which takes no reference). The lint refuses a reference to
a path the envelope cannot address (`UNDEFINED_FIELD`). The path may itself be a placeholder
(`{"$field": {"$declared": "<what field>"}}`) — staff name the field; until then the rule never matches.

**Parameter schema** (2.6): the value of `conforms_to`, a JSON-Schema subset —
`{"type": "object", "properties": {"<name>": {"type": "<string|number|integer|boolean|array|object>"} | {}},
"required": ["<name>", …], "additionalProperties": true|false}`. The value conforms when it is an object, every
`required` name is present, every name it carries is a property (when `additionalProperties` is `false`), and every
property with a `type` has a value of that type. Each name is one the value holds as data, as a path's part is
(2.17). Any other keyword is refused at load. The generator writes the action's
schema from the scan's traced parameters (the per-action parameter schema of spec §9.11 adopt 5: the names, no types,
`additionalProperties: false`, nothing required — the scan cannot tell an optional argument from a required one).


### Field Path Syntax

Use **dot notation** for nested fields:

| Field Path | Envelope Location |
|------------|-------------------|
| `action` | Top-level field |
| `parameters.amount` | Nested: `envelope.parameters.amount` |
| `target.account_id` | Nested: `envelope.target.account_id` |
| `cost_estimate.dollars` | Nested: `envelope.cost_estimate.dollars` |
| `sensitivity` | Array field (use `contains` operator) |
| `external.<source>.<field>` | The enrichment context, not the envelope: a sync route's answer (2.7; see **Enrichment context**) |

A path is read as written, at every part: `parameters.tool_name` is the parameter of that name. Each part names a
member the object holds as data: a field the envelope schema defines, or a key the call carries. A name a language
gives an object besides its data is not a member (`constructor`, `toString` or `__proto__` in TypeScript; a
model's methods such as `model_dump`, `__class__`, or a `datetime`'s `year` in Python), so every evaluator reads it
as absent. An array holds elements, not keys, so an index or `length` is not a part either: an array is read whole,
by `contains` or `in`, as `sensitivity` is. A path whose head the envelope does not define is the lint's `UNDEFINED_FIELD` (an error, so the rule
is not promoted). No call carries it, so a condition on it reads an absent field (**A field the call does not
carry**): under `skip` a comparison on it is false, `exists: false` is true on every call, and a `none_of` over it
matches unless another of its children is true; under `fail_closed` a rule it leaves open decides `BLOCK` with
`MISSING_FIELD`. A head the envelope renamed is refused naming its new name: `tool_name`, renamed `action` at
envelope schema 1.1, has no alias from 2.0 (2.17; gap row 225, ruled 2026-11-08: "a condition on `tool_name` is
refused by the lint, naming `action`"). The lint refuses it at promotion. A set loaded from a file is loaded with
the lint's error logged, so a rule written for 1.x that reads `tool_name` matches other calls from 2.0 until it is
rewritten to read `action`.

### Complex Condition Example

```yaml
name: "require-approval-risky-prod-payments"
description: "Send large or low-confidence production payments for approval"
priority: 200
conditions:
  all_of:
    - field: "environment"
      operator: "equals"
      value: "prod"
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - any_of:
        - field: "parameters.amount"
          operator: "greater_than"
          value: 10000
        - all_of:
            - field: "parameters.amount"
              operator: "greater_than"
              value: 1000
            - field: "confidence"
              operator: "less_than"
              value: 0.8
decision: "REQUIRE_APPROVAL"
reason_code: "RISKY_PAYMENT"
```

**Evaluation**:
- Must be in `prod` environment
- Must be `process_payment` action
- AND (amount > $10,000 OR (amount > $1,000 AND confidence < 0.8))
- → REQUIRE_APPROVAL

---

## Layer 2: Policy Sets (Phase 1)

A **policy set** is a named collection of rules with:
- Version identifier
- Evaluation order
- Scope (org_id, environment)
- Metadata

### Policy Set Structure (YAML)

```yaml
policy_set:
  name: "payments-policy"
  version: "v2.1.0"
  description: "Payment processing controls for production"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "kill-switch-all-payments"
      description: "Stop every payment while an incident is open"
      lifecycle_stage: "disabled"  # Kill switch, disabled by default
      priority: 1000  # Highest priority
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "KILL_SWITCH"
      reason_code: "KILL_SWITCH_ACTIVE"

    - name: "block-payments-from-suspended-agents"
      description: "Refuse payments from agents that are suspended"
      lifecycle_stage: "active"
      priority: 900
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "agent_id"
            operator: "in"
            value: ["agent-123", "agent-456"]  # Suspended agents
      decision: "BLOCK"
      reason_code: "AGENT_SUSPENDED"

    - name: "require-approval-high-value"
      description: "Send payments over $500 to finance for approval"
      lifecycle_stage: "active"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"
      route: "finance-review"  # Routes to route artifact
      metadata:
        sla_hours: 4

    - name: "allow-payments"
      description: "Allow payments that no other rule stops"
      lifecycle_stage: "active"
      priority: 1  # Lowest priority, default allow
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"

  metadata:
    created_at: "2026-02-01T10:00:00Z"
    created_by: "admin@example.com"
    tags: ["payments", "production", "high-stakes"]

    # (Rate limits are windowed RATE_LIMIT rules — see "Rate-limit rules"; a set-level
    #  `rate_limits` list here is compiled to such rules on load.)
```

### Policy Set Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `policy_set.name` | string | Yes | Policy set identifier |
| `policy_set.version` | string | Yes | Semver version (`v{major}.{minor}.{patch}`, with its `v`) |
| `policy_set.description` | string | Yes | Human-readable description |
| `policy_set.scope` | object | Yes | Scope where this policy applies (see **Scope Fields**) |
| `policy_set.rules` | array | Yes | List of rules (evaluated in priority order) |
| `policy_set.on_missing` | string | No | `skip` (default) or `fail_closed`: how a rule reads a field the call does not carry (see **A field the call does not carry**) |
| `policy_set.metadata` | object | No | Additional data (see Policy Metadata below) |

A set missing a required field, or carrying a `version` in another form (`1.0.0`, `v1`, `v0.1.0-dev`), is refused,
naming the field, in both languages (R-0872; HTL-22 row 165). Every set the repository carries is held to this, the
onboarding default, the zero-config set and the conformance sets among them.

**A set stored before this rule** (row 202, ruled 2026-11-06: "a stored set that does not load under row 165's model
is superseded by a migration with a new semver version, never rewritten in place", by "Deployed versions are immutable
- never modified, only superseded"). The migration reads each active stored set that does not load and writes its
successor in the environment: the same rules, a `scope` of the row's own `org_id` and `environment` where it has none,
a `description` where it has none, and the next semver version unused in the environment (`v1.0.0` for a version in
another form, else the next patch). The successor becomes active, the stored row is deactivated and kept unchanged,
and the change is recorded (`change_type` `UPDATE`, `changed_by` `migration:<revision>` as the migrations before it
record, `actor_type` `system`). A set that still does not load once these three are supplied is not superseded; the
migration names it and stops.

### Policy Metadata (Shareability & Presentation)

Policies are first-class product artifacts — shareable, forkable, presentable, and gradable. The metadata section supports this:

```yaml
metadata:
  # Identification
  author: "security-team@example.com"
  created_at: "2026-02-01T10:00:00Z"
  updated_at: "2026-02-14T10:00:00Z"

  # Shareability
  tags: ["payments", "production", "high-stakes", "pci-dss"]
  intended_use_case: "Payment processing controls for production AI agents"
  target_agent_types: ["payment-agent", "billing-agent"]

  # Template lineage
  template:
    source: "hiitl/templates/payments-basic"   # Template this was forked from
    source_version: "v1.0.0"                    # Version of the source template
    customizations: ["added-approval-threshold", "added-rate-limit"]

  # Visual rendering hints
  display:
    sections:
      - name: "Safety Controls"
        rules: ["kill-switch-all-payments", "block-payments-from-suspended-agents"]
        severity: "critical"
      - name: "Approval Workflows"
        rules: ["require-approval-high-value"]
        severity: "warning"
      - name: "Default Behavior"
        rules: ["allow-payments"]
        severity: "info"

  # Ecosystem references (compliance mapping)
  compliance_references:
    - standard: "SOC2"
      control_ids: ["CC6.1", "CC6.3"]
    - standard: "PCI-DSS"
      control_ids: ["6.4.1", "6.4.2"]

  # Grading hooks
  grading:
    expected_coverage: 0.85           # Expected percentage of actions covered
    minimum_grade_threshold: "B"       # Minimum acceptable grade
    test_scenario_refs: ["payments-basic", "payments-edge-cases"]
```

#### Metadata Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata.author` | string | No | Who created/maintains this policy |
| `metadata.created_at` | datetime | No | Creation timestamp |
| `metadata.updated_at` | datetime | No | Last modification timestamp |
| `metadata.tags` | array[string] | No | Categorization tags for search/filter |
| `metadata.intended_use_case` | string | No | Human-readable description of intended use case |
| `metadata.target_agent_types` | array[string] | No | Agent types this policy is designed for |
| `metadata.template` | object | No | Template lineage (if forked from a template) |
| `metadata.template.source` | string | No | Template identifier this was forked from |
| `metadata.template.source_version` | string | No | Version of the source template |
| `metadata.template.customizations` | array[string] | No | What was customized from the template |
| `metadata.display` | object | No | Visual rendering hints for UI presentation |
| `metadata.display.sections` | array[object] | No | Logical groupings of rules with severity |
| `metadata.compliance_references` | array[object] | No | External standard references (SOC2, PCI-DSS, EU AI Act, NIST AI RMF) |
| `metadata.grading` | object | No | Grading configuration for policy testing |

#### Template Semantics

Policy templates are pre-built, forkable policies for common use cases. Templates enable:

- **Onboarding acceleration** — developers start from a proven template, not a blank page
- **Distribution mechanism** — users discover ECP through well-designed templates for their use case
- **Best practices encoding** — templates embody best practices for specific domains

When a policy is forked from a template:
1. The `metadata.template.source` field records the template origin
2. The `metadata.template.source_version` records which version was forked
3. The `metadata.template.customizations` array describes what was changed
4. The forked policy is fully independent — changes to the template do not auto-propagate

#### Visual Rendering Requirements

The policy format must support clean presentation in a UI. The `metadata.display` section provides:

- **Section groupings** — rules organized into logical groups (safety, approvals, rate limits, defaults)
- **Severity indicators** — critical, warning, info levels for visual differentiation
- **Human-readable labels** — all rule names and descriptions must be presentable to non-developers

The UI renders policies attractively using these hints. A policy file should look professional when shared, not like raw config.

---

## Evaluation Semantics

### Rule Precedence — DENY wins (ruled 2026-10-08; R-0846)

Among the active rules that match an envelope (lifecycle, temporal validity, scope, rollout and conditions all pass),
the **binding rule is the first by (class, −priority, definition order)**:

| class | decisions |
|---|---|
| 0 | `KILL_SWITCH` |
| 1 | `BLOCK` |
| 2 | every other decision |

So a matching `KILL_SWITCH` or `BLOCK` binds over any matching rule of another decision **whatever their
priorities**, a kill switch binds over a block, and within a class the higher priority binds, then the rule defined
first. This is forbid-overrides (Cedar's convention; "DENY always wins"). It is **not configurable**; it is a
design invariant. Priority orders rules within a class; it never lifts a rule of another decision above a block.

Staged rules contend the same way for the *would-be* decision: the staged observation flagged
`would_be_binding: true` is the first matching staged rule in the same order, and observations are listed in that
order.

`RATE_LIMIT` is not in the forbid class. A `RATE_LIMIT` rule with a window meters (see **Rate-limit rules**); one
without a window blocks the calls it matches, as class 2.

If no active rule matches: `BLOCK` with `NO_MATCHING_RULE` (default deny).

Priority bands remain a naming convention for authors (kill switches 1000+, blocks 900–999, rate limits 500–899,
scope 400–499, thresholds 100–399, approvals 50–99, allows 1–49); the forbid classes no longer depend on them.

When this was ruled, a regression compared the old order with this one over every policy set in the repository. Of
109 envelope-and-policy pairs, 5 decisions changed, each a conformance case that now pins the new order (`test_007`,
`test_031`, `test_033`, `test_124`, `test_125`). Of 52 policy sets with no envelope, the 18 that load hold no block
ranked below a rule of another decision that could match the same envelope.

### A field the call does not carry (`on_missing`; HTL-22 row 176)

The evaluate spec's Resolved Design Decision 2: "In observe mode: skip the policy, flag it in the audit trail ("policy X
exists but couldn't evaluate — envelope missing field Y"). In enforce mode: each policy has an `on_missing` setting —
`skip` (default) or `fail_closed`." A policy set carries it.

**What a rule cannot read.** A rule reads the envelope paths its condition tree names: each condition's `field`, and a
`{"$field": …}` value's reference. A condition on a path the call does not carry is open, except `exists`, which
reads the absence. `all_of` is settled by a child that is false, `any_of` by a child that is true, and `none_of` by a
child that is true; otherwise an open child leaves its parent open. A rule whose tree is open is one the call cannot
read. One whose tree the call's fields settle is read as it always was: a payment rule
`all_of [action equals process_payment, parameters.amount ≥ 1000]` is false on a `send_email` call that carries no
amount, whichever order its conditions are in. An `external.*` path is the enrichment context, not the envelope, so it
is never counted; a route's `timeout_action` decides its absence (**Enrichment context**).

- **`skip`** (the default): the rule is read as an absent field has always been read (a condition on it is false,
  `exists` excepted), and it is named in the decision's `missing_fields` (decision_response.md). No decision moves. A
  rule that blocks under `none_of` still blocks a call that does not carry the field.
- **`fail_closed`**: an active rule the call cannot read decides `BLOCK` with `MISSING_FIELD` and a `custom`
  remediation naming the fields. It contends by **Rule Precedence** as a `BLOCK` at its own priority and place in the
  definition order: it binds over a matching rule of class 2 whatever its priority, and a matching `KILL_SWITCH`, or a
  matching `BLOCK` of higher priority, binds over it. A windowed `RATE_LIMIT` rule is read the same way.
- **Observe.** Under `OBSERVE_ALL` every set is read as `skip`, and a staged rule is skipped and flagged whatever its
  set says.

A rule the walk does not reach (after the binding rule, outside its validity window, out of scope, or outside its
rollout) is not read and not named. The rule's scope and rollout field are not reads of its condition tree; the rollout
skips a rule whose hash field is absent (**Scope**).

### Evaluation is Side-Effect Free

Policy evaluation **reads state** (counters, config) but **never mutates it**.

- Counter increments happen **after** evaluation produces an ALLOW decision and the action proceeds
- Rate limit checks **read** the current counter value
- The counter increments **on an ALLOW**, not on evaluation (R-0056: rate limits are "applied post-evaluation on ALLOW
  decisions only"). The ALLOW is the last point at which the control point knows the action proceeds: nothing tells it
  the action ran until a result is recorded (the lifecycle's `EXECUTING → SUCCEEDED | FAILED`). *(HTL-20, row 132:
  restated from "on execution".)*
- A call that one window refuses is counted in **none**. The limiter reads every window before it counts any, and counts
  the call in all of them only when none is exceeded (**Rate-limit rules**).

This ensures replay and simulation produce correct results without side effects.

---

## Layer 3: Policy Hierarchy (Interface Design - Phase 1, Implementation - Phase 2)

**Status**: Interface designed in Phase 1 schema, implemented when teams need it.

Policy hierarchy allows composition across scopes:
- **Org defaults** → apply to all agents in org
- **Team/project overrides** → apply to specific teams
- **Agent-specific policies** → apply to individual agents

### Hierarchy Rules (Design)

- More specific scopes can **tighten** constraints (cannot loosen)
- Clear precedence: Agent > Team > Org
- Policy sets at different scopes are **composed**, not replaced
- DENY always wins (even from broader scope)

### Scope Fields (Schema Support)

```yaml
scope:
  org_id: "org_8f3a2c1d9e7b4a60"
  environment: "prod"
  team_id: "team_payments"      # Phase 2
  project_id: "project_checkout" # Phase 2
  agent_id: "payment-agent"      # Phase 2
```

**Phase 1**: Only `org_id` and `environment` are required: `org_id` in the envelope's form (`org_` and 16 or more
letters and digits) and `environment` one of `dev`, `stage`, `prod`. `team_id`, `project_id` and `agent_id` are
accepted and not yet read; any other key is refused, naming it (HTL-22 row 165). The evaluators do not compare a set's
scope with the call: a local file may name the SDK's default org, `org_devlocal0000000000`.

---

## Layer 4: Signal-Aware Conditions (Interface Design - Phase 1, Implementation - Phase 2)

**Status**: Interface designed in Phase 1, full implementation in Phase 2.

Rules can reference **external signal values** pushed into ECP by ecosystem partners.

### Signal Reference Syntax (Design)

```yaml
name: "escalate-on-high-risk-score"
description: "Escalate payments when the CrowdStrike risk score is above 0.8"
priority: 300
conditions:
  all_of:
    - field: "action"
      operator: "equals"
      value: "process_payment"
    - field: "external.crowdstrike.risk_score"
      operator: "greater_than"
      value: 0.8
decision: "ESCALATE"
reason_code: "HIGH_RISK_SIGNAL"
```

**Field path `external.{source}.{signal_name}`**:
- `external.` prefix indicates signal reference
- `{source}` is the signal source system (crowdstrike, datadog, custom, etc.)
- `{signal_name}` is the signal field

### Signal Availability

Signals are:
- Injected via the **signal ingestion API** (Phase 2)
- Scoped to (org_id, environment, optional agent_id/action)
- Time-limited (TTL - signals expire)
- Versioned (signal schema version)

**Phase 1**: Policy schema supports signal references, but signal ingestion API is not implemented. Policies can be written with signal references for future use.

### Enrichment context — a sync route's answer (2.7; TICKET-046 with TICKET-032's sync half)

*Trevor, 2026-10-11 (R-0905): a sync route's answer re-enters as `external.<source>.<field>`, and a ROUTE enforces once
the answer is read. The mechanics below are CC's reading of the route spec, for review.*

- **Where it lives.** A path `external.<source>.<field>` reads the evaluation's **enrichment context**, which the
  evaluator takes beside the envelope, never inside it. The envelope schema has no `external` field, so a caller
  cannot supply one: an answer reaches a rule only from the route that gave it. The submitted envelope, and its hash,
  stay what the caller sent.
- **One source per route.** `<source>` is the route's name. The answer's fields are the fields the route declares
  (`response_schema.required_fields` and `optional_fields`, routes.md); an undeclared field never re-enters. An answer
  that lacks a declared required field is no answer.
- **The order.**
  - The party that evaluates first evaluates the envelope. That is the SDK in local and hybrid mode, and the hosted
    service in hosted mode.
  - When the binding decision is `ROUTE` and its rule's `route` is a sync route (`direction: bidirectional`) that has
    not answered in this evaluation, that party sends the route its `context` and waits for the answer within
    `sla.timeout`.
  - It adds the answer to the enrichment context and evaluates the same envelope again.
  - A `ROUTE` rule whose route has answered (or failed open) in this evaluation does not match again, so each route is
    asked at most once. The last evaluation's decision is the decision.
  - Routes compose by data flow: one rule may read several sources, and an answer may lead to another route.
- **No merge.** Each answer is written under its own route's name, so two answers never write the same field.
- **No answer** (a timeout, an error response, or a missing required field). The route's `sla.timeout_action`
  decides:
  - `fail_closed` (the default): the decision stays `ROUTE`, not allowed, with reason code `ROUTE_UNANSWERED`.
    `escalate` and `extend` read as `fail_closed` until escalation ladders are built (Door B).
  - `fail_open`: the route counts as answered with no fields. The envelope is evaluated again, and every other rule
    still binds.
- **An absent field**: a condition on it is false (`exists = false` excepted), under either `on_missing`. It is the
  enrichment context, not the envelope (**A field the call does not carry**).
- **Recorded.** The decision carries `enrichment` (the context the last evaluation read) and `routes` (each route
  asked, with its rule and whether it answered; decision_response.md). A record of the action shows which external
  decision it read.
- **hiitl's own record** (`external.hiitl.*`, kind `hiitl_record`) uses the same grammar. Nothing writes that source
  yet, so a rule reading it is not promotable.

---

## Policy Versioning & Immutability

### Version Requirements

- All policy sets carry a **version identifier** (semver: `v{major}.{minor}.{patch}`)
- **Deployed versions are immutable** - never modified, only superseded
- **Rollback = activating a previous version**, not editing current version
- Breaking changes require major version bump + migration guide
- **A version identifies what evaluates** (Trevor, 2026-10-10; Model A of the 2026-05-13 rule-versioning design
  call: editing any rule produces a new, immutable, append-only version, and audit events reference it):
  - Every rule edit writes a new version string: a lifecycle transition (stage, promote, rollback, a kill switch's
    activation), an accepted suggestion, or an edit.
  - The server assigns the next unused string by bumping the patch number (`v1.0.3` → `v1.0.4`). The bump keeps
    semver: a version in another form is refused, naming it, never extended (HTL-22 row 165).
  - A version string names one policy content per organisation and environment, so a decision's `policy_version`
    resolves the policy alone.
  - A write that reuses a version string with different content is given the next unused string **[CC]**. The write
    is never refused, and the stored set and the decision both carry the string it was given.

### Backward Compatibility

- **New optional fields** can be added (minor version bump)
- **Existing fields cannot be removed** (major version bump required)
- **Field types cannot change** (major version bump required)
- **Evaluation semantics changes** require major version bump

### How a policy applies (Trevor, 2026-10-10)

Policies are centrally managed, and each applies by its conditions over the envelope's fields. The envelope never names
the policies that apply. `policy_refs` was read by nothing: deprecated in `envelope_schema.json` v1.3, it is removed
at 2.0 (2026-11-07, row 223), and an envelope carrying it is refused as a field the schema does not define, naming it.

### Policy Version in Decisions

Every decision includes the **policy version(s)** used in evaluation. This enables:
- Replay against historical policy version
- Debugging (know exactly what policy applied)
- Audit trail (what policy was in effect when action was evaluated)

---

## Storage

### Local Mode
- Policies loaded from **YAML/JSON files on disk**
- File path: `policies/{org_id}/{environment}/{policy_set_name}.yaml`
- Version = filename or embedded version field

### Hosted Mode
- Policies stored in **database** (PostgreSQL)
- Managed via **API** (CRUD operations)
- Immutable versioning (new version = new row, old row never updated)
- Active version tracked separately (can be changed to activate different version)

**"Policy is code"** means versioned, testable, and reviewable — database-backed versioning with API management achieves this.

---

## Policy Testing & Validation

### Validation Requirements

Before deploying a policy:

1. **Syntax validation**: YAML/JSON is well-formed
2. **Schema validation**: All required fields present, types correct
3. **Condition validation**: Field paths are valid, operators supported
4. **Decision validation**: Decision type is valid enum value
5. **Priority validation**: No duplicate priorities within policy set
6. **Replay simulation**: Test policy against recent traffic (dry-run)

### Policy Testing

Policies are code. Test them:

- **Unit tests**: Given envelope, assert expected decision
- **Integration tests**: Full policy set evaluation
- **Conformance tests**: Language-neutral test suite
- **Replay tests**: Historical envelopes against new policy version

---

## Policy Format Examples

### Example 1: Simple Allow/Deny

```yaml
policy_set:
  name: "dev-environment-policy"
  version: "v1.0.0"
  description: "Simple Allow/Deny"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"

  rules:
    - name: "allow-all-in-dev"
      description: "Allow every action in dev"
      lifecycle_stage: "active"
      priority: 1
      conditions:
        all_of:
          - field: "environment"
            operator: "equals"
            value: "dev"
      decision: "ALLOW"
      reason_code: "DEV_ENVIRONMENT"
```

### Example 2: Rate Limiting

A rate limit is a windowed `RATE_LIMIT` rule (see **Rate-limit rules**); it is counted post-evaluation, on ALLOW
decisions only (evaluation is side-effect free).

```yaml
policy_set:
  name: "email-policy"
  version: "v1.0.0"
  description: "Rate Limiting"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "allow-emails"
      description: "Allow email sending"
      lifecycle_stage: "active"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"

    - name: "emails-per-user-hour"
      description: "At most 50 emails an hour per user"
      lifecycle_stage: "active"
      priority: 0
      conditions: {field: "action", operator: "equals", value: "send_email"}
      decision: "RATE_LIMIT"
      reason_code: "EMAIL_RATE"
      rate_limit: {limit: 50, window_seconds: 3600, scope: "user"}
```

When the rate limit is exceeded, the caller receives a `RATE_LIMIT` decision naming the rule in `matched_rules`, with
`rate_limit` carrying `scope`, `window`, `limit`, `current`, and `reset_at`. Several windowed rules may match one call
(e.g., 50/hour and 10/minute); the first exceeded triggers, and the refused call is counted in neither. An allowed call
is counted in both, and its `ALLOW` carries the counter state of the one nearer its limit. The earlier set-level form
(`metadata.rate_limits`) is compiled to exactly such rules on load.

### Example 3: Sensitive Action Approval

```yaml
- name: "require-approval-for-admin-grants"
  description: "Send grants of admin, superuser or root to security review"
  lifecycle_stage: "active"
  priority: 200
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "grant_access"
      - field: "parameters.role"
        operator: "in"
        value: ["admin", "superuser", "root"]
  decision: "REQUIRE_APPROVAL"
  reason_code: "ADMIN_PERMISSION_GRANT"
  route: "security-review"
  metadata:
    sla_hours: 2
    reviewer_role: "security_team"
```

### Example 4: Block with Remediation

```yaml
- name: "block-protected-field-access"
  description: "Refuse user searches that request SSN, tax ID or bank account fields"
  lifecycle_stage: "active"
  priority: 800
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "search_users"
      - any_of:
          - field: "parameters.fields"
            operator: "contains"
            value: "ssn"
          - field: "parameters.fields"
            operator: "contains"
            value: "tax_id"
          - field: "parameters.fields"
            operator: "contains"
            value: "bank_account"
  decision: "BLOCK"
  reason_code: "PROTECTED_FIELD_ACCESS"
  remediation:
    message: "Query includes protected fields that require elevated permissions."
    suggestion: "Remove protected fields and retry, or escalate to an authorized reviewer."
    type: "field_restriction"
    details:
      blocked_fields:
        ref: "parameters.fields"
        filter: ["ssn", "tax_id", "bank_account"]
      allowed_alternative:
        fields: ["name", "email", "department", "title", "start_date"]
```

When this rule triggers, the decision response includes the `remediation` object with the computed `blocked_fields` and `allowed_alternative`. An agent reading the remediation can remove the protected fields and retry successfully.

### Example 5: Kill Switch

```yaml
- name: "kill-switch-database-deletes"
  description: "Stop every database delete while an incident is open"
  lifecycle_stage: "disabled"  # Disabled by default, enabled when incident declared
  priority: 1000
  conditions:
    all_of:
      - field: "operation"
        operator: "equals"
        value: "delete"
      - field: "target.resource_type"
        operator: "equals"
        value: "database"
  decision: "KILL_SWITCH"
  reason_code: "KILL_SWITCH_ACTIVE_DATABASE_DELETES"
```

---

## Implementation Requirements

All policy evaluator implementations must:

1. **Parse YAML/JSON policy files** into internal representation
2. **Validate policy structure** against this specification
3. **Evaluate conditions** deterministically (same envelope + policy = same decision)
4. **Respect priority order** (highest priority first)
5. **Apply precedence rules** (DENY wins, fixed evaluation sequence)
6. **Pass conformance test suite** (language-neutral test cases)
7. **Return decision with metadata** (decision type, reason code, policy version, matched rule)
8. **Be side-effect free** (evaluation does not mutate state)

---

## Conformance Testing

The conformance test suite (`/tests/conformance/`) contains test cases in the format:

```jsonc
{
  "test_name": "high_value_payment_requires_approval",
  "envelope": { /* full envelope JSON */ },
  "policy_set": { /* full policy set */ },
  "expected_decision": {
    "decision": "REQUIRE_APPROVAL",
    "reason_code": "HIGH_VALUE_PAYMENT",
    "matched_rule": "require-approval-high-value",
    "policy_version": "v2.1.0"
  }
}
```

Every evaluator implementation runs the full suite. All must produce identical decisions.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial policy format specification | Phase 0 Setup |
| 1.1 | 2026-02-16 | Added: policy metadata (shareability, templates, visual rendering, ecosystem references, grading hooks), HITL config references on escalation rules, template semantics | Strategic Evolution |
| 1.2 | 2026-02-24 | Renamed hitl_config → route on rules. Added remediation block on rules for BLOCK/RATE_LIMIT decisions. Updated all references from HITL Config Spec to Route Spec. | Strategic Evolution v2 |
| 1.3 | 2026-02-27 | Added rule `mode` field (observe/enforce). Renamed tool_name → action in envelope (backward compat preserved). Added OBSERVE decision type. | TICKET-028.1 |
| 2.0 | 2026-05-11 | **Schema break (clean cut, no users):** removed `enabled` and `mode` fields. Added `lifecycle_stage` (draft/staged/active/disabled/archived), `scope` (agents/users/environments whitelist + deterministic percentage rollout), `valid_from` / `valid_to` temporal validity, `observation_window_days`. New evaluator skip chain: lifecycle → temporal → scope → percentage → conditions. Per-rule observe is now `lifecycle_stage=staged`; staged rules are skipped in Block 1A's binding evaluation and recorded as `staged_observations` in Block 1B. | Wave 9 Block 1A |
| 2.1 | 2026-10-08 | **DENY wins** implemented as ruled (class KILL_SWITCH > BLOCK > other, then priority, then definition order; R-0846). Added: `rate_limit` window on `RATE_LIMIT` rules (they meter; R-0852); the `$uncalibrated` typed placeholder (a rule carrying one never matches, cannot be promoted); `tests` shipped with a rule; `suggested_by` and `requirement_citation` lineage written by accept. | T-130 |
| 2.2 | 2026-10-08 | **One rate-window representation** (T47): `metadata.rate_limits` compiled to windowed `RATE_LIMIT` rules on load; rule scope `user_action` added; lint `RATE_LIMIT_BOTH_FORMS`. **No field is dropped** (S2): every policy model refuses a field it does not define; `enabled` / `mode` refused naming `lifecycle_stage`. | T-130 follow-up |
| 2.3 | 2026-10-08 | `requirement_citation` may be a list (one rule answering several determinations); `waits_on` — a rule's unmet dependency, a promotion gate (`RULE_DEPENDENCY_UNMET`). | T-130 |
| 2.4 | 2026-10-08 | `waits_on` kinds `session` (hiitl's record of the session's prior decisions) and `route` (route-response enrichment, TICKET-046). A condition may read `session.<name>` (hiitl's record of the session) and a signal reference `external.<source>[.<name>]` (see **Signal Reference Syntax**); the lint accepts both — the rule's `waits_on` says what the value waits on. | T-130 |
| 2.5 | 2026-10-09 | The DECLARED placeholder `{"$declared": "<what staff declare>"}` beside `$uncalibrated` — a value only staff can set (T49); a rule carrying one never matches and is not promoted (`RULE_UNDECLARED`, naming it) until a kept edit sets it. `waits_on` kind `session` removed — hiitl's own record is an enrichment source, `external.hiitl.<field>` (kind `hiitl_record`); `session.<name>` is no longer a condition namespace. | T-130 |
| 2.6 | 2026-10-09 | A field reference as a condition's value (`{"$field": "<path>"}`, resolved against the same envelope; the lint refuses an unaddressable reference); the `conforms_to` operator over a parameter schema (a JSON-Schema subset; never a regex); `in` / `not_in` with an array on the left are subset tests. | T-130 |
| 2.7 | 2026-10-11 | **Enrichment context** (TICKET-046): `external.<source>.<field>` resolves against the context the evaluator takes beside the envelope — a sync route's declared answer fields, written once per evaluation; a `ROUTE` rule whose route has answered does not match again; an unanswered route fails closed (`ROUTE_UNANSWERED`) unless its SLA says `fail_open`. `waits_on {kind: route}` names the path the rule reads (was `TICKET-046`) and is met when a record of an action the rule binds carries it. A `ROUTE` decision carries its rule's `route` as `route_ref`. | TICKET-046; R-0905 |
| 2.8 | 2026-11-03 | Brought current to the ruled changes: staged observation is built (`staged_observations`), the `ROUTE` decision's meaning, Example 1's required `description`, Example 4's operators (`any_of` over `contains`), the `stage` environment value (HTL-17) | CC |
| 2.9 | 2026-11-04 | **Rate-limit rules** (HTL-20): the limiter reads every window before it counts any, so a refused call is counted in none, and an `ALLOW` carries the counter state of the window nearest its limit. Under `OBSERVE_ALL` a call past a limit is `OBSERVE` with `would_be: RATE_LIMIT`, and a failing limiter is a `BLOCK` (`RATE_LIMIT_SERVICE_ERROR`), observed as one under `OBSERVE_ALL`, never an `ALLOW`. The counter increments on an `ALLOW` (R-0056; it said "on execution"). `rate_limit_rules[]` carries each rule's `reason_code` and `remediation`, and the exceeded rule's remediation reaches the caller. **Computed details**: a remediation detail that states a fact of the call is computed from it, and a `blocked_fields` of any other shape is refused. **The create path** stages what it writes: no rule reaches `active` without the promotion gate, and an edit to a staged or active rule is its refinement. | HTL-20 rows 132, 146, 138 |
| 2.10 | 2026-11-04 | A rule's `decision` excludes the produced-only values (`OBSERVE`, `SIGNATURE_INVALID`, `CONTROL_PLANE_UNAVAILABLE`) and `scope.environments` takes only the envelope's environment values; each is refused naming the rule or the value, in both languages (R-0872 / R-0881 swept; HTL-20 row 147) | CC |
| 2.11 | 2026-11-05 | **A field the call does not carry** (HTL-22 row 176): a policy set's `on_missing`, `skip` (default) or `fail_closed`. Under `fail_closed` an active rule the call cannot read decides `BLOCK` / `MISSING_FIELD` at its own priority; under `skip`, in observe mode and in the staged lane it is read as before and named in `missing_fields`. `external.*` is not counted. | CC |
| 2.12 | 2026-11-05 | A set's `version` (semver with its `v`), `description` and `scope` are required in both languages, and a set without one is refused naming it; the scope's `org_id` is in the envelope's form, its `environment` an envelope environment, and an undefined scope key is refused. The version bump keeps semver. | HTL-22 row 165 |
| 2.13 | 2026-11-05 | **The create path**: a set the write leaves allowing nothing is refused (422 `ALWAYS_BLOCK`) unless the current set already allowed nothing; a set whose content is a stored version's is that version re-posted, written as stored and recorded `ROLLBACK`. A regression report records the body of the rule it read, and the gate passes a rule only on a report for its body. | HTL-22 row 162 |
| 2.14 | 2026-11-05 | The produced-only values include the error decisions `VALIDATION_ERROR` and `POLICY_ERROR` (decision_response.md 1.12; HTL-22 row 159): no rule writes one, and a loader refuses each, naming the rule | CC |
| 2.15 | 2026-11-06 | As ruled 2026-11-06 (HTL-23): **a first create** into an environment with no set carries the onboarding default after its own rules, as accept does (row 201); **a set stored before row 165** that does not load is superseded by a migration with the next unused semver version, never rewritten in place (row 202) | CC |
| 2.16 | 2026-11-07 | As ruled 2026-11-07 (HTL-24 row 220): **a rule's name is unique within its set**, refused by each core model naming it; **the set as it would be written** (the default and the refinements carried) is loaded before the `ALWAYS_BLOCK` check and refused 422 `POLICY_VALIDATION_ERROR` when it does not load, the loader's code with the status saying which set; **every write loads what it stores**, at the one writer of a version; `policy_refs`, removed at envelope schema 2.0 (row 223), is restated in "How a policy applies" | CC |
| 2.17 | 2026-11-08 | As ruled 2026-11-08 (HTL-27 row 225): **the `tool_name` alias leaves at envelope schema 2.0**. A condition on `tool_name` is the lint's `UNDEFINED_FIELD`, naming `action`, and reads an absent field, as any field the call lacks (corrected 2026-11-09 on Codex's review: not "never matches"; `exists: false` on it matches every call). A path is read as written at every part, each part a member the object holds as data, so `parameters.tool_name` is no longer read as `parameters.action`, and an inherited name or a model's method is absent in every evaluator; `conforms_to` and the rollout's hash field read names the same way | CC |
| 2.18 | 2026-11-10 | HTL-29 review, condition 5: **a rule's `valid_from` and `valid_to` are RFC 3339 date-times**, read by that grammar as ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar" states, one reader in each core against one table. The Python core no longer reads a time with no offset as UTC, nor a form outside the grammar (a space for `T`, no seconds, `+0100`); the TypeScript core takes a numeric offset and a lower case `t` or `z`, as the grammar does. **A YAML policy resolves no timestamp**: a date-time written in YAML is the string written ("a thin parsing layer that converts to JSON"), in both SDKs | CC |

| 2.19 | 2026-11-14 | HTL-43, Trevor's ruling `13d5d855`: optional fields are omitted; explicit null follows the declared type. The three lineage/dependency child tables state the shared non-null types and requiredness of both SDKs, including the citation object/array forms. Open JSON data remains open. Numeric representation and the public Python keyword boundary are separate pending rulings; this entry chooses neither. | Codex |
| 2.20 | 2026-11-14 | HTL-43 rulings `04ee6245`, `1c1611da`, `d82fe0f5`: every number follows the single admission domain beside C; scope percentage is an integer 0–100, and rate-window limit/duration are positive integers or the declared placeholder. Both loaders use YAML 1.2 Core scalar resolution. No new grammar for the three separately open conditions. | Codex |
| 2.21 | 2026-11-15 | HTL-43 `93d827ef` and `fc00ed9a`: structural JSON equality and membership; wrong-kind operands stop an unsettled reached rule with the existing policy error, independent of condition order, and fixed wrong-kind literals are refused at load where the operator declares the right-side kind. Absent/null and placeholders retain their declared reading. | Codex |
| 2.22 | 2026-11-17 | HTL-45, Trevor's ruling `8613a7bc` (R-0173): **`matches` is removed** from the operator table. A policy naming it is refused at load in both languages by the refusal for an operator the format does not have, which names `starts_with`, `ends_with`, `contains` and `in`; the regex errors each evaluator swallowed leave with it. Breaking for policies written against 0.1.0. The envelope schema's `pattern` checks on hiitl's own identifier formats are unchanged. | CC |
| 2.23 | 2026-11-17 | HTL-45 `d0640d7a`, gap 322, decided by the record: **a condition's `value` is required** in both languages, as Python already read it, and TypeScript now refuses its absence (or an `undefined` value, since JSON has none) at load at the same path. An object that is neither condition form (`{}`, or two logical sets) is refused at the condition's own path in both. Breaking for TypeScript policies written against 0.1.0 that omit `value`. | CC |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Field paths referenced in conditions
- [Decision Response Spec](decision_response.md) - Decision output format
- [Route Spec](routes.md) - Route schema (external communication — outbound, inbound, bidirectional)

---

**This specification is the source of truth. Implementations follow the spec. If two implementations disagree, the spec decides.**
