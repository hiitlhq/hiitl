"""hiitl-mcp-proxy — drop-in MCP proxy that governs every tool call via evaluate().

The user points Claude Desktop at `hiitl-mcp-proxy --config hiitl-mcp.yaml`
instead of their original MCP servers. The proxy spawns the original
servers as child processes (stdio) or connects to them via SSE,
discovers their tools, and re-exposes them under their original names.
Every tool call flows through the hiitl SDK's `evaluate()` before being
forwarded.

ALLOW forwards, BLOCK returns an MCP error, and PAUSE /
REQUIRE_APPROVAL / ESCALATE open a review case on the hiitl backend
and wait for the reviewer (SSE) when the config names `server_url` and
`api_key`. Without them the call is refused with a message saying the
review flow requires a hiitl backend. The original decision is in the
audit trail either way.

Read the module docstrings for `config.py`, `upstream.py`, `proxy.py`,
and `cli.py` for the per-component design.
"""

__all__ = [
    "ProxyConfig",
    "UpstreamServer",
    "UpstreamManager",
    "build_proxy_server",
    "run_proxy",
]

from hiitl.mcp_proxy.config import ProxyConfig
from hiitl.mcp_proxy.upstream import UpstreamServer, UpstreamManager
from hiitl.mcp_proxy.proxy import build_proxy_server, run_proxy
