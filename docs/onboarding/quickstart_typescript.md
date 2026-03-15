# TypeScript Quickstart - HIITL ECP

**Goal**: From install to first evaluated action in **under 5 minutes**.

**Target**: TypeScript/JavaScript developers building AI agents that take real-world actions.

---

## Prerequisites

- Node.js 18+ (you're on v19.9.0 - perfect!)
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

HIITL can run entirely locally with zero dependencies. Perfect for testing!

### For Hosted Mode

1. Sign up at https://hiitl.ai
2. Create an organization
3. Copy your API key from the dashboard
4. Set environment variable:
   ```bash
   export HIITL_API_KEY="your_api_key_here"
   ```

---

## Step 3: Write Your First Protected Action (2 minutes)

Create `example.ts`:

```typescript
import { HIITL } from '@hiitl/sdk';

// Initialize HIITL (no API key = local mode, auto-detected)
const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-first-agent',
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
    tool: 'process_payment',
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
# or compile and run:
tsc example.ts && node example.js
```

Expected output:
```
✓ Payment processed: { status: 'success', transactionId: 'txn_123' }
```

**Congratulations!** You just:
1. Installed HIITL SDK
2. Evaluated an action through the control point
3. Executed based on ECP's decision

---

## Step 5: Add a Policy (1 minute)

Create `policies/my-policy.yaml`:

```yaml
policy_set:
  name: "my-first-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_dev000000000000000"  # must match org_[a-z0-9]{18,} pattern
    environment: "dev"

  rules:
    - name: "block-high-value-payments"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "BLOCK"
      reason_code: "PAYMENT_TOO_HIGH"

    - name: "allow-all-else"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"
```

Update `example.ts` to load the policy:

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-first-agent',
  policyPath: 'policies/my-policy.yaml',  // Load policy (no apiKey = local mode)
});

async function main() {
  // Try a payment over $500
  const decision = await hiitl.evaluate({
    tool: 'process_payment',
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
✗ Payment blocked: ['PAYMENT_TOO_HIGH']
```

**The policy worked!** Payments over $500 are now blocked.

---

## What Just Happened?

1. **Envelope Creation**: The SDK created a structured envelope with all required metadata
2. **Policy Evaluation**: Your policy was evaluated against the envelope
3. **Deterministic Decision**: The rule matched (amount > 500) → BLOCK decision
4. **Audit Trail**: An immutable audit record was created (check `~/.hiitl/audit.db` in local mode)

---

## Key Concepts

### Mode Auto-Detection

The SDK automatically detects the mode based on which config fields you provide:

| Mode | Config | Best For |
|------|--------|----------|
| **Local** | No `apiKey` (just `policyPath`) | Development, testing, low-latency |
| **Hosted** | `apiKey` + `serverUrl` | Production, team collaboration, managed infrastructure |
| **Hybrid** | `apiKey` only (no `serverUrl`) | Local evaluation with remote audit/policy sync |

### The Execution Envelope

The `evaluate()` call creates an envelope with:
- **Identifiers**: org_id, environment, agent_id, action_id (auto-generated)
- **Action definition**: tool, operation, target, parameters
- **Risk signals**: sensitivity, cost_estimate (optional)
- **Context**: reason, timestamps (auto-generated)

**You only specify what's unique to this action**. Everything else is handled by the SDK.

### Decisions

| Decision | Meaning | Your Action |
|----------|---------|-------------|
| `ALLOW` | Safe to proceed | Execute the action |
| `BLOCK` | Denied by policy | Do not execute, log reason |
| `REQUIRE_APPROVAL` | Needs human review | Send to approval queue |
| `RATE_LIMIT` | Too many requests | Wait and retry |
| `KILL_SWITCH` | Emergency stop | Alert ops, do not retry |

---

## Common Patterns

### Pattern 1: Simple Action Protection

```typescript
const decision = await hiitl.evaluate({
  tool: 'send_email',
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
  tool: 'grant_access',
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
  tool: 'run_batch_job',
  operation: 'execute',
  target: { jobId: 'job_456' },
  parameters: { records: 1000000 },
  cost_estimate: { dollars: 50.00, tokens: 100000 },  // Estimated cost
});

if (decision.allowed) {
  await startExpensiveJob(...);
}
```

### Pattern 4: Handling Rate Limits

```typescript
const decision = await hiitl.evaluate(...);

if (decision.decision === 'RATE_LIMIT') {
  // SDK provides helper to wait until reset
  const resetTime = decision.rate_limit?.reset_at;
  console.log(`Rate limited. Retry after ${resetTime}`);
  // Or use: await hiitl.waitUntilReset(decision);
} else if (decision.allowed) {
  await executeAction(...);
}
```

### Pattern 5: TypeScript Type Safety

```typescript
import { HIITL, Decision } from '@hiitl/sdk';

interface PaymentParams {
  amount: number;
  currency: string;
}

interface PaymentTarget {
  accountId: string;
}

const decision = await hiitl.evaluate<PaymentTarget, PaymentParams>({
  tool: 'process_payment',
  operation: 'execute',
  target: { accountId: 'acct_123' },
  parameters: { amount: 150.00, currency: 'usd' },
});

// TypeScript knows the shape of target and parameters
console.log(decision.allowed);  // boolean
console.log(decision.decision); // DecisionType
```

---

## Debugging & Observability

### See Timing Metadata

```typescript
const decision = await hiitl.evaluate(...);
console.log(`Evaluation took ${decision.timing.total_ms}ms`);
```

**Target latency**:
- Local mode: < 10ms
- Hosted mode: < 50ms

### View Audit Log (Local Mode)

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({ environment: 'dev', agentId: 'my-first-agent' });

// Query audit log
const events = await hiitl.audit.query({
  agentId: 'my-first-agent',
  decision: 'BLOCK',
  limit: 10,
});

for (const event of events) {
  console.log(`${event.timestamp}: ${event.decision} - ${event.reason_codes}`);
}
```

### Enable Debug Logging

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-agent',
  debug: true,  // Enable debug logging
});

// Now HIITL will log detailed evaluation steps
```

---

## Integration with Popular Frameworks

### Next.js API Route

```typescript
// app/api/process-payment/route.ts
import { HIITL } from '@hiitl/sdk';
import { NextRequest, NextResponse } from 'next/server';

const hiitl = new HIITL({
  apiKey: process.env.HIITL_API_KEY!,
  serverUrl: process.env.HIITL_SERVER_URL!,  // apiKey + serverUrl = hosted mode
  environment: 'prod',
  agentId: 'payment-api',
});

export async function POST(request: NextRequest) {
  const { accountId, amount } = await request.json();

  const decision = await hiitl.evaluate({
    tool: 'process_payment',
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
  apiKey: process.env.HIITL_API_KEY!,
  serverUrl: process.env.HIITL_SERVER_URL!,  // apiKey + serverUrl = hosted mode
  environment: 'prod',
  agentId: 'express-api',
});

app.post('/api/process-payment', async (req, res) => {
  const { accountId, amount } = req.body;

  const decision = await hiitl.evaluate({
    tool: 'process_payment',
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

const hiitl = new HIITL({
  apiKey: process.env.HIITL_API_KEY!,
  serverUrl: process.env.HIITL_SERVER_URL!,  // apiKey + serverUrl = hosted mode
  environment: 'prod',
  agentId: 'ai-assistant',
});

async function handleToolCall(toolName: string, args: any) {
  // Evaluate before executing tool
  const decision = await hiitl.evaluate({
    tool: toolName,
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
- Rate limiting: `rate_limit: {scope: "agent_id", window: "hour", limit: 100}`
- Kill switches: High-priority rules you can enable/disable instantly
- Approval workflows: `decision: "REQUIRE_APPROVAL"` for high-stakes actions

See: [Policy Cookbook](policy_cookbook.md)

### 2. Integrate with Your Framework

HIITL works with any TypeScript code, but we have examples for:
- Vercel AI SDK agents
- LangChain.js
- Custom agent loops

See: [Integration Examples](integration_examples.md)

### 3. Deploy to Production

When ready:
1. Sign up for hosted ECP at https://hiitl.ai
2. Create production environment
3. Update SDK config (adding `apiKey` + `serverUrl` auto-switches to hosted mode):
   ```typescript
   const hiitl = new HIITL({
     apiKey: process.env.HIITL_API_KEY,
     serverUrl: process.env.HIITL_SERVER_URL,
     environment: 'prod',
     agentId: 'my-agent',
   });
   ```
4. Deploy policies via API or dashboard

### 4. Monitor & Observe

- View audit trail in dashboard
- Set up webhook alerts for blocks/kill switches
- Export audit logs for compliance

---

## Troubleshooting

### Import Error: `Cannot find module '@hiitl/sdk'`

**Solution**: Install the SDK: `npm install @hiitl/sdk`

### Policy Not Loading

**Solution**: Check file path. Use absolute path or relative to current directory:
```typescript
import path from 'path';

const hiitl = new HIITL({
  policyPath: path.join(__dirname, 'policies/my-policy.yaml'),
  ...
});
```

### Decision Always ALLOW (Policy Not Applying)

**Solution**: Check policy scope matches your SDK config:
- Policy `org_id` must match SDK `org_id` (must follow `org_[a-z0-9]{18,}` pattern)
- Policy `environment` must match SDK `environment`

### "Signature Invalid" Error

**Solution**: In hosted mode, ensure your API key is correct:
```typescript
const hiitl = new HIITL({
  apiKey: process.env.HIITL_API_KEY,  // Check this is set correctly
  serverUrl: process.env.HIITL_SERVER_URL,
  ...
});
```

### TypeScript Type Errors

**Solution**: Ensure you're using TypeScript 4.5+ and have strict mode enabled:
```json
{
  "compilerOptions": {
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": false
  }
}
```

---

## SDK Reference

### HIITL Configuration

```typescript
interface HIITLConfig {
  // Mode is auto-detected:
  //   No apiKey              → local mode
  //   apiKey + serverUrl     → hosted mode
  //   apiKey only            → hybrid mode
  apiKey?: string;              // Triggers hosted/hybrid mode when present
  serverUrl?: string;           // Server URL for hosted mode
  environment: 'dev' | 'stage' | 'prod';
  agentId: string;              // Stable agent identifier
  policyPath?: string;          // Path to policy YAML/JSON (local/hybrid mode)
  failMode?: 'closed' | 'open'; // Default: 'closed'
  timeout?: number;             // Request timeout in ms (default: 5000)
  sync?: boolean;               // Synchronous evaluation (default: false)
  debug?: boolean;              // Enable debug logging
}

const hiitl = new HIITL(config);
```

### evaluate() Parameters

```typescript
interface EvaluateParams<T = any, P = any> {
  tool: string;                 // Required: Tool/action name
  operation: 'read' | 'write' | 'create' | 'delete' | 'execute' | 'update';
  target: T;                    // Required: Resource identifiers
  parameters: P;                // Required: Action parameters
  sensitivity?: Array<'money' | 'identity' | 'permissions' | 'regulated' | 'irreversible'>;
  cost_estimate?: {
    tokens?: number;
    dollars?: number;
    api_calls?: number;
  };
  user_id?: string;             // Optional: End-user ID
  session_id?: string;          // Optional: Session ID
  reason?: string;              // Optional: Brief reason string
}

const decision = await hiitl.evaluate(params);
```

### Decision Object

```typescript
interface Decision {
  action_id: string;
  decision: DecisionType;
  allowed: boolean;
  reason_codes: string[];
  matched_rules: Array<{
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
  rate_limit?: {
    scope: string;
    window: string;
    limit: number;
    current: number;
    reset_at: string;
  };
  approval_metadata?: {
    approval_id: string;
    sla_hours: number;
    reviewer_role: string;
    resume_url: string;
  };
}

type DecisionType =
  | 'ALLOW'
  | 'BLOCK'
  | 'PAUSE'
  | 'REQUIRE_APPROVAL'
  | 'SANDBOX'
  | 'RATE_LIMIT'
  | 'KILL_SWITCH'
  | 'ESCALATE'
  | 'ROUTE'
  | 'SIGNATURE_INVALID'
  | 'CONTROL_PLANE_UNAVAILABLE';
```

---

## Getting Help

- **Documentation**: https://docs.hiitl.ai
- **Examples**: https://github.com/hiitlhq/hiitl/tree/main/examples
- **Issues**: https://github.com/hiitlhq/hiitl/issues
- **Discord**: https://discord.gg/hiitl

---

**You're now ready to add deterministic control to your AI agents! 🚀**
