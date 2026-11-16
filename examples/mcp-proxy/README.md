# hiitl MCP Proxy — Claude Desktop Recipe

Drop-in governance for every MCP tool call in Claude Desktop. One config change, everything still works, every tool call goes through `hiitl.evaluate()`.

## What you get

- **Observability from minute one.** Every tool call lands in the audit trail, each argument by name with an HMAC-SHA256 hash of its value unless `recorded_arguments` in `hiitl-mcp.yaml` names it. The dashboard populates as you use Claude normally.
- **Policy enforcement when you want it.** Write a policy (or accept a suggested one from the intelligence layer), and BLOCK/ALLOW decisions happen at the proxy — the agent can't bypass it.
- **No code changes to your MCP servers.** The proxy spawns your existing servers as child processes (stdio) or connects to them via SSE.
- **Tools keep their original names.** `send_email` stays `send_email`. The agent doesn't know it's talking to a proxy.

## Setup (3 steps)

### 1. Install

```bash
pip install 'hiitl[mcp]'
```

This installs the `hiitl-mcp-proxy` command and the MCP SDK.

### 2. Move your MCP servers into a hiitl config

If your Claude Desktop config today looks like this:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx" }
    }
  }
}
```

…copy [`hiitl-mcp.yaml`](./hiitl-mcp.yaml) from this directory, and translate each `mcpServers` entry into a `servers:` entry:

```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    secret_refs:
      GITHUB_PERSONAL_ACCESS_TOKEN: "env:GITHUB_PERSONAL_ACCESS_TOKEN"
```

A secret an upstream's `env` held moves to `secret_refs`, by reference to a variable of the proxy's environment, so `hiitl-mcp.yaml` holds no token. The proxy reads the variable when it starts, and stops, naming it, if it is unset. Its value goes in the proxy's entry in step 3.

Save it somewhere stable — your home directory works fine: `~/hiitl-mcp.yaml`.

### 3. Repoint Claude Desktop

Replace your Claude Desktop config (location below) with the contents of [`claude_desktop_config.json`](./claude_desktop_config.json), updating the absolute path to your `hiitl-mcp.yaml`:

```json
{
  "mcpServers": {
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/me/hiitl-mcp.yaml"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx" }
    }
  }
}
```

Then restart Claude Desktop.

**Claude Desktop config locations:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

That's it. Open Claude Desktop, look at the MCP icon — your tools should appear with their original names. Use Claude normally; every tool call is now governed.

## What happens to each tool call

```
Claude Desktop
     │
     │ tools/call(name="send_email", args={...})
     ▼
hiitl-mcp-proxy ────── hiitl.evaluate() ──── audit trail / dashboard
     │
     │ if ALLOW: forward
     ▼
upstream MCP server  (your email-mcp-server, spawned as a child process)
```

- `ALLOW` (or `SANDBOX` / `OBSERVE`) → proxy forwards to the upstream and returns its result unchanged.
- `BLOCK` → proxy returns a structured error to Claude Desktop with the policy reason. The upstream is never called.
- `REQUIRE_APPROVAL` / `PAUSE` / `ESCALATE` → if the proxy has `server_url` + `api_key` set, it opens a review case and waits (over SSE) for a reviewer to approve, reject, or modify. Modified-arguments approvals forward to the upstream with the reviewer's values. A case waits the route's `sla.timeout` when it fits within `review_timeout_seconds`, and a timeout the service records takes the route's `sla.timeout_action` (`fail_open` forwards; anything else is refused); a shorter wait records `fail_closed`. Without `server_url` configured, the call is blocked with a message that it needs human approval — the placeholder for local-only deployments.

## Observe-first onboarding

You don't need to write a policy first. With no policy file configured, hiitl runs in `OBSERVE_ALL` mode: every action is allowed and logged. After a few sessions you'll have real behavior data — that's when the intelligence layer starts suggesting policies you can accept.

## Tool name collisions

If two upstream servers expose a tool with the same name (e.g., both expose `search`), the proxy refuses to start and tells you which servers collide on which tool. Fix the config — rename one upstream's tool, or drop a duplicate dependency — and restart.

## Troubleshooting

**The proxy starts but I see no tools in Claude Desktop.**
Check the proxy logs (stderr). They'll show how many tools were discovered per upstream server. If the count is zero for an upstream, that server probably had an error during `list_tools`.

**Claude Desktop reports "MCP server disconnected".**
Check the proxy logs — most likely an upstream crashed (bad config, missing env var, invalid path). The proxy crashes on startup errors so Claude Desktop sees a clean disconnect rather than a half-broken stub.

**`hiitl-mcp-proxy: command not found`.**
Verify the install: `which hiitl-mcp-proxy`. If your Claude Desktop config can't find it (different PATH than your shell), use the absolute path: `command: /full/path/to/hiitl-mcp-proxy`.

## What the next release adds

- **Reviewer UI.** A page in the hiitl Control Center at `/app/reviews` for triaging pending cases — sortable list with 5s auto-refresh, a per-case detail drawer showing the envelope + policy decision, and approve / reject / **approve with edits** (JSON editor for `modified_arguments`) actions. Authenticated via your Clerk session — org owners get reviewer access automatically; no admin API key paste required. Block 4a deliverable. For automation, `curl` against `/v1/reviews/pending` + `/v1/reviews/{id}/resolve` still works.
- **TypeScript proxy.** Same protocol, no Python dependency for TS-shop deployments. Tracked separately.

## See also

- [docs/onboarding/quickstart_mcp.md](../../docs/onboarding/quickstart_mcp.md) — full quickstart with policy authoring.
- [docs/specs/policy_format.md](../../docs/specs/policy_format.md) — policy syntax.
