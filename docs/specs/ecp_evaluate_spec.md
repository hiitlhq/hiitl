# ECP Core: The `evaluate()` Call

## What This Document Is

This is the foundational specification for how developers interact with ECP. Everything else — the SDK, the docs, the website, the onboarding story, the pricing model — flows from what's described here. If this is wrong, everything downstream is wrong.

This document serves two purposes: (1) it documents the **current implemented API** with copy-paste accurate code examples, and (2) it describes the **product vision** for features not yet implemented, clearly marked as such.

## The Principle

There is one call: `evaluate()`.

It sits in the same place in the developer's code, always. It accepts the same payload shape, always. What it *does* depends on how policies are configured — not on which function the developer called.

The developer never changes their integration code to change ECP's behavior. They change configuration.

---

## What `evaluate()` Does

The developer calls `evaluate()` when their agent is about to take an action. ECP receives the action, evaluates it, and returns a result.

```python
from hiitl import HIITL

hiitl = HIITL(
    agent_id="intake-bot",
    environment="prod",
    mode="RESPECT_POLICY",
    policy_path="./policy.yaml",
)

result = hiitl.evaluate(
    "send_email",
    target={"recipient": "applicant@example.com"},
    parameters={
        "subject": "Your application status",
        "body": "We're pleased to inform you...",
    },
    sensitivity=["pii"],
    cost_estimate={"tokens": 200},
)
```

That's it. One call. The developer doesn't decide whether this is a "check" or a "real evaluation." ECP decides what happens based on policy.

---

## The Envelope

Every `evaluate()` call produces an envelope internally. The envelope is a structured, machine-readable representation of the action. The developer never constructs the envelope directly — the SDK builds it from the arguments to `evaluate()`.

An argument left at its declared default is absent from the envelope. Python's own optional
arguments retain `None` as their not-given default; this does not remove a null supplied in
a caller's file, body or mapping, or a null inside open `parameters` data (Trevor, HTL-43
`04ee6245`, 2026-11-14). TypeScript's existing call-option defaults are unchanged by this
ruling; the data envelope the SDK builds follows its schema.

Every supplied number, including numbers nested in caller data, follows the
[shared numeric domain](sync_engine.md#numeric-domain) before evaluation, signing,
hashing or recording. A refused value is identified by its location and the remedy is to
pass it as text; text remains text and cannot then be compared as a number by a policy.

### Required Fields (minimum viable call)

At the call site, only one field is required:

| Field | Purpose |
|-------|---------|
| `action` | What the agent is trying to do (tool name, action type) |

That's the minimum. One argument. `agent_id` defaults to `"default"` at initialization and can be overridden per-call. This is what "three lines of code" means on the website:

```python
from hiitl import HIITL

hiitl = HIITL()

result = hiitl.evaluate("send_email")
```

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL();

const decision = hiitl.evaluate({ action: 'send_email' });
```

Zero-config starts in `OBSERVE_ALL` mode — no policy file needed, no API key needed. Every action is observed and logged.

### Optional Fields (richer evaluation)

Everything else is optional. The more context the developer provides, the more ECP can do.

| Field | Purpose | What it enables |
|-------|---------|-----------------|
| `target` | What resource is being acted on (dict) | Resource-specific policies |
| `parameters` | Full action payload (dict) | Content-based evaluation, complete audit trail, PAUSE/resume with full context |
| `sensitivity` | Developer-declared risk flags (list) | Sensitivity-based routing, graduated controls |
| `cost_estimate` | Expected cost (tokens, dollars) | Budget enforcement, spend limits |
| `user_id` | End user who triggered the action | Per-user rate limits, user-specific policies |
| `session_id` | Conversation or workflow session | Correlation, session-level analysis via routes |
| `operation` | Operation type (default: "execute") | Operation-specific policies (read/write/delete) |
| `agent_id` | Override per-call (default set at init) | Multi-agent flows from one client |
| `confidence` | Upstream model confidence score (0-1) | Confidence-based escalation |
| `idempotency_key` | Deduplication key (auto-generated) | Prevents duplicate execution |
| `reason` | Why the agent wants to do this | Audit context, reviewer context |
| `requested_scopes` | Permission scopes this call requests (list) | Scope-based policies |
| `principal_token` | A token your configured `principal_verifier` checks | A verified `principal` on the envelope, for identity-based policies |

> **Note:** `org_id` and `environment` are set at initialization, not per-call. The SDK auto-generates `action_id`, `idempotency_key`, `timestamp`, and `signature`.

### A date-time is read by RFC 3339's grammar

Every field the specs type `date-time` is read by RFC 3339's `date-time` grammar (JSON Schema's `format: date-time` is
that grammar), by one reader in each core, `hiitl.core.date_time` and `@hiitl/core`'s `date-time.ts`, both read against
one table, `tests/conformance/date_time/` *(HTL-29 review, condition 5)*. The fields read are the envelope's `timestamp`
and `principal.verified_at`, a rule's `valid_from` and `valid_to` (policy_format.md), a decision's `rate_limit.reset_at`
(decision_response.md), an uploaded record's `timestamp` (sync_engine.md §2.1) and a telemetry record's `window_start`
and `window_end` (telemetry_schema.md). The others the specs type `date-time` are read by no core to an instant: the
sync responses' `updated_at`, `activated_at` and `server_time` are written by the service, and the rate limit sync's
`client_time` and `window_start` (sync_engine.md §2.5) are not built.

- **The form** (RFC 3339 §5.6): a full date, `T`, a full time and its offset, `Z` or `±hh:mm`. The section's note lets
  `T` and `Z` be lower case, so `t` and `z` are read as `T` and `Z`. A fraction of a second is `.` and one or more
  digits. Every digit is `0`–`9`.
- **The ranges** (§5.6, §5.7): month `01`–`12`; day `01` to the month's last day, February's `29` only in a leap year
  (divisible by 4, and not by 100 unless by 400); hour `00`–`23`; minute `00`–`59`; second `00`–`59`; an offset's hour
  `00`–`23` and its minute `00`–`59`.
- **For an instant read**, what is held is the instant, with its offset as written. A fraction finer than a core holds is truncated, never
  rounded, so the instant stays within the second written: Python holds microseconds, TypeScript milliseconds.
  That precision belongs to the reader comparing times for windows, clocks and dedup; it does not replace the
  supplied date-time text in an envelope's policy comparison, recorded JSON, signed form or hash.
- **A new envelope keeps the supplied date-time text** at each of those boundaries, including date-time members
  inside a compared object or list (HTL-43 `0c210c59`, 2026-11-15). As event_format.md **Order**, row 134, declares,
  "The envelope's signature and `envelope_hash` are computed over the envelope as sent"; its recorded envelope
  therefore replays the same policy-comparison text. An aware native Python `datetime` has no supplied string and
  uses its existing JSON serialization. Old records keep their text, hash and integrity unchanged, by
  sync_engine.md's "A record written before this keeps the hash it was written with." The service's
  `models.Instant` columns keep their existing instant reading. Proposed system architecture §2: SDK decision and audit planes.
- **In a policy condition** (Trevor, 2026-11-15, HTL-43 `fc00ed9a`), a date-time member is the supplied JSON
  string, compared by its characters exactly as sent. String operators and JSON-value equality or membership read
  that value, including inside a compared object or list and as a field-reference operand. This is not equality
  of temporal instants. Rule windows, clocks and dedup retain the instant reading below. By policy_format.md's
  "Equality compares the six JSON kinds by their values," in the proposed system architecture §2 SDK decision plane.
- **A refusal names the element and its range** (for example "has offset minute 60; an offset's minute is 00 to 59"), in
  the same words in both cores. The object that carries the field is refused as that object is refused: an envelope or
  a policy is not valid, an uploaded record is `TIMESTAMP_INVALID`, a telemetry record is refused at its index.
- **What the grammar allows and no core holds is refused, naming why:** a leap second (`60`); a date written in the
  year `0000`, whatever its offset, as what is held is the instant with its offset as written and no core holds that
  date ("has year 0000; …", named first, the year being written first); and an instant outside
  `0001-01-01T00:00:00Z`–`9999-12-31T23:59:59Z` in UTC, as a date written in `0001` or `9999` whose offset carries it
  past either end. These are hiitl's limits, not RFC 3339's, whose grammar writes the year `0000`; both readers refuse
  each in the same words *(HTL-29 second review, condition 5)*.
- **In Python** a field also takes a `datetime` that carries its offset; one with none is refused, as a date-time has
  an offset. **A YAML policy or route** is "a thin parsing layer that converts to JSON" (policy_format.md), and JSON has
  no timestamp: YAML's timestamp type is not resolved, so a date-time written in YAML is the string written, read here,
  and an explicit `!!timestamp` is refused.
- **Where two are compared** (a rule's window against the call's clock; the dedup window, a recorded envelope's
  `timestamp` against the call's), each is the instant this reader reads; no store reads a date-time by a function of
  its own. A recorded `timestamp` the store cannot read leaves the key not known to be new, as an unreadable store does
  (row 193).
- **The service's store holds each time as its instant, in UTC**, by one column type, `models.Instant`: a time is
  written in UTC, and a time read back without its zone is the UTC it was written in. The SQLite test double keeps no
  zone, and asyncpg writes the two instants at Python's bounds, `0001-01-01T00:00:00Z` and
  `9999-12-31T23:59:59.999999Z`, as Postgres's `-infinity` and `infinity` and reads them back without one. No reader of
  the store restores a zone of its own.

The envelope gets richer over time as the developer adds more context. This is the natural progression:

1. **Day one:** `action` only → ECP observes, starts logging
2. **Week one:** Add `target`, `sensitivity` → richer policy evaluation
3. **Month one:** Add `parameters`, `cost_estimate`, `user_id` → full policy evaluation, budget enforcement
4. **When ready for human review:** Add `parameters` (full payload) + `reason` → enables PAUSE with complete reviewer context

---

## Policy Modes

Every rule has a lifecycle stage, and the client has a mode. Together they determine what ECP does when a rule matches an action.

### Observe Mode

Under `OBSERVE_ALL` (the default) the policy evaluates but does not enforce. ECP logs the action and records what *would* have happened. A decision that allows (ALLOW, SANDBOX) comes back as itself. Any other decision comes back as `OBSERVE` with `would_be` set to it:

```python
# result.decision == "OBSERVE"
# result.observed == True
# result.allowed == True
# result.would_be == "BLOCK"
# result.would_be_reason_codes == ["exceeds_spend_threshold"]
```

The developer's code doesn't need to handle this differently. The result comes back, the agent continues. The audit trail records that this action would have been blocked.

A rate limit is one of those decisions. Past its limit under `OBSERVE_ALL`, the call comes back `OBSERVE` with `would_be: "RATE_LIMIT"`, and the counters count what enforcing would have counted, so the observed record matches what enforcement would do. A limiter that fails is `BLOCK` under `RESPECT_POLICY` and `OBSERVE` with `would_be: "BLOCK"` under `OBSERVE_ALL`, never a silent allow (policy_format.md **Rate-limit rules**).

### Enforce Mode

The policy evaluates and enforces. The result is binding.

```python
# result.decision == "BLOCK"
# result.blocked == True
# result.allowed == False
# result.reason_codes == ["exceeds_spend_threshold"]
# result.remediation.message == "Amount exceeds $10K threshold"
# result.remediation.suggestion == "Reduce amount below $10,000 or request approval"
```

The agent must respect the decision. BLOCK means don't execute. ALLOW means proceed.

### Mixed Mode

Different policies can be in different modes simultaneously. This is how progressive rollout works. Each rule has a `lifecycle_stage`. `active` rules bind; `staged` rules only record what they would have decided, in `staged_observations`; `draft`, `disabled` and `archived` rules are skipped.

The developer doesn't manage this in code. It's configuration. They promote a rule from `staged` to `active` when they trust it.

### Global Mode Override

The developer sets a global mode at initialization.

- `OBSERVE_ALL` — every policy runs in observe mode regardless of individual settings. This is the default for new clients.
- `RESPECT_POLICY` — active rules bind and staged rules observe. An action no rule matches is BLOCK `NO_MATCHING_RULE`. This is the normal operating state.

```python
# Onboarding: observe everything (default)
hiitl = HIITL()

# Production: active rules enforce, staged rules observe
hiitl = HIITL(mode="RESPECT_POLICY", policy_path="./policy.yaml")
```

---

## What `evaluate()` Returns

The return type is always a `Decision` object with consistent fields. What's populated depends on what happened.

### Current Decision Model (Implemented)

```python
Decision:
    # Always present
    action_id: str                        # "act_abc123..."
    decision: DecisionType                # "ALLOW", "BLOCK", "OBSERVE", etc.
    allowed: bool                         # True if action can proceed
    reason_codes: List[str]               # ["exceeds_spend_threshold"]
    policy_version: str                   # "1.0.0"
    timing: Timing                        # { ingest_ms, evaluation_ms, total_ms }

    # Present when decision is OBSERVE
    would_be: Optional[str]               # Original decision if enforced
    would_be_reason_codes: Optional[List[str]]  # Original reason codes

    # Present when decision is BLOCK or RATE_LIMIT
    remediation: Optional[Remediation]    # { message, suggestion, type, details }

    # Present on RATE_LIMIT (the exceeded window) and on any decision the limiter counted (the window nearest its limit)
    rate_limit: Optional[RateLimit]       # { scope, window, limit, current, reset_at }

    # Present for escalation decisions (REQUIRE_APPROVAL, PAUSE, ESCALATE)
    resume_token: Optional[str]           # Token to correlate with reviewer response
    route_ref: Optional[str]              # Route artifact name from matched rule
    escalation_context: Optional[dict]    # The route_ref route, flattened: { endpoint, protocol, timeout, timeout_action,
                                          #   decision_options, fields, severity, summary, escalation_ladder, token_field }
                                          #   (decision_response.md; set by the SDK or the service from the route)

    # Security
    envelope_hash: Optional[str]          # SHA-256 of evaluated envelope

    # Error (mutually exclusive with remediation)
    error: Optional[ErrorDetail]          # { code, message } — only when ECP itself failed

    # Evaluation detail
    matched_rules: Optional[List[MatchedRule]]  # Rules that matched
    staged_observations: List[StagedObservation]  # always a list; [] when no staged rule matched
    rate_limit_rules: List[RateLimitRule]
    enrichment: Optional[dict]
    routes: Optional[List[RouteAsked]]
    cache_status: Optional[str]  # hybrid only
```

### Valid Decision Types

These are the implemented `DecisionType` values:

| Decision | `allowed` | Meaning |
|----------|-----------|---------|
| `ALLOW` | `True` | Action permitted |
| `OBSERVE` | `True` | Observed only (not enforced); `would_be` shows what would have happened |
| `SANDBOX` | `True` | Routed to sandbox environment |
| `BLOCK` | `False` | Blocked by policy |
| `PAUSE` | `False` | Paused for review |
| `REQUIRE_APPROVAL` | `False` | Requires human approval |
| `ESCALATE` | `False` | Escalated to a configured route |
| `RATE_LIMIT` | `False` | Rate limit exceeded |
| `KILL_SWITCH` | `False` | Kill switch activated |
| `ROUTE` | `False` | A sync route was asked and has not answered |
| `SIGNATURE_INVALID` | `False` | Envelope signature failed verification |
| `VALIDATION_ERROR` | `False` | The envelope is not one the control point admits (decision_response.md, Error Decisions) |
| `POLICY_ERROR` | `False` | The policy could not be loaded, read or evaluated |
| `CONTROL_PLANE_UNAVAILABLE` | `False` | ECP unreachable (fail-closed) |

### Convenience Properties

The Decision object provides convenience properties for common checks:

```python
result = hiitl.evaluate("send_email", parameters={"to": "user@example.com"})

result.allowed         # True if action can proceed (ALLOW, OBSERVE, SANDBOX)
result.ok              # Alias for .allowed
result.blocked         # True if hard-blocked (BLOCK, KILL_SWITCH, RATE_LIMIT)
result.needs_approval  # True if human review needed (REQUIRE_APPROVAL, PAUSE, ESCALATE)
result.observed        # True if observed only (OBSERVE mode)
```

### Phase 2 Vision: Additional Response Fields

> **These fields are NOT yet implemented.** They represent the product direction for future releases. Included here to inform design decisions and ensure the current model has clean extension points.

- **`suggestions`** — Proactive guidance from ECP (e.g., "no rate limit configured for send_email", "adding sensitivity flags would enable PII-aware routing"). This is the suggestion engine's output, designed to help developers progressively enrich their integration.
- **`status`** — `RESOLVED` vs `PENDING` distinction for async workflows. Currently all local-mode decisions are synchronous. Hosted mode with approval queues will introduce `PENDING` status.
- **`callback_url`** — Developer-configured webhook for async resolution notifications.
- **`review_context`** — Structured context sent to human reviewers for PAUSE/REQUIRE_APPROVAL decisions.
- **`ttl`** — How long a paused action remains valid before auto-expiring.

### Handling the Response

For most decisions, the response is synchronous. The call returns, the developer acts on the decision, done.

```python
result = hiitl.evaluate(
    "send_email",
    parameters={"to": "user@example.com", "subject": "Welcome"},
)

if result.ok:
    send_email()
elif result.blocked:
    handle_block(result.remediation)
elif result.needs_approval:
    notify_user("Action requires approval.")
elif result.observed:
    # OBSERVE mode — action proceeds, but ECP logged what would have happened
    send_email()
```

For `PAUSE` / `REQUIRE_APPROVAL`, the decision is returned immediately but resolution may be async. The developer has options:

**Option 1: Check back later**
```python
if result.needs_approval:
    # Store the action_id for later resolution
    save_pending_action(result.action_id, result.resume_token)
```

**Option 2: Just tell the user**
```python
if result.needs_approval:
    send_to_user("Your request is being reviewed. We'll notify you when it's resolved.")
```

> **Phase 2:** Polling helpers (`hiitl.get_action(action_id)`) and callback webhooks will provide richer async resolution patterns. See the Phase 2 Vision section above.

The key insight: async only happens when a policy in enforce mode triggers PAUSE or REQUIRE_APPROVAL. The developer opted into both enforce mode and a policy with human approval. They know it's coming. It's not a surprise.

---

## When PAUSE / REQUIRE_APPROVAL Can Trigger

An escalation decision is the binding rule's decision, as the rule states it:

- The client respects the policy (`RESPECT_POLICY`); under `OBSERVE_ALL` the decision is `OBSERVE` and the escalation is its `would_be`
- The binding rule's `decision` is `REQUIRE_APPROVAL`, `PAUSE`, or `ESCALATE`

What the reviewer sees is named by the rule's route: its `context.fields` (routes.md; the decision returns them as `escalation_context.fields`), each read from the envelope. A field the envelope does not carry is absent from the review; the decision does not change. So a rule whose review depends on a parameter names that parameter in its own conditions (a comparison on `parameters.amount` does not match an envelope without it), and the route lists it in `context.fields`.

This is deterministic and predictable. The developer knows: the review shows what the route names, read from what I send.

---

## The Onboarding Progression

This is how the developer experience unfolds. No code changes between steps — only configuration and envelope richness.

### Step 1: Drop in, observe everything

```python
from hiitl import HIITL

hiitl = HIITL()  # defaults: mode="OBSERVE_ALL", agent_id="default", environment="dev"

# Wrap existing tool calls
result = hiitl.evaluate("send_email")
send_email(params)  # always executes — observe mode
```

**What they get:** Visibility. Action audit log. Every action recorded. Zero enforcement. Zero risk.

### Step 2: Add context, get richer evaluation

```python
result = hiitl.evaluate(
    "send_email",
    target={"recipient": "applicant@example.com"},
    sensitivity=["pii"],
    user_id="user_42",
)
```

**What they get:** Richer policy matching. Sensitivity-based rules can fire (in observe mode). Per-user rate limits become possible. The audit trail captures more context.

### Step 3: Enable enforcement on trusted policies

```python
hiitl = HIITL(
    mode="RESPECT_POLICY",
    policy_path="./policy.yaml",
)
# In policy.yaml: rate_limit_emails rule has lifecycle_stage: active
#                 flag_pii rule has lifecycle_stage: staged
```

**What they get:** Rate limiting enforced. PII flagging still staged (its would-be decision is in `staged_observations`). Same code. They see the observe results in the audit log and gain confidence.

### Step 4: Full enforcement with human review

```python
hiitl = HIITL(
    agent_id="finance-bot",
    environment="prod",
    mode="RESPECT_POLICY",
    policy_path="./policy.yaml",
    org_id="org_acmecorp123456789",
)

result = hiitl.evaluate(
    "send_payment",
    target={"vendor": "ACME Corp", "account": "****4521"},
    parameters={
        "amount": 50000,
        "currency": "USD",
        "recipient": "ACME Corp",
    },
    sensitivity=["money", "irreversible"],
    cost_estimate={"dollars": 50000.0},
    reason="Quarterly vendor payment per contract #1234",
)

if result.needs_approval:
    notify_user("Payment requires approval. A reviewer has been notified.")
```

**What they get:** Full enforcement. Human-in-the-loop for high-stakes actions. Audit trail proving the control was applied. Same `evaluate()` call they've been using since day one.

---

## API Comparison: Python vs TypeScript

Both SDKs are first-class citizens with idiomatic APIs.

### Python: kwargs-style

```python
from hiitl import HIITL

hiitl = HIITL(
    agent_id="payment-agent",
    environment="prod",
    mode="RESPECT_POLICY",
    policy_path="./policy.yaml",
)

result = hiitl.evaluate(
    "process_payment",                     # action is the first positional arg
    parameters={"amount": 500},            # everything else is keyword-only
    target={"account_id": "acct_123"},
    sensitivity=["money"],
)
```

### TypeScript: options-object style

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
    agent_id: 'payment-agent',
    environment: 'prod',
    mode: 'RESPECT_POLICY',
    policy_path: './policy.yaml',
});

const decision = hiitl.evaluate({
    action: 'process_payment',
    parameters: { amount: 500 },
    target: { account_id: 'acct_123' },
    sensitivity: ['money'],
});
```

Both produce identical envelopes and identical decisions for identical inputs. The conformance test suite validates this.

---

## What This Kills

### `check()` was removed.

There is no separate lightweight preview call. The `check()` function was removed during the pre-launch API consolidation in favor of a single `evaluate()` call with sparse or rich envelopes.

A sparse `evaluate()` in observe mode is functionally what `check()` was — fast, synchronous, informational. But it's the same function, the same integration point, and the same return shape. The developer doesn't need to decide which function to use. They use `evaluate()` and send what they have.

### No code changes to change behavior.

The developer never renames a function call. They never switch from one SDK method to another. They change policy configuration and envelope richness. The integration is write-once.

### Mode is not a code decision.

Observe vs enforce is never passed as a parameter to `evaluate()`. It's a property of each rule (its `lifecycle_stage`) and of the client (its mode, set at initialization). The code doesn't know or care what mode it's in. This means a single deployment can have some rules observing and others enforcing, without any conditional logic in the application.

---

## Resolved Design Decisions

### 1. Global mode: code vs configuration

Code-level mode (`HIITL(mode="OBSERVE_ALL")`) is a development convenience and the onboarding default. Production uses `RESPECT_POLICY`, with each rule's `lifecycle_stage` managed in the policy file. If a code-level override is active in a production environment, the SDK logs a warning. This prevents conflicting states between dashboard config and application code.

### 2. Sparse envelopes hitting policies that need more context

In observe mode: skip the policy, flag it in the audit trail ("policy X exists but couldn't evaluate — envelope missing field Y"). In enforce mode: each policy has an `on_missing` setting — `skip` (default) or `fail_closed`. Default is `skip` because developers starting with sparse envelopes are in early adoption and false blocks kill trust. Developers who need fail-closed behavior on specific policies opt into it explicitly per-policy.

### 3. Rate limiting on sparse envelopes

Rate limits apply to whatever identifiers are present. Sparse envelopes with only `action` can be rate-limited by action type. Per-user rate limits require `user_id` in the envelope. This is another reason the envelope naturally gets richer over time — the developer adds fields to unlock capabilities they want. The docs must clearly map which capabilities require which fields.

### 4. Idempotency

The SDK generates an `idempotency_key` automatically (UUID-based) if the developer doesn't provide one. This prevents duplicate PAUSE requests on retries without requiring the developer to think about it. Developers can override with their own key for explicit deduplication control. Deduplication is scoped to `org_id` + `environment` + `idempotency_key` (environment separation is mandatory: the same key in two environments is two actions). A call under a key already recorded, for an envelope whose timestamp is within the dedup window (default 24 hours) of its own, returns the first decision and writes no record (row 143).

**The read and the write are one step** (HTL-29 row 160, ruled 2026-11-09; Principle 5, "Embrace idempotency, retries, deduplication, and partial failure as first-class concerns"). Two calls in flight at once under one new key are taken as if one came first. One is evaluated and recorded; the other returns its decision and writes no record. The hosted service takes a transaction-scoped Postgres advisory lock on (`org_id`, `environment`, `idempotency_key`) before the read, in the read's own statement: one database function, `hiitl_decisions_under_key`, takes the lock and then reads the decisions recorded under the key, the read under a snapshot taken once the lock is held (gap row 190, ruled 2026-11-11: "one database function for the hold and the dedup read"). It holds the lock until the transaction that writes the call's record ends, so a second call under the key waits and its read sees the first call's record. The function reads under row-level security, and the read's org filter is the calling statement's, over what the function returns, as every repository's filter is (TICKET-133). Calls under another key, or under the same key in another org or environment, do not wait. A sync route's job is written and waited on in a session of its own: committing the job on the call's session would end the call's transaction, and with it the hold, before the record is written. So a call that asks a sync route holds its key, and a database connection, for the route's wait. The key is taken before the limiter's keys (policy_format.md **Rate-limit rules**), and a call takes one key, so no two calls each wait on the other's. Each SDK holds the key in its audit store, from the read to the record's write, so the clients of one process that share a store share its holds. A store is its file, whatever name reaches it: the holds are keyed by the file's device and inode, which POSIX names its identity (`<sys/stat.h>`, "The st_ino and st_dev fields taken together uniquely identify the file within the system"), so a name through a symbolic link or a hard link holds the key the file's own path holds (HTL-29 review, condition 3). An in-memory store is its own. Python holds it under a lock per key. TypeScript decides synchronously except where it asks a sync route, and a call under a key whose evaluation is in flight follows that evaluation. The service's SQLite backend is the single-process test and development double, and holds the key within its process, as for the limiter. The key's index is not unique: a key may recur after the window, which bounds the dedup.

### 5. Constructor pattern (not init function)

Both SDKs use a constructor pattern (`HIITL(...)` / `new HIITL({...})`) rather than a separate `init()` function. This is idiomatic in both languages, enables type checking at construction time, and supports the context manager pattern (`with HIITL(...) as hiitl:` in Python).

---

## Summary

One call. One integration point. Configuration controls behavior. Sparse envelopes for early adoption, rich envelopes for full control. Observe mode is default. Enforce is opt-in: `mode="RESPECT_POLICY"` on the client, and `active` rules in the policy. Async only happens when the developer has deliberately configured human review on enforced policies.

The developer's code never changes. Their configuration evolves. That's the product.
