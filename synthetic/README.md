# Synthetic Test Data & Scenarios

**Purpose**: Synthetic data for testing, development observation, and demos.

Synthetic data is a product requirement, not an afterthought.

---

## Overview

Synthetic data serves three purposes:

1. **Continuous testing** - Automated test suites with realistic, varied action patterns
2. **Development observation** - Realistic traffic to observe behavior through audit viewer and metrics
3. **Demos and evaluation** - Compelling, realistic scenarios for potential users

---

## Structure

```
synthetic/
├── agents/                    # Agent persona definitions
│   └── payment-agent.json
│
├── scenarios/                 # Pre-built test scenarios
│   ├── basic-allow-block.json
│   ├── escalation-workflow.json
│   ├── high-value-payment-approval.json
│   ├── kill-switch-activation.json
│   └── multi-rule-priority.json
│
├── policies/                  # Test policies for scenarios
│   ├── kill-switch-policy.json
│   ├── multi-rule-policy.json
│   └── payment-policy.json
│
└── README.md                  # This file
```

**CLI tool**: `python/hiitl/synthetic/` (run with `python -m hiitl.synthetic`)

---

## Running the CLI

All commands run from the `python/` directory of a clone of this repository:

```bash
cd python
```

The CLI reads the scenarios, personas and policies in this `synthetic/` directory. To use your own, pass `--scenarios-dir` (`run`, `list`) and `--agents-dir` (`run`, `generate`, `grade`).

### List Available Scenarios

```bash
python3 -m hiitl.synthetic list
```

### Run Scenarios

```bash
# Run a single scenario
python3 -m hiitl.synthetic run basic-allow-block

# Run all scenarios
python3 -m hiitl.synthetic run --all

# Run with JSON output (for UI consumption)
python3 -m hiitl.synthetic run --all --json

# Run with a specific policy override
python3 -m hiitl.synthetic run basic-allow-block --policy ../synthetic/policies/payment-policy.json

# Save the JSON report to a file
python3 -m hiitl.synthetic run --all --output report.json
```

Exit codes: `0` = all passed, `1` = failures detected, `2` = error (e.g., scenario not found)

### Generate Synthetic Envelopes

Generate envelopes from agent persona distributions:

```bash
# Generate 100 envelopes from payment-agent persona
python3 -m hiitl.synthetic generate payment-agent -n 100

# Deterministic generation with seed
python3 -m hiitl.synthetic generate payment-agent -n 100 --seed 42

# Same seed = same tool selection, parameters and IDs
python3 -m hiitl.synthetic generate payment-agent -n 10 --seed 42
python3 -m hiitl.synthetic generate payment-agent -n 10 --seed 42  # same output, except the timestamps
```

Output is JSONL (one envelope per line):

```jsonl
{"schema_version":"v2.0","org_id":"org_synthetictest00001","environment":"dev","agent_id":"payment-agent","action_id":"act_76a81a57899322473081cd27","idempotency_key":"idem_7bcd1e3763ea0bf5ee5974c3790f2b56","action":"process_payment",...,"operation":"execute","target":{"account_id":"acct_7a43b9b21175306c"},"parameters":{"amount":248.66,"currency":"usd","account_id":"acct_bd2b4acec46edf28"},...,"sensitivity":["money","irreversible"],...}
```

### Grade Policy Coverage

Evaluate a policy against synthetic traffic to measure coverage:

```bash
# Grade payment policy with 100 synthetic envelopes
python3 -m hiitl.synthetic grade ../synthetic/policies/payment-policy.json \
  --agent payment-agent -n 100 --seed 42

# JSON output for programmatic consumption
python3 -m hiitl.synthetic grade ../synthetic/policies/payment-policy.json \
  --agent payment-agent -n 100 --seed 42 --json
```

Output includes:
- **Coverage %** — percentage of active rules matched at least once
- **Rule effectiveness** — per-rule match counts and percentages
- **Gaps** — unmatched rules and uncovered actions
- **Decision distribution** — count per decision type (ALLOW, BLOCK, etc.)

---

## Agent Personas

Agent personas define realistic behavioral profiles with different action patterns.

### Agent Persona Format

```json
{
  "agent_id": "payment-agent",
  "name": "Payment Processing Agent",
  "description": "Processes customer payments and refunds",
  "behavior_profile": {
    "tools": ["process_payment", "process_refund", "check_balance"],
    "action_frequency": {
      "process_payment": 0.7,
      "process_refund": 0.2,
      "check_balance": 0.1
    },
    "parameter_distributions": {
      "process_payment": {
        "amount": {
          "type": "distribution",
          "distribution": "exponential",
          "mean": 150,
          "min": 10,
          "max": 10000
        },
        "currency": {
          "type": "categorical",
          "values": ["usd", "eur", "gbp"],
          "probabilities": [0.7, 0.2, 0.1]
        },
        "account_id": {
          "type": "pattern",
          "pattern": "acct_{random_id}"
        }
      }
    }
  },
  "sensitivity_flags": {
    "process_payment": ["money", "irreversible"],
    "process_refund": ["money"],
    "check_balance": ["money"]
  }
}
```

### Distribution Types

| Type | Description | Parameters |
|------|-------------|------------|
| `distribution` | Numeric sampling, clamped to `min`..`max` and rounded to 2 places | `distribution` (`exponential`, the default; `normal`, with `stddev`; or `uniform`), `mean`, `min`, `max` |
| `categorical` | Weighted random choice | `values`, `probabilities` |
| `pattern` | String with `{random_id}` replaced by 16 hex characters | `pattern` |

A parameter whose name ends in `_id` is also sampled into the envelope's `target`. `sensitivity_flags` sets the envelope's `sensitivity` per tool.

---

## Test Scenarios

Scenarios are pre-built sequences of actions that demonstrate specific ECP capabilities.

### Available Scenarios

| Scenario | Category | Description |
|----------|----------|-------------|
| `basic-allow-block` | smoke_test | Low-value payment allowed, balance check allowed, unknown tool blocked |
| `high-value-payment-approval` | approval_workflows | $5000 payment triggers REQUIRE_APPROVAL with resume_token; the approve, execute and audit steps are skipped |
| `kill-switch-activation` | kill_switch | Kill switch blocks payments, non-payment tools unaffected |
| `escalation-workflow` | escalation | REQUIRE_APPROVAL with route_ref for reviewer routing |
| `multi-rule-priority` | rule_ordering | Deletes are blocked; reads and executes are allowed by their own rules |

### Scenario Format

```json
{
  "scenario_id": "basic-allow-block",
  "name": "Basic Allow and Block",
  "description": "Smoke test for basic policy evaluation",
  "category": "smoke_test",
  "difficulty": "basic",
  "policy_path": "../policies/payment-policy.json",
  "steps": [
    {
      "step": 1,
      "name": "Low-value payment allowed",
      "action": "evaluate",
      "agent_id": "payment-agent",
      "envelope": {
        "action": "process_payment",
        "operation": "execute",
        "target": {"account_id": "acct_test_001"},
        "parameters": {"amount": 50.00, "currency": "usd"}
      },
      "expected_decision": "ALLOW",
      "expected_reason_codes": ["STANDARD_OPERATION"],
      "assertions": [
        {"field": "decision.allowed", "equals": true},
        {"field": "decision.decision", "equals": "ALLOW"}
      ]
    }
  ]
}
```

### Step Types

| Action | Status | Description |
|--------|--------|-------------|
| `evaluate` | Executed | Evaluates envelope against policy, validates assertions |
| `approve` | Skipped | Reviewer approval. Not run yet: reported as skipped |
| `execute` | Skipped | Action execution after approval. Not run yet: reported as skipped |
| `verify_audit` | Skipped | Audit trail verification. Not run yet: reported as skipped |

A step's envelope is a call to `evaluate()`, written as its keyword members: the ones `evaluate()`'s own signature
names (`python/hiitl/sdk/client.py`) that the envelope carries, read from the signature rather than from a list.
`action` is required, as it is in the call; a member the call defaults is defaulted as the call defaults it, and an
`agent_id` in the envelope overrides the step's own as the call's overrides the client's. `principal_token` is not
taken: `evaluate()` verifies it with the client's verifier, which the runner does not have. A scenario is refused when
it loads, naming the step and the member, if a step's envelope names any other member (`tool`, the format's earlier
name for `action`, included) or an evaluate step names no `action` (HTL-29, row 233, ruled 2026-11-09: "a scenario
step names its action as the envelope does, `action`; `tool` is refused as a field the step does not define").

The scenario, its steps, their assertions and its variations are read the same way: a member the format does not
define is refused when the scenario loads, naming it, and never ignored (R-0872, "no field is ever silently dropped");
an assertion with a misspelled operator would otherwise check nothing. `run --all` stops on a scenario that is
refused, naming its file, as `run <name>` does; it does not skip it.

### Assertion Operators

| Operator | Example |
|----------|---------|
| `equals` | `{"field": "decision.allowed", "equals": true}` |
| `not_equals` | `{"field": "decision.decision", "not_equals": "BLOCK"}` |
| `exists` | `{"field": "decision.resume_token", "exists": true}` |
| `greater_than` | `{"field": "decision.timing.evaluation_ms", "greater_than": 0}` |
| `less_than` | `{"field": "decision.timing.evaluation_ms", "less_than": 10}` |
| `contains` | `{"field": "decision.reason_codes", "contains": "HIGH_VALUE"}` |

---

## Policy Grading

The grading engine measures how well a policy covers the action space for a given agent.

### Metrics

- **Coverage %** — Rules matched at least once / total active rules
- **Rule effectiveness** — Per-rule: match count, percentage of total evaluations
- **Gaps** — Two types:
  - `unmatched_rule` — Active rules that never matched any evaluation
  - `uncovered_action` — Actions that hit no matching rule (fell to default)
- **Decision distribution** — Counts per decision type

### Architecture: Strategy Pattern (LLM-Ready)

The grading engine uses a strategy pattern for future extensibility:

```
PolicyGrader (data collection — always deterministic)
  └── GradingStrategy (analysis — pluggable)
       ├── DeterministicGradingStrategy  ← today
       └── LLMGradingStrategy            ← Future (standards assessment, recommendations)
```

**Today**: `DeterministicGradingStrategy` — coverage %, rule effectiveness, gap identification.

**Future**: `LLMGradingStrategy` — LLM interprets patterns, assesses against standards (EU AI Act, NIST AI RMF, SOC2), proposes rule changes as structured diffs.

---

## CI/CD Integration

```yaml
# A step in your CI workflow
- name: Run Synthetic Scenarios
  run: |
    cd python
    python3 -m hiitl.synthetic run --all
    if [ $? -ne 0 ]; then
      echo "Synthetic scenarios failed"
      exit 1
    fi
```

---

## Extending

### Adding a New Agent Persona

1. Create `agents/my-agent.json` following the persona format
2. Define tools, action frequencies, parameter distributions
3. Test generation: `python3 -m hiitl.synthetic generate my-agent -n 100`

### Adding a New Scenario

1. Create `scenarios/my-scenario.json` following the scenario format
2. Define steps, expected decisions, assertions
3. Test run: `python3 -m hiitl.synthetic run my-scenario`

### Adding a New Policy

1. Create `policies/my-policy.json` following the policy format
2. Reference it from scenarios via `policy_path` field
3. Or override at CLI: `--policy ../synthetic/policies/my-policy.json`

---

## Related Documents

- [Envelope Schema](../docs/specs/envelope_schema.json) - Action structure
- [Policy Format](../docs/specs/policy_format.md) - Policy structure for scenarios
- [Decision Response](../docs/specs/decision_response.md) - Decision output format

---

**Synthetic data is essential infrastructure for building, testing, and demonstrating ECP.**
