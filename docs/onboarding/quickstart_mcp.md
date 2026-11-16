# Govern Every MCP Tool Call in 5 Minutes

You're using Claude Desktop (or another MCP client) with one or more MCP servers — email, GitHub, filesystem, database, whatever. You want visibility into every tool the agent calls, and the ability to block, rate-limit, or require approval before execution.

The fastest path: **point Claude Desktop at `hiitl-mcp-proxy` instead of your MCP servers directly.** The proxy spawns your existing servers, discovers their tools, exposes them under their original names, and runs every tool call through `hiitl.evaluate()` before forwarding. No code changes to your MCP servers.

**Important — the proxy is the wrapper, not the server.** It works with MCP servers written in **any language** (Python, TypeScript, Go, Rust) because it spawns them as child processes and speaks MCP to them over stdio (or connects via SSE). If you're running a TypeScript MCP server like `@modelcontextprotocol/server-github`, you do *not* need a TypeScript version of hiitl-mcp-proxy — the Python proxy spawns it as `npx ... server-github` and governs every call.

A second path exists for developers writing their own MCP server who want the governance call inline — see [Path B: Inline `evaluate()` Inside Your Server](#path-b-inline-evaluate-inside-your-server) below.

---

## Path A: Drop-In Proxy (recommended)

This is the primary path for anyone running off-the-shelf MCP servers (`@modelcontextprotocol/server-filesystem`, `@modelcontextprotocol/server-github`, etc.) with Claude Desktop.

### Before

`claude_desktop_config.json` points at MCP servers directly:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

### After

One `mcpServers` entry — the hiitl proxy. The original servers move into `hiitl-mcp.yaml` and get spawned by the proxy.

`~/hiitl-mcp.yaml`:
```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
```

`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/me/hiitl-mcp.yaml"]
    }
  }
}
```

### Install + run

```bash
pip install 'hiitl[mcp]'
# Edit ~/hiitl-mcp.yaml as above
# Edit claude_desktop_config.json as above
# Restart Claude Desktop
```

That's it. Open Claude Desktop. The MCP icon shows your tools with the names each upstream server gives them. Every tool call now flows through hiitl. Resource and prompt reads are forwarded as they are, without an `evaluate()`.

### What happens per call

```
Claude Desktop ──tools/call──▶ hiitl-mcp-proxy ──evaluate()──▶ audit trail
                                       │
                                       │ ALLOW
                                       ▼
                              upstream MCP server (e.g. github-mcp-server)
```

- **`ALLOW`** / `SANDBOX` / `OBSERVE` → proxy forwards to upstream, returns result unchanged.
- **`BLOCK`** / `RATE_LIMIT` / `KILL_SWITCH` → proxy returns an error result naming the decision and its reason codes, plus the rule's remediation message when it has one. Upstream never called.
- **`ROUTE`** → the SDK has already asked the sync route the rule names; a `ROUTE` that reaches the proxy went unanswered, so the call is refused. Upstream never called.
- **`REQUIRE_APPROVAL`** / **`PAUSE`** / **`ESCALATE`** → if `hiitl-mcp.yaml` sets both `server_url` and `api_key`, the proxy opens a review case on the hiitl backend and waits (via Server-Sent Events) for a human reviewer to **approve**, **reject**, or **modify** the request. On approve → proxy forwards. On modify → proxy forwards with the reviewer's arguments instead of the original. On reject or timeout (`review_timeout_seconds`, default 300) → MCP error with the reason. If the backend cannot be reached, the call is refused. If either `server_url` or `api_key` is missing, no reviewer is asked and the call is refused with a "review flow requires a hiitl backend" message.

### Observe-first onboarding

With no `api_key` in `hiitl-mcp.yaml`, the proxy runs in `OBSERVE_ALL` mode — every call is forwarded and recorded, nothing is blocked. The proxy reads no local policy file. The audit trail is `hiitl_audit.db` in the directory the MCP client starts the proxy in. Use Claude normally for a few sessions and read what the agent calls.

With an `api_key`, the proxy enforces the policies synced from your hiitl org (`RESPECT_POLICY`), and the audit trail syncs up. A call no rule matches is refused with `NO_MATCHING_RULE`, and so is every call before the first policy sync. Put ALLOW rules for the tools you mean to let through in your org's policy before you add the key.

### Tool name collisions

Two upstream servers expose the same tool name → proxy refuses to start with a clear error naming both servers and the tool. Rename one upstream's tool (or drop a duplicate dependency) and restart.

### Full recipe

The complete working example with a Claude Desktop config and a multi-upstream YAML lives in [examples/mcp-proxy/](../../examples/mcp-proxy/).

---

## Path B: Inline `evaluate()` Inside Your Server

For developers writing their own MCP server who want the governance call inline (no proxy process). Wraps existing tool handlers with one line of code.

### Before & After

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
    result = hiitl.evaluate(name, parameters=arguments)   # <-- one line added
    if not result.ok:                                     # <-- check result
        return [TextContent(type="text", text=f"Blocked: {result.reason_codes}")]

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

Add hiitl initialization alongside your MCP server setup.

**Python:**
```python
from hiitl import HIITL
from mcp.server import Server
from mcp.types import TextContent

server = Server("my-mcp-server")

hiitl = HIITL(
    environment="dev",
    agent_id="my-mcp-server",
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
)
```

**TypeScript:**
```typescript
import { HIITL } from '@hiitl/sdk';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';

const server = new Server({ name: 'my-mcp-server', version: '1.0.0' }, { capabilities: { tools: {} } });

const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'my-mcp-server',
  policy_path: './policy.yaml',
  mode: 'RESPECT_POLICY',
});
```

No API key needed for local mode. The SDK runs evaluation entirely in-process. `mode="RESPECT_POLICY"` enforces the policy; without it the SDK runs in `OBSERVE_ALL`, which records every call and returns a BLOCK or approval as `OBSERVE`, with the rule's decision in `would_be`. A windowed `RATE_LIMIT` rule still refuses the call past its limit in either mode. TypeScript options are snake_case.

---

## Step 3: Wrap Tool Handlers (2 minutes)

Add `evaluate()` at the top of your tool handler. The first argument is the action name, and `parameters=` takes the arguments -- which map directly to what MCP already gives you.

**Python:**
```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    # Evaluate with ECP before executing
    result = hiitl.evaluate(name, parameters=arguments)

    if not result.ok:
        # Return the block reason to the AI agent
        return [TextContent(type="text", text=f"Action blocked by policy: {result.reason_codes}")]

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
  const result = await hiitl.evaluate({ action: name, parameters: args ?? {} });

  if (!result.allowed) {
    return { content: [{ type: 'text', text: `Action blocked by policy: ${result.reason_codes.join(', ')}` }] };
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

The Python Decision:

| Property | Type | Meaning |
|----------|------|---------|
| `result.ok` | bool | Safe to proceed (ALLOW, SANDBOX or OBSERVE) |
| `result.blocked` | bool | Denied by policy (BLOCK, KILL_SWITCH or RATE_LIMIT) |
| `result.needs_approval` | bool | Requires human review (REQUIRE_APPROVAL, PAUSE or ESCALATE) |
| `result.reason_codes` | list | Why the decision was made |
| `result.remediation` | object | Guidance on what to do |

The TypeScript Decision has no `ok`, `blocked` or `needs_approval`: read `result.allowed` and `result.decision`.

---

## Step 4: Add a Policy (1 minute)

Create `policy.yaml`:

```yaml
policy_set:
  name: "mcp-server-policy"
  version: "v1.0.0"
  description: "Controls on the MCP server's tools"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"

  rules:
    - name: "block-large-payments"
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

    - name: "rate-limit-emails"
      description: "At most 20 emails an hour from this server"
      priority: 90
      conditions:
        field: "action"
        operator: "equals"
        value: "send_email"
      decision: "RATE_LIMIT"
      reason_code: "EMAIL_RATE_LIMITED"
      rate_limit:
        limit: 20
        window_seconds: 3600
        scope: "agent"

    - name: "allow-all"
      description: "Every other tool call proceeds"
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
- Allows 20 emails an hour; the 21st is `RATE_LIMIT` with reason code `RATE_LIMIT_EXCEEDED`
- Allows everything else

---

## Step 5: Run It

Start your MCP server as usual. The `evaluate()` calls happen inline -- no extra processes, no network calls in local mode.

```bash
python my_server.py
```

When an AI agent calls a tool through your server, you'll see decisions in the local audit log (`hiitl_audit.db`, in the directory the server runs in).

---

## Handling Different Decisions

For more sophisticated handling, use the boolean accessors:

**Python:**
```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    result = hiitl.evaluate(name, parameters=arguments)

    if result.ok:
        return await execute_tool(name, arguments)

    if result.needs_approval:
        # Nothing is queued: the decision comes back to you. Tell the agent, or open a review case.
        return [TextContent(type="text", text=f"This action requires approval. Action ID: {result.action_id}")]

    if result.blocked:
        # Return helpful guidance (covers BLOCK, KILL_SWITCH and RATE_LIMIT)
        msg = f"Blocked: {result.reason_codes}"
        if result.remediation:
            msg += f"\nSuggestion: {result.remediation.suggestion}"
        return [TextContent(type="text", text=msg)]

    # ROUTE or other
    return [TextContent(type="text", text=f"Action not allowed: {result.reason_codes}")]
```

**TypeScript:**
```typescript
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const result = await hiitl.evaluate({ action: name, parameters: args ?? {} });

  if (result.allowed) {
    return await executeTool(name, args);
  }

  if (['REQUIRE_APPROVAL', 'PAUSE', 'ESCALATE'].includes(result.decision)) {
    return { content: [{ type: 'text', text: `Requires approval. Action ID: ${result.action_id}` }] };
  }

  if (['BLOCK', 'KILL_SWITCH', 'RATE_LIMIT'].includes(result.decision)) {
    const msg = `Blocked: ${result.reason_codes.join(', ')}`;
    const suggestion = result.remediation?.suggestion ? `\nSuggestion: ${result.remediation.suggestion}` : '';
    return { content: [{ type: 'text', text: msg + suggestion }] };
  }

  return { content: [{ type: 'text', text: `Not allowed: ${result.reason_codes.join(', ')}` }] };
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
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
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
    result = hiitl.evaluate(name, parameters=arguments)

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

When you're ready to go live, add an API key. In Python that puts the SDK in hybrid mode: evaluation stays in-process, policies sync down from your hiitl org, and the audit trail syncs up. The `policy_path` file is used while nothing has synced yet.

```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    environment="prod",
    agent_id="governed-mcp-server",
)
```

`server_url` is where the SDK syncs; leave it unset to use the default. Hosted evaluation (a network call per decision) is a separate opt-in, `evaluation="remote"`. The `evaluate()` calls stay exactly the same. Only the initialization changes.

---

## Path A vs Path B — Which to Pick

- Running off-the-shelf MCP servers (filesystem, GitHub, etc.) → **Path A (proxy).** Three-line install, zero code changes.
- Writing your own MCP server and you want governance inline → **Path B (inline `evaluate()`).** Full control over how each tool is governed; useful for server authors who already maintain the handler code.

Both paths use the same `hiitl.evaluate()` API and the same policy format. You can run them side by side: a proxy in front of off-the-shelf servers AND inline governance in a custom server you wrote. With the same `api_key`, every call lands in your org's audit trail; in local mode each process writes its own `hiitl_audit.db`.

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

You're running without a policy, or without `mode="RESPECT_POLICY"`: the default mode, `OBSERVE_ALL`, returns a BLOCK or approval as `OBSERVE` and records what the policy would have decided in `would_be`. Create a `policy.yaml` and pass both to hiitl:
```python
hiitl = HIITL(policy_path="./policy.yaml", mode="RESPECT_POLICY", agent_id="my-mcp-server")
```

### Action name mismatch

The `name` in `evaluate(name, parameters=arguments)` must match the `action` in your policy conditions. If your MCP tool is called `process_payment`, the policy condition must use `value: "process_payment"`.

### Arguments structure

`evaluate()` passes `arguments` directly as parameters. Policy conditions reference them as `parameters.field_name`. If your tool receives `{"amount": 100}`, the policy condition is `field: "parameters.amount"`.

---

## Next Steps

- [Pattern Repository](../../patterns/README.md) — Copy starter policies for your tools
- [Policy Cookbook](policy_cookbook.md) — Advanced policy patterns
- [Python Quickstart](quickstart_python.md) — Deep dive into the Python SDK
- [TypeScript Quickstart](quickstart_typescript.md) — Deep dive into the TypeScript SDK
