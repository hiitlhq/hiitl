# `hiitl-mcp-proxy` recipes

End-to-end recipes for the two MCP clients most developers use day-to-day.

| Recipe | Outcome | Smoke-test status |
|--------|---------|-------------------|
| [Claude Desktop](claude_desktop.md) | Govern filesystem MCP server through Claude Desktop on macOS | Engineering-validated; manual smoke pending |
| [Cursor](cursor.md) | Govern GitHub MCP server through Cursor | Engineering-validated; manual smoke pending |

Each recipe is self-contained — a developer following only one of these files should reach "governed tool calls visible in the hiitl dashboard" in under 5 minutes.

The recipes intentionally use **TypeScript upstream MCP servers** (filesystem, GitHub) to demonstrate the wrapper pattern: the Python proxy spawns TS servers as child processes and speaks MCP over stdio. See the [package README](../README.md) for the Pattern 1 vs Pattern 2 framing.

---

## What "verified" means in this folder

For V1.0 GA, each recipe must:

1. Reach governed-tool-call state on a clean machine in under 5 minutes by following only the recipe (no other docs).
2. Show a working config snippet that's copy-paste ready modulo your own API keys and paths.
3. Include a failure-mode table — "if you see X, fix Y" — covering the realistic top 5 issues.
4. Be manually tested by an author on the relevant client.

The Claude Desktop and Cursor recipes here meet (1)–(3); (4) is pending.

Recipes for other clients (Zed, Continue, custom MCP clients) are out of scope for V1.0 GA — open an issue if you need one.
