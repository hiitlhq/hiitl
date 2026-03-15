# See What Your Agents Are Doing in 5 Minutes

Your AI agents are taking actions — sending emails, processing payments, querying databases, calling APIs. Right now, you can't see what they're doing until something goes wrong.

HIITL gives you instant visibility. Add one line of code per action, and see every tool call your agents make — what they tried, what happened, and when.

No configuration. No rules to write. Just visibility.

---

## Step 1: Install (30 seconds)

**Python:**
```bash
pip install hiitl
```

**TypeScript:**
```bash
npm install @hiitl/sdk
```

---

## Step 2: Initialize (30 seconds)

**Python:**
```python
from hiitl import HIITL

hiitl = HIITL(
    api_key="your_api_key",     # Get this from https://hiitl.ai
    environment="dev",
    agent_id="my-agent",
)
```

**TypeScript:**
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  apiKey: 'your_api_key',     // Get this from https://hiitl.ai
  environment: 'dev',
  agentId: 'my-agent',
});
```

---

## Step 3: Wrap Your Tool Calls (2 minutes)

Before each tool call, add an `evaluate()`. The simplest version takes an action name and the parameters.

**Python:**
```python
# Before: invisible tool call
def handle_agent_action(action_name, params):
    return execute_tool(action_name, params)

# After: every action is visible
def handle_agent_action(action_name, params):
    result = hiitl.evaluate(action_name, params)
    if result.ok:
        return execute_tool(action_name, params)
    else:
        return f"Action not allowed: {result.reason_codes}"
```

**TypeScript:**
```typescript
// Before: invisible tool call
async function handleAgentAction(actionName: string, params: Record<string, unknown>) {
  return await executeTool(actionName, params);
}

// After: every action is visible
async function handleAgentAction(actionName: string, params: Record<string, unknown>) {
  const result = hiitl.evaluate({ action: actionName, params });
  if (result.ok) {
    return await executeTool(actionName, params);
  } else {
    return `Action not allowed: ${result.reason_codes}`;
  }
}
```

That's it. You've added observability to your agent.

---

## Step 4: Run Your Application

Start your application as usual. HIITL runs inline — no extra processes, no significant latency (under 10ms locally, under 50ms hosted).

```bash
python my_app.py
```

Every tool call your agent makes is now recorded.

---

## Step 5: See What's Happening

Open the HIITL dashboard. You'll see:

- **Every tool call** your agents are making
- **Parameters** for each call (amount, recipient, query, etc.)
- **Timing** — how long each evaluation took
- **Frequency** — which tools are called most often
- **Patterns** — unusual spikes, new tools appearing, parameter distributions

### What You'll Learn

Within the first hour, you'll know:
- Which tools your agents use most
- What parameter ranges are normal (payment amounts, email counts, query sizes)
- How frequently each tool is called
- Which agents are most active

Within the first day, you'll see patterns:
- Normal operating ranges for amounts, volumes, and frequencies
- Peak activity windows
- The full catalog of tools your agents are using

---

## Real-World Example

Here's a customer service agent with three tool calls, each wrapped with `evaluate()`:

**Python:**
```python
from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    environment="prod",
    agent_id="customer-service-agent",
)

async def handle_customer_request(request):
    # Look up the customer
    result = hiitl.evaluate("query_customer", {
        "customer_id": request.customer_id,
        "fields": ["name", "email", "account_status"],
    })
    if not result.ok:
        return "Unable to look up customer"
    customer = await db.get_customer(request.customer_id)

    # Send a response email
    result = hiitl.evaluate("send_email", {
        "to": customer.email,
        "subject": f"Re: {request.subject}",
        "template": "support_response",
    })
    if not result.ok:
        return "Unable to send email"
    await email.send(customer.email, subject=f"Re: {request.subject}", body=response_text)

    # Issue a refund if requested
    if request.wants_refund:
        result = hiitl.evaluate("issue_refund", {
            "amount": request.refund_amount,
            "order_id": request.order_id,
            "reason": "customer_request",
        })
        if not result.ok:
            return f"Refund requires review: {result.reason_codes}"
        await payments.refund(request.order_id, request.refund_amount)

    return "Request handled successfully"
```

After running this for a day, your dashboard shows:
- `query_customer` called 340 times, all ALLOW
- `send_email` called 280 times, all ALLOW
- `issue_refund` called 45 times, amounts range $5-$890

Now you have the data to make informed decisions about what guardrails to add — and you didn't have to write a single rule to get here.

---

## What Happens Without Policies?

Without any policies configured, `evaluate()` returns ALLOW for every action. Nothing is blocked. Your application runs exactly as before.

But every call is recorded. You get:
- A complete audit trail of every action
- Timing data showing ECP adds negligible latency
- Parameter distributions that reveal your agents' behavior patterns

This is the observe-first approach: **see first, then govern.**

---

## When You're Ready for Guardrails

After observing your agents' behavior, you'll naturally spot patterns that should have guardrails. Common first rules:

**"Refunds over $500 should need approval"**
— You noticed your agent issues refunds up to $890 automatically. That feels too high.

**"Don't send more than 50 emails per hour"**
— Your agent sent 200 emails in one hour during a busy period. That's close to spam.

**"Block database queries in production that access the users table"**
— Your agent is querying the users table directly. That should go through the API.

When you're ready, add a policy file or use the dashboard to create rules. The [Policy Cookbook](policy_cookbook.md) and [Pattern Repository](../../patterns/README.md) have starter policies for common scenarios.

But that's step two. Step one is visibility — and you've already done that.

---

## Adding More Context

As you get comfortable, you can add more context to your `evaluate()` calls to enable richer policies later:

```python
# Basic: just action name and params
result = hiitl.evaluate("process_payment", {"amount": 150.00})

# With user context: enables per-user rate limits
result = hiitl.evaluate("process_payment", {"amount": 150.00}, user_id="user_123")

# With target: enables resource-level policies
result = hiitl.evaluate("process_payment", {"amount": 150.00},
    user_id="user_123",
    target={"account_id": "acct_456"},
)
```

None of this is required upfront. Start simple, add context when you need it.

---

## Local Mode (No API Key)

Want to try this without signing up? Run entirely locally:

**Python:**
```python
hiitl = HIITL(
    environment="dev",
    agent_id="my-agent",
    org_id="org_devlocal000000000",
)
```

**TypeScript:**
```typescript
const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-agent',
  orgId: 'org_devlocal000000000',
});
```

Audit records are stored locally in SQLite (`~/.hiitl/audit.db`). No network calls, no account needed. When you're ready for the hosted dashboard, add an API key -- the `evaluate()` calls stay the same.

---

## FAQ

### Does this slow down my application?

No. Local evaluation takes under 1ms. Hosted evaluation takes under 50ms. Timing data is included in every response so you can verify.

### What data does HIITL see?

The action name and parameters you pass to `evaluate()`. HIITL never sees raw prompts, model outputs, or anything you don't explicitly pass. See our [privacy documentation](../../docs/specs/telemetry_schema.md) for details.

### Can I remove HIITL later?

Yes. Remove the `evaluate()` calls and the import. Your application works exactly as before. HIITL is additive -- it doesn't change how your code runs.

### What if HIITL is unavailable?

By default, HIITL fails closed (blocks actions) when the hosted service is unreachable. You can configure fail-open for non-critical paths. The SDK handles this automatically.

---

## Next Steps

You're observing. Here's what comes next when you're ready:

- **[Pattern Repository](../../patterns/README.md)** — Browse 25 starter policies for common tools
- **[Policy Cookbook](policy_cookbook.md)** — Write your first policy rule
- **[MCP Quickstart](quickstart_mcp.md)** — Specific guide for MCP server integration
- **[Python Quickstart](quickstart_python.md)** — Deep dive into the Python SDK
- **[TypeScript Quickstart](quickstart_typescript.md)** — Deep dive into the TypeScript SDK

---

Within a few days, ECP will suggest policies based on your agent's actual behavior. You'll go from observing to governing without writing a single rule.
