# ECP Architectural Evolution — Hybrid Mode & Inferred Policies

## Purpose

This document describes two interconnected architectural decisions that significantly affect the SDK design, onboarding flow, product architecture, GTM messaging, pricing model, and documentation. These should be incorporated into the ECP planning and specification documents.

These are not incremental features. They change the default product architecture and the primary onboarding motion.

**Status (hiitl 0.2.0).** This is the decision record, and most of it is built: hybrid mode, the sync engine and the disk cache in both SDKs, observe-first onboarding, and policy suggestions. Usage telemetry is sent by the Python SDK only. Where the shipped product differs from the decision, the text below says so.

---

## Decision 1: Hybrid Mode as the Default Product Architecture

### What It Is

The SDK is not a thin HTTP client that calls a hosted service for every evaluation. It is a **local evaluator with a cloud sync engine.** Evaluation happens in-process at microsecond latency. Policy management, audit aggregation, telemetry, and intelligence features live in the hosted service and sync in the background.

This is analogous to how CDNs work: content is cached at the edge for speed, managed at the origin for control. ECP caches policies locally in the SDK for fast evaluation, manages them in the hosted service for visibility and intelligence.

### How It Works

The SDK has three internal components:

**1. The Evaluator** — runs in-process, evaluates actions against cached policies. This is the hot path. Pure computation, no I/O, no network calls. Microsecond latency.

**2. The Sync Engine** — background process that maintains a connection to the hosted service:
- **Pulls:** policy updates (new versions, activations, deactivations) and route updates. Kill switches and rate-limit rules are rules in the policy, so they arrive with the policy sync (every 5 minutes by default).
- **Pushes:** audit records (batched, gzip-compressed when large, async) and, from the Python SDK, telemetry (action patterns, decision distributions, timing metrics). Rate-limit counters stay in the SDK process; they are not synced.
- Handles connection failures gracefully: each sync channel has a circuit breaker (it opens after 5 consecutive failures and tries again after 60 seconds), and audit records stay in the local audit log until the hosted service accepts them
- The sync engine never blocks the evaluator. If the hosted service is unreachable, evaluation continues against cached policies. Audit records buffer locally and flush when connectivity returns.

**3. The Local Cache** — policies and routes. In memory for fast access. Persisted to disk (`~/.hiitl/cache/` by default) so the SDK works across restarts without requiring an immediate sync. Rate-limit counters are held in memory only.

### SDK Startup Behavior

- **First run (no cache):** No policies cached. The SDK tries a first sync. If that fails and there is no local policy fallback, evaluation uses an empty policy set in the client's own mode while the sync engine keeps trying: `OBSERVE_ALL` observes, and `RESPECT_POLICY` blocks with `NO_MATCHING_RULE`; each decision carries `cache_status: "empty"`. If no policies exist yet, the empty set continues to be evaluated in that mode. This is the default `cold_start_behavior`, `warn-and-observe`. With `fail-closed` the SDK raises an error instead (Python when the client is created, TypeScript at the first `evaluate()`); `observe-silent` uses the same client-mode behavior and logs at INFO.
- **Subsequent runs:** Load policies from local disk cache. Begin evaluating immediately against cached policies. Sync engine connects in background and pulls any updates. The SDK is functional from the first millisecond, even before the first sync completes.

### Three Deployment Modes

**Hybrid mode (default, recommended for production):** SDK connects to hosted service for sync. Evaluation is local. This is the default when an API key is configured (in both SDKs, when remote evaluation is not requested; `server_url` is the sync target when supplied, defaulting to `https://api.hiitl.com`). The developer doesn't think about "local vs hosted" — they configure an API key and the SDK handles everything.

**Pure local mode (development, air-gapped):** No hosted connection. Policies loaded from local files. Audit written to local storage. No telemetry, no sync, no cloud features. Useful for development, CI/CD, and environments that cannot connect to external services.

**Pure hosted mode (optional, for teams that prefer it):** Every evaluation makes a network call to the hosted service. Higher latency (low tens of ms instead of microseconds). Useful for teams that want no local policy state and accept the latency trade-off. It holds a local audit store only for what the service could not take, an outage decision's record and a result, pushed when the service answers (Trevor, 2026-11-06, Stop B (i): "the pure-hosted client keeps a local audit buffer for the records the service could not take, pushed when it answers, as hybrid buffers", by Principle 6; decision_response.md "Where the error is answered"). Python selects it with `evaluation="remote"`, the API key, its signing secret and `server_url`; TypeScript with `evaluation: 'remote'`, the API key, its signing secret and `server_url`. The server evaluates under `RESPECT_POLICY`.

### What This Changes

**SDK architecture:** The SDK is no longer a simple HTTP client wrapper. It contains the evaluator, a sync engine, a local cache with disk persistence, and connection management. Both the Python and TypeScript SDKs have this architecture. The sync engine is specified in the [sync engine spec](../specs/sync_engine.md).

**Latency profile:** The hot path (evaluation) has zero network dependency in hybrid mode. Latency is determined by in-process computation only. The "single-digit ms locally, low tens of ms hosted" latency requirement becomes "microsecond evaluation in hybrid mode" — significantly better than originally specified.

**Resilience:** In hybrid mode, evaluation continues against cached policies during a hosted service outage; sync circuit breakers protect the background calls. In hosted mode, an unreachable service returns a recorded `CONTROL_PLANE_UNAVAILABLE` decision. `FAIL_CLOSED` blocks by default; explicit `FAIL_OPEN` allows the action with a recorded warning. If the local audit store cannot write the outage record, the action is blocked with `AUDIT_WRITE_FAILED` under either fail mode. See [Error Handling](../specs/decision_response.md#error-handling).

**Metering (not built):** The plan is to meter actions via the audit records synced to the hosted service. The hosted service sees every action (with a sync delay, 30 seconds by default), which would enable usage-based pricing without affecting evaluation latency.

### Implications for Existing Documentation

| Document | Required Updates |
|---|---|
| **Project requirements — SDK Requirements** | Rewrite SDK architecture to describe three components (evaluator, sync engine, local cache). Update deployment modes (hybrid/local/hosted). Update latency requirements (microsecond evaluation in hybrid mode). |
| **Project requirements — Infrastructure Specs** | Update "Control Plane Outage Behavior" — hybrid mode means outages don't affect evaluation, only sync. Update "Storage & Durability" — local cache persistence requirements. |
| **Infrastructure Analysis** | Rewrite "What Kind of System Is ECP" — it's a local evaluator with a cloud intelligence backend, not just an inline enforcement gateway. Update deployment topology diagrams. |
| **Product Spec — Adoption/Integration Path** | Update to reflect that the SDK is self-contained with cloud sync, not a client that calls a server. |
| **Decision Response Spec** | No change — decision format is the same regardless of where evaluation happens. |
| **Security Architecture** | Add analysis of the sync engine as a new data flow. Telemetry security: what data is shipped, encryption in transit, redaction controls on telemetry. Policy sync integrity. |

---

## Decision 2: Inferred Policies and the Observe-First Onboarding

### What It Is

ECP's default onboarding path requires zero policy configuration. The developer instruments their agent's actions with `hiitl.evaluate()`, runs their application, and ECP observes the behavior patterns. After sufficient observation, an analysis of the recorded actions (run on demand, `POST /v1/suggestions/analyze`) generates suggested policies specific to the application's actual behavior. The developer reviews and accepts suggestions with one click.

This solves the cold-start problem: developers don't need to know what policies to write. ECP tells them.

### The Onboarding Sequence

**Minute 0-5: Install and instrument.**

```bash
pip install hiitl
```

```python
import os

from hiitl import HIITL

hiitl = HIITL(api_key=os.environ["HIITL_API_KEY"])

# Wrap each agent action — one line per action
result = hiitl.evaluate("send_payment", parameters={"amount": 500, "to": "vendor_123"})
if result.ok:
    actually_send_payment(...)

result = hiitl.evaluate("query_user_data", parameters={"user_id": "usr_456"})
if result.ok:
    actually_query_data(...)
```

No policies configured. No policy files created. The developer doesn't encounter the word "policy" during initial setup. All actions are allowed and logged: each decision is `OBSERVE`, with `allowed` true.

**Day 1-3: Observation phase.**

The SDK logs every action locally and syncs the audit records to the hosted service (every 30 seconds by default); the Python SDK also syncs telemetry. The developer can see their agent's behavior in the dashboard: every tool call and its parameters on the Audit page, and, from the Python SDK's telemetry, frequency patterns and timing on the Behavior page. This is the first value moment — visibility into agent behavior that didn't exist before.

**Day 3-7: Suggestions arrive.**

The hosted service analyzes observed behavior patterns and generates suggested policies. The analysis runs when it is asked for (`POST /v1/suggestions/analyze`, admin scope); nothing schedules it. Suggestions appear in the dashboard, each one specific and explained:

- "Your payment-agent processes amounts between $10-$800. **Suggested: flag amounts over $2,000 for review, block over $10,000.**"
- "Your data-agent queries user records ~150/hour. **Suggested: rate limit at 200/hour.**"
- "Your agent calls delete_record occasionally. **Suggested: require approval for all delete operations.**"
- "No kill switch exists for your high-risk actions. **Suggested: add a kill switch for each.**"

Each suggestion is one-click accept. An accepted rule is added to the policy as `staged`: it records what it would decide and does not enforce until it is promoted (a suggested kill switch is added `disabled`). Hybrid SDKs pick up the new policy with their next policy sync.

**Day 7+: Refinement.**

The developer modifies accepted policies, adds custom rules, writes their own policies for edge cases. Testing and grading tools help them iterate. Policy assessment reports show coverage gaps. The full policy design workflow is available for those who want it.

### What the Suggestion Engine Needs

**Input:** The recorded actions (the audit records the SDK syncs, from either language) — tool names, parameter distributions, action frequency, timing patterns, agent identifiers, decision history.

**Analysis:** Pattern recognition on the telemetry to infer:
- What tools exist and how they're used
- What "normal" parameter ranges look like (amount distributions, frequency baselines)
- Which actions touch sensitive categories (money, permissions, data mutations, external communications) based on tool names and parameter shapes
- What the application's purpose appears to be (payment processing, data management, customer communication, etc.)

**Output:** Suggested policies as fully-formed policy objects (JSON) with:
- Human-readable explanation of why this policy is suggested
- The observed data that justifies the thresholds/rules
- Confidence level (how much data informed the suggestion)
- One-click accept action
- Ability to modify before accepting

**Important: Suggestions are never auto-applied.** The developer always reviews and accepts. ECP observes and recommends; the human decides. This is both a trust requirement (developers won't trust auto-applied rules) and philosophically consistent with the hiitl mission (human intelligence in the loop — even for the policies themselves).

### The Suggestion Engine as a Product

The suggestion engine is not a Phase 1 feature in full. But the telemetry pipeline that feeds it IS Phase 1, because the SDK needs to ship telemetry from day one for the observation phase to work.

**Phase 1:** SDK ships telemetry. Dashboard shows agent behavior (visibility). Basic suggestions possible with rule-based heuristics (e.g., "you have no kill switches" doesn't require ML, just inspection).

**Phase 2:** LLM-powered suggestion engine that analyzes telemetry patterns and generates context-aware policy suggestions. This is where the "ECP learns your application" promise is fully realized.

**Phase 3:** Continuous suggestion refinement based on ongoing observation, policy grading results, and human review patterns (the feedback loop from Section 8 of the Strategic Evolution doc).

**Built today (0.2.0):** Phase 1's rule-based suggestions, read from the recorded actions rather than from telemetry, and an LLM-assisted pass that the same analysis runs when the hosted service has a model configured. Phase 3 is not built.

### The Zero-Config Value Proposition

The critical insight: **with no policies configured, ECP is still immediately valuable.** It provides:

- Complete audit trail of every agent action
- Visibility into agent behavior patterns (frequency, parameters, timing)
- A queryable record that didn't exist before
- The foundation for suggested policies

This means the barrier to initial adoption is truly one line of code and an API key. No decisions to make, no configuration to learn, no blank page to fill. The developer gets value immediately and more value accumulates over time.

### Implications for Existing Documentation

| Document | Required Updates |
|---|---|
| **Project requirements — Developer Onboarding & Trust** | Rewrite the onboarding flow around observe-first. The quickstart is "see what your agents are doing in 5 minutes," not "add runtime control." No policies in the initial quickstart. |
| **Project requirements — Phase 1 Scope** | Add telemetry pipeline as a Phase 1 requirement. Add basic suggestion capability (rule-based heuristics). Add dashboard behavior visibility as a Phase 1 UI feature. |
| **Project requirements — SDK Requirements** | The `evaluate()` function with no policies should allow-all and log. The SDK should work meaningfully with zero configuration beyond an API key. |
| **Project requirements — Phase 1 UI** | Add agent behavior visibility (tool usage patterns, frequency, parameter distributions) as a dashboard feature. Add suggested policies display with accept/modify/dismiss actions. |
| **North Star — Right-Now Product** | Update to reflect the observe-first value proposition. The immediate value is visibility, not control. Control follows from visibility. |
| **GTM Plan** | Messaging overhaul — see "GTM Messaging" section below. The primary message becomes "see what your AI agents are doing" with control as the natural next step. |
| **Product Spec** | Add policy suggestion engine as a product capability. Define the telemetry pipeline requirements. Define the suggestion generation and delivery workflow. |
| **Policy Format Spec** | Policies need metadata indicating origin: `source: "suggested"` vs `source: "user-created"` vs `source: "template"`. Suggested policies should include the observation data that justified them. |
| **Security Architecture** | Telemetry pipeline security: what data flows to the hosted service, how it's secured, what redaction controls exist. The suggestion engine processes action data — what privacy implications exist? |
| **Pricing Model** | Clarify that observation (visibility) is part of the free tier. Suggestions may be gated by tier (basic suggestions free, full LLM-powered suggestions in usage/enterprise tier). |

---

## GTM Messaging Updates

This section records the messaging proposed with the decision. It does not describe what is built.

### Primary Message

**Before:** "hiitl is the control point for software that can act. A deterministic boundary for AI between decision and execution."

**After:** "See what your AI agents are doing. Then take control."

The original message is still true and still used — but it's the explanation, not the hook. The hook is visibility. The developer's immediate reaction should be "I want that" not "I need to understand what a deterministic boundary is."

### The Two-Step Value Proposition

1. **Visibility** — one line of code, see everything your agents do. Immediate, free, zero config.
2. **Control** — ECP suggests the policies you need based on what it observes. One-click to activate.

### Positioning Lines

- "One line of code. Complete visibility into your AI agent's behavior."
- "ECP learns your application and suggests the policies you need."
- "From zero to governed in days, not weeks."
- "LangChain gets you into the mess, Datadog gives you a front row seat when it goes wrong, add ECP and you take back control to survive production."
- "Do you know what your agents are actually doing in production?"

### Audience-Specific Messaging

**Developers:** "Do you know what your agents are actually doing? Add `hiitl.evaluate()` and find out. ECP observes your agents, suggests the controls you need, and enforces them in microseconds."

**Engineering leadership:** "Your team is shipping AI agents into production. ECP gives you visibility into what they're doing and suggests the controls your team should have in place — without slowing anything down."

**Compliance/security:** "ECP doesn't just give you a control point — it tells you if your controls are sufficient. Every action recorded, every policy graded, every gap identified."

### Website Structure

**Hero:** "See what your AI agents are doing. Then take control."

Subtext: "Add one line of code. ECP observes your agents, suggests the policies you need, and enforces them at runtime — in microseconds."

**Three-step visual:**
1. **Instrument** -- show `hiitl.evaluate("send_payment", parameters=params)` -- one line
2. **Observe** — dashboard showing agent behavior patterns
3. **Control** — suggested policies with one-click accept

**How it works:**
- "Evaluation runs locally in your application — microsecond latency, zero network overhead. Policy management, audit trails, and intelligence run in the cloud. Your agents stay fast. Your team stays informed."

**CTA:** "Start free — see what your agents are doing" (not "configure your control point")

---

## Pricing Model Clarification

### How Hybrid Mode Affects Pricing

This section records the pricing model proposed with the decision. It is not a price list. Features marked "not built" below do not exist yet.

Local evaluation is free and unlimited. The SDK evaluator is never throttled, crippled, or artificially limited. This is critical for developer trust and adoption.

Revenue comes from the hosted service — the things that require cloud infrastructure and provide value beyond local evaluation:

**Free tier:**
- Full SDK with local evaluation (unlimited)
- Telemetry sync to hosted service (Python SDK)
- Dashboard with agent behavior visibility
- Up to ~10K actions/month synced
- Basic policy suggestions (rule-based heuristics after observation)
- Community support

**Usage tier ($200-$2,000/month):**
- Higher action volume (10K-250K/month synced)
- Full LLM-powered policy suggestion engine
- Policy grading and assessment
- Extended audit retention (not built)
- Testing and synthetic data tools
- Webhook integrations (not built)
- Email support

**Enterprise ($75K-$250K+ ARR):**
- Unlimited synced actions
- Security Tier 2 (multi-party approval, hash chains, anomaly detection) (not built)
- Routes (formerly HITL configs) with managed routing (managed routing not built)
- Reviewer Cockpit (today: a review page that lists pending cases to approve, reject or modify)
- GRC integrations (one-click Vanta/Drata) (not built)
- Policy assessment against compliance standards
- Custom retention (not built) and SLA
- Dedicated support

**What's metered (metering is not built):** Actions synced to the hosted service. This is tracked via the audit records the sync engine ships. The developer never feels metered on the evaluation itself — only on the cloud intelligence and storage.

**The upgrade triggers:**
- **Free → Usage:** Action volume exceeds 10K/month, or team wants full suggestion engine and grading
- **Usage → Enterprise:** Team needs security tiers, compliance features, HITL routing, or SLA commitments

---

## Quickstart Guide Structure

### Primary Quickstart: "See What Your Agents Are Doing in 5 Minutes"

**Target:** Developer with an AI agent that calls tools. Any framework.

**Steps:**
1. `pip install hiitl` (or `npm install @hiitl/sdk`)
2. `hiitl = HIITL(api_key="...")` — get API key from dashboard
3. Wrap your agent's tool calls with `hiitl.evaluate(action, parameters=params)` -- show 2-3 examples
4. Run your application
5. Open your dashboard — see every action your agent takes

**Ends with:** how to run an analysis of the recorded actions and review the proposed policies on the dashboard's **Suggestions** page.

No mention of writing policies. No mention of envelopes, schemas, or evaluation order. Just: instrument, run, see.

### Framework-Specific Quickstarts

- "ECP + LangChain in 5 minutes" -- shows exactly where to add `evaluate()` in LangChain tool execution
- "ECP + OpenAI Agents in 5 minutes" — shows integration with OpenAI function calling
- "ECP + Custom Agent Loop in 5 minutes" — generic pattern for any agent architecture

Each follows the same structure: install, configure, wrap tool calls, run, see results. They are written as sections of the [integration examples](../onboarding/integration_examples.md), with CrewAI, AutoGen and the Vercel AI SDK alongside.

### Secondary Guide: "Writing Your First Policy"

For developers who want to skip observation and write policies immediately. This guide exists but is NOT the default onboarding path. It covers:
- Policy file structure (JSON, or YAML)
- Basic rule syntax (`conditions` / `decision`)
- Loading policies (local file, or `POST /v1/policies`; the dashboard shows policies but does not edit them)
- Testing a policy against a sample action
- Seeing the policy in action

### Tertiary Guide: "Understanding Policy Suggestions"

Explains how the suggestion engine works, how to review suggestions, how to modify before accepting, how to dismiss, and how to provide feedback that improves future suggestions.

---

## API Documentation Structure

### SDK API Reference (Developer-Facing)

The primary developer documentation. Short, practical, copy-paste-ready.

**Core functions:**
- `HIITL(api_key, ...)` — initialize the SDK. Options for environment, agent_id, sync settings.
- `hiitl.evaluate(action, parameters=..., **options)` -- evaluate an action. Returns a decision.
- `hiitl.status()` (Python) — mode, sync state, cached policy version and cache age, circuit breaker state.

**Decision object:**
- `result.ok` — boolean, true if action is allowed
- `result.decision` — full decision type (ALLOW, BLOCK, PAUSE, RATE_LIMIT, etc.)
- `result.reason_codes` — the reason codes for the decision; on a block, `result.remediation` carries a human-readable message
- `result.needs_approval` — boolean, true if action requires human review
- `result.resume_token` — a token on approval, pause and escalation decisions, to match the reviewer's response
- `result.timing` — evaluation latency metadata

`ok` and `needs_approval` are Python properties. The TypeScript decision has none of these helpers: check `allowed` and `decision`.

**Configuration options:**
- Sync intervals and the telemetry level, which sets telemetry redaction (Python, through `SyncConfig`); cache location (`cache_dir`); cold-start behavior (`cold_start_behavior`)

### Hosted API Reference (Management + Intelligence)

The API that powers the dashboard and is accessible to agentic coding tools.

**Policy management:** create (each create is a new version, and the newest is active), list, read, change history with diffs, rule lifecycle (stage, promote, rollback)
**Audit queries:** List with filters, read one record
**Suggestions:** Run an analysis, list suggested policies, accept, modify, dismiss
**Testing:** Regression reports for a staged rule against recorded traffic
**Routes (formerly HITL configs):** Create, list, read; versioned
**System:** Health, metrics
**Integrations:** Webhook configuration, partner connections (not built)

---

## Summary of Phase 0 Additions

These items should be added to the Phase 0 specification work:

| Spec | New/Updated | What to Define | Status (0.2.0) |
|---|---|---|---|
| **SDK Sync Engine Spec** | New | Sync protocol, batching, compression, retry behavior, conflict resolution, cache persistence format, startup behavior | Written: [sync engine spec](../specs/sync_engine.md) |
| **Telemetry Schema** | New | What telemetry the SDK ships, field definitions, redaction controls, privacy boundaries | Written: [telemetry schema](../specs/telemetry_schema.md) |
| **Suggestion Engine Interface** | New | Input (telemetry), output (suggested policies), delivery mechanism (dashboard + API), acceptance workflow | Built: the analysis reads the recorded actions (audit records) and runs on demand (`POST /v1/suggestions/analyze`); suggestions are reviewed on the Suggestions page |
| **Envelope Schema** | Updated | Ensure `evaluate(action, params)` maps cleanly to envelope construction with minimal required fields | Done: only `action` is required at the call site; the SDK fills in the rest |
| **Policy Format Spec** | Updated | Add `source` metadata (suggested/user-created/template), observation data references on suggested policies | Partly: a rule accepted from a suggestion carries `suggested_by` lineage, and a forked template carries `metadata.template.source`. There is no user-created marker and no observation data reference |
| **Decision Response Spec** | Updated | Ensure `result.ok` boolean convenience property alongside full decision detail | Python only (`ok`, `blocked`, `needs_approval`, `observed`); the TypeScript decision has no helpers |

## Summary of Phase 1 Additions

These capabilities should be added to the Phase 1 implementation scope:

| Capability | Priority | Notes | Status (0.2.0) |
|---|---|---|---|
| SDK sync engine (policy pull, audit push, telemetry push) | High | Core architecture — everything depends on this | Built in both SDKs; telemetry push from the Python SDK only |
| Local cache with disk persistence | High | SDK must work across restarts | Built in both SDKs |
| Telemetry pipeline (SDK → hosted service) | High | Required for observation phase and suggestions | Built from the Python SDK. Suggestions read the audit records instead |
| Dashboard: agent behavior visibility | High | First value moment for new users | Built: the Audit page lists every recorded call; the Behavior page reads the Python SDK's telemetry |
| `evaluate(action, params)` with zero-config allow-all behavior | High | The one-line onboarding | Built: with no policy, every call comes back `OBSERVE` with `allowed` true |
| Basic policy suggestions (rule-based heuristics) | Medium | "You have no kill switches" level — doesn't require ML | Built; the analysis runs on demand (`POST /v1/suggestions/analyze`) |
| Dashboard: suggested policies with accept/modify/dismiss | Medium | The second value moment | Built: the Suggestions page offers accept and dismiss; modify is through the API (`PATCH /v1/suggestions/{suggestion_id}`) |
| Framework-specific quickstarts (LangChain, OpenAI, custom) | Medium | Adoption accelerators | Written as sections of the [integration examples](../onboarding/integration_examples.md) |
| Full LLM-powered suggestion engine | Later (Phase 2) | Requires sufficient telemetry data and ML infrastructure | An LLM-assisted pass runs within the same analysis when the hosted service has a model configured |
