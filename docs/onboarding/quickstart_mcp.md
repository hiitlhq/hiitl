# Add ECP to Your MCP Server in 5 Minutes

You have an MCP server with tool handlers. You want governance — visibility into what tools your AI agents are calling, and the ability to block, rate-limit, or require approval before execution.

HIITL's `evaluate()` call wraps your existing tool handlers with one line of code. No new framework, no architectural changes.

---

## Before & After

Here's the minimal change. Everything else in your MCP server stays the same.

### Before (unprotected)

```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    if name == "send_email":
        return await send_email(arguments["to"], arguments["subject"], arguments["body"])
```

### After (protected by ECP)

```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    result = hiitl.evaluate(name, arguments)         # <-- one line added
    if not result.ok:                                # <-- check result
        return f"Blocked: {result.reason_codes}"

    if name == "send_email":
        return await send_email(arguments["to"], arguments["subject"], arguments["body"])
```

That's it. Every tool call now passes through the control point before executing.

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

Add HIITL initialization alongside your MCP server setup.

**Python:**
```python
from hiitl import HIITL
from mcp.server import Server

server = Server("my-mcp-server")

hiitl = HIITL(
    environment="dev",
    agent_id="my-mcp-server",
    org_id="org_devlocal000000000",
    policy_path="./policy.yaml",
)
```

**TypeScript:**
```typescript
import { HIITL } from '@hiitl/sdk';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';

const server = new Server({ name: 'my-mcp-server', version: '1.0.0' }, { capabilities: { tools: {} } });

const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-mcp-server',
  orgId: 'org_devlocal000000000',
  policyPath: './policy.yaml',
});
```

No API key needed for local mode. The SDK runs evaluation entirely in-process.

---

## Step 3: Wrap Tool Handlers (2 minutes)

Add `evaluate()` at the top of your tool handler. The first argument is the action name, the second is the parameters -- which map directly to what MCP already gives you.

**Python:**
```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    # Evaluate with ECP before executing
    result = hiitl.evaluate(name, arguments)

    if not result.ok:
        # Return the block reason to the AI agent
        return f"Action blocked by policy: {result.reason_codes}"

    # Proceed with normal tool execution
    if name == "send_email":
        return await send_email(arguments["to"], arguments["subject"], arguments["body"])
    elif name == "query_database":
        return await run_query(arguments["sql"])
    elif name == "process_payment":
        return await charge_card(arguments["amount"], arguments["currency"])
```

**TypeScript:**
```typescript
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  // Evaluate with ECP before executing
  const result = hiitl.evaluate({ action: name, params: args ?? {} });

  if (!result.ok) {
    return { content: [{ type: 'text', text: `Action blocked by policy: ${result.reason_codes}` }] };
  }

  // Proceed with normal tool execution
  if (name === 'send_email') {
    return await sendEmail(args.to, args.subject, args.body);
  } else if (name === 'query_database') {
    return await runQuery(args.sql);
  } else if (name === 'process_payment') {
    return await chargeCard(args.amount, args.currency);
  }
});
```

### What `evaluate()` gives you

| Property | Type | Meaning |
|----------|------|---------|
| `result.ok` | bool | Safe to proceed (ALLOW or SANDBOX) |
| `result.blocked` | bool | Denied by policy |
| `result.needs_approval` | bool | Requires human review |
| `result.reason_codes` | list | Why the decision was made |
| `result.remediation` | object | Guidance on what to do |

---

## Step 4: Add a Policy (1 minute)

Create `policy.yaml`:

```yaml
policy_set:
  name: "mcp-server-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_devlocal000000000"
    environment: "dev"

  rules:
    - name: "block-large-payments"
      enabled: true
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

    - name: "rate-limit-emails"
      enabled: true
      priority: 90
      conditions:
        field: "action"
        operator: "equals"
        value: "send_email"
      decision: "RATE_LIMIT"
      reason_code: "EMAIL_RATE_LIMITED"

    - name: "allow-all"
      enabled: true
      priority: 1
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"
```

Now your MCP server:
- Blocks payments over $500
- Rate-limits email sending
- Allows everything else

---

## Step 5: Run It

Start your MCP server as usual. The `evaluate()` calls happen inline -- no extra processes, no network calls in local mode.

```bash
python my_server.py
```

When an AI agent calls a tool through your server, you'll see decisions in the local audit log (`~/.hiitl/audit.db`).

---

## Handling Different Decisions

For more sophisticated handling, use the boolean accessors:

**Python:**
```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    result = hiitl.evaluate(name, arguments)

    if result.ok:
        return await execute_tool(name, arguments)

    if result.needs_approval:
        # Queue for human review
        return f"This action requires approval. Action ID: {result.action_id}"

    if result.blocked:
        # Return helpful guidance
        msg = f"Blocked: {result.reason_codes}"
        if result.remediation:
            msg += f"\nSuggestion: {result.remediation.suggestion}"
        return msg

    # Rate limited or other
    return f"Action not allowed: {result.reason_codes}"
```

**TypeScript:**
```typescript
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const result = hiitl.evaluate({ action: name, params: args ?? {} });

  if (result.ok) {
    return await executeTool(name, args);
  }

  if (result.needs_approval) {
    return { content: [{ type: 'text', text: `Requires approval. Action ID: ${result.action_id}` }] };
  }

  if (result.blocked) {
    const msg = `Blocked: ${result.reason_codes}`;
    const suggestion = result.remediation?.suggestion ? `\nSuggestion: ${result.remediation.suggestion}` : '';
    return { content: [{ type: 'text', text: msg + suggestion }] };
  }

  return { content: [{ type: 'text', text: `Not allowed: ${result.reason_codes}` }] };
});
```

---

## Full Working Example

Here's a complete MCP server with ECP governance.

**Python:**
```python
from hiitl import HIITL
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("governed-mcp-server")

hiitl = HIITL(
    environment="dev",
    agent_id="governed-mcp-server",
    org_id="org_devlocal000000000",
    policy_path="./policy.yaml",
)

@server.list_tools()
async def list_tools():
    return [
        Tool(name="process_payment", description="Process a payment", inputSchema={
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "account_id": {"type": "string"},
            },
            "required": ["amount", "currency", "account_id"],
        }),
        Tool(name="send_email", description="Send an email", inputSchema={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        }),
    ]

@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    # Every tool call goes through the control point
    result = hiitl.evaluate(name, arguments)

    if not result.ok:
        return [TextContent(type="text", text=f"Blocked by ECP: {result.reason_codes}")]

    if name == "process_payment":
        # ... actual payment logic ...
        return [TextContent(type="text", text=f"Payment of ${arguments['amount']} processed")]

    if name == "send_email":
        # ... actual email logic ...
        return [TextContent(type="text", text=f"Email sent to {arguments['to']}")]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## Moving to Production

When you're ready to go live, switch from local to hosted mode by adding an API key:

```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    environment="prod",
    agent_id="governed-mcp-server",
)
```

The `evaluate()` calls stay exactly the same. Only the initialization changes.

---

## Coming Soon: `hiitl-mcp` Middleware

We're building a dedicated middleware package that makes this even simpler:

```python
# Future: hiitl-mcp package (Phase 2)
from hiitl_mcp import govern

server = govern(server, hiitl)  # Automatically wraps all tool handlers
```

Until then, the `evaluate()` wrapper pattern shown above gives you full control over how each tool is governed.

---

## Starter Policies for Common MCP Tools

Copy policies from the [Pattern Repository](../../patterns/README.md) for common tools:

| Your MCP Tool | Pattern | Policy Focus |
|---------------|---------|--------------|
| Payment processing | [process_payment](../../patterns/financial/process_payment.yaml) | Amount thresholds, rate limits |
| Email sending | [send_email](../../patterns/communication/send_email.yaml) | Rate limits, recipient validation |
| Database queries | [query_database](../../patterns/data_access/query_database.yaml) | PII access, query scope |
| File operations | [export_data](../../patterns/data_access/export_data.yaml) | Size limits, format controls |
| API calls | [call_external_api](../../patterns/external/call_external_api.yaml) | Rate limits, cost controls |

---

## Troubleshooting

### "evaluate() always returns ok"

You're running without a policy. Create a `policy.yaml` and pass the path to HIITL:
```python
hiitl = HIITL(policy_path="./policy.yaml", ...)
```

### Action name mismatch

The `name` in `evaluate(name, arguments)` must match the `action` in your policy conditions. If your MCP tool is called `process_payment`, the policy condition must use `value: "process_payment"`.

### Arguments structure

`evaluate()` passes `arguments` directly as parameters. Policy conditions reference them as `parameters.field_name`. If your tool receives `{"amount": 100}`, the policy condition is `field: "parameters.amount"`.

---

## Next Steps

- [Pattern Repository](../../patterns/README.md) — Copy starter policies for your tools
- [Policy Cookbook](policy_cookbook.md) — Advanced policy patterns
- [Python Quickstart](quickstart_python.md) — Deep dive into the Python SDK
- [TypeScript Quickstart](quickstart_typescript.md) — Deep dive into the TypeScript SDK
