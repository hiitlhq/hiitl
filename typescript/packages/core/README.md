# @hiitl/core

**hiitl Policy Evaluator** — the deterministic enforcement engine that decides whether an action proceeds.

Evaluates policies (JSON / YAML) against execution envelopes and returns `ALLOW`, `BLOCK`, `PAUSE`, `REQUIRE_APPROVAL`, `OBSERVE`, or one of seven other decision types — with timing metadata, matched-rule attribution, and structured remediation guidance.

[![TypeScript](https://img.shields.io/badge/TypeScript-5.3+-blue.svg)](https://www.typescriptlang.org/)
[![Conformance](https://img.shields.io/badge/conformance-shared_fixtures-brightgreen.svg)](https://github.com/hiitlhq/hiitl/tree/main/tests/conformance)
[![Performance](https://img.shields.io/badge/performance-%3C0.5ms-brightgreen.svg)](https://github.com/hiitlhq/hiitl)

## Features

**Shared conformance fixtures** compare the Python and TypeScript evaluators against the same declared answers; see the [current cases](https://github.com/hiitlhq/hiitl/tree/main/tests/conformance/cases).
⚡ **Sub-millisecond evaluation** — typical decisions in <0.5ms, well under the < 1ms requirement
🔒 **Type-safe** — full TypeScript types and Zod schema validation
🎯 **Deterministic** — the same complete inputs, including the evaluation clock, produce the same decision
🧪 **Shared cases** — the conformance runner reads the current cases from `tests/conformance/cases`
🪜 **Per-rule lifecycle** — `active` / `staged` / `draft` / `disabled` / `archived` stages drive the observe → stage → enforce workflow
🎚️ **Scope filters** — per-rule whitelists on agents / users / environments, deterministic SHA-256 percentage rollouts, temporal `valid_from` / `valid_to` windows

## Installation

```bash
npm install @hiitl/core
```

## Quick Start

```typescript
import { PolicyEvaluator } from '@hiitl/core';

const evaluator = new PolicyEvaluator();

// Define your execution envelope
const envelope = {
  schema_version: 'v2.0',
  org_id: 'org_abc123def456ghi789',
  environment: 'prod',
  agent_id: 'payment-agent',
  action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK',
  idempotency_key: 'idem_payment_123',
  action: 'process_payment',
  operation: 'execute',
  target: { account_id: 'acct_source' },
  parameters: {
    amount: 1000,
    currency: 'USD',
    recipient_account_id: 'acct_recipient',
  },
  timestamp: '2024-01-15T10:30:00Z',
  signature: 'a3f1c9e27b4d8f60e5a2c7b91d3f4e8a6c0b2d5f7e9a1c3b5d7f9e0a2c4b6d8e', // 64 hex chars (HMAC-SHA256)
};

// Define your policy
const policy = {
  name: 'payment-controls',
  version: 'v1.0.0',
  description: 'Payment controls for this example',
  scope: { org_id: 'org_abc123def456ghi789', environment: 'prod' },
  rules: [
    {
      name: 'allow-small-amounts',
      description: 'Allow payments under $5000',
      priority: 100,
      decision: 'ALLOW',
      reason_code: 'SMALL_AMOUNT',
      conditions: {
        field: 'parameters.amount',
        operator: 'less_than',
        value: 5000,
      },
    },
  ],
};

// Evaluate and get decision (the evaluator enforces by default: RESPECT_POLICY)
const decision = evaluator.evaluate(envelope, policy);

if (decision.allowed) {
  console.log('✅ Action allowed:', decision.reason_codes);
  await executePayment();
} else {
  console.log('❌ Action blocked:', decision.reason_codes);
}
```

## API Reference

### PolicyEvaluator

Main evaluation class for deterministic policy evaluation.

```typescript
class PolicyEvaluator {
  /**
   * Evaluate a policy against an execution envelope.
   *
   * @param envelope - Execution envelope (validated against envelope schema)
   * @param policy - Policy set (validated against policy schema)
   * @param mode - 'RESPECT_POLICY' (default) enforces; 'OBSERVE_ALL' observes
   * @param enrichment - Answers from sync routes, read as external.<route>.<field> (optional)
   * @returns Decision response with action decision, reason codes, and timing
   */
  evaluate(
    envelope: Envelope | Record<string, unknown>,
    policy: PolicySet | Record<string, unknown>,
    mode?: 'OBSERVE_ALL' | 'RESPECT_POLICY',
    enrichment?: Enrichment | null
  ): Decision;
}
```

**Returns:** `Decision` object with:
- `decision`: Decision type (`'ALLOW'`, `'BLOCK'`, `'PAUSE'`, etc.)
- `allowed`: Boolean (true if allowed)
- `reason_codes`: Array of reason codes
- `policy_version`: Version of the policy set evaluated
- `timing`: Performance metrics (`ingest_ms`, `evaluation_ms`, `total_ms`)
- `matched_rules`: Array of matched rules (if any)
- `remediation`: Guidance on how to fix a blocked call, when the rule defines it
- `would_be`, `would_be_reason_codes`: Under `OBSERVE_ALL`, what enforcement would decide when the call comes back `OBSERVE`
- `staged_observations`: Staged rules that matched (they are observed, never bound)

Under `OBSERVE_ALL`, a decision that allows the call (`ALLOW`, `SANDBOX`) comes back as itself. Any other decision comes back `OBSERVE`, with `allowed` true, `reason_codes` `['OBSERVED']`, and `would_be` set to the rule's decision.

### evaluate()

Convenience function for one-off evaluations.

```typescript
import { evaluate } from '@hiitl/core';

const decision = evaluate(envelope, policy);
```

## Condition Operators

The evaluator supports these condition operators:

### Equality
- `equals` - Field equals value
- `not_equals` - Field does not equal value

### Numeric Comparison
- `greater_than` - Field > value
- `greater_than_or_equal` - Field >= value
- `less_than` - Field < value
- `less_than_or_equal` - Field <= value

### String/Array Operations
- `contains` - String contains substring OR array contains element
- `not_contains` - Inverse of contains
- `starts_with` - String starts with prefix
- `ends_with` - String ends with suffix

### Set Operations
- `in` - Field value is in array
- `not_in` - Field value is not in array

### Existence
- `exists` - Field exists (not null/undefined)

### Schema
- `conforms_to` - Field value conforms to a parameter schema (a JSON Schema subset; never a regex)

## Logical Operators

Combine conditions with logical operators:

```typescript
{
  all_of: [  // AND - all conditions must match
    { field: 'parameters.amount', operator: 'less_than', value: 5000 },
    { field: 'parameters.currency', operator: 'equals', value: 'USD' },
  ]
}

{
  any_of: [  // OR - at least one must match
    { field: 'environment', operator: 'equals', value: 'dev' },
    { field: 'environment', operator: 'equals', value: 'stage' },
  ]
}

{
  none_of: [  // NOT - none may match
    { field: 'sensitivity', operator: 'contains', value: 'pii' },
  ]
}
```

## Field Path Resolution

Access nested fields using dot notation:

```typescript
{
  field: 'parameters.amount',  // Access parameters.amount
  operator: 'less_than',
  value: 5000
}

{
  field: 'target.account_id',  // Access target.account_id
  operator: 'equals',
  value: 'acct_123'
}
```

## Precedence: DENY Wins

When several rules match, the decision is chosen in this order:

1. `KILL_SWITCH` beats everything
2. `BLOCK` beats every other decision
3. Among the rest, the highest `priority` wins
4. On equal priority, the rule defined first wins

A matching `BLOCK` beats a higher-priority rule of any other decision:

```typescript
{
  rules: [
    { name: 'allow-payments', priority: 200, decision: 'ALLOW', ... },
    { name: 'block-frozen-account', priority: 10, decision: 'BLOCK', ... },  // Wins when both match
  ]
}
```

## Safe-by-Default

If no rule matches, the evaluator returns `BLOCK` with reason code `NO_MATCHING_RULE`:

```typescript
const decision = evaluator.evaluate(envelope, {
  name: 'empty',
  version: 'v1.0.0',
  description: 'An empty policy denies every action',
  scope: { org_id: 'org_abc123def456ghi789', environment: 'prod' },
  rules: [],
});
// decision.decision === 'BLOCK'
// decision.reason_codes === ['NO_MATCHING_RULE']
```

## TypeScript Types

All types are exported for type safety:

```typescript
import type {
  Envelope,
  PolicySet,
  Decision,
  Rule,
  Condition,
  LogicalCondition,
  DecisionType,
  ConditionOperator,
} from '@hiitl/core';
```

## Runtime Validation

Zod schemas are included for runtime validation:

```typescript
import { EnvelopeSchema, PolicySetSchema, DecisionSchema } from '@hiitl/core';

// Validate envelope
const result = EnvelopeSchema.safeParse(data);
if (result.success) {
  console.log('Valid envelope:', result.data);
} else {
  console.error('Validation errors:', result.error);
}
```

## Enum Constants

Access enum values programmatically:

```typescript
import { DecisionType, ConditionOperator, Environment, Operation } from '@hiitl/core';

console.log(DecisionType.ALLOW);  // 'ALLOW'
console.log(ConditionOperator.EQUALS);  // 'equals'
console.log(Environment.PROD);  // 'prod'
console.log(Operation.EXECUTE);  // 'execute'
```

## Performance

Benchmarks (average over 1000 iterations):
- Simple atomic condition: **0.045ms**
- Logical operators (all_of): **0.072ms**
- Multiple rules (priority sorting): **0.025ms**
- Nested conditions: **0.091ms**

All evaluations are **well under 1ms**, matching Python evaluator performance.

## Conformance Testing

The shared conformance suite checks both evaluators against the same declared answers:
- Shared conformance cases run against both evaluators
- ✅ Identical decision logic
- ✅ Identical null handling
- ✅ Identical priority ordering

## Design Principles

1. **Deterministic** - The same envelope, policy, evaluation clock and supplied route answers produce the same decision
2. **Side-effect free** - Evaluation does not modify state
3. **Fast** - Sub-millisecond evaluation using native JavaScript features
4. **Type-safe** - Full TypeScript types with Zod validation
5. **Shared cases** - The conformance runner reads the current cases from `tests/conformance/cases`

## Examples

### Block Large Transactions

```typescript
const policy = {
  name: 'transaction-limits',
  version: 'v1.0.0',
  description: 'Payment controls for this example',
  scope: { org_id: 'org_abc123def456ghi789', environment: 'prod' },
  rules: [
    {
      name: 'block-large-amounts',
      description: 'Block transactions over $10,000',
      priority: 100,
      decision: 'BLOCK',
      reason_code: 'AMOUNT_TOO_LARGE',
      conditions: {
        field: 'parameters.amount',
        operator: 'greater_than',
        value: 10000,
      },
    },
  ],
};
```

### Require Approval for Risky Actions

```typescript
const policy = {
  name: 'risk-controls',
  version: 'v1.0.0',
  description: 'Payment controls for this example',
  scope: { org_id: 'org_abc123def456ghi789', environment: 'prod' },
  rules: [
    {
      name: 'require-approval-for-money',
      description: 'Require approval for money operations',
      priority: 100,
      decision: 'REQUIRE_APPROVAL',
      reason_code: 'SENSITIVE_OPERATION',
      conditions: {
        field: 'sensitivity',
        operator: 'contains',
        value: 'money',
      },
    },
  ],
};
```

### Complex Multi-Condition Rules

```typescript
const policy = {
  name: 'production-safeguards',
  version: 'v1.0.0',
  description: 'Payment controls for this example',
  scope: { org_id: 'org_abc123def456ghi789', environment: 'prod' },
  rules: [
    {
      name: 'block-prod-delete',
      description: 'Block delete operations in production',
      priority: 200,
      decision: 'BLOCK',
      reason_code: 'PROD_DELETE_FORBIDDEN',
      conditions: {
        all_of: [
          { field: 'environment', operator: 'equals', value: 'prod' },
          { field: 'operation', operator: 'equals', value: 'delete' },
        ],
      },
    },
  ],
};
```

## License

Apache-2.0

## Links

- [GitHub Repository](https://github.com/hiitlhq/hiitl)
- [Documentation](https://hiitl.com/docs)
- [Conformance Test Suite](https://github.com/hiitlhq/hiitl/tree/main/tests/conformance)
