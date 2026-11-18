# Event & Audit Format Specification

**Version**: 2.0.2
**Status**: Phase 0 Specification
**Last Updated**: 2026-11-09

---

## Purpose

This document defines the **audit record** of the hiitl Execution Control Plane: the record every attempted action
leaves, the fields it carries, the event each record is, and how an action's records make its lifecycle.

The record is one shape wherever it is held: the SDK's local store writes it, the sync engine uploads it
(sync_engine.md §2.1 is its upload), and the hosted service writes it for the evaluations it makes. This document and
§2.1 name the same fields.

Every numeric value admitted through this format, including each integer member and open data, follows
[the single numeric domain](sync_engine.md#numeric-domain). This is admission before evaluation, signing,
hashing or recording; existing stored records, hashes and signatures remain as written.

---

## Design Principles

1. **Immutable audit trail** - Append-only, no mutation, no soft-delete
2. **Every attempted action produces a record** - Even if blocked, and an evaluation that failed is its error decision, recorded (decision_response.md "Error Handling")
3. **Structured, not narrative** - Machine-readable JSON with consistent field naming
4. **Derived state is computed, never stored** - A record's `event_type` and `allowed` are read from what it carries
5. **OTel-compatible** - Maps cleanly to OpenTelemetry spans and events

---

## The Record

A record is §2.1's record. Its content is its `envelope` and its `decision`, and, where it carries them, its
`execution_result` and its `redaction`; its `content_hash` covers its `event_id` and each of those, in that order
(sync_engine.md §2.1, "The content hash"). The other fields are read from the content, so a reader can filter on them
without opening the JSON.

**Ruled by Trevor (2026-11-06, Stop A, HTL-22 row 191):** "each content member a record carries beyond its envelope
and decision joins the hash as a further term in a fixed order (`…:{C(execution_result)}` on a result,
`…:{C(redaction)}` where a path is named); a record carrying neither hashes exactly as today, so every record written
and `tests/conformance/audit_hash/` stand; one function per language". It rests on the security architecture §1.4,
"Every audit record includes a SHA-256 hash of its own content, computed at write time", and Tier 1's "individual
record tamper detection". It lives in the SDK, the control point's audit plane and Postgres (proposed architecture).

| Field | Type | What it holds |
|-------|------|---------------|
| `event_id` | string | The record's identifier, `evt_` and 20 characters, written once |
| `timestamp` | string (date-time) | When the record was written, by its writer: the SDK's store, or the hosted service for a record it writes. An uploaded record keeps its writer's (sync_engine.md §2.1; HTL-29 row 242) |
| `org_id` | string | The organization: the envelope's, which the service checked is the key's; for a refused envelope, the key's |
| `environment` | string | `dev`, `stage` or `prod`, read as `org_id` is |
| `action_id` | string | The envelope's `action_id` |
| `envelope` | object | The envelope as stored: a declared field's value replaced (see Redaction) |
| `decision` | object | The decision response as returned (decision_response.md): `decision`, `allowed`, `reason_codes`, `policy_version`, `matched_rules`, `timing`, `error` and the rest |
| `policy_version` | string | The decision's `policy_version` |
| `decision_type` | string | The decision's `decision`, one of decision_response.md's decision types |
| `action` | string or null | The envelope's `action` (`tool_name` before 2.0; see From 1.x) |
| `agent_id` | string or null | The envelope's `agent_id` |
| `content_hash` | string | SHA-256 over `{event_id}:{C(envelope)}:{C(decision)}`, then `:{C(execution_result)}` on a record carrying `execution_result`, then `:{C(redaction)}` on a record carrying `redaction`, then `:{C(review)}` on a record carrying `review`. A record carrying none of them hashes over the first three terms alone |
| `event_type` | string | **Computed** from the record as it is read (see Event types), carried on every record as it is read and uploaded, stored in no column |
| `execution_result` | object | **On a result record only** (see The lifecycle): `status` (`succeeded`, `failed` or `canceled`), `error` (string) and `duration_ms` (non-negative number) when given |
| `redaction` | object | **Only where a declared path is absent** (see Redaction): `{"absent": [<declared path>, …]}`, the declared fields at which the envelope holds no value. A record whose every declared path is present, or whose store declares none, carries no `redaction` |
| `review` | object | **On a result record whose writer holds no review case** (see The Lifecycle; row 217, ruled 2026-11-07): `{"unread": <the decision's resume_token>}`, naming the review the writer could not read, in the form `redaction` names a declared path the call does not carry. Only a result for a held decision carries it, and the hosted service, which reads the case, writes none |

The hosted service reads a record back (`GET /v1/audit`, `GET /v1/audit/{event_id}`) with its `event_id`,
`action_id`, `agent_id`, `action`, `decision_type`, `event_type`, `envelope`, `decision`, `content_hash` and
`timestamp`, `allowed` (the decision's own `allowed`), and `execution_result`, `redaction` and `review` where the
record carries them, so a reader holds every term its hash covers.

### From 1.x

**Ruled by Trevor (2026-11-09, HTL-29 row 230):** "the record's projection of the action takes its source's name,
`action`, in the next version of the record format, as `action_id`, `agent_id`, `policy_version` and `decision_type`
already do; the hosted `AuditEvent` column, both SDK stores' columns and the audit query's filter rename with it, by
migration, never in place. By B.foundation.6 (one representation per fact) and row 225's ruling."

At 2.0 the record's `tool_name` is `action`. The record projects the envelope's members under the envelope's names, so
the rename it carries is the envelope schema's (`ENVELOPE_RENAMED` in each core), and no other. The hosted service
renames its column by its schema migration. Each SDK store, when it opens, renames each column of its own whose name
the envelope schema renamed, so a store written before 2.0 keeps each record it holds, with its value, its hash and its
`synced` mark; the member is outside the content hash. The audit query filters by `action` and refuses `tool_name` as a
parameter it does not define, naming `action`. A record a 1.x SDK uploads carrying `tool_name` is stored as any record
is: the service reads each projected member from the record's content, never as sent.

### Where it is held

- **The SDK's local store** (both SDKs): an SQLite table `audit_log` with the columns above but `event_type`, plus
  two marks beside the record: `synced`, on a record the service has accepted, and `refused`, the code the service
  refused it with for its own content (sync_engine.md §2.1). A mark is no content: no hash covers it (Audit Log
  Storage). `execution_result`, `redaction` and `review` are null on a
  record that does not carry them. `event_type` is computed by every reader: `query_by_org` / `queryByOrgId`,
  `query_by_action_id` / `queryByActionId`, `queryByDecisionType`, `get`, `get_unsynced` / `getUnsynced` (so the
  upload carries it) and `lifecycle`. In hosted mode the store holds the records the service could not take (an
  outage decision) until the service answers, and the results the service could not take (decision_response.md
  "Where the error is answered").
- **The hosted service**: a Postgres table `audit_events` with the same content (and the envelope's own
  `envelope_hash`), no `event_type` column, keyed by the record's `org_id`, `environment` and `event_id` (HTL-29 row
  136): an `event_id` names a record within its org and environment, and a request reads its key's alone, so
  `GET /v1/audit/{event_id}` answers another's as one that does not exist. Its readers compute `event_type` as the
  SDKs' do. The role a request
  runs as holds no UPDATE or DELETE on it (Audit Log Storage).
- **The upload** (sync_engine.md §2.1): a record may carry `event_type`. The service computes it from the record's
  decision and refuses a record whose `event_type` is not that, with `EVENT_TYPE_MISMATCH` naming the value sent and
  the value computed. A record with none is accepted. A result record's `review` is checked against its form, and
  the result against the case the service holds (The Lifecycle, "A result whose writer holds no case"). The record
  keeps its writer's `timestamp`, and one that is not a date-time is refused with `TIMESTAMP_INVALID`; the service's
  own write is its table's `created_at`, which is no member of the record (HTL-29 row 242, ruled 2026-11-09).

---

## Event Types

A record's `event_type` is what the record is, computed from what it carries: a result record by its
`execution_result.status`, a decision record by its decision. One function per language computes it, read by every
reader (`hiitl.core.lifecycle.event_type`, `eventType` in `@hiitl/core`). This table is that function.

| `event_type` | Record | Decision | `execution_result.status` |
|--------------|--------|----------|---------------------------|
| `action.evaluated` | a decision record | any other | none |
| `signature.invalid` | a decision record | `SIGNATURE_INVALID` | none |
| `control_plane.unavailable` | a decision record | `CONTROL_PLANE_UNAVAILABLE` | none |
| `action.executed` | a result record | the decision it attaches to | `succeeded` |
| `action.failed` | a result record | the decision it attaches to | `failed` |
| `action.canceled` | a result record | the decision it attaches to | `canceled` |

Every decision the evaluator or the evaluate path produces is a decision record, so `VALIDATION_ERROR` and
`POLICY_ERROR` are `action.evaluated`, with the cause in `reason_codes`, and so are `BLOCK`, `RATE_LIMIT`,
`KILL_SWITCH`, `REQUIRE_APPROVAL`, `PAUSE`, `ESCALATE`, `ROUTE`, `SANDBOX`, `OBSERVE` and `ALLOW` (row 195, ruled
2026-11-06 as built: no sentence names a type of their own for the other two error decisions). Each error decision's
type is therefore this table's: `SIGNATURE_INVALID` is `signature.invalid`; `CONTROL_PLANE_UNAVAILABLE` is
`control_plane.unavailable` under either fail mode; `VALIDATION_ERROR` and `POLICY_ERROR` are `action.evaluated`; and
the control point's `BLOCK`s (`AUDIT_WRITE_FAILED`, `EVALUATION_FAILED`, `AUDIT_READ_FAILED`, decision_response.md
"Error Handling") are `action.evaluated`, as every `BLOCK` is.

**Names earlier versions listed that are no record's type.** Each is a fact a record already holds, read where it is
held:

| Earlier name | Where the fact is |
|--------------|-------------------|
| `action.escalated` | A decision record whose decision is `REQUIRE_APPROVAL`, `PAUSE` or `ESCALATE`, carrying its `route_ref`, `resume_token` and `escalation_context` (`action.evaluated`) |
| `action.review_pending`, `action.review_received`, `action.resumed` | The review case and its transitions (the review case API), not the audit record |
| `rate_limit.exceeded` | A decision record whose decision is `RATE_LIMIT`, carrying its `rate_limit` counter state (`action.evaluated`) |
| `kill_switch.activated`, `kill_switch.deactivated` | A kill switch's activation is a new policy version, with its policy change record; an action it stops is a decision record whose decision is `KILL_SWITCH` (`action.evaluated`) |
| `policy.changed` | The policy change record (the policy change audit), not the audit record |

### Example: a decision record

```json
{
  "event_id": "evt_01HQZ7A1B2C3D4E5F6G7",
  "timestamp": "2026-02-14T12:34:56.789Z",
  "org_id": "org_abc1230000000000",
  "environment": "prod",
  "action_id": "act_01HQZ6X8Z9P5ABCDEFGH",
  "envelope": { "action": "process_payment", "parameters": { "amount": 5000, "currency": "usd" } },
  "decision": {
    "action_id": "act_01HQZ6X8Z9P5ABCDEFGH",
    "decision": "REQUIRE_APPROVAL",
    "allowed": false,
    "reason_codes": ["HIGH_VALUE_PAYMENT"],
    "policy_version": "v2.1.0",
    "route_ref": "finance-review"
  },
  "policy_version": "v2.1.0",
  "decision_type": "REQUIRE_APPROVAL",
  "action": "process_payment",
  "agent_id": "payment-agent",
  "content_hash": "…",
  "event_type": "action.evaluated"
}
```

The envelope and decision are shortened here.

---

## The Lifecycle

An action's lifecycle (Principle 4: Intent → Attempt → Result) is read from its records: the records under one org,
environment and `action_id`, oldest first (`lifecycle` in both SDKs' stores; the hosted service reads the same).

- **The decision.** The action's decision is its latest record that carries no `execution_result`: the answer the
  caller acted on.
- **The result.** A result is recorded on an action that executed, as a record carrying `execution_result` (the
  Stop 1 ruling, HTL-20: "the lifecycle record is sync_engine §2.1's record carrying event_format's lifecycle fields
  (`event_type`; `execution_result` on a result), appended against the decision's `action_id`"). The caller records it
  with `record_result` (Python) or `recordResult` (TypeScript), or in hosted mode with
  `POST /v1/actions/{action_id}/result`, whose body is the `execution_result`.
- **What a result carries (ruled 2026-11-06, row 197).** Its members are this document's `execution_result`:
  `status`, `error` and `duration_ms`. The product spec's "status, response metadata, errors" is these members, by
  "one representation per fact": a caller's response metadata has no member of its own, and a body naming one is
  refused `RESULT_INVALID`. The path is `POST /v1/actions/{action_id}/result`.
  The result body is checked against [numeric admission](sync_engine.md#numeric-domain) before its members are
  selected or its record is read or written. An out-of-domain number is `RESULT_INVALID` (422), naming its exact
  body path and the declared type/range for a typed numeric member such as `duration_ms`. Only a member that admits text is directed to text, by [Numeric domain](sync_engine.md#numeric-domain); text is not a valid numeric duration.
- **The record it attaches to (row 197 (c)).** The action's latest decision record, by Infrastructure spec 2's
  "idempotent state transitions": the decision the caller acted on.
- **The result record.** A new record under the decision record's `org_id`, `environment` and `action_id`, with its
  own `event_id` and `timestamp`. It carries the decision record's `envelope`, `decision` and `redaction` as stored,
  the `execution_result`, and `review` where its writer holds no case for a held decision (below); its `content_hash`
  covers every term it carries. Every store writes it this way: the SDK's local
  store (and, in hybrid mode, uploads it, sync_engine.md §2.1), and the hosted service.
- **A reader of decisions.** A result record repeats its decision record's `envelope` and `decision`: it records the
  action's execution, not a second evaluation. So a reader that counts or reads decisions (evaluations by decision
  type, by action, by rule or by session; the observations the instrument reads; the staged decisions the regression
  report reads) reads the records that carry no `execution_result`, by "The decision" above. A reader of records
  (the audit query, an action's lifecycle, a record's verification) reads every record.
- **An action a review case decided (ruled 2026-11-06, row 196):** "a result attaches to an action whose review case
  resolved approved, read from the case's transitions", by Principle 4 (QUEUED → EXECUTING). A decision held for
  review did not allow the action itself. It is read by what it carries, a `resume_token`, "Used by the caller to
  resume or cancel the action after review" (decision_response.md; the evaluator sets one on `REQUIRE_APPROVAL`,
  `PAUSE` and `ESCALATE`). The action executed if its review let it, as the gateway reads the same transitions
  (routes.md "A review case"): `approved`; `modified`, on which the gateway forwards the reviewer's arguments; or
  `timed_out` where the case's `timeout_action` is `fail_open` ("allow the action with warning", the `auto_approve` of
  routes.md's rename table). Any other review (`rejected`, a timeout under another `timeout_action`, or none yet)
  leaves the action unexecuted, and a case reaches no decision that carries no `resume_token` (BLOCKED is terminal).
  The hosted service reads the review as the latest transition across the action's cases under the key's org and
  environment, with that case's `timeout_action`. A timeout is the recorded one: "Only a recorded timeout is a
  timeout" (routes.md), so a case past its deadline with no `timed_out` transition is still pending.
- **A result whose writer holds no case (ruled 2026-11-07, row 217):** "the local store writes the result, naming the
  review it cannot read … the service, which holds the case, reads the case at sync ingest and refuses the record when
  the case did not let the action run; in local mode the record stands as named", by the ontology §4 commitment 3
  ("under-attribution the operator sees as requires_information, never a silent 'governed'") and Principle 4. One rule
  reads every writer's review, `result_refusal` in both cores: the writer passes the review as it holds it. The hosted
  service passes the case it reads. An SDK's local store holds no case, so it passes the review as unread: a held
  decision whose review is unread is not refused, and the result record carries
  `review: {"unread": <the decision's resume_token>}`, the handle decision_response.md gives "to resume or cancel the
  action after review". A decision that carries no `resume_token` is refused as above, read or unread (BLOCKED is
  terminal). The store writes the same record in local and hybrid mode. At the sync ingest the service checks the
  `review` member against its form, `REVIEW_INVALID` (sync_engine.md §2.1), reads the action's review case as the
  result API reads it, and refuses `RESULT_ON_UNALLOWED_DECISION` when the case did not let the action run, so a
  stored result names an action its review let execute. In local mode, which no service reads, the record stands as
  named: the review is unread, and the record says so.
- **What is refused.** Each refusal is a reason code, the same in both SDKs and the service:

| Reason | When | Hosted status |
|--------|------|---------------|
| `RESULT_INVALID` | The result is not an `execution_result`: `status` is not one of the three, `error` is not a string, `duration_ms` is not a non-negative number, or the body names another member | 422 |
| `ACTION_NOT_FOUND` | No decision is recorded for the `action_id` in the org and environment | 404 |
| `RESULT_ON_UNALLOWED_DECISION` | The action's decision did not allow it, and no review case let it execute (above), so it never executed and has no result (BLOCKED is terminal). At the sync ingest, the case the service reads did not let it execute (row 217) | 409 |
| `RESULT_ALREADY_RECORDED` | A different result is recorded for the action; a result is recorded once (Infrastructure spec 2: "idempotent state transitions"). At the sync ingest, the result the service holds refuses a different one uploaded (gap row 265) | 409 |

- **The same result again** returns the record that holds it, so a retried send is safe.
- **One step (HTL-29 review, condition 4).** A result is recorded once only if its writer reads the action's records
  and writes its result as one step. So a writer holds the action, by its org, environment and `action_id`, from that
  read until its write commits, as the limiter holds its key (policy_format.md "Rate-limit rules"). Two results posted
  at once are then refused or recorded as if one came first. The hosted service holds the action across instances,
  at the result API and the sync ingest alike. The Python store holds it within its process and store, as it holds
  an idempotency key (ecp_evaluate_spec.md §4).
  The TypeScript store's read and write run in one synchronous step, so no other call in its process comes between
  them. The answer is the record as the write stored it, read in the write's own transaction and never after its
  commit, so a failure after the write commits is never answered as the write's (security architecture §1.1).
- **Every writer, the sync ingest included (ruled 2026-11-11, gap row 265):** "every writer of a result shares the
  action's result-once contract, sync ingest included. An identical repeat adds no second result; a conflicting upload
  is refused with the code the result API already uses, `RESULT_ALREADY_RECORDED` (no new code), and the SDK marks
  its local record refused as row 224 ruled." The ingest holds the action and reads its records as the result API
  does (sync_engine.md §2.1). An uploaded result the action already holds is a duplicate, stored no second time, and a
  different one is refused `RESULT_ALREADY_RECORDED`, a refusal of the record's own content: the store that wrote it
  keeps it as written, marked refused, and never sends it again. So the service records an action's result once,
  whether it was posted to the result API or uploaded from a store.
- **A result the hosted service could not take (ruled 2026-11-06, row 200):** "The hosted result write does not raise
  on an outage: with 192 (i) ruled, the result is held in the same local buffer and pushed; a typed error only when
  the buffer itself cannot be written". While it is held, `record_result` / `recordResult` returns the result it holds
  (`action_id`, `execution_result` and `held: true`) and logs a warning. The hosted client pushes it to
  `POST /v1/actions/{action_id}/result` after the records it holds (decision_response.md "Where the error is
  answered"), so a result that follows an outage decision finds its decision. A held result the service refuses at the
  push is a refusal of this table: it is removed from the buffer and logged at error, naming the action and the
  reason, because a refused result is no record and the service's answer is final.

---

## OpenTelemetry Compatibility

The record is designed to **map cleanly to OpenTelemetry spans and events**.

### OTel Span Mapping

hiitl record → OTel span:

| hiitl Field | OTel Span Field |
|-------------|-----------------|
| `event_id` | `span.id` |
| `timestamp` | `span.start_time` |
| `decision.timing.total_ms` | `span.duration` |
| `event_type` | `span.name` |
| `org_id` | `span.attributes["org.id"]` |
| `agent_id` | `span.attributes["agent.id"]` |
| `action` | `span.attributes["action"]` |
| `decision_type` | `span.attributes["decision"]` |
| `policy_version` | `span.attributes["policy.version"]` |

No OTel exporter is built: records leave hiitl through the audit API and the sync upload.

---

## Audit Log Storage

### Append-Only Requirement

Principle 6: "Audit records are append-only. Nothing deletes or mutates audit entries." **Ruled by Trevor (2026-11-08,
HTL-27 row 224):** "a mark beside the record is what the append-only rule already allows; the record's content never
changes". It lives in the SDK, the control point's audit plane and Postgres (proposed architecture).

- **No UPDATE or DELETE** of a record in either store. A record's content, and each member read from it, stays as
  written. The one write after the insert is a mark beside it, outside its hash.
- **The SDK's store** marks a record `synced` when the service accepts it and `refused` when the service refuses it
  for its own content (sync_engine.md §2.1). A result the hosted client could not send is no record until the
  service takes it. It waits in `held_results`, and the client removes it once the service answers it
  (decision_response.md "Where the error is answered").
- **The hosted store holds it at the database** (HTL-29 row 137). A request runs as the tenant role `hiitl_tenant`,
  which holds SELECT and INSERT on `audit_events` and no UPDATE or DELETE. The same is true of every table the models
  declare append-only, each on its own table (`APPEND_ONLY`, the hosted service's models), the change records among them.
  Each such table's migration revokes the two privileges. A table declared append-only whose role still holds either
  fails the cell that reads the declaration against the database's catalog. Migrations and hiitl's own operator work
  run as the table owner, which the role's privileges do not bind.
- The hosted service exposes no endpoint that updates or deletes a record.

---

## Redaction

Sensitive parameters must be redactable before audit log storage.

**Ruled (HTL-20 row 139, 2026-11-04):** "a declared redaction list applies before every write in both stores; the
gateway records argument names with hashed values unless a field is declared". It rests on three of hiitl's
engineering rules: "Sensitive parameters must be redactable. Never log raw secrets"; "ECP evaluates declared facts, not
raw content"; and "No prompt logging by default". It lives in the SDK, the MCP gateway and Postgres (proposed
architecture).

**Ruled by Trevor (2026-11-05, on HTL-20; HTL-22 row 163):** "(a) the hybrid SDK pulls the org's redaction policy; (b)
review cases, `modified_arguments` and route payloads take the declaration; (c) the gateway's hash is keyed (HMAC); (d)
a redaction-policy change writes a change record; (e) a declared path the call does not carry is named in the record,
never skipped silently". It rests on "one representation per fact", on this section's "applies before every write", on
hiitl's security requirement "Redacted fields are irreversible", and on Tier 1's "Every policy modification produces an
immutable audit record". It lives in the SDK (sync), the MCP gateway, Routes and Postgres (proposed architecture).

### The declaration

A declared field is a path into the envelope, `<object>.<member>[.<member>...]`: `parameters.account_number`,
`target.email`, `parameters.card.number`. It names a member of one of the envelope's objects, never a top-level field,
because the stores key a record by its top-level fields (`org_id`, `environment`, `action_id`, `agent_id`, `action`).
The path is walked through objects, and through every item of an array it meets.

Two places declare, each read by the store that writes (hiitl's security requirements, "Sensitive Parameter
Redaction"):

| Who declares | How | Read by |
|---|---|---|
| The SDK ("SDK supports marking parameters as sensitive") | `HIITL(redact_fields=[...])` in Python, `new HIITL({ redact_fields: [...] })` in TypeScript | the SDK's local audit store, at every write. A record it uploads leaves already redacted |
| The org ("Org-level redaction configuration") | `redaction_policy`, set with `PUT /v1/redaction-policy` (admin scope) | every hosted write of the call's values: the record `/v1/evaluate` writes, each record `/v1/sync/audit` receives, a review case's envelope and decision, the reviewer's `modified_arguments`, and a route job's `payload`. And a hybrid SDK's local audit store, from its policy pull |

```yaml
redaction_policy:
  manual_redact_fields:
    - "parameters.account_number"
    - "target.email"
```

In hosted evaluation the service writes the record, under the org's declaration. The SDK's store writes only what the
service could not take (an outage decision, Stop B (i), ruled 2026-11-06), under the SDK's declaration, and at the
upload the service applies the org's as it does to every record it receives.

**The hybrid SDK.** `GET /v1/sync/policies` carries the org's declaration as `redaction_policy`
(`{"manual_redact_fields": [...]}`), with or without policies (sync_engine.md §2.2). The SDK's cache keeps it with the
policies, and its local store redacts, at each write, every path either declaration names: the SDK's own and the org's
as last pulled. A pull without the member, or with an entry that is not a declared field, is refused and the cache
keeps what it had. It is never read as "nothing declared", because that would write an org-declared field in clear.

**Every other write.** A review case's envelope and decision, the reviewer's `modified_arguments` on its transition
(as the action's `parameters`), and a route job's `payload` take the org's declaration before their write. A route
party and a reviewer are sent the payload as stored, so they receive the marker at a declared path (row 212, ruled
2026-11-06: the stored form is what is sent, by "applies before every write" and "one representation per fact"). A
route that must read a value is given it by a field the org does not declare. Evaluation, and a route answer's
re-entry, see the call whole.

**A marker in a reviewer's `modified_arguments` (row 213, ruled 2026-11-06):** "the gateway fills a marked argument
from the call it holds", by "the human contributes to the work". Each path at which the reviewer's arguments hold the
marker takes the call's own value at that path, and the gateway forwards the result. A marked path at which the call
holds no value is refused at the gateway, naming the path, and nothing is forwarded: the gateway never forwards the
marker in place of a value.

**A change is recorded.** A `PUT /v1/redaction-policy` that changes the declaration writes a row to
`redaction_policy_change_audit` in the same commit, in the policy change record's form (security architecture §1.1):

- `change_id`, `org_id` and `changed_by` (the key that made the change);
- `actor_type`, as every change record carries it (security architecture §1.1; row 215, ruled 2026-11-06);
- `change_type`, `CREATE` or `UPDATE`;
- `old_content_hash` and `new_content_hash`, each the SHA-256 of the declaration's canonical form
  (sync_engine.md §2.2's `canonical_hash`);
- `diff`, the paths `added` and `removed`;
- `created_at`.

The declaration is org-wide and unversioned, so the record has no environment or version: its content hashes name the
before and the after. A `PUT` of the declaration already held writes nothing. A change whose record fails is rejected
(503 `REDACTION_POLICY_CHANGE_NOT_RECORDED`), and the declaration is unchanged.

### What the stored record holds

- A declared field's value is replaced by `"[REDACTED]"`. The name stays, so a reader can see that the field was
  there and was declared.
- A remediation that states the call's value at a field takes that field's treatment, wherever in the decision a
  `remediation` sits (today, the decision's own). decision_response.md names two such details: `threshold`'s
  `current_value` at `field`, and `field_restriction`'s `blocked_fields` at `field_ref`.
- **The gateway** (the MCP proxy) records each argument's name, and its value as `"hmac-sha256:<hex>"`:
  HMAC-SHA256 under the store's key, over the value's canonical form (sync_engine.md §2.1's serialisation). The
  exception is an argument `recorded_arguments` declares for that tool in `hiitl-mcp.yaml`, which is recorded as
  given. The SDK option underneath is `recorded_parameters` (`{action: [parameter names]}`). When it is unset, the SDK
  records parameters as given.
- **The key.** The store makes it at its first start and keeps it beside itself, at `<audit_db_path>.value_hash.key`,
  mode 0600. Beside itself is beside the file `audit_db_path` resolves to, read once the store has opened: SQLite
  opens a database "by its canonical name" (howtocorrupt §2.6), its links resolved, and keeps its journal there, so a
  name through a symbolic link reads the one key (HTL-29 review, condition 3). **A key already beside a name on the
  way is the store's key:** a release before this one made the key beside the name it was given, so a key beside the
  name as written, or beside a symbolic link the name passes through to the file, is the key the store's records were
  hashed under. It is written beside the file and never removed from where it was, so a value hashes the same across
  the upgrade. Keys on the way that differ fail the start, naming each file, and none is chosen; so does one of
  another length (HTL-29 second review, condition 3). Every name, the one given and each on the way, is read as the
  filesystem reads it, a link to a directory included: `..` after such a link is the parent of the directory the link
  reaches, never the name's text with its last part taken off, so a name through a directory link finds the key beside
  each name on its way (HTL-29 third review, condition 3). A hard link is a second name for the file in a directory of its
  own, and its key is beside that name (gap row 259). It is never synced, uploaded or written into a record. It is L bytes, SHA-256's digest size, the least
  RFC 2104 §3 allows without "strongly discouraged". Every later start reads it, so a value hashes the same across
  restarts and two records of one store compare. A reader who holds the record and not the key cannot test a guessed
  value against a hash, however small the set of values ("Redacted fields are irreversible"). A key file of another
  length fails the start, naming the file; a lost key leaves the old hashes comparable with nothing new. A store that
  hashes no parameter makes no key.
- **A declared path the call does not carry** (row 163 (e): "named in the record, never skipped silently") is named in
  the record's `redaction` member, `{"absent": [<declared path>, …]}`: each declared field at which the envelope holds
  no value, walked as the declaration is (through objects, and through every item of an array met), in the order the
  store's declaration lists them (the SDK's own, then the org's as joined). A record with no absent path carries no
  `redaction`, so its hash is unchanged. The member joins the record's hash (Stop A).
- Nothing else in the record changes, and nothing is detected. A field is redacted because it is declared, never
  because of its name or its content ("No content detection"). The `auto` mode and the `auto_redact_patterns` this
  section once listed are not built (open, named).

### Order

1. The envelope is evaluated whole. Redaction happens after policy evaluation.
2. The envelope's signature and `envelope_hash` are computed over the envelope as sent (row 134). The caller
   recomputes the hash from what it sent.
3. The record is redacted. Redaction works on a copy; the decision the caller receives is unchanged.
4. The record's `content_hash` is computed over the record as stored ("a SHA-256 hash of its own content at write
   time"). The record keeps the `envelope_hash` from step 2. A record that holds a redacted field re-derives its
   signature and `envelope_hash` only with the caller's original.

At sync upload, the hosted store checks the SDK's `content_hash` over the record as received, every term it carries.
It then applies the org's declaration: each org-declared path the received envelope holds no value at is named after
the record's own absent paths, once. It stores `content_hash` over the record as stored, and keeps the `envelope_hash`
the SDK put on the decision.

A redacted value is a string (the marker or a hash). A reader that summarises numbers, such as the suggestion engine's
parameter distributions, therefore has none for that field; the field's name is still counted.

### Open

- **The window before the first pull (row 211, ruled 2026-11-06: the cold-start sentence governs).** A hybrid SDK
  writes records before its first pull lands: a warn-mode cold start, the TypeScript SDK's background first sync, a
  cache written before row 163. sync_engine.md §5's cold start "logs a warning and evaluates against an empty policy
  set, in the client's own mode, with `cache_status: "empty"` until a sync succeeds", so those records are written,
  never held, and take the SDK's own declaration only. The first pull that lands carries the org's, and every later
  write takes both. Each such record reaches the service through the upload, where the org's declaration is applied
  before it is stored.
- Name-pattern detection (`auto`, `auto_redact_patterns`) is not built, by "No content detection".

### Redacted Envelope Example

Original:
```json
{
  "parameters": {
    "account_number": "1234567890",
    "amount": 500
  }
}
```

Redacted:
```json
{
  "parameters": {
    "account_number": "[REDACTED]",
    "amount": 500
  }
}
```

**Important**: Redaction happens **after policy evaluation** (evaluation sees full envelope), and after the
envelope's signature and `envelope_hash` (see Order above).

---

## Outbound Events

**Built for the hosted service (HTL-29 row 131, 2026-11-09).** Each record the hosted service writes is sent to each
outbound `async` route of its org and environment whose `filters` it passes (routes.md "Outbound routes and filters").
- **What is sent.** The record as the audit API reads it (`GET /v1/audit/{event_id}`): the record as stored, under the
  org's declaration, `event_type` included and computed, never stored.
- **What the filter reads.** The record's own fields: `decision_type`, `action`, `agent_id`, and its envelope's
  `sensitivity`, as stored.
- **When.** The jobs are written in the record's own transaction, so a record and its jobs are written together or
  not at all. A hybrid SDK's records are sent once its upload is taken.
- **Not built.** A pure-local SDK sends no outbound event; its records leave through the sync upload and the audit API.

---

## Retention

**Not built.** No retention job or export endpoint exists in this version: records are kept. The SDK's local store
keeps every record it wrote, uploaded or not.

---

## Conformance Testing

- **The content hash.** `tests/conformance/audit_hash/` hashes fixed records to the same digest in both languages:
  a record carrying no further term (the cases written before 1.5, byte for byte), one carrying
  `execution_result`, one carrying `redaction`, one carrying both, and a held result carrying all three (1.6;
  `review` is carried only beside `execution_result`). The cells read the terms and their order from the
  `content_hash` row of the record table.
- **The event type.** Each language's cells read the Event Types table above and check `event_type` against it for
  every decision type and every result status (`python/hiitl/core/tests/test_row150.py`,
  `typescript/packages/core/tests/unit/row150.test.ts`).

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-14 | Initial event format specification | Phase 0 Setup |
| 1.1 | 2026-02-16 | Added: escalation lifecycle events (action.escalated, action.review_pending, action.review_received, action.resumed) with HITL config references | Strategic Evolution |
| 1.2 | 2026-11-03 | Brought current to the ruled changes: the `decision` enum includes OBSERVE (HTL-17) | CC |
| 1.3 | 2026-11-04 | Redaction as ruled (HTL-20 row 139): the declaration (the SDK's `redact_fields`, the org's `redaction_policy`), what the stored record holds, the gateway's hashed arguments, the order after the hash and signature; `auto` and `auto_redact_patterns` not built; three needs-a-ruling | CC |
| 1.3.1 | 2026-11-05 | Redaction, row 163 ruled (HTL-22): the hybrid SDK pulls the org's declaration and applies the union; review cases, `modified_arguments` and route job payloads take it; the gateway's hash is HMAC-SHA256 under the store's key; a change writes `redaction_policy_change_audit`. Open: an absent declared path (Stop A), three needs-a-ruling | CC |
| 1.4 | 2026-11-05 | Restated as the fields §2.1's record carries (HTL-22 row 150): the record table and where it is held; `event_type` computed from the record (six values, one function per language), carried as read and uploaded, in no column, and checked on upload (`EVENT_TYPE_MISMATCH`); the earlier names that are no record's type, each pointed to where its fact is; the lifecycle and the result API with its five refusals, the result write waiting on Stop A; the storage SQL, webhooks and retention restated as built (none of the last two is) | CC |
| 1.5 | 2026-11-06 | As ruled 2026-11-06 (HTL-23): the hash's further terms, `execution_result` then `redaction` (Stop A); the `redaction` member naming a declared path the call does not carry (row 163 (e)); the result write in every store, `RESULT_WRITE_UNAVAILABLE` retired; a result's members, path and record (row 197) and an action a review case let execute (row 196); the hosted client's buffer for an outage decision and a held result (Stop B (i), row 200); the stored form sent to a route party (row 212), a marker filled from the call (row 213) and the window before the first pull (row 211); each error decision's type stated (row 195); `actor_type` on the redaction-policy change record (row 215); a reader of decisions reads the records that carry no `execution_result` (row 219) | CC |
| 1.6 | 2026-11-07 | As ruled 2026-11-07 (HTL-24 row 217): a result whose writer holds no review case — the local store passes the review as unread and the result record carries `review: {"unread": <resume_token>}`, the hash's next term after `redaction`; the service reads the case at sync ingest and refuses the record when the case did not let the action run (`REVIEW_INVALID` on the member's form) | CC |
| 2.0 | 2026-11-09 | As ruled 2026-11-09 (HTL-29 row 230): the record's projection of the action is `action`, its source's name, in place of `tool_name` (From 1.x); the hosted column and both SDK stores' columns renamed by migration, each record, its hash and its `synced` mark standing; the audit query filters by `action` and refuses `tool_name`, naming it | CC |
| 2.0.1 | 2026-11-09 | Append-only as built (HTL-29 row 137): the marks `synced` and `refused` beside the record, outside its hash; the hosted tenant role holds no UPDATE or DELETE on any table the models declare append-only | CC |
| 2.0.2 | 2026-11-09 | As ruled 2026-11-09 (HTL-29 row 242): an uploaded record keeps its writer's `timestamp`, the service's own write is `created_at`, and a record whose `timestamp` is not a date-time is refused `TIMESTAMP_INVALID` | CC |
| 2.0.3 | 2026-11-10 | HTL-29 review, condition 4, swept to the result write: the read of an action's records and its result's write are one step under the action's hold, and the answer is the record as its write stored it | CC |
| 2.0.4 | 2026-11-11 | HTL-29 second review: a key a release before this one made beside a name on the way to the store's file is the store's key, written beside the file and left where it was, and keys that differ fail the start (condition 3); the result-once statement qualified at the sync ingest, which reads no other result of the action (gap row 265) | CC |
| 2.0.5 | 2026-11-11 | As ruled 2026-11-11 (gap row 265): every writer of a result shares the action's result-once contract, the sync ingest included; an identical upload is a duplicate and a different one is refused `RESULT_ALREADY_RECORDED`, final at the store | CC |

---

## Related Documents

- [Envelope Schema](envelope_schema.json) - Source data for events
- [Decision Response Spec](decision_response.md) - Decision metadata included in events
- [Sync Engine Spec](sync_engine.md) - §2.1, the record's upload and its content hash
- [Policy Format Spec](policy_format.md) - Policy version tracking
- [Route Spec](routes.md) - Route schema (escalation, routing, SLA)

---

**This specification is the source of truth for event and audit format.**
