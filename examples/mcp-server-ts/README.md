# MCP server with hiitl inline (TypeScript)

A real MCP server (`@modelcontextprotocol/sdk`'s `McpServer`). Each tool handler calls `hiitl.evaluate()` before its
effect, the TypeScript counterpart of [`examples/mcp-server`](../mcp-server). `policy.json` blocks `delete_note`;
`read_note` and `write_note` run. Every call is recorded in the local audit log.

```bash
npm install
NOTES_DIR=./notes npx tsx server.ts      # speaks MCP on stdio
```

`@hiitl/sdk` is linked from this repository (`file:../../typescript/packages/sdk`); `npm install` builds it, and the
`@hiitl/core` it imports, from their lock files (the `prepare` script), so nothing is built by hand. `server.ts` reads
`import.meta.dirname`; use Node.js 22 or later, as required by both hiitl TypeScript packages.

Point any MCP client at `npx tsx server.ts`. A blocked call returns a tool error (`isError: true`) naming the rule's
reason code (`hiitl: BLOCK (DELETE_BLOCKED)`). Remove `policy_path` and `mode` to observe without enforcing. The other path is
the proxy, which needs no code change: [`examples/mcp-proxy`](../mcp-proxy).
