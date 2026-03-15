# HIITL Product Specification - Reference

**Version**: 1.1
**Last Updated**: 2026-02-16

---

## Primary Product Specification

The complete product specification for HIITL Execution Control Plane is located at:

**[../product_planning/hiitl_ecp_product_spec (1).md](../product_planning/hiitl_ecp_product_spec%20(1).md)**

That document contains the full product requirements across all phases:
- Phase 1: ECP MVP (Developer wedge)
- Phase 2: Operational correctness features
- Phase 3: Human intervention layer (BYO humans)
- Phase 4: Cockpit + Certified network
- Non-functional requirements

---

## Technical Specifications (This Directory)

This `/specs/` directory contains the **technical specifications** that define ECP's behavior:

1. **[envelope_schema.json](envelope_schema.json)** - JSON Schema for execution envelope
2. **[policy_format.md](policy_format.md)** - Policy format and evaluation semantics (includes remediation blocks on rules)
3. **[decision_response.md](decision_response.md)** - Decision response format (includes remediation object, route_ref)
4. **[event_format.md](event_format.md)** - Audit record and event emission format
5. **[signal_schema.md](signal_schema.md)** - Signal ingestion schema (interface design, subsumed by inbound routes)
6. **[routes.md](routes.md)** - Route schema — unified model for all external communication (outbound, inbound, bidirectional). Replaces the former hitl_config.md. Routes cover escalation, observability, compliance, security signals, policy management, and assessment.
7. **[hitl_config.md](hitl_config.md)** - *(Deprecated — replaced by routes.md. Retained for historical reference.)*

These are **language-neutral specifications**. All implementations (TypeScript, Python, future languages) must conform to these specs.

---

## Relationship Between Documents

**Product Spec** (in product_planning/) answers:
- **WHAT** we're building
- **WHY** we're building it
- **WHO** it's for
- **WHEN** (phasing and priorities)

**Technical Specs** (in specs/) answer:
- **HOW** it works
- **WHAT FORMAT** the data takes
- **WHAT RULES** govern behavior
- **HOW TO VALIDATE** implementations

---

## Other Key Documents

- **[CLAUDE.md](../CLAUDE.md)** - Project control document (how we work, architectural principles)
- **[North Star](../product_planning/hiitl_north_star.md)** - Vision and decision principles
- **[Infrastructure Analysis](../technical/ecp_infrastructure_analysis.md)** - Technical architecture decisions
- **[Security Requirements](../security/security_requirements.md)** - Security requirements and review checklist
- **[Security Architecture](../security/ecp_security_architecture.md)** - Attack surfaces, tiered requirements, hot-path analysis
- **[Strategic Evolution v1](../product_planning/ecp_strategic_evolution_feb_2026.md)** - Strategic refinements (Feb 2026)
- **[Strategic Evolution v2](../product_planning/ecp_strategic_evolution_feb_2026_v2.md)** - Remediation responses, MCP, patterns, unified routes (Feb 2026)
- **[Hybrid Architecture](../architecture/ecp_hybrid_architecture.md)** - Hybrid SDK + observe-first onboarding (Feb 2026)

---

## For Implementation Work

When implementing features:

1. **Read the product spec** to understand requirements
2. **Read the relevant technical specs** for contract details
3. **Read CLAUDE.md** for architectural constraints and principles
4. **Implement against the specs** (specs are source of truth)
5. **Validate with conformance tests** (in `/tests/conformance/`)

---

**This document is a navigation aid. The full product specification is in the product_planning directory.**
