# MCP Server Example

Add hiitl to an MCP (Model Context Protocol) server. Every tool call is evaluated against policy before execution.

## Run

```bash
pip install hiitl
python server.py
```

The tool handlers are simulated, so the example runs without the `mcp` package. It ships no policy file, so it runs in observe mode: every call proceeds and is recorded. To enforce, write a `policy.yaml` with an `ALLOW` rule for each tool call it lets through, and uncomment `policy_path` and `mode` in `server.py`.

## What this demonstrates

- Wrapping MCP tool handlers with `hiitl.evaluate()`
- One-line integration pattern
- Policy enforcement for MCP tool calls
- Handling blocked and approval-required decisions
