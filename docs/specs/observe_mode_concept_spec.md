# Observe Mode: The Intelligent Control Layer

> **Status (2026-05-18)**: Policy versioning direction changed.
> The Sprint B refresh (2026-05-16) described observe-mode lifecycle
> as **per-rule** (each rule has its own `lifecycle_stage`; staged
> rules evaluate alongside active rules within a single active
> policy). The corrected V1.0 model is **per-policy**: a policy is
> in one lifecycle state; multiple policies can be active simultaneously
> for the same `(org_id, environment)`; staged policies evaluate
> alongside active ones; **merge** or **promote** integrates them.
>
> The `lifecycle_stage` field on individual rules from Block 1A
> remains in the schema as metadata but is no longer the operational
> mechanism. Multi-active-policy evaluation is **🟡 new architecture
> landing in Wave 9.2.5** — the evaluator currently loads one active
> policy per `(org_id, environment)`.
> This spec describes the V1.0 target the dashboard and intelligence
> layer build toward.
>
> See the conversation transcript on 2026-05-17/18 for the full
> rationale: convention-based "remember to think per-rule" was the
> wrong primary mental model. Policy-level lifecycle + composition
> is clearer for operators ("I have a security policy, a compliance
> policy, and a fraud policy — they compose; I'm testing a new
> escalation policy alongside them") and easier to enforce in the
> schema once multi-active-policy is wired.

## What This Document Is

This is the concept spec for hiitl's observe mode — the core product experience that turns raw system observation into a deployable, testable, continuously improving control layer. This isn't a new idea. It's the convergence of concepts that have been evolving across sessions: the suggestion engine, the pattern repository, context enrichment suggestions, observe-first onboarding, the route ecosystem, and the developer-supplied context model. This document assembles them into the coherent product experience.

**Implementation:** the suggestion engine, the analyzers and lenses (5 lenses, and the guidance analyzer of Block 4b-2),
the rule lifecycle and the regression reports run in the hosted service; the dashboard surfaces them (suggestion cards;
a policy's lifecycle progression and its regression reports).

## The Problem Observe Mode Solves

A developer building autonomous systems faces a cold start problem: they know they need controls, but they don't know what controls they need, what policies to write, what their envelope should contain, what services to connect, or what the right thresholds are for their specific system. They're not governance experts. They're builders.

Today, the options are: hire a consultant to analyze your system and recommend controls (expensive, slow, one-time), copy generic best practices from documentation (not calibrated to your system), or build it yourself through trial and error (fragile, incomplete, never finished).

Observe mode replaces all of that. Install hiitl, call evaluate() on your actions, and the system analyzes your actual behavior and produces a deployable control layer — policies, envelope enrichments, routes, kill switches — calibrated to your specific system, backed by your real data, and adoptable in clicks.

---

## How It Works

### Phase 1: Collection

When a developer calls evaluate() with no policies configured, every action is allowed. But every action is recorded. ECP collects:

- Which agents exist and what they do
- Which tools each agent calls and how frequently
- What parameters are typical for each action type
- What the volume and distribution patterns look like (time of day, per user, per environment)
- What parameter values suggest about risk (amounts, recipient types, data classifications)
- What's missing from the envelope that would enable better governance

This collection happens from the first evaluate() call. Within hours of production traffic, ECP has a meaningful picture of the system.

### Phase 2: Analysis

The analysis engine processes observation data at increasing levels of sophistication:

**Structural observation (hours).** No AI required — pure pattern recognition. Which agents exist, what tools they call, how often, what the volume looks like. This produces the system map: a complete picture of the developer's autonomous system that most developers don't have themselves.

**Risk surface identification (days).** Heuristic analysis on structured data. Scanning parameter values for patterns that indicate risk — amounts that suggest financial transactions, fields that look like PII, actions that target external recipients, operations that modify or delete data. Identifying missing envelope fields that would enable better policies.

**Policy generation (week+).** The intelligence layer — powered by the pattern repository and advisor engine — generates specific, deployable policy configurations calibrated to the developer's actual traffic patterns. Rate limits based on observed p95 volumes. Spend thresholds based on actual transaction ranges. Sensitivity classifications based on observed parameter patterns.

**Route recommendation (ongoing).** Based on observed system characteristics, the engine identifies which external services would address specific gaps. Financial transactions → fraud detection services. PII in external communications → content governance services. Irreversible operations → backup services. High-stakes decisions → human review workflows. Regulated data → confidential computing services.

### Phase 3: Presentation — The Dashboard

Analysis results appear as cards on the dashboard. Each card is a self-contained, deployable component — not a recommendation to think about, but an artifact to adopt.

---

## Card Types

The suggestion engine emits **eight card types** today, each backed by a specific analyzer or lens. The eight are:

| `suggestion_type` | Source | Status |
|---|---|---|
| `policy_rule` | Behavior lenses (security, operational, ux, waste, compliance) | ✅ Built |
| `kill_switch` | Operational lens — agent without emergency-stop coverage | ✅ Built |
| `rate_limit` | Operational lens — observed traffic exceeds safe defaults | ✅ Built |
| `route_sync` | Compliance / security lenses — synchronous external eval needed | ✅ Built (sync suggested; route execution Phase 1.5) |
| `route_async` | Operational / compliance lenses — async telemetry / evidence shipping | ✅ Built |
| `context_enrichment` | Behavior lenses — envelope fields would unlock additional policies | ✅ Built (JSON artifact; code-snippet generation is 🟡 deferred) |
| `coverage_gap` | Coverage analyzer — actions with zero policy coverage | ✅ Built |
| `guidance_to_policy` | Guidance analyzer (Block 4b-2) — joins scanner-uploaded guidance findings × audit events | ✅ Built; distinct UI card layout (Block 4b-3) |

Each card carries a `suggestion_type`, `lens`, `priority`, structured `evidence` blob, and (when applicable) the deployable artifact: `suggested_policy`, `suggested_route`, or `context_enrichment`.

### Policy Cards (`policy_rule`)

A policy card contains everything needed to activate a specific policy.

**What the developer sees:**

- **Title:** "Rate limit send_email to 60/hour per agent"
- **Why:** "Based on 7 days of observation, your agent intake-bot averages 47 send_email calls per hour. This policy protects against runaway execution while allowing 25% headroom above normal volume."
- **Retrospective:** "In the last 7 days, this policy would have triggered 0 times on normal traffic. It would have caught the spike on Tuesday at 2pm where your agent sent 112 emails in one hour."
- **The policy:** Complete, deployable JSON — the actual artifact the policy engine consumes, not pseudocode.
- **Action:** "Accept" button. One click. Accept creates a **new staged policy** containing the suggested rule (lifecycle_stage on the policy: `staged`). The new policy evaluates alongside existing active policies but does NOT bind decisions — see lifecycle below.

### Kill Switch Cards (`kill_switch`)

- **Title:** "Add kill switch for agent intake-bot"
- **Why:** "You have no emergency stop mechanism for this agent. A kill switch lets you halt all actions from intake-bot instantly without affecting other agents."
- **Status on accept:** Creates a new policy in `disabled` state containing a single KILL_SWITCH rule. Distinct from policy_rule cards because kill switches are pure off-switches — there's nothing to observe in staged mode. An operator flips the policy to `active` during an incident; until then it stays inert. (The KILL_SWITCH rule itself retains a `lifecycle_stage` field for metadata symmetry, but it has no operational meaning when the containing policy is disabled.)

### Rate Limit Cards (`rate_limit`)

Variant of policy_rule for `RATE_LIMIT` decisions. Same lifecycle flow (accept → staged policy → merge or promote); emitted separately so the UI can present a different threshold-tuning UX.

### Route Cards (`route_sync` / `route_async`)

Two suggestion types because the lifecycle differs. **Sync routes** participate in the decision (the action waits for the route's response). **Async routes** never touch the hot path (observability, evidence shipping, alerting). The dashboard surfaces them in the same shape but the UX clarifies impact:

**Sync route card:**

- **Title:** "Add fraud detection for payment transactions"
- **Why:** "Your agent finance-bot processes payments ranging from $50 to $45,000. 3% of transactions exceed $10,000."
- **Estimated impact:** "+200ms p95 latency for matching transactions" — sync routes add latency by design.
- **Suggested route config:** Complete config — endpoint, response schema, timeout, fail-mode.
- **Action:** "Accept" — the route lands in the org's route configs and is referenced by the matching policy rule's `route` field.

**Async route card:**

- **Title:** "Ship audit events to Datadog"
- **Why:** "You have 3 agents generating 2,400 actions per day. Connecting Datadog gives you real-time visibility..."
- **Estimated impact:** "Zero — events batch every 30s; evaluate() latency unaffected."
- **Action:** "Accept" — same.

### Context Enrichment Cards (`context_enrichment`)

A context-enrichment card identifies envelope fields that would unlock additional policies if the developer populated them.

**What the developer sees today:**

- **Title:** "Add sensitivity flags to send_email actions"
- **Why:** "12% of your send_email calls include parameters that appear to contain PII (email addresses, phone numbers in the body field). Declaring sensitivity enables PII-aware policies."
- **`envelope_requirements`:** Structured JSON describing the fields to add — used by future tooling to render a copy-able snippet.
- **Action:** Accept — records the developer's intent to add the fields. **🟡 Code-snippet generation is not yet built**; the card today is informational. Snippet generation lands when there's enough framework-integration content to make the snippets reliably accurate.

### Coverage Gap Cards (`coverage_gap`)

- **Title:** "No policies cover `update_inventory`"
- **Why:** "You have 1,247 actions for `update_inventory` in the last 14 days. Zero active rules match it. Even an OBSERVE rule would give you visibility."
- **Action:** "Acknowledge" — signals the operator has seen the gap. No artifact is generated automatically (coverage gaps are flagged for human decision; auto-generating an OBSERVE rule for every uncovered action would spam policies). The card stays surfaced until the gap is closed by a manually-added rule.

### Guidance-to-Policy Cards (`guidance_to_policy`) — Block 4b-2 / 4b-3

The bridge between **what your instruction files say** and **what your infrastructure enforces**. Read the dedicated section below for the full workflow.

**Distinct UI** (Block 4b-3): amber accent + "Guidance only" badge differentiates these from engine-inferred suggestions. Operator immediately recognizes "this is a rule I already wrote that's not yet enforced."

### Planned card type: Human Collaboration

> **🟡 Planned, not built.** The spec previously listed "Human Collaboration Cards" as a card type with its own dashboard treatment. The underlying capability — pausing execution for human review via routes — is fully built (Block 3a/3b: review case API, pg_notify/SSE, MCP proxy integration). What's NOT built: a dedicated suggestion card type that recommends "add human review here." Today human-review setup is route-card territory (`route_sync` with a human-review provider). A dedicated card lands when there's enough data to recommend human review based on observed value-at-stake patterns.

---

## The Policy Lifecycle

No policy goes from recommended to enforced in one step. The unit of lifecycle is the **policy**, not the individual rule. A policy is in one state; the state determines whether its rules bind decisions or merely observe. Five states exist; the lifecycle UI on `PolicyDetailPage` surfaces transitions and history for each policy.

> **🟡 Architecture note (Wave 9.2.5):** Multi-active-policy evaluation
> is new architecture landing in Wave 9.2.5. The current evaluator
> loads one active policy per `(org_id, environment)`. The model below
> describes the V1.0 target. Until 9.2.5 lands, accept-flow UX
> behaves as-if-but-isn't: a "staged policy" today is a staged
> rule within the single active policy. The user-facing operations
> (accept, merge, promote) and the conceptual model are the same
> in both worlds; only the storage shape changes underneath.

### The five states

| State | Evaluator behavior | Typical entry path |
|---|---|---|
| `draft` | Skipped entirely. Visible in the UI but doesn't evaluate. | Manually authored and held back before any go-live |
| `staged` | Evaluates against live traffic; emits "would have" decisions as `staged_observations` on every Decision; does NOT bind. | **Default landing state for accepted policy_rule / rate_limit suggestions** (creates a new staged policy). |
| `active` | Binds decisions. The first matching active rule across all active policies (by priority within and across) drives the actual ALLOW/BLOCK/PAUSE outcome. | Promoted from `staged` after regression report review |
| `disabled` | Skipped entirely. Distinct from `draft` — the policy was once active and was turned off. | Kill-switch policies land here; flipped to `active` during incidents |
| `archived` | Skipped entirely. Distinct from `disabled` — explicitly retired, kept for audit history. | Old policies being replaced |

### Composition — what "multiple active policies" means

The evaluator walks every active policy in priority order, producing a single Decision. **Composition emerges through envelope enrichment**: a route response from one policy's rule lands as an envelope field, which a later policy's rule can match against. Example:

> Security policy fires a `route_sync` to a fraud check → fraud score lands on the envelope → compliance policy's threshold rule sees the score → routes to human review → reviewer response enriches the envelope further → audit policy emits to Datadog.

Three perspectives — security, compliance, operations — composing on one action through configuration. No integration code, no orchestration glue. **That composition story is the load-bearing differentiator** for the policy-level direction; it's why per-rule lifecycle within one mega-policy was the wrong primary model.

Staged policies participate in this walk too, but produce `staged_observations` instead of binding the outcome.

### Suggestion → Staged Policy

The developer clicks "Accept" on a `policy_rule` (or `rate_limit`) card. The engine creates **a new staged policy** containing the suggested rule(s). The new policy evaluates against live traffic immediately, but only emits `staged_observations` — none of its rules bind the actual Decision.

This is the **side-by-side evaluation** model: active policies and staged policies walk together in a single pass. The Decision response carries `staged_observations: [...]` (always an array; empty when no staged policy matched). Filters (scope / temporal / percentage) apply identically to staged and active policies.

### Staged → Regression Report

Each staged policy carries an `observation_window_days` (default 7). After the window, an auto-trigger or manual trigger generates a regression report comparing what the staged policy would have decided against what the active policies actually decided over the window.

The regression report stores:
- Total envelope volume in the window
- Staged-policy match count + would-be decision distribution
- Divergence count (cases where the staged policy would have BLOCKed but the active set ALLOWed, or vice versa)
- Per-divergence envelope snapshots (capped) so the operator can spot-check
- `promotion_safety` heuristic: `safe` / `review` / `risky` based on divergence magnitude

Regression reports are **stored artifacts**, not ephemeral one-shots — the full history of staged → active (or staged → merged) transitions is queryable for the audit trail.

### Regression Report → Two integration paths

The operator reviews the regression report on `PolicyDetailPage`, then chooses how to integrate the staged policy:

**Promote** — make the staged policy active as its own thing. State transitions `staged → active`. It joins the set of active policies, composes with them, binds decisions on matching envelopes. Used when the staged policy represents a distinct concern that should evolve independently (a new security policy, a new compliance overlay).

**Merge** — fold the staged policy's rules into an existing active policy as a new policy version. The staged policy ends in `archived`; the target active policy gets a version bump containing the merged rules. Used when the staged policy is an incremental refinement of an existing concern (a tighter threshold, an additional matching condition).

The default choice on `PolicyDetailPage` is Promote unless the staged policy was generated as a refinement card (in which case Merge is offered first). Both record who did it and when, and link back to the regression report that justified the transition.

### Active → Disabled / Archived (rollback paths)

If an active policy misbehaves in production, the operator can flip it to `disabled` (pause, retain) or `archived` (retire, replace). Both are skip-from-evaluator semantically; the distinction matters for humans reading the policy history.

Auto-rollback (Block 4b-1) operates at policy level: if a policy's BLOCK rate spikes above a cooldown threshold within a window of being promoted, the system flips the whole policy back to `staged` automatically and surfaces a notification. Operator review required to re-promote.

### Refinement loop

After a policy is `active`, the engine continues observing. If traffic patterns shift, a refinement card surfaces — typically as a new staged policy proposing a variant. The same flow applies: staged → regression report → promote or merge. Nothing changes enforcement without a regression report behind it.

### What about the per-rule `lifecycle_stage` field?

Block 1A added a `lifecycle_stage` field on individual rules. With the policy-level direction, that field stays in the rule schema as **metadata** (useful for human reading of who-tweaked-what within a policy version, and for compatibility with the existing dashboard rendering) but **is not the operational mechanism**. The evaluator gates evaluation by the containing policy's state, not by per-rule stage.

A future cleanup may remove the per-rule field entirely. Until then, treat it as informational. The dashboard's RuleCard component reads it for display continuity.

---

## Guidance-to-Policy: The Scanner Bridge (Block 4b-2 / 4b-3)

A workflow the spec didn't originally describe but which is now central to observe-mode value.

### The problem it solves

Developers write rules in coding-agent memory files, `.cursorrules`, system prompts, MCP configs, and other instruction files. These are intent — "the agent should never X" or "always Y" — but they have no architectural enforcement. The agent might follow them; the agent might not. There's no audit trail proving compliance.

The scanner (Ring 5.5) extracts these guidance rules from the codebase. Each finding includes the rule text, source location (file + line), rule type, and which Ring 3/4 actions it likely governs.

### The workflow

1. **Scan.** Developer runs `hiitl scan --upload --hiitl-key sk_...` against their codebase. Findings POST to `/v1/guidance-findings/bulk` (org-scoped, environment-scoped, idempotent per scan_id).

2. **Analyze.** The guidance analyzer joins the findings against `audit_events` over a configurable window (default 14 days). For each finding, it counts how many times the related actions actually ran. If `violation_count > 0` and `confidence_band ∈ {high, medium}`, a `guidance_to_policy` suggestion is emitted.

3. **Surface.** Suggestion appears on the dashboard with a distinct amber-accent card (Block 4b-3) so the operator immediately recognizes "this is a rule I wrote that's being violated." Card shows: source location, rule text, retrospective ("would have caught all N invocations in the last X days"), violations-observed table with timestamps + parameter snippets, and a proposed policy preview.

4. **Activate.** Operator clicks "Activate" — same flow as a normal policy suggestion. Rule lands in `staged` mode for the standard observation window before binding.

For rule types the analyzer can't safely auto-convert (`conditional` / `configuration` / `complex_construction`), `suggested_policy` is null. The card relabels "Activate" → "Acknowledge" and explains why the rule needs hand-writing.

### Why this matters

The two-disciplines thesis (context engineering for reasoning, control point for actions) lives or dies on this loop. **The scanner finds rules that belong in the control point but are stuck in the prompt.** The dashboard surfaces them with their violation evidence. The operator promotes them to enforced rules in two clicks. The rules that were probabilistic become deterministic. That's the bridge.

---

## The Dashboard as Operating Surface

The dashboard has three layers visible at all times:

### Current State

What's actively enforcing right now. Every policy, every route, every kill switch. The system map shows coverage: which agents, which tools, which actions are governed and how. Coverage score: what percentage of consequential actions have at least one active policy.

### Staged Changes

Policies in observation mode, proposed adjustments running against live traffic, new routes being tested. Each one accumulating data toward a regression report. The developer can see exactly what would change if they promoted everything in staging.

### Recommendations

New cards generated by the suggestion engine based on ongoing observation. New tools that appeared without policies. Envelope enrichment opportunities that would unlock new capabilities. Route suggestions for services that address observed gaps. Anomalies that might warrant new policies.

Over time, the dashboard tells the complete story of the system's evolution: when each control was identified, how it was tested, when it was promoted, how it's been refined. The entire history of the control layer, backed by data at every step.

---

## Route Suggestions: The Ecosystem Discovery Engine

Route suggestions deserve special attention because they solve a problem nobody else is addressing: developers don't know what governance services exist, and governance services can't reach the developers who need them.

### How Route Suggestions Work

The observation engine identifies characteristics of the developer's system that indicate a need for specific external services. These aren't generic recommendations — they're based on what the data shows:

- "Your agents send external communications containing PII" → content governance services
- "Your agents process financial transactions above regulatory thresholds" → compliance and fraud detection services
- "Your agents make irreversible changes to production data" → backup and recovery services
- "Your agents operate in healthcare contexts with patient data" → confidential computing services
- "Your agents make high-stakes decisions requiring audit-grade evidence" → cryptographic receipt services
- "Your agents access systems with credentials exceeding operational needs" → credential management and least-privilege tooling

### Why This Matters for Services

For governance services — especially smaller, cutting-edge startups — hiitl's route suggestions are the highest-intent distribution channel possible. Every recommendation is based on observed system behavior that demonstrates the need. The developer isn't browsing a marketplace. They're being told "you have this specific gap and this specific service fills it" at the exact moment they're building their control layer.

A startup building a novel agent security service can't compete with Datadog for mindshare. But if hiitl's engine recognizes that a developer's system has a specific gap that this startup addresses, and surfaces it at the right moment with one-click integration, that startup gets in front of the right buyer with zero marketing spend.

### Why This Matters for Developers

Nobody knows the full landscape of AI governance services. New tools appear weekly. The developer building a payments agent doesn't know that Sardine exists for transaction risk scoring, or that Flagright does real-time fraud monitoring, or that Sanna generates cryptographic receipts. hiitl tells them — not as advertising, but as a specific recommendation tied to their observed system behavior.

### The Platform Flywheel

More systems observed → better recommendations → more services connected → more value for developers → more systems observed. Each new service in the ecosystem makes hiitl's recommendations more complete. Each new developer makes the ecosystem more valuable for services.

---

## Async Routes: Observability, Explainability, and Everything That Shouldn't Touch the Hot Path

A large portion of route value has nothing to do with enforcement decisions. Observability, explainability, analytics, compliance evidence shipping, SIEM integration, alerting — these are things you want happening on every action, but they should never add latency to evaluate().

### The Problem With Wiring Integrations Individually

If a developer wants to send events to Datadog, ship compliance evidence to Vanta, feed an explainability dashboard, and push alerts to PagerDuty, that's four separate integrations they'd normally build and maintain. Four HTTP calls per action, four retry mechanisms, four failure modes, four authentication configurations, four places where a timeout could slow down their agent. At scale, this is untenable. Ten integrations at 50ms each adds half a second to every action.

### How ECP Handles It

ECP distinguishes between routes that participate in the decision (sync) and routes that just need to know what happened (async).

**Sync routes** are on the hot path. Fraud detection, human review, compliance assessment — the decision depends on their response. These add latency by design because the action can't proceed without the answer. They're used sparingly and only where enforcement requires it.

**Async routes** never touch the hot path. The evaluate() call returns in milliseconds with the decision. In the background, the audit record plus relevant envelope data is queued and shipped to every configured async route on a batched schedule. Datadog gets its events. Vanta gets its compliance evidence. The SIEM gets its security telemetry. The explainability service gets the decision trace. PagerDuty gets its alerts. None of them slowed down the action.

ECP manages the batching, retry logic, failure handling, and authentication for every async route. The developer configures the routes once. Adding a new observability integration doesn't add latency, doesn't add a failure mode to the hot path, and doesn't require changes to the application code.

### What This Means for the Dashboard

Async route cards on the dashboard look like:

- **"Ship audit events to Datadog"** — "You have 3 agents generating 2,400 actions per day. Connecting Datadog gives you real-time visibility into action volumes, decision distributions, and policy trigger rates. Events are batched every 30 seconds. Zero impact on evaluate() latency." One-click connect.

- **"Feed explainability service"** — "Your agents make 150 decisions per day that affect customers. An explainability route sends the decision trace — what action was proposed, what policies evaluated, why the decision was made — to a service that can generate human-readable explanations for customers or internal review." One-click connect.

- **"Ship compliance evidence to Vanta"** — "Your control layer has 11 active policies. A Vanta route continuously ships policy evaluations, enforcement events, regression reports, and coverage metrics as compliance evidence. No manual evidence collection." One-click connect.

- **"Push alerts to PagerDuty"** — "Route kill switch activations, anomalous pattern detections, and policy threshold breaches to PagerDuty for incident response. Filtered to high-severity events only — no alert fatigue." One-click connect.

### Why This Matters

The developer gets a fully wired observability and compliance stack by clicking buttons on the dashboard. No integration code. No retry logic. No batch management. No authentication plumbing. And critically — no latency impact on the control point itself. The evaluate() call stays fast no matter how many async routes are configured.

This is one of the strongest arguments for a general-purpose control point over wiring services individually. Every action flows through ECP once. ECP fans out to every service that needs to know about it, asynchronously, in batches, with managed reliability. The alternative — calling each service individually from application code — doesn't scale, adds latency, and creates maintenance burden that grows linearly with every new integration.

---

## For Consultants

The dashboard and card system is a structured engagement model:

**Phase 1 — Analyze:** Install hiitl for the client. Let observe mode run for 1-2 weeks. Review the generated cards with the client. The consultant doesn't do discovery from scratch — hiitl did it. The consultant adds domain judgment and organizational context.

**Phase 2 — Implement:** Activate selected policy cards in staged observation mode. Review regression reports. Adjust thresholds based on the client's risk posture. Promote policies to enforcement. Connect route integrations for services the client needs.

**Phase 3 — Certify:** Verify coverage across all agents and consequential actions. Document the evidence trail: how each control was identified, tested, and promoted. Produce a certification report using the dashboard's history. Ongoing: monitor refinement suggestions, adjust as the system evolves.

Each phase has concrete, data-backed deliverables produced by the system. The consultant's value is domain expertise and organizational judgment on the 20% that requires human decision-making — not the 80% of analysis and configuration that hiitl automates.

---

## For Compliance (The Vanta Connection)

The dashboard is a living record of evidence-based governance:

- Every policy traces back to observation data that identified the need
- Every policy was regression-tested before enforcement, with results recorded
- Every refinement has a data-backed justification
- Every route integration has a rationale tied to observed system characteristics
- The complete history of the control layer's evolution is preserved

A Vanta integration route that ships this evidence automatically — policy activation events, regression reports, enforcement metrics, coverage scores — gives compliance teams exactly what they need: proof that controls exist, were tested, are enforced, and are continuously maintained. Not a point-in-time audit. A continuous, living compliance posture.

---

## What Needs to Be True

### Time to first value must be short

Level 1 structural observation should produce useful cards within hours of production traffic. The developer installs hiitl, sends a few hundred evaluate() calls, and sees their system map plus initial recommendations before the end of the day.

### Suggestions must be specific, not generic

Every card must reference the developer's actual data. "Rate limit to 60/hour because your p95 is 52" — not "consider adding rate limits." Specificity comes from observation data and is what makes this feel like consulting rather than documentation.

### Cards must be deployable, not advisory

Policy cards contain the actual policy artifact. Envelope cards contain the actual code snippet. Route cards contain the actual configuration. The developer's job is to review and adopt, not to translate recommendations into implementation.

### Suggestion volume must be managed

If every evaluate() response or every dashboard visit shows 20 new cards, the developer will be overwhelmed. Prioritize by impact: show the highest-leverage recommendations first. Limit initial cards to the most important — maybe 5-7 after the first week. Expand as the developer adopts and the system learns more.

### The staging lifecycle must be frictionless

Activating a policy card should be one click. The observation period should run automatically. The regression report should generate automatically. Promoting to enforcement should be one click. If any step requires the developer to leave the dashboard and do manual work, adoption stalls.

### Local vs hosted intelligence

Structural observation and basic risk identification (Levels 1-2) should work locally — the open-source control point can generate basic cards from local audit data. Policy generation, route recommendations, and the advisor engine (Levels 3-4) require the hosted intelligence layer. This is the natural free-to-paid boundary: you can see your system for free, but the deployable implementation plan is the paid intelligence layer.

---

## Summary

Observe mode is not a passive phase before enforcement. It's the core product experience: an active analysis engine that produces a deployable, testable, continuously improving control layer expressed as composable components.

The developer installs hiitl. hiitl learns their system. hiitl produces the implementation. The developer reviews and adopts. Policies are staged, regression-tested, and promoted with data at every step. Routes connect the developer to services they didn't know they needed. The dashboard evolves with the system, surfacing refinements and new recommendations as behavior changes.

The cold start problem is solved. The policy authoring problem is solved. The "what services do I need" problem is solved. The "how do I prove my controls work" problem is solved.

One install. One evaluate() call. The control layer builds itself.
