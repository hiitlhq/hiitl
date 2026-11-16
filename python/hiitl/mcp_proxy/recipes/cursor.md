# Recipe: Cursor + `hiitl-mcp-proxy` in 5 minutes

> **Target outcome.** A Cursor user reaches "governed tool calls visible in the hiitl dashboard" in under 5 minutes by following only this recipe.

> **Manual smoke test status.** Engineering-validated against the proxy's config schema + CLI surface. Trevor will smoke-test against a real Cursor install before V1.0 GA; until then treat as "not yet user-smoke-tested."

> **Cursor MCP API note.** Cursor's MCP support is recent (mid-2026 timeframe) and the config schema is similar but not identical to Claude Desktop's. If Cursor changes the schema in a way this recipe doesn't cover, open an issue.

---

## Prerequisites

- [Cursor](https://cursor.com) installed (recent build with MCP support — Settings → Features → MCP servers should be visible)
- Python **3.12+** with `pip`
- Node.js + `npx` (for the upstream MCP servers used in the example)
- A hiitl API key (optional — omit for local OBSERVE_ALL)

---

## Step 1 — Install

```bash
pip install 'hiitl[mcp]'
hiitl-mcp-proxy --help    # should print the usage banner
```

---

## Step 2 — Write `hiitl-mcp.yaml`

Save at `~/hiitl-mcp.yaml`:

```yaml
servers:
  github:
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    secret_refs:
      GITHUB_PERSONAL_ACCESS_TOKEN: "env:GITHUB_PERSONAL_ACCESS_TOKEN"
```

This wraps the GitHub MCP server — another TypeScript upstream proxied by Python. The GitHub server reads a personal access token from `GITHUB_PERSONAL_ACCESS_TOKEN`, and `secret_refs` gives it one by reference: when the proxy starts, it reads `GITHUB_PERSONAL_ACCESS_TOKEN` from its own environment and passes the value to the upstream, so the token is never written in this file. Set it in the `env` of the proxy's entry (Step 3). If it is unset, the proxy does not start, and its error names the variable. The upstream gets nothing else from the proxy's environment but PATH, HOME and the like. A value under an upstream's `env:` is passed as written, so `"${GITHUB_PERSONAL_ACCESS_TOKEN}"` there would reach GitHub as that string.

With no API key, the proxy runs locally: it observes and records every call (OBSERVE_ALL). For hosted mode, set `HIITL_API_KEY` in the `env` of the proxy's entry (Step 3): the proxy reads the key from its environment when `hiitl-mcp.yaml` sets no `api_key`.

---

## Step 3 — Configure Cursor

Open Cursor → **Settings** → **Features** → **MCP servers** → click **Add new MCP server**.

Fill in:

| Field | Value |
|-------|-------|
| Name | `hiitl` |
| Type | `command` |
| Command | `hiitl-mcp-proxy --config /Users/YOUR_USERNAME/hiitl-mcp.yaml` |
| Environment | `GITHUB_PERSONAL_ACCESS_TOKEN` (your token); `HIITL_API_KEY` for hosted mode |

Some Cursor versions instead expose a `~/.cursor/mcp.json`-style config. The equivalent JSON entry is:

```json
{
  "mcpServers": {
    "hiitl": {
      "command": "hiitl-mcp-proxy",
      "args": ["--config", "/Users/YOUR_USERNAME/hiitl-mcp.yaml"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_...", "HIITL_API_KEY": "sk_..." }
    }
  }
}
```

Leave out `HIITL_API_KEY` for local mode.

> **Tip.** Use an **absolute** path to the YAML. Cursor's child-process launcher does not reliably expand `~`.

---

## Step 4 — Reload Cursor

Some Cursor versions need a window reload (`Cmd-Shift-P → Developer: Reload Window`); some restart MCP servers automatically when the config saves.

---

## Step 5 — Verify

1. Open Cursor's Chat or Composer panel.
2. Click the **tools / MCP** affordance. You should see GitHub tools (`create_issue`, `list_issues`, `get_repo`, etc.) listed under the `hiitl` server with their original names.
3. Ask Cursor: *"List the open issues on `octocat/Hello-World`."* The agent invokes `list_issues`. The proxy intercepts, calls `evaluate()`, and forwards to the GitHub upstream.
4. Open the hiitl dashboard — the action should appear within seconds.

---

## Failure modes — if you see X, do Y

| Symptom | Cause | Fix |
|---------|-------|-----|
| `hiitl` server is offline in Cursor's MCP panel | Proxy failed to launch | Check Cursor's developer console (`Cmd-Shift-P → Developer: Toggle Developer Tools`) for stderr. Most common: bad config path or `hiitl-mcp-proxy` not on PATH. |
| `command not found: hiitl-mcp-proxy` | `pip` install dir not on Cursor's launcher PATH | Use absolute path (`which hiitl-mcp-proxy` to find it), or invoke as `python -m hiitl.mcp_proxy.cli`. |
| Tools list is empty | Upstream MCP server failed to spawn | Check the proxy's stderr (Cursor logs). The upstream's own stderr also bubbles up; look for `npx: command not found` or auth errors. |
| The proxy exits naming `GITHUB_PERSONAL_ACCESS_TOKEN` | `secret_refs` names a variable the proxy's environment does not set | Set it in the `env` of the proxy's entry in Cursor's MCP config (Step 3). The proxy reads it from its own environment, never your shell's. |
| `Unauthorized` from GitHub upstream | The token in `GITHUB_PERSONAL_ACCESS_TOKEN` is wrong | The upstream receives the value the proxy's `GITHUB_PERSONAL_ACCESS_TOKEN` holds (Step 3). Check that token. |
| Tool calls work but aren't appearing in the hiitl dashboard | `api_key` missing or wrong, or wrong environment | Set `HIITL_API_KEY` in the `env` of the proxy's entry in Cursor's MCP config (Step 3), or `api_key` in `hiitl-mcp.yaml`. Verify the dashboard's environment selector matches. |
| Proxy exits with `ToolNameCollision` | Two upstreams expose a same-named tool | Drop one upstream from `servers:`, or open an issue for an explicit `prefix:` knob. |

---

## What's happening under the hood

```
Cursor ──tools/call──▶ hiitl-mcp-proxy ──evaluate()──▶ audit + dashboard
                              │
                              │ ALLOW
                              ▼
              @modelcontextprotocol/server-github  (TypeScript)
```

Same pattern as Claude Desktop. The proxy is Python; the upstream is TypeScript; the wire format is MCP-over-stdio. Adding more upstreams (filesystem, postgres, slack, etc.) means more entries in `hiitl-mcp.yaml` — no new processes for Cursor to manage.

---

## Next steps

- **Add OBSERVE → enforce.** Once a day of OBSERVE traffic accumulates, the dashboard surfaces suggestion cards. Accept the ones that match your policies; promote them to active.
- **PAUSE for review.** Policies that return `PAUSE` / `REQUIRE_APPROVAL` block the tool call in Cursor until a human in the hiitl dashboard resolves. The proxy waits on the review case via SSE.
- **Govern your own MCP server.** If you've written a TypeScript MCP server for your team, add it to `hiitl-mcp.yaml` as another `command + args` entry. It does not need to be Python.
