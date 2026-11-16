# @hiitl/sdk

The TypeScript SDK for [hiitl](https://hiitl.com) — the control point for software that can act. Wrap any action your code is about to take with `evaluate()` and get a deterministic decision before it executes.

## Features

- **🚀 Ultra-fast** — <0.5ms average evaluation latency, 4,000+ ops/sec throughput
- **🪐 Three modes** — **local** (zero config, no network), **hybrid** (local evaluator + background sync to the hosted backend), **hosted** (every call over the network, legacy)
- **🔒 Integrity checks** — HMAC-SHA256 envelope signatures when you set `signature_key`, a SHA-256 content hash on every audit record, SHA-256 checks on the disk cache
- **💾 Persistent audit trail** — SQLite-backed queryable history, drained to the hosted backend on a 30s interval in hybrid mode
- **🧠 Background sync engine** — circuit-breaker-protected channels for audit upload + policy / route / kill-switch download, with ETag-conditional GETs for policies and routes
- **⚡ Disk-backed cache** — POSIX-atomic writes, integrity-verified warm-start across SDK restarts
- **🎯 Rate limiting** — sliding-window algorithm, counted per action, agent, user, org, or user and action
- **📝 Multiple formats** — JSON and YAML policy support
- **🔍 Type-safe** — full TypeScript types with Zod validation
- **🤝 Cross-language parity** — the Python and TypeScript evaluators are checked against the [shared conformance fixtures](https://github.com/hiitlhq/hiitl/tree/main/tests/conformance/cases)

## Installation

```bash
npm install @hiitl/sdk
```

(`@hiitl/core` is pulled in transitively — no need to install separately.)

## Quick Start

```typescript
import { HIITL } from '@hiitl/sdk';

// Initialize client
const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'payment-agent',
  org_id: 'org_mycompany123456789',
  policy_path: './policy.yaml',
  mode: 'RESPECT_POLICY', // enforce; the default, OBSERVE_ALL, records what the policy would decide
});

// Evaluate an action
const decision = await hiitl.evaluate({
  action: 'payment_transfer',
  operation: 'execute',
  target: { account: 'dest123' },
  parameters: { amount: 500, currency: 'USD' },
});

// Check decision
if (decision.allowed) {
  console.log('✅ Action allowed:', decision.reason_codes);
  // Execute the action
} else {
  console.log('❌ Action blocked:', decision.reason_codes);
  // Handle block or pause
}

// Clean up
hiitl.close();
```

`evaluate()` returns a `Decision` in local mode and a `Promise<Decision>` in hybrid and hosted mode. `await` it in every mode.

## Configuration

### Constructor Options

```typescript
const hiitl = new HIITL({
  // All options are optional. new HIITL() runs locally in OBSERVE_ALL mode.
  environment: 'dev' | 'stage' | 'prod', // Default: 'dev'
  agent_id: string, // Default: 'default'
  org_id: string, // Format: org_<16+ letters or digits>
  mode: 'OBSERVE_ALL' | 'RESPECT_POLICY', // Default: 'OBSERVE_ALL'
  policy_path: string, // Required for RESPECT_POLICY in local mode
  audit_db_path: string, // Default: './hiitl_audit.db'
  enable_rate_limiting: boolean, // Default: true
  routes_path: string, // Directory of route config files
  signature_key: string, // The API key's signing secret: signs every envelope. Required for hosted evaluation

  // Hybrid and hosted mode
  api_key: string, // Hybrid mode (local evaluation + background sync)
  server_url: string, // The sync target; with evaluation: 'remote', the hosted server
  evaluation: 'local' | 'remote', // Default: 'local'. 'remote' (with api_key + server_url): hosted mode
  sync: boolean, // Default: true. false keeps a client with an api_key local
  cache_dir: string, // Hybrid disk cache. Default: '~/.hiitl/cache/'
  sync_init_timeout: number, // Seconds to wait for the first sync. Default: 10
  cold_start_behavior: 'warn-and-observe' | 'fail-closed' | 'observe-silent', // Default: 'warn-and-observe'
  timeout: number, // Hosted request timeout in ms. Default: 5000
  max_retries: number, // Hosted request retries. Default: 3

  principal_verifier: (token: string) => PrincipalClaims, // Checks evaluate({ principal_token })
  route_fetch: typeof fetch, // The fetch sync routes are asked with. Default: global fetch
});
```

### Environment Variables

The SDK reads each option from its `HIITL_*` variable when the constructor leaves it unset (the full list is on the configuration page); constructor args take precedence:

```bash
export HIITL_ENVIRONMENT=dev
export HIITL_AGENT_ID=payment-agent
export HIITL_ORG_ID=org_mycompany123456789
export HIITL_POLICY_PATH=./policy.yaml
export HIITL_AUDIT_DB_PATH=./audit.db
export HIITL_ENABLE_RATE_LIMITING=true
export HIITL_ROUTES_PATH=./routes
export HIITL_SIGNATURE_KEY=your-secret-key
```

The mode follows the resolved settings: `HIITL_API_KEY` alone is hybrid mode, and with `HIITL_SERVER_URL` and `HIITL_EVALUATION=remote` it is hosted.

## Policy Format

### JSON Policy

```json
{
  "name": "payment-policy",
  "version": "v1.0.0",
  "description": "Payment controls",
  "scope": {
    "org_id": "org_mycompany123456789",
    "environment": "dev"
  },
  "rules": [
    {
      "name": "allow-small-payments",
      "description": "Allow payments under $1000",
      "priority": 100,
      "decision": "ALLOW",
      "reason_code": "SMALL_AMOUNT",
      "conditions": {
        "field": "parameters.amount",
        "operator": "less_than",
        "value": 1000
      }
    },
    {
      "name": "pause-large-payments",
      "description": "Require approval for large payments",
      "priority": 90,
      "decision": "PAUSE",
      "reason_code": "LARGE_AMOUNT",
      "conditions": {
        "field": "parameters.amount",
        "operator": "greater_than_or_equal",
        "value": 1000
      }
    }
  ]
}
```

### YAML Policy (Convenience)

```yaml
name: payment-policy
version: "v1.0.0"
description: "Payment controls"
scope:
  org_id: "org_mycompany123456789"
  environment: "dev"
rules:
  - name: allow-small-payments
    description: Allow payments under $1000
    priority: 100
    decision: ALLOW
    reason_code: SMALL_AMOUNT
    conditions:
      field: parameters.amount
      operator: less_than
      value: 1000

  - name: pause-large-payments
    description: Require approval for large payments
    priority: 90
    decision: PAUSE
    reason_code: LARGE_AMOUNT
    conditions:
      field: parameters.amount
      operator: greater_than_or_equal
      value: 1000
```

## API Reference

### `HIITL` Class

#### `evaluate(options): Decision | Promise<Decision>`

Evaluate an action against policy and return decision.

**Parameters:**

```typescript
{
  // Required
  action: string,

  // Optional
  operation?: 'read' | 'write' | 'create' | 'delete' | 'execute' | 'update', // Default: 'execute'
  target?: Record<string, unknown>, // Default: {}
  parameters?: Record<string, unknown>, // Default: {}
  user_id?: string,
  session_id?: string,
  agent_id?: string, // Overrides the agent_id set at init
  idempotency_key?: string, // Generated if omitted
  confidence?: number, // 0 to 1
  reason?: string,
  sensitivity?: ('money' | 'identity' | 'permissions' | 'regulated' | 'irreversible' | 'pii' | 'sensitive_data')[],
  cost_estimate?: {  // any other key is refused, naming it
    tokens?: number,
    dollars?: number,
    api_calls?: number,
  },
  requested_scopes?: string[],  // scopes this call requests; compared with the verified principal's
  principal_token?: string, // checked by the configured principal_verifier
  correlation_id?: string, // your own ID tying this action to others, such as a request ID
}
```

**Returns:**

```typescript
{
  action_id: string,
  decision: 'ALLOW' | 'OBSERVE' | 'BLOCK' | 'PAUSE' | 'REQUIRE_APPROVAL' | 'SANDBOX' | 'KILL_SWITCH'
    | 'ESCALATE' | 'ROUTE' | 'RATE_LIMIT' | 'SIGNATURE_INVALID' | 'CONTROL_PLANE_UNAVAILABLE'
    | 'VALIDATION_ERROR' | 'POLICY_ERROR',
  allowed: boolean,
  reason_codes: string[],
  policy_version: string,
  timing: {
    ingest_ms: number,
    evaluation_ms: number,
    total_ms: number,
  },
  matched_rules?: Array<{ rule_name: string, ... }>,
  remediation?: { // when the matched rule defines it
    message: string,
    suggestion: string,
    type: 'field_restriction' | 'threshold' | 'scope' | 'rate_limit' | 'temporal' | 'custom',
    details?: Record<string, unknown>,
  },
  would_be?: string, // OBSERVE only: what enforcement would decide
  would_be_reason_codes?: string[], // OBSERVE only
  rate_limit?: {
    scope: string,
    window: string,
    limit: number,
    current: number,
    reset_at: string,
  },
}
```

Under the default `OBSERVE_ALL` mode, a decision that allows the call (`ALLOW`, `SANDBOX`) comes back as itself. Any other policy decision comes back `OBSERVE`, with `allowed` true, `reason_codes` `['OBSERVED']`, and `would_be` set to the rule's decision. A call past a windowed rate limit comes back `OBSERVE` with `would_be: RATE_LIMIT` under `OBSERVE_ALL`; under `RESPECT_POLICY` it comes back `RATE_LIMIT`. Failures such as an unwritable audit record still block in every mode.

#### `queryAudit(options): AuditRecord[]`

Query local audit log records. Not available in hosted mode.

```typescript
hiitl.queryAudit({
  org_id?: string, // Default: config.org_id
  action_id?: string,
  decision_type?: string, // e.g. 'BLOCK', 'OBSERVE'
  limit?: number,
  offset?: number,
});
```

#### `close(): void`

Closes the audit database. Call it when you are done with the client.

```typescript
hiitl.close();
```

## Rate Limiting

### Configuration in Policy

A `RATE_LIMIT` rule carries its window. When the call would otherwise be allowed, the SDK counts it, and returns `RATE_LIMIT` with reason code `RATE_LIMIT_EXCEEDED` once the limit is passed:

```json
{
  "name": "rate-limited-policy",
  "version": "v1.0.0",
  "description": "Rate limits on the agent's actions",
  "scope": {
    "org_id": "org_mycompany123456789",
    "environment": "dev"
  },
  "rules": [
    {
      "name": "limit-transfers-per-user",
      "description": "At most 10 transfers a minute per user",
      "priority": 600,
      "conditions": { "field": "action", "operator": "equals", "value": "payment_transfer" },
      "decision": "RATE_LIMIT",
      "reason_code": "TRANSFER_RATE",
      "rate_limit": { "limit": 10, "window_seconds": 60, "scope": "user" }
    },
    {
      "name": "allow-transfers",
      "description": "Transfers proceed within the limit",
      "priority": 10,
      "conditions": { "field": "action", "operator": "equals", "value": "payment_transfer" },
      "decision": "ALLOW",
      "reason_code": "TRANSFER_ALLOWED"
    }
  ]
}
```

A set-level `metadata.rate_limits` list is also accepted. It is compiled to `RATE_LIMIT` rules when the policy loads:

```json
{
  "name": "rate-limited-policy",
  "version": "v1.0.0",
  "description": "Rate limits on the agent's actions",
  "scope": {
    "org_id": "org_mycompany123456789",
    "environment": "dev"
  },
  "rules": [
    {
      "name": "allow-transfers",
      "description": "Transfers proceed within the limits",
      "priority": 10,
      "conditions": { "field": "action", "operator": "equals", "value": "payment_transfer" },
      "decision": "ALLOW",
      "reason_code": "TRANSFER_ALLOWED"
    }
  ],
  "metadata": {
    "rate_limits": [
      {
        "scope": "org",
        "limit": 100,
        "window_seconds": 60
      },
      {
        "scope": "user:tool",
        "limit": 10,
        "window_seconds": 60
      }
    ]
  }
}
```

### Scope Types

On a rule's `rate_limit`:

- **action** (the default): Rate limit per action
- **agent**: Rate limit per agent
- **user**: Rate limit per user
- **org**: Rate limit per organization
- **user_action**: Rate limit per user+action combination

In `metadata.rate_limits`: `org` (the default), `agent`, `user`, `tool` (per action) and `user:tool` (per user+action).

### Sliding Window

The SDK uses a sliding window algorithm that automatically cleans up expired events. This provides smooth rate limiting without sudden resets at fixed intervals.

## Audit Logging

### Audit Records

Each record in the local SQLite audit log holds:

| Field | Contents |
|-------|----------|
| `event_id` | Unique event ID |
| `timestamp` | When the decision was recorded |
| `org_id`, `environment`, `agent_id` | Who acted, and where |
| `action_id` | The evaluated action's ID |
| `envelope` | The evaluated envelope (JSON) |
| `decision` | The decision (JSON) |
| `policy_version` | The policy version evaluated |
| `decision_type` | `ALLOW`, `BLOCK`, `OBSERVE`, … |
| `action` | The action name, as the envelope names it |
| `content_hash` | SHA-256 of the record's content |

### Querying Audit Logs

```typescript
// Query by org
const records = hiitl.queryAudit({
  org_id: 'org_mycompany123456789',
  limit: 100,
});

// Query by action
const actionRecords = hiitl.queryAudit({
  action_id: decision.action_id,
});

// Query by decision type
const blockedRecords = hiitl.queryAudit({
  decision_type: 'BLOCK',
  limit: 50,
});
```

### Integrity Verification

Each audit record includes a SHA-256 content hash for integrity verification:

```typescript
import { AuditLogger } from '@hiitl/sdk';

const record = hiitl.queryAudit({ action_id: decision.action_id })[0];
const audit = new AuditLogger('./hiitl_audit.db');
const isValid = audit.verifyIntegrity(record.event_id); // Recomputes the hash; false if the record changed
audit.close();
```

## Performance

### Benchmarks (Measured)

- **Average latency**: 0.30ms
- **P95 latency**: 0.50ms
- **Cache hit latency**: 0.22ms
- **Throughput**: 5,300+ ops/sec
- **1000 evaluations**: 186ms

### Optimization Tips

1. **Use in-memory audit DB for maximum speed**: `audit_db_path: ':memory:'`
2. **Disable rate limiting if not needed**: `enable_rate_limiting: false`
3. **Keep policies small**: `active` and `staged` rules are evaluated; `draft`, `disabled` and `archived` rules are skipped
4. **Reuse client instance**: Initialization loads policy and creates DB

## Error Handling

### Error Types

`evaluate()` throws only before an envelope exists. Once it does, a failure is a decision with `allowed` false and is
recorded: `SIGNATURE_INVALID`, `POLICY_ERROR` (a policy file that goes missing or stops parsing), or `BLOCK` with
`error.code` `AUDIT_WRITE_FAILED` when the audit record cannot be written (the one with no record).

```typescript
import {
  HIITL,
  HIITLError,
  ConfigurationError,
  PolicyLoadError,
  AuditLogError,
  EnvelopeValidationError,
} from '@hiitl/sdk';

try {
  const hiitl = new HIITL({ policy_path: './policy.yaml', mode: 'RESPECT_POLICY' });
  const decision = await hiitl.evaluate({ action: 'payment_transfer', parameters: { amount: 500 } });
} catch (error) {
  if (error instanceof ConfigurationError) {
    // Invalid configuration
  } else if (error instanceof PolicyLoadError) {
    // Policy file not found or invalid when the client is constructed
  } else if (error instanceof EnvelopeValidationError) {
    // Invalid envelope fields: the envelope cannot be built
  } else if (error instanceof AuditLogError) {
    // The audit database cannot be created
  }
}
```

### Helpful Error Messages

Errors say what went wrong and how to fix it. An invalid `org_id`:

```
ConfigurationError: Invalid HIITL configuration: [
  {
    "validation": "regex",
    "code": "invalid_string",
    "message": "Invalid org_id. Must match the envelope's org_id pattern /^org_[a-zA-Z0-9]{16,}$/. Use the org id your API key belongs to, e.g. 'org_mycompany123456789'",
    "path": [
      "org_id"
    ]
  }
]

Check that all required parameters are provided and valid.
```

## Advanced Usage

### Custom Components

For power users who need fine-grained control:

```typescript
import { PolicyLoader, PolicyEvaluator, AuditLogger, RateLimiter } from '@hiitl/sdk';
import type { Envelope } from '@hiitl/sdk';

// Load policy
const loader = new PolicyLoader('./policy.yaml');
const policy = loader.load();

// Build an envelope (the `HIITL` client does this for you)
const envelope: Envelope = {
  schema_version: 'v2.0',
  org_id: 'org_mycompany123456789',
  environment: 'dev',
  agent_id: 'payment-agent',
  action_id: 'act_7f3k9m2q8w4e6r1t5y0u',
  idempotency_key: 'idem_7f3k9m2q8w4e6r1t5y0u',
  action: 'payment_transfer',
  operation: 'execute',
  target: { account: 'dest123' },
  parameters: { amount: 500, currency: 'USD' },
  timestamp: new Date().toISOString(),
  signature: '0'.repeat(64), // HMAC-SHA256 hex; the client signs when signature_key is set
  signature_version: 'hmac-sha256-v1',
};

// Evaluate
const evaluator = new PolicyEvaluator();
const decision = evaluator.evaluate(envelope, policy);

// Audit
const logger = new AuditLogger('./audit.db');
logger.write(envelope, decision);

// Rate limit: a RATE_LIMIT decision when a limit is passed, otherwise null
const limiter = new RateLimiter();
const rateLimited = limiter.checkAndIncrement(envelope, decision);
```

## TypeScript Support

Full TypeScript types with strict validation:

```typescript
import type { Decision, DecisionType, Envelope, PolicySet } from '@hiitl/sdk';

const decision: Decision = await hiitl.evaluate({ action: 'payment_transfer', parameters: { amount: 500 } });
console.log(decision.allowed); // Type: boolean
console.log(decision.decision); // Type: DecisionType ('ALLOW' | 'OBSERVE' | 'BLOCK' | 'PAUSE' | …)
```

## Examples

### Payment Gateway

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'prod',
  agent_id: 'payment-gateway',
  org_id: process.env.HIITL_ORG_ID!,
  policy_path: './policies/payment.yaml',
  signature_key: process.env.HIITL_SIGNATURE_KEY,
  mode: 'RESPECT_POLICY',
});

async function processPayment(userId: string, amount: number, destination: string) {
  const decision = await hiitl.evaluate({
    action: 'payment_transfer',
    operation: 'execute',
    target: { account: destination },
    parameters: { amount, currency: 'USD' },
    user_id: userId,
    sensitivity: ['money'],
  });

  if (decision.decision === 'ALLOW') {
    return await executePayment(amount, destination);
  } else if (decision.decision === 'PAUSE') {
    return await requestHumanApproval(decision.action_id);
  } else {
    throw new Error(`Payment blocked: ${decision.reason_codes.join(', ')}`);
  }
}
```

### Database Operations

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'prod',
  agent_id: 'db-agent',
  org_id: process.env.HIITL_ORG_ID!,
  policy_path: './policies/database.yaml',
  mode: 'RESPECT_POLICY',
});

async function deleteUserData(userId: string, tableName: string) {
  const decision = await hiitl.evaluate({
    action: 'database',
    operation: 'delete',
    target: { table: tableName },
    parameters: { user_id: userId },
    user_id: userId,
    sensitivity: ['pii', 'irreversible'],
  });

  if (!decision.allowed) {
    throw new Error(`Delete blocked: ${decision.reason_codes.join(', ')}`);
  }

  return await db.delete(tableName, { user_id: userId });
}
```

## License

Apache-2.0

## Support

- Documentation: https://github.com/hiitlhq/hiitl
- Issues: https://github.com/hiitlhq/hiitl/issues
- Specs: See `docs/specs/` for detailed specifications
