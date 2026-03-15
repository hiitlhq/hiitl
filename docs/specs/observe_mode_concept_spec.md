# Observe Mode: The Intelligent Control Layer

## What This Document Is

This is the concept spec for hiitl's observe mode — the core product experience that turns raw system observation into a deployable, testable, continuously improving control layer. This isn't a new idea. It's the convergence of concepts that have been evolving across sessions: the suggestion engine, the pattern repository, context enrichment suggestions, observe-first onboarding, the route ecosystem, and the developer-supplied context model. This document assembles them into the coherent product experience.

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

### Policy Cards

A policy card contains everything needed to activate a specific policy.

**What the developer sees:**

- **Title:** "Rate limit send_email to 60/hour per agent"
- **Why:** "Based on 7 days of observation, your agent intake-bot averages 47 send_email calls per hour. This policy protects against runaway execution while allowing 25% headroom above normal volume."
- **Retrospective:** "In the last 7 days, this policy would have triggered 0 times on normal traffic. It would have caught the spike on Tuesday at 2pm where your agent sent 112 emails in one hour."
- **The policy:** Complete, deployable YAML/JSON — the actual artifact the policy engine consumes, not pseudocode.
- **Action:** "Activate" button. One click. The policy enters staged observation (not enforcement — see lifecycle below).

### Envelope Enrichment Cards

An envelope enrichment card contains the specific code change needed to add context to evaluate() calls.

**What the developer sees:**

- **Title:** "Add sensitivity flags to send_email actions"
- **Why:** "12% of your send_email calls include parameters that appear to contain PII (email addresses, phone numbers in the body field). Declaring sensitivity enables PII-aware policies."
- **Code snippet:** The exact change to the developer's evaluate() call, in their language (Python or TypeScript), with the new fields highlighted. Framework-specific if they're using a middleware integration.
- **What this unlocks:** "Once you add sensitivity flags, these 3 additional policies become available" — with links to the policy cards that are currently greyed out, waiting for this envelope data.
- **Action:** Copy snippet. Or, for framework integrations, a configuration change they can apply.

### Route Cards

A route card recommends a specific external service integration based on observed system behavior.

**What the developer sees:**

- **Title:** "Add fraud detection for payment transactions"
- **Why:** "Your agent finance-bot processes payments ranging from $50 to $45,000. 3% of transactions exceed $10,000. A fraud detection route evaluates transaction risk before execution."
- **Services:** Curated list of services that integrate with ECP for this use case — with brief descriptions, pricing models, and what they do. Not a generic marketplace — services specifically relevant to what the observation data shows about this developer's system.
- **Route configuration:** Complete route config for each recommended service. Connection setup walkthrough.
- **Estimated volume:** "Based on current traffic, this route would evaluate approximately 15 transactions per day."
- **Action:** "Connect" button for each service. One-click route creation (after providing credentials for the external service).

### Kill Switch Cards

- **Title:** "Add kill switch for agent intake-bot"
- **Why:** "You have no emergency stop mechanism for this agent. A kill switch lets you halt all actions from intake-bot instantly without affecting other agents."
- **Action:** One click to create. The card also shows how to trigger it — API call, dashboard button, or inbound route from a monitoring system.

### Human Collaboration Cards

- **Title:** "Add human review for high-value payments"
- **Why:** "Your agent processes payments up to $45,000. A human review route pauses payments above a configurable threshold for approval before execution."
- **Configuration:** The route config, response schema for the reviewer, suggested threshold based on observed distribution.
- **Estimated volume:** "At a $10,000 threshold, this would generate approximately 4 review requests per day."
- **Action:** Activate. Creates the route and the review workflow.

---

## The Policy Lifecycle

No policy goes from recommended to enforced in one step. Every policy moves through a defined lifecycle, visible on the dashboard:

### Recommended → Staged (Observe)

The developer clicks "Activate" on a policy card. The policy enters staged observation mode. It evaluates every matching action but does not enforce — decisions are recorded as "would have been BLOCKED" or "would have been RATE_LIMITED" but the action proceeds.

The card updates in real time with observation data: how many times the policy would have triggered, on which actions, with what parameters. False positives are identifiable — legitimate actions that would have been incorrectly blocked.

### Staged (Observe) → Regression Report

After a configurable observation period (default: 7 days), the card produces a regression report:

- Total actions evaluated against this policy
- Number of times it would have triggered
- Breakdown of triggers: legitimate blocks vs potential false positives
- Comparison to the developer's actual system behavior
- Suggested adjustments if false positives were detected
- Confidence assessment: "This policy is ready for enforcement" or "Consider adjusting threshold before enforcing"

### Regression Report → Enforced

The developer reviews the regression report, makes any adjustments, and clicks "Promote to enforce." The policy is now live. The card status updates to "Enforcing" with ongoing metrics: how many times it has triggered since enforcement, current trigger rate, any anomalies.

### Enforced → Refinement

After a policy is enforcing, the system continues to monitor. If traffic patterns change, the suggestion engine generates a refinement card:

- "Your send_email volume has increased 40% since you set this rate limit. The current limit of 60/hour triggered 12 times last week, 8 of which were legitimate traffic."
- Suggested adjustment with the new threshold
- Preview: "If this adjustment had been active last week, here's what would have happened"

The refinement follows the same lifecycle: staged observation → regression report → promote. Nothing changes enforcement without data-backed testing first.

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
