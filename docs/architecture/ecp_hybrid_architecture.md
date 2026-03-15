# ECP Architectural Evolution — Hybrid Mode & Inferred Policies

## Purpose

This document describes two interconnected architectural decisions that significantly affect the SDK design, onboarding flow, product architecture, GTM messaging, pricing model, and documentation. These should be incorporated into the ECP planning and specification documents.

These are not incremental features. They change the default product architecture and the primary onboarding motion.

---

## Decision 1: Hybrid Mode as the Default Product Architecture

### What It Is

The SDK is not a thin HTTP client that calls a hosted service for every evaluation. It is a **local evaluator with a cloud sync engine.** Evaluation happens in-process at microsecond latency. Policy management, audit aggregation, telemetry, and intelligence features live in the hosted service and sync in the background.

This is analogous to how CDNs work: content is cached at the edge for speed, managed at the origin for control. ECP caches policies locally in the SDK for fast evaluation, manages them in the hosted service for visibility and intelligence.

### How It Works

The SDK has three internal components:

**1. The Evaluator** — runs in-process, evaluates actions against cached policies. This is the hot path. Pure computation, no I/O, no network calls. Microsecond latency.

**2. The Sync Engine** — background process that maintains a connection to the hosted service:
- **Pulls:** policy updates (new versions, activations, deactivations), HITL config updates, kill switch state, rate limit configuration
- **Pushes:** audit records (batched, compressed, async), telemetry (action patterns, decision distributions, timing metrics), rate limit counter updates
- Handles connection failures gracefully: buffers locally, syncs on recovery
- The sync engine never blocks the evaluator. If the hosted service is unreachable, evaluation continues against cached policies. Audit records buffer locally and flush when connectivity returns.

**3. The Local Cache** — policies, HITL configs, rate limit counters, kill switch state. All in memory for fast access. Persisted to disk so the SDK works across restarts without requiring an immediate sync.

### SDK Startup Behavior

- **First run (no cache):** No policies cached. All actions are allowed and logged (observation phase). Sync engine connects to hosted service, pulls any existing policies. If no policies exist yet, observation continues.
- **Subsequent runs:** Load policies from local disk cache. Begin evaluating immediately against cached policies. Sync engine connects in background and pulls any updates. The SDK is functional from the first millisecond, even before the first sync completes.

### Three Deployment Modes

**Hybrid mode (default, recommended for production):** SDK connects to hosted service for sync. Evaluation is local. This is the default when an API key is configured. The developer doesn't think about "local vs hosted" — they configure an API key and the SDK handles everything.

**Pure local mode (development, air-gapped):** No hosted connection. Policies loaded from local files. Audit written to local storage. No telemetry, no sync, no cloud features. Useful for development, CI/CD, and environments that cannot connect to external services.

**Pure hosted mode (optional, for teams that prefer it):** Every evaluation makes a network call to the hosted service. Higher latency (low tens of ms instead of microseconds). Useful for teams that want zero local state and accept the latency trade-off.

### What This Changes

**SDK architecture:** The SDK is no longer a simple HTTP client wrapper. It contains the evaluator, a sync engine, a local cache with disk persistence, and connection management. Both the Python and TypeScript SDKs need this architecture. The sync engine is a new component that needs its own specification.

**Latency profile:** The hot path (evaluation) has zero network dependency in hybrid mode. Latency is determined by in-process computation only. The "single-digit ms locally, low tens of ms hosted" latency requirement becomes "microsecond evaluation in hybrid mode" — significantly better than originally specified.

**Resilience:** The SDK continues operating during hosted service outages. This eliminates the "what if your service is down?" objection entirely. The circuit breaker and fail-mode specifications still apply but become less critical since the primary failure mode (hosted service unreachable) doesn't affect evaluation.

**Metering:** Actions are metered via the audit records synced to the hosted service. The hosted service sees every action (with a sync delay), enabling usage-based pricing without affecting evaluation latency.

### Implications for Existing Documentation

| Document | Required Updates |
|---|---|
| **Project requirements — SDK Requirements** | Rewrite SDK architecture to describe three components (evaluator, sync engine, local cache). Update deployment modes (hybrid/local/hosted). Update latency requirements (microsecond evaluation in hybrid mode). |
| **Project requirements — Infrastructure Specs** | Update "Control Plane Outage Behavior" — hybrid mode means outages don't affect evaluation, only sync. Update "Storage & Durability" — local cache persistence requirements. |
| **Infrastructure Analysis** | Rewrite "What Kind of System Is ECP" — it's a local evaluator with a cloud intelligence backend, not just an inline enforcement gateway. Update deployment topology diagrams. |
| **Product Spec — Adoption/Integration Path** | Update to reflect that the SDK is self-contained with cloud sync, not a client that calls a server. |
| **Decision Response Spec** | No change — decision format is the same regardless of where evaluation happens. |
| **Security Architecture** | Add analysis of the sync engine as a new data flow. Telemetry security: what data is shipped, encryption in transit, redaction controls on telemetry. Policy sync integrity: how the SDK verifies that synced policies are authentic and untampered (policy content hashing applies here). |

---

## Decision 2: Inferred Policies and the Observe-First Onboarding

### What It Is

ECP's default onboarding path requires zero policy configuration. The developer instruments their agent's actions with `hiitl.evaluate()`, runs their application, and ECP observes the behavior patterns. After sufficient observation, the hosted service generates suggested policies specific to the application's actual behavior. The developer reviews and accepts suggestions with one click.

This solves the cold-start problem: developers don't need to know what policies to write. ECP tells them.

### The Onboarding Sequence

**Minute 0-5: Install and instrument.**

```python
pip install hiitl
```

```python
from hiitl import HIITL

hiitl = HIITL(api_key="...")

# Wrap each agent action — one line per action
result = hiitl.evaluate("send_payment", {"amount": 500, "to": "vendor_123"})
if result.ok:
    actually_send_payment(...)

result = hiitl.evaluate("query_user_data", {"user_id": "usr_456"})
if result.ok:
    actually_query_data(...)
```

No policies configured. No policy files created. The developer doesn't encounter the word "policy" during initial setup. All actions are allowed and logged.

**Day 1-3: Observation phase.**

The SDK logs every action locally and syncs telemetry to the hosted service. The developer can see their agent's behavior in the dashboard immediately: every tool call, parameters, frequency patterns, timing. This is the first value moment — visibility into agent behavior that didn't exist before.

**Day 3-7: Suggestions arrive.**

The hosted service analyzes observed behavior patterns and generates suggested policies. Suggestions appear in the dashboard, each one specific and explained:

- "Your payment-agent processes amounts between $10-$800. **Suggested: flag amounts over $2,000 for review, block over $10,000.**"
- "Your data-agent queries user records ~150/hour. **Suggested: rate limit at 200/hour, alert at 180.**"
- "Your agent calls delete_record occasionally. **Suggested: require approval for all delete operations.**"
- "No kill switch exists for any agent. **Suggested: add kill switches for each agent.**"

Each suggestion is one-click accept. Accepted policies sync to the SDK's local cache via the sync engine. Enforcement begins on the next sync cycle.

**Day 7+: Refinement.**

The developer modifies accepted policies, adds custom rules, writes their own policies for edge cases. Testing and grading tools help them iterate. Policy assessment reports show coverage gaps. The full policy design workflow is available for those who want it.

### What the Suggestion Engine Needs

**Input:** Telemetry data from the SDK — tool names, parameter distributions, action frequency, timing patterns, agent identifiers, decision history.

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

**Important: Suggestions are never auto-applied.** The developer always reviews and accepts. ECP observes and recommends; the human decides. This is both a trust requirement (developers won't trust auto-applied rules) and philosophically consistent with the HIITL mission (human intelligence in the loop — even for the policies themselves).

### The Suggestion Engine as a Product

The suggestion engine is not a Phase 1 feature in full. But the telemetry pipeline that feeds it IS Phase 1, because the SDK needs to ship telemetry from day one for the observation phase to work.

**Phase 1:** SDK ships telemetry. Dashboard shows agent behavior (visibility). Basic suggestions possible with rule-based heuristics (e.g., "you have no kill switches" doesn't require ML, just inspection).

**Phase 2:** LLM-powered suggestion engine that analyzes telemetry patterns and generates context-aware policy suggestions. This is where the "ECP learns your application" promise is fully realized.

**Phase 3:** Continuous suggestion refinement based on ongoing observation, policy grading results, and human review patterns (the feedback loop from Section 8 of the Strategic Evolution doc).

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

### Primary Message

**Before:** "HIITL is the control point for software that can act. A deterministic boundary for AI between decision and execution."

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
1. **Instrument** -- show `hiitl.evaluate("send_payment", params)` -- one line
2. **Observe** — dashboard showing agent behavior patterns
3. **Control** — suggested policies with one-click accept

**How it works:**
- "Evaluation runs locally in your application — microsecond latency, zero network overhead. Policy management, audit trails, and intelligence run in the cloud. Your agents stay fast. Your team stays informed."

**CTA:** "Start free — see what your agents are doing" (not "configure your control point")

---

## Pricing Model Clarification

### How Hybrid Mode Affects Pricing

Local evaluation is free and unlimited. The SDK evaluator is never throttled, crippled, or artificially limited. This is critical for developer trust and adoption.

Revenue comes from the hosted service — the things that require cloud infrastructure and provide value beyond local evaluation:

**Free tier:**
- Full SDK with local evaluation (unlimited)
- Telemetry sync to hosted service
- Dashboard with agent behavior visibility
- Up to ~10K actions/month synced
- Basic policy suggestions (rule-based heuristics after observation)
- Community support

**Usage tier ($200-$2,000/month):**
- Higher action volume (10K-250K/month synced)
- Full LLM-powered policy suggestion engine
- Policy grading and assessment
- Extended audit retention
- Testing and synthetic data tools
- Webhook integrations
- Email support

**Enterprise ($75K-$250K+ ARR):**
- Unlimited synced actions
- Security Tier 2 (multi-party approval, hash chains, anomaly detection)
- HITL configs with managed routing
- Reviewer Cockpit
- GRC integrations (one-click Vanta/Drata)
- Policy assessment against compliance standards
- Custom retention and SLA
- Dedicated support

**What's metered:** Actions synced to the hosted service. This is tracked via the audit records the sync engine ships. The developer never feels metered on the evaluation itself — only on the cloud intelligence and storage.

**The upgrade triggers:**
- **Free → Usage:** Action volume exceeds 10K/month, or team wants full suggestion engine and grading
- **Usage → Enterprise:** Team needs security tiers, compliance features, HITL routing, or SLA commitments

---

## Quickstart Guide Structure

### Primary Quickstart: "See What Your Agents Are Doing in 5 Minutes"

**Target:** Developer with an AI agent that calls tools. Any framework.

**Steps:**
1. `pip install hiitl` (or `npm install hiitl`)
2. `hiitl = HIITL(api_key="...")` — get API key from dashboard
3. Wrap your agent's tool calls with `hiitl.evaluate(action, params)` -- show 2-3 examples
4. Run your application
5. Open your dashboard — see every action your agent takes

**Ends with:** "Within a few days, ECP will suggest policies based on your agent's actual behavior. Find them in your dashboard under Suggested Policies."

No mention of writing policies. No mention of envelopes, schemas, or evaluation order. Just: instrument, run, see.

### Framework-Specific Quickstarts

- "ECP + LangChain in 5 minutes" -- shows exactly where to add `evaluate()` in LangChain tool execution
- "ECP + OpenAI Agents in 5 minutes" — shows integration with OpenAI function calling
- "ECP + Custom Agent Loop in 5 minutes" — generic pattern for any agent architecture

Each follows the same structure: install, configure, wrap tool calls, run, see results.

### Secondary Guide: "Writing Your First Policy"

For developers who want to skip observation and write policies immediately. This guide exists but is NOT the default onboarding path. It covers:
- Policy file structure (JSON)
- Basic rule syntax (`when` / `then`)
- Loading policies (local file or dashboard)
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
- `hiitl.evaluate(action, params, **options)` -- evaluate an action. Returns a decision.
- `hiitl.status()` — sync state, cached policy version, connection health, action counts.

**Decision object:**
- `result.ok` — boolean, true if action is allowed
- `result.decision` — full decision type (ALLOW, BLOCK, PAUSE, RATE_LIMIT, etc.)
- `result.reason` — human-readable reason for the decision
- `result.needs_approval` — boolean, true if action requires human review
- `result.resume_token` — token for resuming paused actions
- `result.timing` — evaluation latency metadata

**Configuration options:**
- Sync interval, cache location, telemetry controls, redaction settings, fail mode

### Hosted API Reference (Management + Intelligence)

The API that powers the dashboard and is accessible to agentic coding tools.

**Policy management:** CRUD, versioning, activation, diff viewing
**Audit queries:** Search, filter, export
**Suggestions:** List suggested policies, accept, modify, dismiss
**Testing:** Run tests, view results, grading reports
**HITL configs:** CRUD, versioning
**System:** Health, metrics, sync status
**Integrations:** Webhook configuration, partner connections

---

## Summary of Phase 0 Additions

These items should be added to the Phase 0 specification work:

| Spec | New/Updated | What to Define |
|---|---|---|
| **SDK Sync Engine Spec** | New | Sync protocol, batching, compression, retry behavior, conflict resolution, cache persistence format, startup behavior |
| **Telemetry Schema** | New | What telemetry the SDK ships, field definitions, redaction controls, privacy boundaries |
| **Suggestion Engine Interface** | New | Input (telemetry), output (suggested policies), delivery mechanism (dashboard + API), acceptance workflow |
| **Envelope Schema** | Updated | Ensure `evaluate(action, params)` maps cleanly to envelope construction with minimal required fields |
| **Policy Format Spec** | Updated | Add `source` metadata (suggested/user-created/template), observation data references on suggested policies |
| **Decision Response Spec** | Updated | Ensure `result.ok` boolean convenience property alongside full decision detail |

## Summary of Phase 1 Additions

These capabilities should be added to the Phase 1 implementation scope:

| Capability | Priority | Notes |
|---|---|---|
| SDK sync engine (policy pull, audit push, telemetry push) | High | Core architecture — everything depends on this |
| Local cache with disk persistence | High | SDK must work across restarts |
| Telemetry pipeline (SDK → hosted service) | High | Required for observation phase and suggestions |
| Dashboard: agent behavior visibility | High | First value moment for new users |
| `evaluate(action, params)` with zero-config allow-all behavior | High | The one-line onboarding |
| Basic policy suggestions (rule-based heuristics) | Medium | "You have no kill switches" level — doesn't require ML |
| Dashboard: suggested policies with accept/modify/dismiss | Medium | The second value moment |
| Framework-specific quickstarts (LangChain, OpenAI, custom) | Medium | Adoption accelerators |
| Full LLM-powered suggestion engine | Later (Phase 2) | Requires sufficient telemetry data and ML infrastructure |
