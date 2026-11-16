# TypeScript Quickstart - hiitl ECP

**Goal**: From install to first evaluated action in **under 5 minutes**.

**Target**: TypeScript/JavaScript developers building AI agents that take real-world actions.

---

## Prerequisites

- Node.js 22+
- npm, yarn, or pnpm

---

## Step 1: Install the SDK (30 seconds)

```bash
npm install @hiitl/sdk
```

Or with yarn:
```bash
yarn add @hiitl/sdk
```

Or with pnpm:
```bash
pnpm add @hiitl/sdk
```

---

## Step 2: Get Your API Key (1 minute)

### For Testing (Local Mode - No API Key Needed)

hiitl can run entirely locally, with no API key and no server. Perfect for testing!

### For Hybrid or Hosted Mode

1. Sign up at https://hiitl.com (your organization is created with your account)
2. Create an API key in the dashboard under **Settings → API Keys** (it is shown once)
3. Set environment variable:
   ```bash
   export HIITL_API_KEY="your_api_key_here"
   ```
4. The SDK reads `HIITL_API_KEY` when no `api_key` option is passed, so setting the variable starts hybrid mode; passing `api_key: process.env.HIITL_API_KEY` does the same explicitly.

---

## Step 3: Write Your First Protected Action (2 minutes)

Create `example.ts`:

```typescript
import { HIITL } from '@hiitl/sdk';

// Initialize hiitl (no API key = local mode, auto-detected)
const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'my-first-agent',
});

// Define an action you want to protect
async function processPayment(accountId: string, amount: number) {
  console.log(`Processing $${amount} payment for account ${accountId}`);
  // ... actual payment logic here ...
  return { status: 'success', transactionId: 'txn_123' };
}

// Wrap the action with ECP evaluation
async function main() {
  const decision = await hiitl.evaluate({
    action: 'process_payment',
    operation: 'execute',
    target: { accountId: 'acct_123' },
    parameters: { amount: 150.00, currency: 'usd' },
  });

  // Check the decision
  if (decision.allowed) {
    // ECP says it's safe to proceed
    const result = await processPayment('acct_123', 150.00);
    console.log('✓ Payment processed:', result);
  } else {
    // ECP blocked or paused the action
    console.log(`✗ Action blocked: ${decision.decision}`);
    console.log(`  Reason: ${decision.reason_codes}`);
  }
}

main().catch(console.error);
```

---

## Step 4: Run It (30 seconds)

```bash
npx tsx example.ts
# or with ts-node:
npx ts-node example.ts
# or compile and run (the SDK is an ES module: set "type": "module" in
# package.json and "module": "NodeNext" in tsconfig.json):
npx tsc && node example.js
```

Expected output:
```
Processing $150 payment for account acct_123
✓ Payment processed: { status: 'success', transactionId: 'txn_123' }
```

With no policy loaded, the action is observed: `decision.decision` is `OBSERVE`, `allowed` is `true`, and `decision.would_be` is `BLOCK` with `NO_MATCHING_RULE`, which is what enforcement would decide while no rule allows the action.

`evaluate()` returns a `Decision` in local mode and a `Promise<Decision>` in hybrid and hosted mode. `await` it in every mode, so your code does not change when you add an API key.

**Congratulations!** You just:
1. Installed the hiitl SDK
2. Evaluated an action through the control point
3. Executed based on ECP's decision

---

## Step 5: Add a Policy (1 minute)

Create `policy.yaml`. An action no rule matches is blocked once you enforce, so the policy allows payments and blocks the large ones. Every rule needs a `description`:

```yaml
policy_set:
  name: "payment-controls"
  version: "v1.0.0"
  description: "Payment controls for the quickstart agent"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"
  rules:
    - name: "block-high-value-payments"
      description: "Payments over $500 are refused"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "BLOCK"
      reason_code: "PAYMENT_TOO_HIGH"
    - name: "allow-payments"
      description: "Other payments proceed"
      priority: 10
      conditions:
        field: "action"
        operator: "equals"
        value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"
```

Update `example.ts` to load the policy and enforce it. The default mode, `OBSERVE_ALL`, only records what the policy would do; `mode: 'RESPECT_POLICY'` enforces it:

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'my-first-agent',
  policy_path: './policy.yaml',  // Load policy (no api_key = local mode)
  mode: 'RESPECT_POLICY',        // Enforce it
});

async function main() {
  // Try a payment over $500
  const decision = await hiitl.evaluate({
    action: 'process_payment',
    operation: 'execute',
    target: { accountId: 'acct_456' },
    parameters: { amount: 1000.00, currency: 'usd' },  // Over the limit!
  });

  if (decision.allowed) {
    console.log('✓ Payment allowed');
  } else {
    console.log(`✗ Payment blocked: ${decision.reason_codes}`);
  }
}

main().catch(console.error);
```

Run it:
```bash
npx tsx example.ts
```

Expected output:
```
✗ Payment blocked: PAYMENT_TOO_HIGH
```

**The policy worked!** Payments over $500 are now blocked.

Without `mode: 'RESPECT_POLICY'`, the same call comes back as `OBSERVE`, with `would_be` `'BLOCK'` and `would_be_reason_codes` `['PAYMENT_TOO_HIGH']`. That lets you watch what a policy would do before you enforce it.

---

## What Just Happened?

1. **Envelope Creation**: The SDK created a structured envelope with all required metadata
2. **Policy Evaluation**: Your policy was evaluated against the envelope
3. **Deterministic Decision**: The rule matched (amount > 500) → BLOCK decision
4. **Audit Trail**: An audit record was written to `./hiitl_audit.db` (the default `audit_db_path`), with a SHA-256 hash of its content

---

## Key Concepts

### Mode Auto-Detection

The SDK automatically detects the mode based on which config fields you provide:

| Mode | Config | Best For |
|------|--------|----------|
| **Local** | No `api_key` (optional `policy_path`) | Development, testing, low-latency |
| **Hybrid** | `api_key` (`server_url`, when given, is the sync target) | Production: local evaluation, with policies and the audit trail synced to `https://api.hiitl.com` |
| **Hosted** | `api_key` + `server_url` + `evaluation: 'remote'` | Every evaluation is a call to the server |

Options are snake_case. An option left out is read from its `HIITL_*` variable (`HIITL_API_KEY`, `HIITL_SERVER_URL`, `HIITL_EVALUATION`, ...), and the mode follows the resolved values. `sync: false` keeps an SDK with an `api_key` in local mode.

### The Execution Envelope

The `evaluate()` call creates an envelope with:
- **Identifiers**: org_id, environment, agent_id, action_id and idempotency key (auto-generated)
- **Action definition**: action, operation, target, parameters
- **Risk signals**: sensitivity, cost_estimate (optional)
- **Context**: reason, timestamps (auto-generated)

**You only specify what's unique to this action**. Everything else is handled by the SDK.

### Decisions

| Decision | `allowed` | Meaning |
|----------|-----------|---------|
| `ALLOW` | `true` | Safe to proceed |
| `OBSERVE` | `true` | Recorded, not enforced (`OBSERVE_ALL` mode); `would_be` holds the enforced decision |
| `BLOCK` | `false` | Denied by policy |
| `REQUIRE_APPROVAL` | `false` | Needs human review before execution |
| `PAUSE` | `false` | Held for later processing |
| `ESCALATE` | `false` | Escalated to a higher authority |
| `ROUTE` | `false` | A sync route was asked and has not answered |
| `RATE_LIMIT` | `false` | Too many requests — wait and retry |
| `KILL_SWITCH` | `false` | Emergency stop — do not retry |
| `SANDBOX` | `true` | Allowed in isolated environment |

Under `OBSERVE_ALL`, an ALLOW or SANDBOX comes back as itself; every other decision comes back as `OBSERVE`. A windowed `RATE_LIMIT` rule still refuses the call past its limit in either mode.

The TypeScript `Decision` has no `.ok` or `.blocked` helpers: check `decision.allowed` and `decision.decision`.

---

## Common Patterns

### Pattern 1: Simple Action Protection

```typescript
const decision = await hiitl.evaluate({
  action: 'send_email',
  operation: 'execute',
  target: { email: 'customer@example.com' },
  parameters: { subject: 'Welcome', body: 'Hello...' },
});

if (decision.allowed) {
  await sendEmailViaProvider(...);
}
```

### Pattern 2: Sensitive Actions

```typescript
const decision = await hiitl.evaluate({
  action: 'grant_access',
  operation: 'create',
  target: { userId: 'user_123' },
  parameters: { role: 'admin' },
  sensitivity: ['permissions', 'irreversible'],  // Flag as sensitive
});

if (decision.allowed) {
  await grantDatabaseAccess(...);
}
```

### Pattern 3: High-Cost Actions

```typescript
const decision = await hiitl.evaluate({
  action: 'run_batch_job',
  operation: 'execute',
  target: { jobId: 'job_456' },
  parameters: { records: 1000000 },
  cost_estimate: { tokens: 100000 },  // Estimated cost
});

if (decision.allowed) {
  await startExpensiveJob(...);
}
```

`CostEstimate` is the envelope's own: `tokens` (a number), `dollars` and `api_calls` (`envelope_schema.json` v1.4), and policies read `cost_estimate.dollars`. A key it does not define is refused, naming it. 0.2.0's type declared `usd_cents`, which the envelope dropped; see the SDK changelog.

### Pattern 4: Handling Rate Limits

A rate limit is a `RATE_LIMIT` rule with a window, such as `rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}`. The call past the limit comes back as `RATE_LIMIT`, with the counter state in `decision.rate_limit`:

```typescript
const decision = await hiitl.evaluate({
  action: 'send_email',
  parameters: { to: 'customer@example.com' },
});

if (decision.decision === 'RATE_LIMIT') {
  const resetTime = decision.rate_limit?.reset_at;
  console.log(`Rate limited. Retry after ${resetTime}`);
} else if (decision.allowed) {
  await executeAction(...);
}
```

### Pattern 5: TypeScript Type Safety

`evaluate()` is not generic: `target` and `parameters` are `Record<string, unknown>`. Type your own values and pass them in; the decision is fully typed:

```typescript
import { HIITL } from '@hiitl/sdk';
import type { Decision } from '@hiitl/sdk';

type PaymentParams = {
  amount: number;
  currency: string;
};

type PaymentTarget = {
  accountId: string;
};

const target: PaymentTarget = { accountId: 'acct_123' };
const parameters: PaymentParams = { amount: 150.00, currency: 'usd' };

const decision: Decision = await hiitl.evaluate({
  action: 'process_payment',
  operation: 'execute',
  target,
  parameters,
});

console.log(decision.allowed);  // boolean
console.log(decision.decision); // DecisionType
```

---

## Debugging & Observability

### See Timing Metadata

```typescript
const decision = await hiitl.evaluate({ action: 'process_payment', parameters: { amount: 50.00 } });
console.log(`Evaluation took ${decision.timing.total_ms}ms`);
```

**Target latency**:
- Local mode: < 10ms
- Hosted mode: < 50ms

### View Audit Log (Local and Hybrid Mode)

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({ environment: 'dev', agent_id: 'my-first-agent' });

// Query the local audit log (not available in hosted mode)
const events = hiitl.queryAudit({
  decision_type: 'BLOCK',
  limit: 10,
});

for (const event of events) {
  console.log(`${event.timestamp}: ${event.action} ${event.decision_type}`);
}
```

`queryAudit()` takes one filter, `org_id`, `action_id` or `decision_type`, with `limit` and `offset`. With no filter it returns your organization's records. The `action` field holds the action name, as the envelope does.

### Logging

There is no debug option. The SDK writes warnings to the console, and in hybrid mode its sync activity as well (at `console.debug`). Evaluation has no step-by-step log; read the decision and the audit record instead.

---

## Integration with Popular Frameworks

### Next.js API Route

```typescript
// app/api/process-payment/route.ts
import { HIITL } from '@hiitl/sdk';
import { NextRequest, NextResponse } from 'next/server';

const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY!,  // api_key alone = hybrid mode: in-process evaluation, synced policies
  environment: 'prod',
  agent_id: 'payment-api',
  mode: 'RESPECT_POLICY',
});

export async function POST(request: NextRequest) {
  const { accountId, amount } = await request.json();

  const decision = await hiitl.evaluate({
    action: 'process_payment',
    operation: 'execute',
    target: { accountId },
    parameters: { amount, currency: 'usd' },
  });

  if (!decision.allowed) {
    return NextResponse.json(
      { error: 'Payment blocked', reasons: decision.reason_codes },
      { status: 403 }
    );
  }

  const result = await processPayment(accountId, amount);
  return NextResponse.json(result);
}
```

### Express.js Middleware

```typescript
import express from 'express';
import { HIITL } from '@hiitl/sdk';

const app = express();
const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY!,  // api_key alone = hybrid mode
  environment: 'prod',
  agent_id: 'express-api',
  mode: 'RESPECT_POLICY',
});

app.post('/api/process-payment', async (req, res) => {
  const { accountId, amount } = req.body;

  const decision = await hiitl.evaluate({
    action: 'process_payment',
    operation: 'execute',
    target: { accountId },
    parameters: { amount, currency: 'usd' },
  });

  if (!decision.allowed) {
    return res.status(403).json({
      error: 'Payment blocked',
      reasons: decision.reason_codes,
    });
  }

  const result = await processPayment(accountId, amount);
  res.json(result);
});
```

### Vercel AI SDK

```typescript
import { HIITL } from '@hiitl/sdk';
import { streamText } from 'ai';
import { openai } from '@ai-sdk/openai';
import { z } from 'zod';

const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY!,  // api_key alone = hybrid mode
  environment: 'prod',
  agent_id: 'ai-assistant',
  mode: 'RESPECT_POLICY',
});

async function handleToolCall(toolName: string, args: any) {
  // Evaluate before executing tool
  const decision = await hiitl.evaluate({
    action: toolName,
    operation: 'execute',
    target: {},
    parameters: args,
  });

  if (!decision.allowed) {
    throw new Error(`Tool blocked: ${decision.reason_codes.join(', ')}`);
  }

  // Execute the actual tool
  return executeTool(toolName, args);
}

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = await streamText({
    model: openai('gpt-4'),
    messages,
    tools: {
      process_payment: {
        description: 'Process a payment',
        parameters: z.object({
          accountId: z.string(),
          amount: z.number(),
        }),
        execute: async ({ accountId, amount }) => {
          return await handleToolCall('process_payment', { accountId, amount });
        },
      },
    },
  });

  return result.toAIStreamResponse();
}
```

---

## Next Steps

### 1. Add More Policies

Create policies for:
- Rate limiting: a `RATE_LIMIT` rule with `rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}`
- Kill switches: `KILL_SWITCH` rules you switch on and off with `lifecycle_stage` (`active` / `disabled`)
- Approval workflows: `decision: "REQUIRE_APPROVAL"` for high-stakes actions. The decision comes back to your code; nothing is queued unless a review case is opened

See: [Policy Cookbook](policy_cookbook.md)

### 2. Integrate with Your Framework

hiitl works with any TypeScript code, but we have examples for:
- Vercel AI SDK agents
- LangChain.js
- Custom agent loops

See: [Integration Examples](integration_examples.md)

### 3. Deploy to Production

When ready:
1. Sign up for hosted ECP at https://hiitl.com
2. Create an API key for the `prod` environment
3. Update SDK config. Adding `api_key` turns on hybrid mode: evaluation stays in-process, and policies and the audit trail sync with the hosted service in the background:
   ```typescript
   const hiitl = new HIITL({
     api_key: process.env.HIITL_API_KEY,
     environment: 'prod',
     agent_id: 'my-agent',
     policy_path: './policy.yaml',  // Used while no synced policy is cached
     mode: 'RESPECT_POLICY',
   });
   ```
   Adding `server_url` and `evaluation: 'remote'` switches to hosted mode, where every call goes to the server. Hosted mode also needs `org_id`.
4. Deploy policies through the API (`POST /v1/policies`, admin scope). The dashboard shows them

### 4. Monitor & Observe

- View audit trail in dashboard
- Query audit logs through the API (`GET /v1/audit`, read scope) for compliance

---

## Troubleshooting

### Import Error: `Cannot find package '@hiitl/sdk'`

**Solution**: Install the SDK: `npm install @hiitl/sdk`. The SDK is an ES module: load it with `import`, not `require()`.

### Policy Not Loading

**Solution**: Check file path. Use absolute path or relative to current directory. In an ES module there is no `__dirname`; resolve the path from `import.meta.url`, which points at the file that runs (with `tsc`, the compiled `.js`):
```typescript
import { fileURLToPath } from 'url';

const hiitl = new HIITL({
  policy_path: fileURLToPath(new URL('./policy.yaml', import.meta.url)),
  ...
});
```

### Decision Always OBSERVE (Policy Not Enforcing)

**Solution**: The default mode, `OBSERVE_ALL`, records what the policy would decide and enforces nothing: a BLOCK comes back as `OBSERVE`, with the rule's decision in `would_be`. Pass `mode: 'RESPECT_POLICY'` to enforce:
```typescript
const hiitl = new HIITL({ policy_path: './policy.yaml', mode: 'RESPECT_POLICY' });
```

### Every Action Blocked with `NO_MATCHING_RULE`

**Solution**: Under `RESPECT_POLICY`, an action no rule matches is blocked. Add an `ALLOW` rule, at a lower priority than your BLOCK rules, for each action you mean to let through.

### Options Rejected (`apiKey`, `policyPath`, `agentId`)

**Solution**: Options are snake_case: `api_key`, `policy_path`, `agent_id`, `server_url`. A camelCase name is a compile error.

### TypeScript Type Errors

**Solution**: Ensure you're using TypeScript 4.5+ and have strict mode enabled. The SDK is an ES module, so use Node's module resolution:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": false
  }
}
```

---

## SDK Reference

### `HIITL` Configuration

```typescript
interface HIITLConfigInput {
  // Mode is auto-detected:
  //   No api_key                                   → local mode
  //   api_key + server_url + evaluation: 'remote'  → hosted mode
  //   api_key otherwise                            → hybrid mode (sync: false → local)
  api_key?: string;             // Triggers hybrid/hosted mode when present
  server_url?: string;          // Hosted server, or the sync target in hybrid mode
  evaluation?: 'local' | 'remote';  // 'remote' opts in to hosted mode (default: 'local')
  environment?: 'dev' | 'stage' | 'prod';  // Default: 'dev'
  agent_id?: string;            // Stable agent identifier
  org_id?: string;              // Must match ^org_[a-zA-Z0-9]{16,}$
  mode?: 'OBSERVE_ALL' | 'RESPECT_POLICY';  // Default: 'OBSERVE_ALL'
  policy_path?: string;         // Path to policy YAML/JSON (local/hybrid mode)
  audit_db_path?: string;       // SQLite audit log (default: './hiitl_audit.db')
  enable_rate_limiting?: boolean;  // Default: true
  routes_path?: string;         // Route configurations
  signature_key?: string;       // HMAC key for envelope signing; required for hosted evaluation
  timeout?: number;             // Hosted request timeout in ms (default: 5000)
  max_retries?: number;         // Hosted retries (default: 3)
  sync?: boolean;               // Sync when api_key is set (default: true); false forces local
  cold_start_behavior?: 'warn-and-observe' | 'fail-closed' | 'observe-silent';  // Hybrid only
  cache_dir?: string;           // Hybrid cache (default: ~/.hiitl/cache/)
  sync_init_timeout?: number;   // Hybrid first-sync timeout in seconds (default: 10)
}

const hiitl = new HIITL(config);
```

### evaluate() Parameters

```typescript
interface EvaluateOptions {
  action: string;               // Required: Action name
  operation?: 'read' | 'write' | 'create' | 'delete' | 'execute' | 'update';  // Default: 'execute'
  target?: Record<string, unknown>;      // Resource identifiers (default: {})
  parameters?: Record<string, unknown>;  // Action parameters (default: {})
  sensitivity?: Array<'money' | 'identity' | 'permissions' | 'regulated' | 'irreversible' | 'pii' | 'sensitive_data'>;
  cost_estimate?: {             // the envelope's own; a key it does not define is refused
    tokens?: number;
    dollars?: number;
    api_calls?: number;
  };
  agent_id?: string;            // Optional: Overrides the configured agent_id
  user_id?: string;             // Optional: End-user ID
  session_id?: string;          // Optional: Session ID
  reason?: string;              // Optional: Brief reason string
  idempotency_key?: string;     // Optional: Auto-generated if omitted
}

const decision = await hiitl.evaluate(options);
```

### Decision Object

```typescript
interface Decision {
  action_id: string;
  decision: DecisionType;
  allowed: boolean;
  reason_codes: string[];
  matched_rules?: Array<{
    rule_name: string;
    policy_set: string;
    priority: number;
  }>;
  policy_version: string;
  timing: {
    ingest_ms: number;
    evaluation_ms: number;
    total_ms: number;
  };
  would_be?: DecisionType;          // The enforced decision, when decision is 'OBSERVE'
  would_be_reason_codes?: string[];
  remediation?: { type: string; message: string; suggestion: string; /* ... */ };
  rate_limit?: {
    scope: string;
    window: string;
    limit: number;
    current: number;
    reset_at: string;
  };
  cache_status?: 'synced' | 'from_disk' | 'empty' | null;  // Hybrid mode
  // ... and further optional fields (envelope_hash, route_ref, escalation_context, ...)
}

type DecisionType =
  | 'ALLOW'
  | 'OBSERVE'
  | 'BLOCK'
  | 'PAUSE'
  | 'REQUIRE_APPROVAL'
  | 'SANDBOX'
  | 'RATE_LIMIT'
  | 'KILL_SWITCH'
  | 'ESCALATE'
  | 'ROUTE'
  | 'SIGNATURE_INVALID'
  | 'CONTROL_PLANE_UNAVAILABLE'
  | 'VALIDATION_ERROR'
  | 'POLICY_ERROR';
```

---

## Getting Help

- **Documentation**: the `docs-site/` directory of https://github.com/hiitlhq/hiitl
- **Examples**: the `examples/` directory of https://github.com/hiitlhq/hiitl
- **Issues**: https://github.com/hiitlhq/hiitl/issues

---

**You're now ready to add deterministic control to your AI agents! 🚀**
