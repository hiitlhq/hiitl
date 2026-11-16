[![PyPI](https://img.shields.io/pypi/v/hiitl)](https://pypi.org/project/hiitl/)
[![CI](https://github.com/hiitlhq/hiitl/actions/workflows/ci.yml/badge.svg)](https://github.com/hiitlhq/hiitl/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://pypi.org/project/hiitl/)

# hiitl

The control point for software that can act.

Every consequential action — payments, deployments, data access, claim approvals, permission changes — passes through hiitl before execution. Whether it's an AI agent, a data pipeline, or an automated workflow, you get visibility immediately. Add policies when you're ready.

```python
from hiitl import HIITL

hiitl = HIITL()

decision = hiitl.evaluate("send_email", parameters={
    "recipient": "user@example.com",
    "recipient_type": "external",
})

if decision.allowed:
    send_email(...)
```

No API key. No config. Actions are observed and recorded locally. Add policies when you're ready.

---

## Why hiitl exists

Software is increasingly acting on its own — AI agents approving claims, pipelines deploying to production, workflows issuing payments, automation granting access. But there's no standard way to observe what these systems are doing, enforce rules before they act, or intervene when something goes wrong.

hiitl is the missing layer: a deterministic control point that sits between decision and execution.

```
System decides → hiitl evaluates → Action executes (or doesn't)
```

## How it works

```
┌─────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│             │     │         hiitl             │     │              │
│   Agent     │────▶│  ┌────────────────────┐   │────▶│   Action     │
│  Decision   │     │  │ Policy Evaluation  │   │     │  Execution   │
│             │     │  │ Rate Limiting      │   │     │              │
│             │◀────│  │ Audit Logging      │   │◀────│              │
│             │     │  │ Kill Switches      │   │     │              │
│             │     │  └────────────────────┘   │     │              │
└─────────────┘     └──────────────────────────┘     └──────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Audit Trail     │
                    │   (immutable)     │
                    └───────────────────┘
```

Each new evaluation of an admitted envelope produces an immutable audit record, including refusals after the envelope exists. A retry under a recorded idempotency key within the configured dedup window returns its original decision without another row. If the record cannot be written, the action is blocked with `AUDIT_WRITE_FAILED`; that failure has no record. A number outside the numeric domain is refused before an envelope exists, with no decision or record, even at the hosted entry when the request carries a string `action_id`; the refusal names the field and its declared type and range, recommending text only where text is admitted.

---

## Install

**Python**
```bash
pip install hiitl
```

**TypeScript**
```bash
npm install @hiitl/sdk
```

---

## Quick start

### 1. Observe (zero config)

Start with visibility. No policies, no config — just see what your agents are doing.

**Python**
```python
from hiitl import HIITL

hiitl = HIITL()

# OBSERVE_ALL records what policy would decide without enforcing that policy.
decision = hiitl.evaluate("process_payment", parameters={
    "amount": 500.00,
    "currency": "USD",
    "account_id": "acct_123",
})

if decision.allowed:  # Check even in OBSERVE_ALL: an audit write failure blocks
    process_payment(...)

# decision.observed == True
# decision.would_be == "BLOCK" (with no policy loaded, every would-be decision is BLOCK with NO_MATCHING_RULE)
```

**TypeScript**
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL();

const decision = await hiitl.evaluate({
  action: 'process_payment',
  parameters: { amount: 500.00, currency: 'USD' },
});

if (decision.allowed) {
  await processPayment(...);
}
```

### 2. Add a policy

When you're ready for enforcement, write a policy and switch to `RESPECT_POLICY` mode.

**policy.yaml**
```yaml
version: "v1.0.0"
name: payment_controls
description: Payment controls for the quickstart agent
scope:
  org_id: "org_devlocal0000000000"
  environment: dev
rules:
  - name: block_large_payments
    priority: 900
    description: Payments over $1,000 require approval
    conditions:
      all_of:
        - field: action
          operator: equals
          value: process_payment
        - field: parameters.amount
          operator: greater_than
          value: 1000
    decision: REQUIRE_APPROVAL
    reason_code: LARGE_PAYMENT

  - name: allow_normal_payments
    priority: 100
    description: Allow standard payments
    conditions:
      field: action
      operator: equals
      value: process_payment
    decision: ALLOW
    reason_code: PAYMENT_ALLOWED
```

**Python**
```python
hiitl = HIITL(
    agent_id="payment-agent",
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
)

decision = hiitl.evaluate("process_payment", parameters={
    "amount": 5000.00,
    "currency": "USD",
})

if decision.allowed:
    process_payment(...)
elif decision.needs_approval:
    queue_for_review(decision)
elif decision.blocked:
    log_blocked_action(decision)

# decision.decision == "REQUIRE_APPROVAL"
# decision.reason_codes == ["LARGE_PAYMENT"]
# decision.policy_version == "v1.0.0"
```

### 3. Go to production

Point at the hosted service for team collaboration, shared policies, and managed audit logs.

```python
hiitl = HIITL(
    agent_id="payment-agent",
    org_id="org_yourcompany1234567",
    api_key="sk_live_...",
    signature_key="...",       # the signing secret shown when the API key was created
    server_url="https://api.hiitl.com",
    evaluation="remote",          # hosted evaluation is an explicit opt-in; api_key alone runs hybrid mode
    environment="prod",
    mode="RESPECT_POLICY",
)

# Same evaluate() call. Same decision object. Different backend.
decision = hiitl.evaluate("process_payment", parameters={
    "amount": 5000.00,
    "currency": "USD",
})
```

### Beyond agents: pipelines and workflows

hiitl works with any software that takes consequential actions. Here's a deployment pipeline:

```python
# CI/CD pipeline — require approval for production deploys
decision = hiitl.evaluate("deploy_service", parameters={
    "service": "payment-api",
    "environment": "production",
    "version": "2.4.1",
})

if decision.allowed:
    deploy(...)
elif decision.needs_approval:
    notify_oncall(decision)  # Routes to Slack, PagerDuty, etc.
```

And an automated claims workflow:

```python
# Claims processing — block high-value claims, audit everything
decision = hiitl.evaluate("approve_claim", parameters={
    "claim_id": "CLM-4829",
    "amount": 24000.00,
    "category": "property_damage",
})

if decision.allowed:
    approve_claim(...)
elif decision.blocked:
    flag_for_manual_review(decision)
```

Same `evaluate()` call. Same policies. Same audit trail.

---

## What you get

**Observe** — Record new evaluations of the actions your systems send through hiitl. See patterns before writing rules.

**Enforce** — Deterministic policy evaluation in single-digit milliseconds. No LLM inference at decision time.

**Intervene** — Block, pause, require approval, rate limit, kill switch. [Decision types](docs/specs/decision_response.md) cover different situations, including recorded error decisions.

**Record** — Immutable records of new evaluations, including blocked actions. A duplicate reuses its first decision; an unwritable record blocks the action. Decisions identify the policy version used.

### Decision types

Selected policy outcomes are shown below; the [decision specification](docs/specs/decision_response.md) defines the full response set.

| Decision | What happens |
|----------|-------------|
| `ALLOW` | Action proceeds |
| `BLOCK` | Action denied |
| `OBSERVE` | Action proceeds, would-be decision logged |
| `REQUIRE_APPROVAL` | Returned for a person's decision; the MCP gateway opens a review case with the hosted service |
| `PAUSE` | Held for later processing |
| `RATE_LIMIT` | Rate limit exceeded |
| `KILL_SWITCH` | Emergency stop active |
| `ESCALATE` | Routed to higher authority |
| `SANDBOX` | Caller executes against its own configured sandbox target |

### Decision object

Every `evaluate()` call returns a `Decision` with:

```python
decision.allowed        # bool — can the action proceed?
decision.decision       # str — "ALLOW", "BLOCK", etc.
decision.reason_codes   # list — why this decision was made
decision.policy_version # str — which policy version was used
decision.timing         # Timing — ingest_ms, evaluation_ms, total_ms

# Convenience properties
decision.ok             # alias for .allowed
decision.blocked        # True if BLOCK, KILL_SWITCH or RATE_LIMIT
decision.needs_approval # True if REQUIRE_APPROVAL, PAUSE or ESCALATE
decision.observed       # True if OBSERVE mode
decision.would_be       # str — what enforce mode would have done (OBSERVE only)
```

---

## Architecture

### Multi-language native evaluators

The policy engine runs natively in Python and TypeScript — no cross-language dependencies, no subprocess calls. Both implementations are validated by the same [conformance test suite](tests/conformance/).

```
┌─────────────────────────────┐
│     Language-Neutral Specs  │
│  (JSON Schema, Markdown)    │
└────────┬──────────┬─────────┘
         │          │
    ┌────▼───┐ ┌────▼──────┐
    │ Python │ │TypeScript │
    │Evaluator│ │Evaluator  │
    └────┬───┘ └────┬──────┘
         │          │
    ┌────▼───┐ ┌────▼──────┐
    │ Python │ │TypeScript │
    │  SDK   │ │   SDK     │
    └────────┘ └───────────┘
```

### Deployment modes

**Local** — Runs in-process with four runtime dependencies (pydantic, pydantic-settings, PyYAML, httpx). SQLite audit log. Policies and routes as files.

**Hybrid** — The same in-process evaluator, with policies synced from the hosted service and the audit log uploaded to it; keeps deciding from its cache when the service is unreachable.

**Hosted** — Evaluation on the service, with PostgreSQL, team collaboration, API-based policy management. An explicit opt-in (`evaluation="remote"` in Python; `evaluation: 'remote'` in TypeScript), with an API key, signing secret and `server_url`.

---

## Documentation

| Resource | Description |
|----------|-------------|
| [Python Quickstart](docs/onboarding/quickstart_python.md) | Install to first evaluated action in 5 minutes |
| [TypeScript Quickstart](docs/onboarding/quickstart_typescript.md) | Install to first evaluated action in 5 minutes |
| [Observe-First Guide](docs/onboarding/quickstart_observe_first.md) | Start with visibility, add controls later |
| [MCP Integration](docs/onboarding/quickstart_mcp.md) | Add hiitl to an MCP server |
| [Integration Examples](docs/onboarding/integration_examples.md) | LangChain, OpenAI, Vercel AI SDK, custom loops |
| [Policy Cookbook](docs/onboarding/policy_cookbook.md) | Payment approval, rate limiting, kill switches |
| [Pattern Repository](patterns/) | 25 copy-paste-ready action patterns |
| [Kill Switch Runbook](docs/onboarding/kill_switch_runbook.md) | Emergency stop operations |

### Specifications

| Spec | What it defines |
|------|----------------|
| [Envelope Schema](docs/specs/envelope_schema.json) | Action representation (JSON Schema) |
| [Policy Format](docs/specs/policy_format.md) | Rule syntax, evaluation order, composition |
| [Decision Response](docs/specs/decision_response.md) | Decision output format |
| [Event Format](docs/specs/event_format.md) | Audit record and event emission |

---

## Examples

See [examples/](examples/) for standalone, runnable examples:

- **[quickstart/](examples/quickstart/)** — Minimal evaluate() call
- **[payment-agent/](examples/payment-agent/)** — Payment processing with approval policies
- **[observe-first/](examples/observe-first/)** — Zero-config observation mode
- **[mcp-server/](examples/mcp-server/)** — MCP server with hiitl protection

---

## Development

### Prerequisites

- Python 3.10+
- Node.js 22+

### Setup

```bash
git clone https://github.com/hiitlhq/hiitl.git
cd hiitl

# Python
cd python && pip install -e . && pip install pytest && cd ..

# TypeScript
cd typescript/packages/core && npm install && cd ../../..
cd typescript/packages/sdk && npm install && cd ../../..
```

### Tests

```bash
# Python conformance tests (the shared cases in tests/conformance/cases)
cd python && python -m pytest hiitl/core/tests/conformance/

# TypeScript conformance tests
cd typescript/packages/core && npx vitest run

# All Python tests
cd python && python -m pytest
```

### Conformance tests

Both evaluators must produce identical decisions for identical complete inputs, including the policy, envelope, clock, route answers and limiter state. The [conformance suite](tests/conformance/) defines the shared test cases as JSON — each is an (envelope, policy, expected decision) tuple that runs against both implementations.

---

## Project structure

```
hiitl/
├── python/hiitl/
│   ├── core/           # Policy evaluator + types
│   └── sdk/            # Python SDK (local + hosted)
├── typescript/packages/
│   ├── core/           # Policy evaluator + types
│   └── sdk/            # TypeScript SDK (local + hosted)
├── tests/conformance/  # Shared cross-language conformance cases
├── patterns/           # 25 action pattern templates
├── docs/specs/         # Language-neutral specifications
├── docs/onboarding/    # Quickstarts and guides
└── examples/           # Standalone runnable examples
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[Apache-2.0](LICENSE). Copyright 2026 Trevor Foster; see [NOTICE](NOTICE).
