# MCP Server Example

Add hiitl to an MCP (Model Context Protocol) server. Every tool call is evaluated against policy before execution.

## Run

```bash
pip install hiitl mcp
python server.py
```

## What this demonstrates

- Wrapping MCP tool handlers with `hiitl.evaluate()`
- One-line integration pattern
- Policy enforcement for MCP tool calls
- Handling blocked and approval-required decisions
