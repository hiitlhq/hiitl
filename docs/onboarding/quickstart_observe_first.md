# See What Your Agents Are Doing in 5 Minutes

Your AI agents are taking actions — sending emails, processing payments, querying databases, calling APIs. Right now, you can't see what they're doing until something goes wrong.

hiitl gives you instant visibility. Add one line of code per action, and see every tool call your agents make — what they tried, what happened, and when.

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

hiitl = HIITL(agent_id="my-agent")
```

**TypeScript:**
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({ agent_id: 'my-agent' });
```

No API key, no policy file. The SDK runs locally and observes every action. To see the calls in the hosted dashboard, add an API key from https://hiitl.com: `api_key=os.environ["HIITL_API_KEY"]` in Python, `api_key: process.env.HIITL_API_KEY` in TypeScript. Evaluation stays in-process, and the records sync to the hosted service in the background (hybrid mode).

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
    result = hiitl.evaluate(action_name, parameters=params)
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
  const result = await hiitl.evaluate({ action: actionName, parameters: params });
  if (result.allowed) {
    return await executeTool(actionName, params);
  } else {
    return `Action not allowed: ${result.reason_codes}`;
  }
}
```

That's it. You've added observability to your agent.

---

## Step 4: Run Your Application

Start your application as usual. hiitl runs inline — no extra processes, no significant latency (under 10ms locally, under 50ms hosted).

```bash
python my_app.py
```

Every tool call your agent makes is now recorded.

---

## Step 5: See What's Happening

Locally, the records are in a SQLite file, `./hiitl_audit.db` (the `audit_db_path` setting). In TypeScript, `hiitl.queryAudit({ limit: 20 })` returns them.

With an API key, open the hiitl dashboard. The **Audit** page lists every recorded call, with its parameters and decision. With the Python SDK in hybrid mode, the **Behavior** page also summarises them:

- **Frequency** — which tools are called most often
- **Timing** — how long evaluations took
- **Decisions** — how each tool's calls were decided
- **Activity over time** — actions per agent across the time range you pick, so spikes stand out

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
import os

from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    environment="prod",
    agent_id="customer-service-agent",
)

async def handle_customer_request(request):
    # Look up the customer
    result = hiitl.evaluate("query_customer", parameters={
        "customer_id": request.customer_id,
        "fields": ["name", "email", "account_status"],
    })
    if not result.ok:
        return "Unable to look up customer"
    customer = await db.get_customer(request.customer_id)

    # Send a response email
    result = hiitl.evaluate("send_email", parameters={
        "to": customer.email,
        "subject": f"Re: {request.subject}",
        "template": "support_response",
    })
    if not result.ok:
        return "Unable to send email"
    await email.send(customer.email, subject=f"Re: {request.subject}", body=response_text)

    # Issue a refund if requested
    if request.wants_refund:
        result = hiitl.evaluate("issue_refund", parameters={
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
- `query_customer` called 340 times, all OBSERVE
- `send_email` called 280 times, all OBSERVE
- `issue_refund` called 45 times, amounts range $5-$890

Now you have the data to make informed decisions about what guardrails to add — and you didn't have to write a single rule to get here.

---

## What Happens Without Policies?

Without any policies configured, `evaluate()` returns `OBSERVE` for every action, with `allowed` true. Nothing is blocked. Your application runs exactly as before.

Each decision also says what enforcement would do: `would_be` is `BLOCK`, with `NO_MATCHING_RULE`, because no rule allows the action yet.

And every call is recorded. You get:
- A complete audit trail of every action
- Timing data showing ECP adds negligible latency
- The parameters of every call, which reveal your agents' behavior patterns

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

When you're ready, add a policy file, or deploy one through the API (`POST /v1/policies`); the dashboard shows policies but does not edit them. Once you enforce, an action no rule matches is blocked, so the policy allows the agent's actions as well as holding the large refunds:

```yaml
policy_set:
  name: "support-controls"
  version: "v1.0.0"
  description: "Support agent controls, enforced after observation"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"
  rules:
    - name: "approve-large-refunds"
      description: "Refunds over $500 wait for a person"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "issue_refund"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "REQUIRE_APPROVAL"
      reason_code: "LARGE_REFUND"
    - name: "allow-support-actions"
      description: "The support agent's actions proceed"
      priority: 10
      conditions:
        field: "action"
        operator: "in"
        value: ["query_customer", "send_email", "issue_refund"]
      decision: "ALLOW"
      reason_code: "SUPPORT_ACTION"
```

**Python:**
```python
# Still observing: everything proceeds, and each decision says what the policy would do
hiitl = HIITL(policy_path="./policy.yaml")

# Enforcing
hiitl = HIITL(policy_path="./policy.yaml", mode="RESPECT_POLICY")
```

**TypeScript:**
```typescript
// Still observing: everything proceeds, and each decision says what the policy would do
let hiitl = new HIITL({ policy_path: './policy.yaml' });

// Enforcing
hiitl = new HIITL({ policy_path: './policy.yaml', mode: 'RESPECT_POLICY' });
```

The `evaluate()` calls don't change. With the policy loaded and still observing, a $890 refund comes back `OBSERVE` with `would_be` `REQUIRE_APPROVAL`. Once you enforce, it comes back `REQUIRE_APPROVAL` with `allowed` false, and the other actions come back `ALLOW`.

The [Policy Cookbook](policy_cookbook.md) and [Pattern Repository](../../patterns/README.md) have starter policies for common scenarios.

But that's step two. Step one is visibility — and you've already done that.

---

## Adding More Context

As you get comfortable, you can add more context to your `evaluate()` calls to enable richer policies later:

```python
# Basic: just action name and params
result = hiitl.evaluate("process_payment", parameters={"amount": 150.00})

# With user context: enables per-user rate limits
result = hiitl.evaluate("process_payment", parameters={"amount": 150.00}, user_id="user_123")

# With target: enables resource-level policies
result = hiitl.evaluate("process_payment", parameters={"amount": 150.00},
    user_id="user_123",
    target={"account_id": "acct_456"},
)
```

None of this is required upfront. Start simple, add context when you need it.

---

## Local Mode vs Hybrid

Observe mode is the default in local and hybrid mode alike:

| Mode | Setup | Audit storage | Best for |
|------|-------|---------------|----------|
| **Local** | No API key | SQLite on disk (`./hiitl_audit.db`) | Development, quick evaluation |
| **Hybrid** | An API key | SQLite on disk, synced to the hosted service | Team visibility, production |

Local mode makes no network calls and needs no account. Its audit records stay in SQLite on the machine that wrote them. When you're ready for the hosted dashboard, add an API key — the `evaluate()` calls stay the same.

---

## FAQ

### Does this slow down my application?

No. Local evaluation takes under 1ms. Hosted evaluation takes under 50ms. Timing data is included in every response so you can verify.

### What data does hiitl see?

In local mode, nothing leaves your machine. With an API key, hiitl receives what you pass to `evaluate()` (the action name, parameters and target), the identifiers and timestamps the SDK adds, and the decision. In hybrid mode the Python SDK also sends usage telemetry that summarises those calls (on by default; `HIITL(telemetry_level="off")` or `HIITL_TELEMETRY_LEVEL=off` turns it off). hiitl never sees raw prompts, model outputs, or anything you don't explicitly pass. See the [telemetry schema](../../docs/specs/telemetry_schema.md) for details.

### Can I remove hiitl later?

Yes. Remove the `evaluate()` calls and the import. Your application works exactly as before. hiitl is additive -- it doesn't change how your code runs.

### What if hiitl is unavailable?

In local and hybrid mode, evaluation runs in your process, so an unreachable hosted service does not stop it. A hybrid SDK keeps evaluating against its cached policies and keeps audit records on disk until it can sync them. In hosted mode, when the server cannot be reached, `evaluate()` returns a `CONTROL_PLANE_UNAVAILABLE` decision with `allowed` false (fail-closed): the action was not evaluated, so don't run it.

---

## Next Steps

You're observing. Here's what comes next when you're ready:

- **[Pattern Repository](../../patterns/README.md)** — Browse 25 starter policies for common tools
- **[Policy Cookbook](policy_cookbook.md)** — Write your first policy rule
- **[MCP Quickstart](quickstart_mcp.md)** — Specific guide for MCP server integration
- **[Python Quickstart](quickstart_python.md)** — Deep dive into the Python SDK
- **[TypeScript Quickstart](quickstart_typescript.md)** — Deep dive into the TypeScript SDK

---

With an API key, the hosted service can also propose policies from your recorded actions. Run an analysis (`POST /v1/suggestions/analyze`, admin scope), then review the proposals on the dashboard's **Suggestions** page. An accepted rule does not enforce at once: it starts staged, recording what it would decide (a suggested kill switch starts disabled).
