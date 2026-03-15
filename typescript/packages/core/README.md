# @hiitl/core

**HIITL Policy Evaluator** - Core runtime enforcement engine for TypeScript.

Deterministic policy evaluation for execution control. Evaluates policies (JSON objects) against execution envelopes and returns allow/block decisions.

[![TypeScript](https://img.shields.io/badge/TypeScript-5.3+-blue.svg)](https://www.typescriptlang.org/)
[![Tests](https://img.shields.io/badge/tests-146%2F146-brightgreen.svg)](https://github.com/hiitlhq/hiitl)
[![Conformance](https://img.shields.io/badge/conformance-54%2F54-brightgreen.svg)](https://github.com/hiitlhq/hiitl)
[![Performance](https://img.shields.io/badge/performance-%3C0.1ms-brightgreen.svg)](https://github.com/hiitlhq/hiitl)

## Features

✅ **100% Behavioral Parity** with Python evaluator (54/54 conformance tests pass)
⚡ **Sub-millisecond Performance** (<0.1ms average for simple policies)
🔒 **Type-safe** with full TypeScript types and Zod schema validation
🎯 **Deterministic** - same (envelope, policy) always produces same decision
🧪 **Well-tested** - 146 tests passing (91 unit + 55 conformance)

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
  schema_version: 'v1.0',
  org_id: 'org_abc123def456ghi789',
  environment: 'prod',
  agent_id: 'payment-agent',
  action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK',
  idempotency_key: 'idem_payment_123',
  tool_name: 'process_payment',
  operation: 'execute',
  target: { account_id: 'acct_source' },
  parameters: {
    amount: 1000,
    currency: 'USD',
    recipient_account_id: 'acct_recipient',
  },
  timestamp: '2024-01-15T10:30:00Z',
  signature: 'a1b2c3d4...',
};

// Define your policy
const policy = {
  name: 'payment-controls',
  version: '1.0',
  rules: [
    {
      name: 'allow-small-amounts',
      description: 'Allow payments under $5000',
      priority: 100,
      enabled: true,
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

// Evaluate and get decision
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
   * @returns Decision response with action decision, reason codes, and timing
   */
  evaluate(
    envelope: Envelope | Record<string, unknown>,
    policy: PolicySet | Record<string, unknown>
  ): Decision;
}
```

**Returns:** `Decision` object with:
- `decision`: Decision type (`'ALLOW'`, `'BLOCK'`, `'PAUSE'`, etc.)
- `allowed`: Boolean (true if allowed)
- `reason_codes`: Array of reason codes
- `timing`: Performance metrics (`ingest_ms`, `evaluation_ms`, `total_ms`)
- `matched_rules`: Array of matched rules (if any)

### evaluate()

Convenience function for one-off evaluations.

```typescript
import { evaluate } from '@hiitl/core';

const decision = evaluate(envelope, policy);
```

## Condition Operators

The evaluator supports 14 condition operators:

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
- `matches` - Regex pattern matching

### Set Operations
- `in` - Field value is in array
- `not_in` - Field value is not in array

### Existence
- `exists` - Field exists (not null/undefined)

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

## Priority and First-Match Semantics

Rules are evaluated by priority (descending order). **First-match wins**:

```typescript
{
  rules: [
    { name: 'high-priority', priority: 200, ... },  // Evaluated first
    { name: 'medium-priority', priority: 100, ... },
    { name: 'low-priority', priority: 50, ... },
  ]
}
```

## Safe-by-Default

If no rule matches, the evaluator returns `BLOCK` with reason code `NO_MATCHING_RULE`:

```typescript
const decision = evaluator.evaluate(envelope, { rules: [] });
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

This TypeScript evaluator maintains **100% behavioral parity** with the Python evaluator:
- ✅ 54/54 conformance tests pass
- ✅ Identical decision logic
- ✅ Identical null handling
- ✅ Identical priority ordering

## Design Principles

1. **Deterministic** - Same (envelope, policy) always produces same decision
2. **Side-effect free** - Evaluation does not modify state
3. **Fast** - Sub-millisecond evaluation using native JavaScript features
4. **Type-safe** - Full TypeScript types with Zod validation
5. **Well-tested** - 146 tests (91 unit + 55 conformance)

## Examples

### Block Large Transactions

```typescript
const policy = {
  name: 'transaction-limits',
  version: '1.0',
  rules: [
    {
      name: 'block-large-amounts',
      description: 'Block transactions over $10,000',
      priority: 100,
      enabled: true,
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
  version: '1.0',
  rules: [
    {
      name: 'require-approval-for-money',
      description: 'Require approval for money operations',
      priority: 100,
      enabled: true,
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
  version: '1.0',
  rules: [
    {
      name: 'block-prod-delete',
      description: 'Block delete operations in production',
      priority: 200,
      enabled: true,
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

MIT

## Links

- [GitHub Repository](https://github.com/hiitlhq/hiitl)
- [Documentation](https://hiitl.ai/docs)
- [Conformance Test Suite](https://github.com/hiitlhq/hiitl/tree/main/tests/conformance)
