# hiitl Product Specification - Reference

**Version**: 1.1
**Last Updated**: 2026-02-16

---

## Primary Product Specification

The complete product specification for hiitl Execution Control Plane is hiitl's own planning document; it is not
published in this repository. It holds the full product requirements across all phases:
- Phase 1: ECP MVP (Developer wedge)
- Phase 2: Operational correctness features
- Phase 3: Human intervention layer (BYO humans)
- Phase 4: Cockpit + Certified network
- Non-functional requirements

---

## Technical Specifications (This Directory)

This `docs/specs/` directory contains the **technical specifications** that define ECP's behavior:

1. **[envelope_schema.json](envelope_schema.json)** - JSON Schema for execution envelope
2. **[policy_format.md](policy_format.md)** - Policy format and evaluation semantics (includes remediation blocks on rules)
3. **[decision_response.md](decision_response.md)** - Decision response format (includes remediation object, route_ref)
4. **[event_format.md](event_format.md)** - Audit record and event emission format
5. **[signal_schema.md](signal_schema.md)** - Signal ingestion schema (interface design, subsumed by inbound routes)
6. **[routes.md](routes.md)** - Route schema — unified model for all external communication (outbound, inbound, bidirectional). Replaces the former HITL config spec. Routes cover escalation, observability, compliance, security signals, policy management, and assessment.
7. **[ecp_evaluate_spec.md](ecp_evaluate_spec.md)** - The `evaluate()` call: the envelope, the client modes and the Decision
8. **[observe_mode_concept_spec.md](observe_mode_concept_spec.md)** - Observe mode: from observed actions to suggested, testable policies
9. **[sync_engine.md](sync_engine.md)** - Sync engine protocol for hybrid mode: policy, route and kill-switch pulls, audit and telemetry pushes, the local cache
10. **[telemetry_schema.md](telemetry_schema.md)** - Telemetry record format and redaction levels

These are **language-neutral specifications**. All implementations (TypeScript, Python, future languages) must conform to these specs.

---

## Relationship Between Documents

**Product Spec** answers:
- **WHAT** we're building
- **WHY** we're building it
- **WHO** it's for
- **WHEN** (phasing and priorities)

**Technical Specs** (in docs/specs/) answer:
- **HOW** it works
- **WHAT FORMAT** the data takes
- **WHAT RULES** govern behavior
- **HOW TO VALIDATE** implementations

---

## Other Key Documents

- **[Hybrid Architecture](../architecture/ecp_hybrid_architecture.md)** - Hybrid SDK + observe-first onboarding (Feb 2026)

---

## For Implementation Work

When implementing features:

1. **Read the product spec** to understand requirements
2. **Read the relevant technical specs** for contract details
3. **Implement against the specs** (specs are source of truth)
4. **Validate with conformance tests** (in `/tests/conformance/`)

---

**This document is a navigation aid to the technical specifications in this directory.**
