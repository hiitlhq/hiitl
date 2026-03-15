# @hiitl/sdk

TypeScript SDK for HIITL (Human-in-the-Loop) policy evaluation in local/edge mode.

## Features

- **🚀 Ultra-fast**: < 0.5ms average latency, 5000+ ops/sec throughput
- **📦 Zero external dependencies**: Embedded evaluator, SQLite audit log, in-memory rate limiting
- **🔒 Secure**: HMAC-SHA256 signatures, append-only audit log with SHA-256 integrity hashes
- **💾 Persistent audit trail**: SQLite database with queryable history
- **⚡ Smart caching**: Sub-millisecond cache hits with mtime-based invalidation
- **🎯 Rate limiting**: Sliding window algorithm with configurable scopes (org, user, tool, user:tool)
- **📝 Multiple formats**: JSON and YAML policy support
- **🔍 Type-safe**: Full TypeScript types with Zod validation

## Installation

```bash
npm install @hiitl/sdk @hiitl/core
```

## Quick Start

```typescript
import { HIITL } from '@hiitl/sdk';

// Initialize client
const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'payment-agent',
  org_id: 'org_mycompany123456789',
  policy_path: './policy.yaml',
});

// Evaluate an action
const decision = hiitl.evaluate({
  tool: 'payment_transfer',
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

## Configuration

### Constructor Options

```typescript
const hiitl = new HIITL({
  // Required
  environment: 'dev' | 'stage' | 'prod',
  agent_id: string,
  org_id: string, // Format: org_<18+ chars>
  policy_path: string,

  // Optional
  audit_db_path: string, // Default: './hiitl_audit.db'
  enable_rate_limiting: boolean, // Default: true
  signature_key: string, // For HMAC-SHA256 signatures
});
```

### Environment Variables

The SDK supports environment variable configuration (constructor args take precedence):

```bash
export HIITL_ENVIRONMENT=dev
export HIITL_AGENT_ID=payment-agent
export HIITL_ORG_ID=org_mycompany123456789
export HIITL_POLICY_PATH=./policy.yaml
export HIITL_AUDIT_DB_PATH=./audit.db
export HIITL_ENABLE_RATE_LIMITING=true
export HIITL_SIGNATURE_KEY=your-secret-key
```

## Policy Format

### JSON Policy

```json
{
  "name": "payment-policy",
  "version": "1.0",
  "rules": [
    {
      "name": "allow-small-payments",
      "description": "Allow payments under $1000",
      "priority": 100,
      "enabled": true,
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
      "enabled": true,
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
version: "1.0"
rules:
  - name: allow-small-payments
    description: Allow payments under $1000
    priority: 100
    enabled: true
    decision: ALLOW
    reason_code: SMALL_AMOUNT
    conditions:
      field: parameters.amount
      operator: less_than
      value: 1000

  - name: pause-large-payments
    description: Require approval for large payments
    priority: 90
    enabled: true
    decision: PAUSE
    reason_code: LARGE_AMOUNT
    conditions:
      field: parameters.amount
      operator: greater_than_or_equal
      value: 1000
```

## API Reference

### HIITL Class

#### `evaluate(options): Decision`

Evaluate an action against policy and return decision.

**Parameters:**

```typescript
{
  // Required
  tool: string,
  operation: 'execute' | 'read' | 'write' | 'delete' | string,
  target: Record<string, unknown>,
  parameters: Record<string, unknown>,

  // Optional
  user_id?: string,
  session_id?: string,
  idempotency_key?: string,
  confidence?: number,
  reason?: string,
  sensitivity?: ('money' | 'identity' | 'permissions' | 'regulated' | 'irreversible' | 'pii' | 'sensitive_data')[],
  cost_estimate?: {
    tokens?: number,
    usd_cents?: number,
  },
}
```

**Returns:**

```typescript
{
  action_id: string,
  decision: 'ALLOW' | 'BLOCK' | 'PAUSE' | 'RATE_LIMIT',
  allowed: boolean,
  reason_codes: string[],
  policy_version: string,
  timing: {
    ingest_ms: number,
    evaluation_ms: number,
    total_ms: number,
  },
  rate_limit?: {
    scope: string,
    window: string,
    limit: number,
    current: number,
    reset_at: string,
  },
}
```

#### `queryAudit(options): AuditRecord[]`

Query audit log records.

```typescript
hiitl.queryAudit({
  org_id?: string, // Default: config.org_id
  action_id?: string,
  decision_type?: 'ALLOW' | 'BLOCK' | 'PAUSE' | 'RATE_LIMIT',
  limit?: number,
  offset?: number,
});
```

#### `close(): void`

Close all resources (audit database). Should be called when done with the client.

```typescript
hiitl.close();
```

## Rate Limiting

### Configuration in Policy

```json
{
  "name": "rate-limited-policy",
  "version": "1.0",
  "rules": [...],
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

- **org**: Rate limit per organization
- **user**: Rate limit per user
- **tool**: Rate limit per tool
- **user:tool**: Rate limit per user+tool combination

### Sliding Window

The SDK uses a sliding window algorithm that automatically cleans up expired events. This provides smooth rate limiting without sudden resets at fixed intervals.

## Audit Logging

### SQLite Schema

```sql
CREATE TABLE audit_log (
  event_id TEXT PRIMARY KEY,
  timestamp TEXT NOT NULL,
  org_id TEXT NOT NULL,
  environment TEXT NOT NULL,
  action_id TEXT NOT NULL,
  envelope TEXT NOT NULL,
  decision TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  tool_name TEXT,
  agent_id TEXT,
  content_hash TEXT NOT NULL
);
```

### Querying Audit Logs

```typescript
// Query by org
const records = hiitl.queryAudit({
  org_id: 'org_mycompany123456789',
  limit: 100,
});

// Query by action
const records = hiitl.queryAudit({
  action_id: 'act_abc123',
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
const record = hiitl.queryAudit({ action_id: 'act_abc123' })[0];
const isValid = verifyIntegrity(record); // Check if tampered
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
3. **Keep policies small**: Only enabled rules are evaluated
4. **Reuse client instance**: Initialization loads policy and creates DB

## Error Handling

### Error Types

```typescript
import {
  HIITLError,
  ConfigurationError,
  PolicyLoadError,
  AuditLogError,
  EnvelopeValidationError,
} from '@hiitl/sdk';

try {
  const hiitl = new HIITL({ ... });
  const decision = hiitl.evaluate({ ... });
} catch (error) {
  if (error instanceof ConfigurationError) {
    // Invalid configuration
  } else if (error instanceof PolicyLoadError) {
    // Policy file not found or invalid
  } else if (error instanceof EnvelopeValidationError) {
    // Invalid envelope fields
  } else if (error instanceof AuditLogError) {
    // Audit database error
  }
}
```

### Helpful Error Messages

All errors include helpful context and links to documentation:

```
ConfigurationError: Invalid HIITL configuration: Invalid org_id format

Check that all required parameters are provided and valid.
Required: environment, agent_id, policy_path, org_id

Org ID must match pattern: org_<18+ alphanumeric characters>
```

## Advanced Usage

### Custom Components

For power users who need fine-grained control:

```typescript
import { PolicyLoader, PolicyEvaluator, AuditLogger, RateLimiter } from '@hiitl/sdk';

// Load policy
const loader = new PolicyLoader('./policy.yaml');
const policy = loader.load();

// Evaluate
const evaluator = new PolicyEvaluator();
const decision = evaluator.evaluate(envelope, policy);

// Audit
const logger = new AuditLogger('./audit.db');
logger.write(envelope, decision);

// Rate limit
const limiter = new RateLimiter();
const rateLimited = limiter.checkAndIncrement(envelope, decision, policy.metadata);
```

## TypeScript Support

Full TypeScript types with strict validation:

```typescript
import type { Decision, Envelope, PolicySet } from '@hiitl/sdk';

const decision: Decision = hiitl.evaluate({ ... });
console.log(decision.allowed); // Type: boolean
console.log(decision.decision); // Type: 'ALLOW' | 'BLOCK' | 'PAUSE' | 'RATE_LIMIT'
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
});

async function processPayment(userId: string, amount: number, destination: string) {
  const decision = hiitl.evaluate({
    tool: 'payment_transfer',
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
});

async function deleteUserData(userId: string, tableName: string) {
  const decision = hiitl.evaluate({
    tool: 'database',
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

MIT

## Support

- Documentation: https://github.com/hiitlhq/hiitl
- Issues: https://github.com/hiitlhq/hiitl/issues
- Specs: See `docs/specs/` for detailed specifications
