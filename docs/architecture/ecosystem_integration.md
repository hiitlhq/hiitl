# Ecosystem Integration - HIITL ECP

**Version**: 1.1
**Last Updated**: 2026-02-16

---

## Overview

HIITL ECP is **connective infrastructure** (CLAUDE.md line 22). It does not compete with the AI ecosystem — it gives the ecosystem a deterministic enforcement layer to plug into.

This document describes how ECP integrates with each ecosystem category and the value it provides to each.

---

## Integration Philosophy

Per CLAUDE.md lines 12-21:

> **Where ECP Sits in the Ecosystem**
>
> ECP does not replace the AI infrastructure ecosystem. It gives the ecosystem a deterministic enforcement layer to plug into.
>
> - Observability platforms detect. ECP enforces.
> - Security tools signal risk. ECP consumes those signals and acts on them.
> - Eval tools measure drift. ECP turns that into runtime guardrails.
> - GRC platforms audit. ECP produces the enforceable control evidence they certify against.
> - Agent frameworks orchestrate. ECP sits between their decisions and execution, unchanged.
> - Cloud providers supply infrastructure. ECP standardizes the AI execution boundary across all of them.

**ECP increases the ROI of every system it integrates with.** Detection without enforcement is frustrating. Governance without runtime control is theoretical. ECP is where insight becomes intervention.

---

## Integration Surfaces

ECP has **three integration surfaces**:

1. **SDK Inbound** - Actions entering the control point via developer SDKs
2. **Ecosystem Outbound** - Structured execution events emitted to external platforms
3. **Signal Ingestion Inbound** - External systems pushing risk signals into ECP

---

## 1. Observability Platforms

### Category Examples
- Datadog
- Honeycomb
- New Relic
- Dynatrace
- Grafana

### How They Integrate with ECP

**Outbound: Event Emission**

ECP emits structured execution events to observability platforms via:
- **Webhooks** (Phase 1)
- **OpenTelemetry export** (Phase 2)
- **Native integrations** (roadmap)

**What observability platforms receive**:
- Every action attempted (allowed, blocked, paused)
- Decision outcomes with reason codes
- Timing metadata (latency per evaluation)
- Policy versions applied
- Rate limit counter states
- Kill switch activations

**Event format**: See [Event Format Spec](../specs/event_format.md)

**Inbound: Signal Ingestion**

Observability platforms can push signals into ECP:
- System load alerts (`cpu_percent`, `memory_percent`)
- Incident mode flags (`incident_active: true`)
- Error rate thresholds (`error_rate_high: true`)

**Policy example**:
```yaml
- name: "throttle-during-high-load"
  conditions:
    all_of:
      - field: "external.datadog.system_load.cpu_percent"
        operator: "greater_than"
        value: 80
  decision: "RATE_LIMIT"
  metadata:
    rate_limit:
      limit: 10  # Reduce limit during high load
```

### Value ECP Provides

**Before ECP**:
- Observability platforms detect issues but can't stop actions
- Teams manually intervene (change config, restart services, enable feature flags)
- Slow feedback loop from detection to action

**With ECP**:
- Observability alerts trigger ECP interventions automatically
- Policies reference observability signals in real-time
- Actions throttled, paused, or blocked based on system health
- Closed-loop: detect → signal → enforce → observe outcome

---

## 2. Security Platforms

### Category Examples
- CrowdStrike
- Wiz
- Palo Alto Networks
- Snyk
- Lacework

### How They Integrate with ECP

**Inbound: Signal Ingestion**

Security platforms push risk signals:
- Agent risk scores (`risk_score: 0.85`)
- Anomaly detection flags (`anomaly_detected: true`)
- Threat levels (`threat_level: "high"`)
- Compliance violations (`compliance_violation: "GDPR"`)

**Policy example**:
```yaml
- name: "escalate-high-risk-agent"
  conditions:
    all_of:
      - field: "external.crowdstrike.risk_score"
        operator: "greater_than"
        value: 0.8
  decision: "ESCALATE"
  reason_code: "HIGH_SECURITY_RISK"
```

**Outbound: Event Emission**

Security platforms receive execution events:
- Actions attempted by each agent
- Blocked actions (potential threats)
- Kill switch activations
- Sensitive data access patterns

### Value ECP Provides

**Before ECP**:
- Security tools detect threats but can't block agent actions
- Manual incident response (disable API keys, restart agents)
- No runtime enforcement of security policies

**With ECP**:
- Security signals trigger runtime enforcement (block, escalate, pause)
- Policies encode security requirements (no PII access from untrusted agents)
- Immediate response to threats (kill switch for compromised agent)
- Security team has runtime control point (not just detection)

---

## 3. Eval & Testing Tools

### Category Examples
- Braintrust
- Weights & Biases
- LangSmith
- Humanloop
- Arthur AI

### How They Integrate with ECP

**Inbound: Signal Ingestion**

Eval platforms push quality signals:
- Model drift flags (`model_drift: true`)
- Accuracy drops (`accuracy_drop: 0.15`)
- Eval failures (`eval_failure: true`)
- Confidence thresholds (`confidence_below_threshold: true`)

**Policy example**:
```yaml
- name: "pause-on-model-drift"
  conditions:
    all_of:
      - field: "external.braintrust.model_drift"
        operator: "equals"
        value: true
  decision: "PAUSE"
  reason_code: "MODEL_DRIFT_DETECTED"
```

**Outbound: Event Emission**

Eval platforms receive execution data:
- Actions taken by agents
- Decision patterns (what gets blocked vs. allowed)
- Confidence scores from agents
- Outcomes (success/failure)

### Value ECP Provides

**Before ECP**:
- Eval tools measure quality but can't prevent low-quality actions
- Teams manually rollback or disable agents
- Quality degradation causes user-facing issues before intervention

**With ECP**:
- Quality signals trigger runtime controls (pause, sandbox, require approval)
- Low-quality agents automatically sandboxed
- Confidence thresholds enforced at runtime
- Continuous quality enforcement, not just measurement

---

## 4. GRC & Compliance Platforms

### Category Examples
- Vanta
- Drata
- OneTrust
- TrustArc
- Secureframe

### How They Integrate with ECP

**Outbound: Event Emission (Audit Evidence)**

GRC platforms receive comprehensive audit trails:
- Every action attempted (allowed or blocked)
- Policy versions applied
- Approval workflows (who approved what, when)
- Kill switch activations
- Rate limit enforcement
- Access control decisions

**Audit format**: Immutable, timestamped, complete
- See [Event Format Spec](../specs/event_format.md)

**Inbound: Signal Ingestion**

Compliance platforms push regulatory signals:
- Compliance flags (`regulatory_restriction: "GDPR_DATA_FREEZE"`)
- Audit mode activation (`audit_mode: true`)
- Policy violations (`policy_violation: "SOC2"`)

**Policy example**:
```yaml
- name: "block-on-compliance-restriction"
  conditions:
    all_of:
      - field: "external.compliance-system.regulatory_restriction"
        operator: "exists"
        value: true
  decision: "BLOCK"
  reason_code: "REGULATORY_RESTRICTION_ACTIVE"
```

### Value ECP Provides

**Before ECP**:
- GRC platforms audit but can't enforce
- Compliance controls scattered across codebases (hard to prove)
- Audit evidence stitched from multiple logs (incomplete)
- No proof of runtime enforcement

**With ECP**:
- **Enforceable control evidence**: Policies + audit trail prove controls are active
- **Centralized audit**: Single source of truth for all agent actions
- **Provable enforcement**: "This action was blocked by policy X at time Y"
- **Compliance automation**: Regulatory restrictions flow directly into runtime policies
- **SOC 2 / ISO 27001 readiness**: Comprehensive, immutable audit trail

---

## 5. Agent Frameworks & Orchestration

### Category Examples
- LangChain / LangChain.js
- LlamaIndex
- OpenAI Agents SDK
- Vercel AI SDK
- CrewAI
- AutoGen
- Custom agent loops

### How They Integrate with ECP

**Inbound: SDK Integration**

Agent frameworks integrate ECP via SDK:
- Python SDK for Python frameworks (LangChain, CrewAI, AutoGen)
- TypeScript SDK for JS frameworks (LangChain.js, Vercel AI SDK)
- Wrap tool calls with `hiitl.evaluate()`

**Integration pattern**:
```python
# Before
result = agent.execute_tool("process_payment", {...})

# After
decision = hiitl.evaluate(tool="process_payment", ...)
if decision.allowed:
    result = agent.execute_tool("process_payment", {...})
```

**Outbound: Event Emission**

Agent frameworks receive execution events:
- Which actions were allowed/blocked
- Rate limit states
- Policy decisions

### Value ECP Provides

**Before ECP**:
- Each team builds their own control logic (scattered, inconsistent)
- Rate limits, approval workflows, kill switches implemented ad hoc
- No standard place to enforce policy across different agent frameworks
- Orchestration frameworks don't include deterministic control

**With ECP**:
- **Standard control layer** across all frameworks (LangChain, custom loops, etc.)
- **Consistent enforcement** regardless of orchestration choice
- **Framework-agnostic policies**: Same policy works with any agent framework
- **Additive integration**: ECP doesn't replace orchestration, it adds control
- **No architectural lock-in**: Switch frameworks without rewriting control logic

---

## 6. Explainability Platforms

### Category Examples
- Fiddler AI
- Truera
- Arthur AI (explainability features)
- Custom explainability tools

### How They Integrate with ECP

**Outbound: Decision Metadata as Explanation Input**

ECP provides the raw material for explaining AI execution decisions to non-technical stakeholders:
- Deterministic decisions with clear reason codes
- Matched rules with human-readable names and descriptions
- Policy versions (what rules were in effect)
- Timing metadata
- HITL config details (when human review was involved)
- Full escalation lifecycle (who reviewed, what they decided, why)

**Event format**: See [Event Format Spec](../specs/event_format.md)

**Inbound: Signal Ingestion**

Explainability platforms can push signals:
- Explanation quality scores (`explanation_quality: "insufficient"`)
- User comprehension flags (`user_confusion_detected: true`)
- Regulatory explanation requirements (`explanation_required: "GDPR_Article_22"`)

### Value ECP Provides

**Before ECP**:
- AI decisions are opaque ("the model decided")
- Explanation efforts require stitching data from multiple systems
- No standardized data for explanation generation
- Regulatory explanation requirements (EU AI Act, GDPR Article 22) hard to satisfy

**With ECP**:
- **Deterministic decision data**: Every decision has clear reason codes and matched rules
- **Audit trail for explanations**: Complete record of what was evaluated, what decision was made, and why
- **Human review context**: When humans were involved, the full review lifecycle is recorded
- **Standardized format**: Explainability platforms receive structured, consistent data
- **Regulatory compliance**: Decision records satisfy explanation requirements

---

## 7. Cloud Providers

### Category Examples
- AWS
- Google Cloud
- Azure
- Cloudflare Workers
- Vercel / Netlify

### How They Integrate with ECP

**Deployment Modes**:
- **Local/Edge**: ECP runs in customer's cloud environment (ultra-low latency)
- **Hosted**: ECP runs as managed service (any cloud)

**Infrastructure Primitives**:
- Storage: PostgreSQL (audit log), Redis (rate limits)
- Compute: Stateless evaluator (horizontal scale)
- Networking: HTTPS API, webhooks

**Cloud-agnostic design**:
- No vendor-specific dependencies
- Runs on any cloud provider
- Same behavior regardless of infrastructure

### Value ECP Provides

**Before ECP**:
- Each cloud provider has different primitives
- Teams build control logic using cloud-specific services
- Migrating clouds means rewriting control infrastructure

**With ECP**:
- **Standardized execution boundary** across all clouds
- **Portable control logic**: Policies work regardless of cloud provider
- **Multi-cloud support**: Same ECP instance can govern agents across AWS, GCP, Azure
- **Hybrid deployment**: Local mode for edge, hosted for central control

---

## Integration Priority (Phased)

### Phase 1: Developer-First
**Focus**: SDK integration, basic outbound events

**Integrations**:
- ✅ LangChain (Python)
- ✅ LangChain.js (TypeScript)
- ✅ OpenAI Agents SDK
- ✅ Vercel AI SDK
- ✅ Custom agent loops
- ✅ Webhooks (basic event emission)

### Phase 2: Ecosystem Expansion
**Focus**: Signal ingestion, native integrations

**Integrations**:
- Datadog (signal ingestion + event export)
- CrowdStrike (risk score signals)
- Braintrust (eval drift signals)
- Vanta/Drata (audit export)
- OpenTelemetry (native OTel export)

### Phase 3: Enterprise & GRC
**Focus**: Compliance automation, native integrations

**Integrations**:
- OneTrust (compliance signal ingestion)
- ServiceNow (approval workflow integration)
- Slack (notification + approval bots)
- PagerDuty (kill switch alerts)

---

## One-Click Integration Pattern

Pre-built, lightweight connectors for key ecosystem categories. The vision: "Connect your Datadog → ECP sends execution events automatically." "Connect your Vanta → ECP feeds compliance evidence continuously."

### Why One-Click Integrations Matter

- **Critical for adoption and retention** — customers who integrate ECP with 3+ tools in their stack are much stickier
- **Lightweight to implement** — mostly mapping ECP's existing event/webhook output to the partner's expected format (thin layers on top of the standard emission system)
- **Demonstrates ecosystem value** — shows ECP is connective infrastructure in practice, not just theory

### Careful Rollout Strategy

Don't build 20 integrations at launch:

1. **Phase 1**: Build the webhook/event emission system (already planned)
2. **Phase 1.5**: Build 1-2 showcase integrations that demonstrate the pattern (e.g., Datadog event export, Slack notifications)
3. **Phase 2**: Provide clear documentation for how partners/community can build their own connectors
4. **Ongoing**: Add pre-built integrations based on customer demand signals

### Integration Connector Architecture

Each one-click integration is a thin mapping layer:
- **Input**: Standard ECP event (from webhook/event emission)
- **Transform**: Map ECP fields to partner's expected format
- **Output**: Partner-specific API call or event format
- **Config**: Partner credentials + filter rules (which events to send)

This keeps the core event system simple while enabling partner-specific formatting.

---

## Integration Patterns

### Pattern 1: Detect → Enforce (Observability)

1. Observability platform detects issue (high error rate, latency spike)
2. Platform pushes signal to ECP (`external.datadog.error_rate: 0.15`)
3. ECP policy references signal in condition
4. Policy decision enforces action (throttle, pause, escalate)
5. ECP emits event back to observability platform (closed loop)

### Pattern 2: Measure → Guard (Eval Tools)

1. Eval tool measures quality (model drift, accuracy drop)
2. Tool pushes signal to ECP (`external.braintrust.model_drift: true`)
3. ECP policy pauses or sandboxes actions from drifted agent
4. Eval tool receives execution events (what was blocked)
5. Team reviews, fixes model, signal clears, actions resume

### Pattern 3: Audit → Certify (GRC)

1. ECP enforces policies (rate limits, approvals, blocks)
2. Every action produces immutable audit record
3. GRC platform ingests audit trail via export API or webhook
4. GRC platform certifies controls are enforced (SOC 2, ISO 27001)
5. Auditors review ECP audit trail as evidence

### Pattern 4: Orchestrate → Control (Agent Frameworks)

1. Agent framework decides to take action (LangChain tool call)
2. SDK wraps action with ECP evaluation
3. ECP evaluates against policy
4. Decision returned to framework (allowed/blocked)
5. Framework executes (if allowed) or handles denial

---

## Ecosystem Partner Value Propositions

### For Observability Vendors
- "Make your alerts actionable with runtime enforcement"
- "Close the loop: detect → signal → enforce → observe"
- "Turn monitoring into control"

### For Security Vendors
- "Your threat detection becomes runtime protection"
- "Block malicious actions automatically, not just detect them"
- "Unified security enforcement for AI systems"

### For Eval Vendors
- "Turn quality measurement into quality enforcement"
- "Prevent low-quality actions before they reach users"
- "Continuous quality guardrails, not just post-hoc analysis"

### For GRC Vendors
- "Provable, auditable runtime controls"
- "Compliance automation: regulations → runtime policies"
- "SOC 2 / ISO 27001 evidence generation"

### For Agent Framework Vendors
- "Give your users a standard control layer"
- "Production-ready governance out of the box"
- "Enable enterprise adoption with built-in controls"

### For Explainability Vendors
- "Structured, deterministic decision data for explanation generation"
- "Complete human review lifecycle records"
- "Satisfy regulatory explanation requirements (EU AI Act, GDPR Article 22)"

---

## Competitive Moats from Ecosystem Integration

1. **Network effects**: More integrations → more valuable for all users
2. **Data moat**: Aggregate insights across observability, security, eval platforms
3. **Standards**: ECP becomes the de facto execution control standard
4. **Distribution**: Ecosystem partners drive ECP adoption (co-marketing, bundling)

---

## Next Steps

### For Ecosystem Partners

**Want to integrate?**
1. Review [Signal Schema Spec](../specs/signal_schema.md) for signal ingestion
2. Review [Event Format Spec](../specs/event_format.md) for webhook events
3. Contact partnerships@hiitl.ai for integration support

### For Developers

**Want to integrate your tools?**
- See [Integration Examples](../onboarding/integration_examples.md)
- Use SDK for custom tools
- Submit PRs for new framework adapters

---

## Related Documents

- [CLAUDE.md](../CLAUDE.md) - Ecosystem Integration Design (lines 367-391)
- [Signal Schema Spec](../specs/signal_schema.md) - Signal ingestion format
- [Event Format Spec](../specs/event_format.md) - Outbound event format
- [North Star](../product_planning/hiitl_north_star.md) - Where HIITL Sits in the Ecosystem

---

**ECP is connective infrastructure. It makes the ecosystem more valuable.**
