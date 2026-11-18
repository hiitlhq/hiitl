# Recipe: Claude Desktop + `hiitl-mcp-proxy` in 5 minutes

> **Target outcome.** A clean Claude Desktop install on macOS reaches "governed tool calls visible in the hiitl dashboard" in under 5 minutes by following only this recipe.

> **Manual smoke test status.** This recipe is the authoritative steps based on the proxy's config schema + CLI surface ([`config.py`](../config.py), [`cli.py`](../cli.py)). Trevor will smoke-test against a real Claude Desktop install before V1.0 GA; until then treat as "engineering-validated, not yet user-smoke-tested."

---

## Prerequisites

- macOS with [Claude Desktop](https://claude.ai/download) installed
- Python **3.12+** with `pip`
- Node.js + `npx` (for the upstream MCP servers used in the example below)
- A hiitl API key — get one at [app.hiitl.com](https://app.hiitl.com) → Settings → API keys, or skip and run in `OBSERVE_ALL` local mode

---

## Step 1 — Install

```bash
pip install 'hiitl[mcp]'
```

Verify:

```bash
hiitl-mcp-proxy --help
```

You should see the proxy's usage banner. If `command not found`, your `pip` install path isn't on `PATH` — find the binary with `python -m pip show -f hiitl | grep 'hiitl-mcp-proxy$'` and either add its directory to PATH or invoke it as `python -m hiitl.mcp_proxy.cli`.

---

## Step 2 — Write `hiitl-mcp.yaml`

Save this at `~/hiitl-mcp.yaml`:

```yaml
servers:
  filesystem:
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/Users/YOUR_USERNAME/Documents"
```

Replace `YOUR_USERNAME` with your macOS username. The upstream filesystem server is a TypeScript MCP server — the Python proxy spawns it as a child process and speaks MCP over stdio. (This is the wrapper pattern documented in [README.md](../README.md).)

With no API key, the proxy runs locally: it observes and records every call (OBSERVE_ALL). For a hosted-platform connection, give the proxy your key as `HIITL_API_KEY` in the `env` of its entry in Step 3: that is the environment Claude Desktop starts the proxy with, and the proxy reads the key from it when `hiitl-mcp.yaml` sets no `api_key`. A value in `hiitl-mcp.yaml` is read as written, so `api_key: "${HIITL_API_KEY}"` would be that string, not your key.

---

## Step 3 — Update `claude_desktop_config.json`

The file lives at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS.

```json
{
  "mcpServers": {
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/YOUR_USERNAME/hiitl-mcp.yaml"]
    }
  }
}
```

With a hosted-platform connection, the entry carries your key:

```json
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/YOUR_USERNAME/hiitl-mcp.yaml"],
      "env": { "HIITL_API_KEY": "sk_..." }
    }
```

If you already have other entries under `mcpServers`, **remove them** (the proxy is now spawning them — see Step 2). Or keep them temporarily for side-by-side comparison.

> **Tip.** Use the absolute path to your config. `~` may not be expanded reliably by Claude Desktop's launcher.

---

## Step 4 — Restart Claude Desktop

Fully quit and relaunch (Cmd-Q, then reopen). The proxy starts as a child process the moment Claude Desktop launches.

---

## Step 5 — Verify

1. Open a new chat.
2. Click the MCP icon (🔌 in the input bar). You should see your upstream tools listed under the `hiitl` server — `read_file`, `write_file`, `list_directory`, etc. (Original names, not prefixed.)
3. Ask Claude: *"List the files in my Documents folder."* Claude will invoke `list_directory`. The proxy intercepts, calls `evaluate()`, and (in OBSERVE_ALL mode) forwards to the upstream.
4. Open the hiitl dashboard. Within seconds you should see the action recorded.

---

## Failure modes — if you see X, do Y

| Symptom | Cause | Fix |
|---------|-------|-----|
| MCP icon shows no tools after restart | Proxy failed to start | Tail the Claude Desktop log: `tail -f ~/Library/Logs/Claude/mcp.log`. Look for stderr from `hiitl-mcp-proxy`. Most common: bad YAML path. |
| `command not found: hiitl-mcp-proxy` | `pip install` didn't put the binary on PATH | Use the absolute path to the binary in `claude_desktop_config.json` (`which hiitl-mcp-proxy`), or invoke as `python -m hiitl.mcp_proxy.cli`. |
| Proxy crashes with `ToolNameCollision` at startup | Two upstreams expose a tool with the same name | Re-namespace at the upstream's own config (e.g. only mount one filesystem server), or open an issue if you need a `prefix:` knob on the proxy. |
| Tool calls appear in dashboard but never reach upstream | Decision was BLOCK (intentional) | Check `hiitl_decision: BLOCK` in the audit row. Adjust the matching policy. |
| `[mcp] Permission denied: /Users/.../Documents` | Upstream filesystem server doesn't have macOS Privacy permissions | System Settings → Privacy & Security → Files and Folders → grant Claude Desktop access to the directory. Restart. |
| All decisions return `OBSERVE_ALL` and you wanted enforcement | No policy active for your org / environment | Either set `HIITL_API_KEY` in the proxy entry's `env` (Step 3) and configure policies in the dashboard, or set `policy_path:` in `hiitl-mcp.yaml` to enforce a local policy file (see the README's local-mode quick start). |

---

## What's happening under the hood

```
Claude Desktop ──tools/call──▶ hiitl-mcp-proxy ──evaluate()──▶ audit + dashboard
                                        │
                                        │ ALLOW
                                        ▼
                          @modelcontextprotocol/server-filesystem   (TypeScript)
```

The proxy is the wrapper. The upstream filesystem server is TypeScript. The proxy is Python. They talk MCP over stdio — language doesn't matter.

---

## Next steps

- **Govern more servers.** Add entries under `servers:` in `hiitl-mcp.yaml`. The proxy multiplexes — tools from every upstream show up under their original names.
- **Add policies.** Once you've watched a day of OBSERVE traffic, accept suggestion cards from the hiitl dashboard to convert observed patterns into enforcement.
- **Handle PAUSE.** When a policy returns `PAUSE` / `REQUIRE_APPROVAL`, the proxy waits on a review case via SSE / `pg_notify` (Block 3b) until a reviewer resolves. See [`review_client.py`](../review_client.py).
