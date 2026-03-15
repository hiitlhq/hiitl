[![PyPI](https://img.shields.io/pypi/v/hiitl)](https://pypi.org/project/hiitl/)
[![CI](https://github.com/hiitlhq/hiitl/actions/workflows/ci.yml/badge.svg)](https://github.com/hiitlhq/hiitl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://pypi.org/project/hiitl/)

# hiitl

The control point for AI agents.

Every consequential action your agent takes — payments, emails, data access, permission changes — passes through hiitl before execution. You get visibility immediately. Add policies when you're ready.

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

No API key. No config. Every action is logged. Add policies when you're ready.

---

## Why hiitl exists

AI systems are starting to take real actions — approving claims, issuing payments, granting access, modifying data. But there's no standard way to observe what they're doing, enforce rules before they act, or intervene when something goes wrong.

hiitl is the missing layer: a deterministic control point that sits between AI decision and execution.

```
Agent decides → hiitl evaluates → Action executes (or doesn't)
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

Every action produces an immutable audit record, even if blocked.

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

# Every call is logged. In OBSERVE mode (default), nothing is blocked.
decision = hiitl.evaluate("process_payment", parameters={
    "amount": 500.00,
    "currency": "USD",
    "account_id": "acct_123",
})

if decision.allowed:  # Always true in OBSERVE mode
    process_payment(...)

# decision.observed == True
# decision.would_be == "BLOCK" (if a policy would have blocked it)
```

**TypeScript**
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL();

const decision = hiitl.evaluate({
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
version: "1.0.0"
name: payment_controls
rules:
  - name: block_large_payments
    priority: 900
    enabled: true
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
    enabled: true
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
# decision.policy_version == "1.0.0"
```

### 3. Go to production

Point at the hosted service for team collaboration, shared policies, and managed audit logs.

```python
hiitl = HIITL(
    agent_id="payment-agent",
    org_id="org_yourcompany1234567",
    api_key="sk_live_...",
    server_url="https://ecp.hiitl.com",
    environment="prod",
    mode="RESPECT_POLICY",
)

# Same evaluate() call. Same decision object. Different backend.
decision = hiitl.evaluate("process_payment", parameters={
    "amount": 5000.00,
    "currency": "USD",
})
```

---

## What you get

**Observe** — Log every action your agents attempt. See patterns before writing rules.

**Enforce** — Deterministic policy evaluation in single-digit milliseconds. No LLM inference at decision time.

**Intervene** — Block, pause, require approval, rate limit, kill switch. Nine decision types for different situations.

**Record** — Immutable audit trail for every action, even blocked ones. Policy version attached to every decision.

### Decision types

| Decision | What happens |
|----------|-------------|
| `ALLOW` | Action proceeds |
| `BLOCK` | Action denied |
| `OBSERVE` | Action proceeds, would-be decision logged |
| `REQUIRE_APPROVAL` | Queued for human review |
| `PAUSE` | Held for later processing |
| `RATE_LIMIT` | Rate limit exceeded |
| `KILL_SWITCH` | Emergency stop active |
| `ESCALATE` | Routed to higher authority |
| `SANDBOX` | Routed to sandbox environment |

### Decision object

Every `evaluate()` call returns a `Decision` with:

```python
decision.allowed        # bool — can the action proceed?
decision.decision       # str — "ALLOW", "BLOCK", etc.
decision.reason_codes   # list — why this decision was made
decision.policy_version # str — which policy version was used
decision.timing         # dict — evaluation_ms, total_ms

# Convenience properties
decision.ok             # alias for .allowed
decision.blocked        # True if BLOCK
decision.needs_approval # True if REQUIRE_APPROVAL
decision.observed       # True if OBSERVE mode
decision.would_be       # str — what enforce mode would have done (OBSERVE only)
```

---

## Architecture

### Multi-language native evaluators

The policy engine runs natively in Python and TypeScript — no cross-language dependencies, no subprocess calls. Both implementations are validated by the same [conformance test suite](tests/conformance/) (75 tests).

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

**Local** — Zero dependencies, runs in-process. SQLite audit log. Sub-millisecond evaluation. Perfect for development and edge deployment.

**Hosted** — Managed service with PostgreSQL, team collaboration, API-based policy management. Same `evaluate()` call, different backend.

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

- Python 3.12+
- Node.js 18+

### Setup

```bash
git clone https://github.com/hiitlhq/hiitl.git
cd hiitl

# Python
cd python && pip install -e ".[dev]" && cd ..

# TypeScript
cd typescript/packages/core && npm install && cd ../../..
cd typescript/packages/sdk && npm install && cd ../../..
```

### Tests

```bash
# Python conformance tests (75 tests)
cd python && python -m pytest hiitl/core/tests/conformance/

# TypeScript conformance tests
cd typescript/packages/core && npx vitest run

# All Python tests
cd python && python -m pytest
```

### Conformance tests

Both evaluators must produce identical decisions for identical inputs. The [conformance suite](tests/conformance/) defines 75 test cases as JSON — each is an (envelope, policy, expected decision) tuple that runs against both implementations.

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
├── tests/conformance/  # 75 cross-language conformance tests
├── patterns/           # 25 action pattern templates
├── docs/
│   ├── specs/          # Language-neutral specifications
│   ├── onboarding/     # Quickstarts and guides
│   └── security/       # Security architecture
└── examples/           # Standalone runnable examples
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

[MIT](LICENSE)
