# hiitl — TypeScript SDK

The control point for AI agents. TypeScript SDK with embedded policy evaluator.

## Install

```bash
npm install @hiitl/sdk
```

## Quick start

```typescript
import { HIITL } from '@hiitl/sdk';

// Zero config — observe everything, block nothing
const hiitl = new HIITL();

const decision = hiitl.evaluate({
  action: 'send_email',
  parameters: { to: 'user@example.com', subject: 'Order update' },
});

if (decision.allowed) {
  await sendEmail(...);
}
```

## With policy enforcement

```typescript
const hiitl = new HIITL({
  agentId: 'payment-agent',
  policyPath: './policy.yaml',
  mode: 'RESPECT_POLICY',
});

const decision = hiitl.evaluate({
  action: 'process_payment',
  parameters: { amount: 5000.00, currency: 'USD' },
});

if (decision.allowed) {
  await processPayment(...);
} else if (decision.needs_approval) {
  await queueForReview(decision);
} else if (decision.blocked) {
  logBlocked(decision);
}
```

## Hosted mode

```typescript
const hiitl = new HIITL({
  agentId: 'payment-agent',
  orgId: 'org_yourcompany1234567',
  apiKey: 'sk_live_...',
  serverUrl: 'https://ecp.hiitl.com',
  environment: 'prod',
  mode: 'RESPECT_POLICY',
});

// Same evaluate() call, same Decision object
const decision = await hiitl.evaluate({
  action: 'process_payment',
  parameters: { amount: 500 },
});
```

## API

### `new HIITL(options?)`

All options are optional. `new HIITL()` works with no arguments.

| Option | Default | Description |
|--------|---------|-------------|
| `agentId` | `"default"` | Agent identifier |
| `environment` | `"dev"` | `dev`, `stage`, or `prod` |
| `mode` | `"OBSERVE_ALL"` | `OBSERVE_ALL` or `RESPECT_POLICY` |
| `policyPath` | `undefined` | Path to policy file (YAML or JSON) |
| `apiKey` | `undefined` | API key for hosted mode |
| `serverUrl` | `undefined` | Server URL for hosted mode |

### `hiitl.evaluate(options): Decision`

| Option | Required | Description |
|--------|----------|-------------|
| `action` | Yes | Action name (e.g., `'send_email'`) |
| `parameters` | No | Action parameters object |
| `target` | No | Target resource object |
| `operation` | No | Operation type (default: `'execute'`) |
| `user_id` | No | User identifier |
| `sensitivity` | No | Sensitivity labels |

### `Decision`

| Property | Type | Description |
|----------|------|-------------|
| `.allowed` | `boolean` | Can the action proceed? |
| `.decision` | `string` | Decision type (`ALLOW`, `BLOCK`, etc.) |
| `.reason_codes` | `string[]` | Why this decision was made |
| `.policy_version` | `string` | Policy version used |
| `.ok` | `boolean` | Alias for `.allowed` |
| `.blocked` | `boolean` | True if `BLOCK` |
| `.needs_approval` | `boolean` | True if `REQUIRE_APPROVAL` |
| `.observed` | `boolean` | True if `OBSERVE` mode |
| `.would_be` | `string` | What enforce mode would do (OBSERVE only) |

## Packages

This SDK consists of two packages:

- **`@hiitl/core`** — Policy evaluator and types (used internally)
- **`@hiitl/sdk`** — Developer-facing SDK (install this one)

## Requirements

- Node.js 18+

## Documentation

- [TypeScript Quickstart](../docs/onboarding/quickstart_typescript.md)
- [Full Documentation](../docs/)
- [Examples](../examples/)

## License

[MIT](../LICENSE)
