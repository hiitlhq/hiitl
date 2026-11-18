# `hiitl-mcp-proxy`

**A drop-in MCP wrapper that governs every tool call.** Point your MCP client (Claude Desktop, Cursor, etc.) at the proxy instead of your servers, and every `tools/call` flows through hiitl's `evaluate()` before reaching the upstream server.

---

## What this is — and what it isn't

There are two patterns the phrase *"hiitl + MCP"* can describe. This package is unambiguously **Pattern 2.**

| | Pattern 1 — *not what this is* | **Pattern 2 — what this is** |
|---|---|---|
| **Role** | hiitl is *an* MCP server you connect your client to | hiitl is a **wrapper** that sits between your client and your existing MCP servers |
| **Topology** | Client → hiitl (server) | Client → **hiitl-mcp-proxy** → your existing MCP server(s) |
| **What you give up** | You'd swap your tools for hiitl-specific tools | Nothing. Your tools keep their original names and behavior |
| **Upstream language** | N/A | **Any language**. The proxy spawns upstream servers as child processes and speaks MCP over stdio (or connects via SSE) |

The proxy is the parent process. It doesn't care what language the upstream MCP server is written in — Python, TypeScript, Go, Rust — because it talks to it via the MCP protocol over stdio or SSE.

**Concretely:** if you're running an off-the-shelf TypeScript MCP server like `@modelcontextprotocol/server-github`, you don't need a Python wrapper around it. You don't need to port it. You point hiitl-mcp-proxy at it, and the proxy spawns it as `npx -y @modelcontextprotocol/server-github` and governs every `tools/call` that flows through.

---

## Quick start (Claude Desktop)

Before — Claude Desktop points at MCP servers directly:

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

After — one entry, the hiitl proxy. The original servers move into `hiitl-mcp.yaml` and get spawned by the proxy:

```yaml
# ~/hiitl-mcp.yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
```

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/me/hiitl-mcp.yaml"]
    }
  }
}
```

```bash
pip install 'hiitl[mcp]'
# Edit the two configs above
# Restart Claude Desktop
```

That's it. The MCP icon in Claude Desktop shows your tools with their original names. Every call now flows through hiitl.

### Enforce your own policy file (local mode, no API key)

With no API key and no policy file, the proxy observes policy decisions and records new evaluations. An audit write failure blocks the call even in this mode. Add a policy file and its rules bind: the SDK evaluates it in-process without a hosted hiitl service. The proxy still forwards allowed calls to your configured tool servers, which may be remote, and those tools may make network calls. Add a routes directory, and a `ROUTE` rule asks its route before the call runs.

```yaml
# ~/hiitl-mcp.yaml
policy_path: /Users/me/hiitl/policy.json     # absolute: the MCP client picks the working directory
routes_path: /Users/me/hiitl/routes          # optional: one JSON file per route
audit_db_path: /Users/me/hiitl/audit.db      # optional: the SDK's default is ./hiitl_audit.db
servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
```

```json
{
  "version": "v1.0.0",
  "description": "Controls on the agent's git tools",
  "scope": {
    "org_id": "org_devlocal0000000000",
    "environment": "dev"
  },
  "name": "claude_desktop",
  "rules": [
    {
      "name": "no-pushes-to-main",
      "priority": 900,
      "conditions": {"all_of": [
        {"field": "action", "operator": "equals", "value": "push_files"},
        {"field": "parameters.branch", "operator": "equals", "value": "main"}
      ]},
      "decision": "BLOCK",
      "reason_code": "NO_PUSH_TO_MAIN",
      "description": "The agent opens a branch; it never pushes to main"
    },
    {
      "name": "allow-otherwise",
      "priority": 1,
      "conditions": {"field": "action", "operator": "exists", "value": true},
      "decision": "ALLOW",
      "reason_code": "ALLOWED",
      "description": "Everything else"
    }
  ]
}
```

A call that no rule matches is blocked (`NO_MATCHING_RULE`), so a policy file usually ends with an allow rule. `mode: OBSERVE_ALL` records what policy would decide without enforcing policy refusals. Failures such as an audit write failure still block. Retries within the dedup window reuse the recorded decision without another row. To sign envelopes, set `HIITL_SIGNATURE_KEY` in the proxy's environment (the `env` of its entry in the MCP client's config). The key is never a field in `hiitl-mcp.yaml`. A route file's shape is in [routes.md](../../../docs/specs/routes.md).

End-to-end recipes:
- [**Claude Desktop** (5-minute recipe)](recipes/claude_desktop.md) — wraps `@modelcontextprotocol/server-filesystem`
- [**Cursor** (5-minute recipe)](recipes/cursor.md) — wraps `@modelcontextprotocol/server-github`

---

## Per-call flow

```
MCP client ──tools/call──▶ hiitl-mcp-proxy ──evaluate()──▶ audit + dashboard
                                  │
                                  │ ALLOW
                                  ▼
                         upstream MCP server  (any language)
```

- **ALLOW** → forwards to upstream and returns the result.
- **BLOCK / RATE_LIMIT / KILL_SWITCH** → MCP error returned to the client, with the reason codes. The upstream is not called. Audit row written.
- **ROUTE** → the SDK has already asked the rule's sync route (from `routes_path`) and evaluated again with its answer, so the answer decides. A `ROUTE` that reaches the proxy is one the route did not answer: it fails closed. A route's wait holds its own call only; the proxy answers every other call meanwhile.
- **PAUSE / REQUIRE_APPROVAL / ESCALATE** → with `api_key` and `server_url`, the proxy waits on a hiitl review case (Block 3b SSE / pg_notify); reviewer's approve/modify/reject resolves the wait and the proxy either forwards (with the modified arguments) or returns an error. The case waits the route's `sla.timeout` when it fits within `review_timeout_seconds`; a timeout the service records takes the route's `sla.timeout_action` (`fail_open` forwards, anything else is refused), and a shorter wait records `fail_closed`. Without them, the call is blocked with a message that it needs human approval.
- **OBSERVE** → forwards and audits, doesn't block.
- **The record** → each new evaluation of an admitted envelope writes one row; a repeated idempotency key reuses the first decision without another row. An unwritable record blocks with `AUDIT_WRITE_FAILED` and leaves no row. A numeric value refused before an envelope exists also leaves no row or decision; the error names the field and directs the caller to pass it as text. Each written row holds each argument by name with an HMAC-SHA256 hash of its value, unless `recorded_arguments` names it for that tool. Policies evaluate the real arguments, and the upstream receives them. The key is made at the gateway's first start beside its audit file (`<audit_db_path>.value_hash.key`, mode 0600) and never leaves it ([Data handling](../../../docs-site/security/data-handling.mdx#redaction)).

---

## Configuration

```yaml
# hiitl-mcp.yaml — every field but `servers` is optional; values are read as written (a `${VAR}` is that string),
# and an upstream's `secret_refs` names a variable of the proxy's environment (for an SSE upstream, a header's value)
servers:
  # stdio upstream — child process
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    secret_refs:                            # optional: each variable's value is read from the proxy's environment when it
      GITHUB_PERSONAL_ACCESS_TOKEN: env:GITHUB_PERSONAL_ACCESS_TOKEN   # starts; an unset one stops the start, naming it
    # env: {LOG_LEVEL: debug}               # optional: values passed as written. The upstream's environment is these,
                                            # plus PATH, HOME and the like, never the rest of the proxy's own

  # SSE upstream — already-running remote MCP server
  my-internal:
    url: https://mcp.internal.example.com/sse   # https naming a host; any other URL stops the load, naming it
    secret_refs:                            # optional: each header's value is read from the proxy's environment when it
      Authorization: env:MY_INTERNAL_AUTH   # starts (the whole value, e.g. "Bearer …"); an unset one stops the start
    # headers: {X-Team: platform}           # optional: values sent as written; a header has one source, here or above

# Local mode — the SDK's own configuration, passed through
policy_path: /Users/me/hiitl/policy.json    # its rules bind
routes_path: /Users/me/hiitl/routes         # a ROUTE rule's sync route is asked
audit_db_path: /Users/me/hiitl/audit.db
# recorded_arguments:                       # per tool, the arguments the record holds as given; every other argument
#   create_issue: [repo]                    # is recorded by name with an HMAC-SHA256 hash of its value (unset: all hashed)
# mode: OBSERVE_ALL                         # OBSERVE_ALL | RESPECT_POLICY; unset: RESPECT_POLICY with an api_key or a policy file

# Hybrid — optional. Unset: the proxy reads HIITL_API_KEY from its environment (the `env` of its entry in the
# MCP client's config); with neither, local mode
# api_key: sk-hiitl-...
# server_url: https://api.hiitl.com         # the SDK's sync target, and the review API for PAUSE / REQUIRE_APPROVAL / ESCALATE

environment: prod                           # dev | stage | prod
agent_id: claude-desktop
timeout_seconds: 30
review_timeout_seconds: 300
```

Full reference in [`config.py`](config.py).

---

## CLI

```bash
hiitl-mcp-proxy --config /path/to/hiitl-mcp.yaml
hiitl-mcp-proxy --config ./hiitl-mcp.yaml --log-level DEBUG
HIITL_MCP_CONFIG=~/hiitl-mcp.yaml hiitl-mcp-proxy
```

Logs go to **stderr only** — stdout is reserved for MCP protocol traffic, since MCP clients speak over stdio.

The proxy reads two variables of its own: `HIITL_MCP_CONFIG`, the config file when `--config` is not given, and
`HIITL_MCP_LOG_LEVEL`, the log level when `--log-level` is not given (a name Python's `logging` defines, such as
`DEBUG` or `WARNING`; default `INFO`). Any other `HIITL_MCP_*` variable, set, stops the proxy at start-up, naming the
variables it reads, and so does a log level `logging` does not define: a setting is never ignored or read as another
value without a word (docs/specs/sync_engine.md section 9). The SDK client the proxy runs reads its own
`HIITL_SYNC_*` and `HIITL_TELEMETRY_*` variables and refuses an unread one of those the same way.

---

## FAQ

**Q: My MCP server is TypeScript. Does the Python proxy work for me?**
A: Yes. The proxy spawns your TypeScript server as a child process (`npx ... your-mcp-server`) and speaks MCP to it over stdio. The proxy is the parent; the language of the child doesn't matter.

**Q: I need to govern multiple MCP servers. Do I run one proxy per server?**
A: No. One proxy handles many upstreams. List them all under `servers:` in `hiitl-mcp.yaml`. The proxy multiplexes — tools from every upstream are exposed under their original names, with collision detection at startup.

**Q: What about tool-name collisions across upstreams?**
A: Detected at startup and fails loudly. Rename the colliding tool's namespace via the upstream's own config, or open an issue if you need an explicit `prefix:` knob on the proxy side.

**Q: Is there a TypeScript version of the proxy?**
A: Not currently. The Python proxy manages TypeScript MCP servers fine (see above), so a TS rewrite isn't a near-term need.

**Q: Where do PAUSE / human review responses come from?**
A: Block 3b shipped a backend review case API with SSE / pg_notify push. The proxy waits on a review case to resolve, then forwards the (possibly modified) tool call. See [`review_client.py`](review_client.py).

---

## Source layout

| File | Purpose |
|------|---------|
| [`cli.py`](cli.py) | `hiitl-mcp-proxy` entry point |
| [`config.py`](config.py) | YAML parsing + validation |
| [`upstream.py`](upstream.py) | Stdio / SSE upstream lifecycle, tool discovery, collision detection |
| [`proxy.py`](proxy.py) | The MCP-server side of the proxy: `tools/call` interception + `evaluate()` |
| [`review_client.py`](review_client.py) | PAUSE / REQUIRE_APPROVAL waiting via the hiitl review case API |
| `tests/` | Integration tests (in-memory MCP transport; ~1.2s suite) |

---

## Related

- [Project README](../../../../README.md) — overall hiitl project
- [MCP Quickstart](../../../docs/onboarding/quickstart_mcp.md) — narrative version of this README, plus Path B (inline `evaluate()` in your own MCP server)
- TICKET-117 — this docs clarification work
- TICKET-118 — verified end-to-end recipes for Claude Desktop and Cursor
