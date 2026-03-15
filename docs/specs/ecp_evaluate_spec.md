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

> **Note:** `org_id` and `environment` are set at initialization, not per-call. The SDK auto-generates `action_id`, `idempotency_key`, `timestamp`, and `signature`.

The envelope gets richer over time as the developer adds more context. This is the natural progression:

1. **Day one:** `action` only → ECP observes, starts logging
2. **Week one:** Add `target`, `sensitivity` → richer policy evaluation
3. **Month one:** Add `parameters`, `cost_estimate`, `user_id` → full policy evaluation, budget enforcement
4. **When ready for human review:** Add `parameters` (full payload) + `reason` → enables PAUSE with complete reviewer context

---

## Policy Modes

Every policy has a mode. The mode determines what ECP does when the policy matches an action.

### Observe Mode

The policy evaluates but does not enforce. ECP logs the action, records what *would* have happened, and returns immediately. The agent continues regardless.

The decision comes back as `OBSERVE` with `would_be` indicating the original decision:

```python
# result.decision == "OBSERVE"
# result.observed == True
# result.allowed == True
# result.would_be == "BLOCK"
# result.would_be_reason_codes == ["exceeds_spend_threshold"]
```

The developer's code doesn't need to handle this differently. The result comes back, the agent continues. The audit trail records that this action would have been blocked.

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

Different policies can be in different modes simultaneously. This is how progressive rollout works. Individual rules within a policy set have a `mode` field (`"observe"` or `"enforce"`).

The developer doesn't manage this in code. It's configuration. They flip a rule from observe to enforce when they trust it.

### Global Mode Override

The developer can set a global mode at initialization that overrides individual policy modes.

- `OBSERVE_ALL` — every policy runs in observe mode regardless of individual settings. This is the default for new clients.
- `RESPECT_POLICY` — each policy/rule uses its own configured mode. This is the normal operating state.

```python
# Onboarding: observe everything (default)
hiitl = HIITL()

# Production: respect per-rule mode settings
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

    # Present when rate limited
    rate_limit: Optional[RateLimit]       # { scope, window, limit, current, reset_at }

    # Present for escalation decisions (REQUIRE_APPROVAL, PAUSE, ESCALATE)
    approval_metadata: Optional[ApprovalMetadata]  # { approval_id, sla_hours, reviewer_role, resume_url }
    resume_token: Optional[str]           # Token to correlate with reviewer response
    route_ref: Optional[str]              # Route artifact name from matched rule
    escalation_context: Optional[dict]    # Populated by SDK from route config

    # Present for SANDBOX decisions
    sandbox_metadata: Optional[SandboxMetadata]  # { sandbox_endpoint, sandbox_environment }

    # Security
    envelope_hash: Optional[str]          # SHA-256 of evaluated envelope

    # Error (mutually exclusive with remediation)
    error: Optional[ErrorDetail]          # { code, message } — only when ECP itself failed

    # Evaluation detail
    matched_rules: Optional[List[MatchedRule]]  # Rules that matched
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
| `ROUTE` | `False` | Routed to a configured destination |
| `SIGNATURE_INVALID` | `False` | Envelope signature failed verification |
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

Escalation decisions require the envelope to have enough context for a meaningful review. Specifically:

- The `parameters` field should be populated (the reviewer needs to see what's being approved)
- The policy must be in enforce mode
- The matched rule must have a `decision` of `REQUIRE_APPROVAL`, `PAUSE`, or `ESCALATE`

If a rule would trigger an escalation but the envelope lacks `parameters`, ECP returns:

```python
# result.decision == "BLOCK"
# result.blocked == True
# result.reason_codes == ["missing_parameters_for_approval"]
# result.remediation.message == "Policy requires approval but envelope lacks full parameters for review"
# result.remediation.suggestion == "Include full parameters to enable human review"
```

This is deterministic and predictable. The developer knows: if I want human review to work, I need to send full payloads. If I'm only sending sparse envelopes, escalation can't trigger — the action will be BLOCKED instead if it hits an approval policy.

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
# In policy.yaml: rate_limit_emails rule has mode: "enforce"
#                 flag_pii rule has mode: "observe"
```

**What they get:** Rate limiting enforced. PII flagging still in observe mode. Same code. They see the observe results in the audit log and gain confidence.

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

Observe vs enforce is never passed as a parameter to `evaluate()`. It's a property of the policy (per-rule `mode` field) or a global configuration (set at initialization). The code doesn't know or care what mode it's in. This means a single deployment can have some rules observing and others enforcing, without any conditional logic in the application.

---

## Resolved Design Decisions

### 1. Global mode: code vs configuration

Code-level mode (`HIITL(mode="OBSERVE_ALL")`) is a development convenience and the onboarding default. Production uses `RESPECT_POLICY`, with modes managed per-rule in the policy file. If a code-level override is active in a production environment, the SDK logs a warning. This prevents conflicting states between dashboard config and application code.

### 2. Sparse envelopes hitting policies that need more context

In observe mode: skip the policy, flag it in the audit trail ("policy X exists but couldn't evaluate — envelope missing field Y"). In enforce mode: each policy has an `on_missing` setting — `skip` (default) or `fail_closed`. Default is `skip` because developers starting with sparse envelopes are in early adoption and false blocks kill trust. Developers who need fail-closed behavior on specific policies opt into it explicitly per-policy.

### 3. Rate limiting on sparse envelopes

Rate limits apply to whatever identifiers are present. Sparse envelopes with only `action` can be rate-limited by action type. Per-user rate limits require `user_id` in the envelope. This is another reason the envelope naturally gets richer over time — the developer adds fields to unlock capabilities they want. The docs must clearly map which capabilities require which fields.

### 4. Idempotency

The SDK generates an `idempotency_key` automatically (UUID-based) if the developer doesn't provide one. This prevents duplicate PAUSE requests on retries without requiring the developer to think about it. Developers can override with their own key for explicit deduplication control. Deduplication is scoped to `org_id` + `idempotency_key`.

### 5. Constructor pattern (not init function)

Both SDKs use a constructor pattern (`HIITL(...)` / `new HIITL({...})`) rather than a separate `init()` function. This is idiomatic in both languages, enables type checking at construction time, and supports the context manager pattern (`with HIITL(...) as hiitl:` in Python).

---

## Summary

One call. One integration point. Configuration controls behavior. Sparse envelopes for early adoption, rich envelopes for full control. Observe mode is default. Enforce is opt-in per policy. Async only happens when the developer has deliberately configured human review on enforced policies.

The developer's code never changes. Their configuration evolves. That's the product.
