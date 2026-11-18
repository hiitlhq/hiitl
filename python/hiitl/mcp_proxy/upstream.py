"""Upstream MCP server lifecycle + tool discovery.

`UpstreamManager` owns the set of upstream MCP servers the proxy
fronts for. For each entry in `ProxyConfig.servers`:

1. Open a transport (stdio child process or SSE connection).
2. Wrap it in an MCP `ClientSession`.
3. Drive the MCP initialize handshake.
4. Call `list_tools`, `list_resources`, `list_prompts` to discover what
   the upstream offers.
5. Build a tool-name → upstream-label routing table.

**Tool name collision policy (Block 3a):** if two upstreams expose the
same tool name, fail at startup with a clear error naming both servers
and the tool. Silent collisions at runtime would be a debugging
nightmare. The user fixes their config (rename one upstream's tool, or
remove a duplicate dependency) before anything runs.

For resources and prompts, the same policy applies — they're identified
by URI (resources) or name (prompts), and collisions are similarly
errors.
"""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from mcp import types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hiitl.mcp_proxy.config import (
    ProxyConfig,
    SseServerConfig,
    StdioServerConfig,
    UpstreamConfig,
)


logger = logging.getLogger(__name__)


@dataclass
class UpstreamServer:
    """A connected upstream server: its label, its session, and what it offers."""

    label: str
    session: ClientSession
    tools: list[mcp_types.Tool] = field(default_factory=list)
    resources: list[mcp_types.Resource] = field(default_factory=list)
    prompts: list[mcp_types.Prompt] = field(default_factory=list)
    # The server's reported capabilities — proxy uses this to know whether
    # forwarding e.g. list_resources is meaningful.
    capabilities: Optional[mcp_types.ServerCapabilities] = None


class ToolCollisionError(RuntimeError):
    """Two upstreams expose the same tool name. Fail loud at startup."""


class ResourceCollisionError(RuntimeError):
    """Two upstreams expose the same resource URI."""


class PromptCollisionError(RuntimeError):
    """Two upstreams expose the same prompt name."""


class UpstreamConnectError(RuntimeError):
    """An upstream failed to connect or initialize."""


class UpstreamManager:
    """Manages the lifecycle of N upstream MCP servers + maintains routing tables.

    Use as an async context manager so child processes and SSE
    connections are torn down cleanly on exit:

        async with UpstreamManager(config) as mgr:
            await mgr.start()
            tool_name_to_label = mgr.tool_routes
            ...
    """

    def __init__(self, config: ProxyConfig):
        self._config = config
        self._stack: AsyncExitStack = AsyncExitStack()
        self._servers: dict[str, UpstreamServer] = {}
        # Routing tables: name/uri → upstream label.
        self._tool_routes: dict[str, str] = {}
        self._resource_routes: dict[str, str] = {}
        self._prompt_routes: dict[str, str] = {}
        self._started: bool = False

    # ------------------------------------------------------------------ #
    # Context-manager plumbing
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "UpstreamManager":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)

    # ------------------------------------------------------------------ #
    # Public properties
    # ------------------------------------------------------------------ #

    @property
    def servers(self) -> dict[str, UpstreamServer]:
        return dict(self._servers)

    @property
    def tool_routes(self) -> dict[str, str]:
        """Map of tool_name → upstream label."""
        return dict(self._tool_routes)

    @property
    def resource_routes(self) -> dict[str, str]:
        return dict(self._resource_routes)

    @property
    def prompt_routes(self) -> dict[str, str]:
        return dict(self._prompt_routes)

    def all_tools(self) -> list[mcp_types.Tool]:
        """Flat list of every tool discovered across all upstreams.

        Tool name uniqueness is already enforced at startup, so this is
        what the proxy re-exposes verbatim to the downstream client.
        """
        out: list[mcp_types.Tool] = []
        for srv in self._servers.values():
            out.extend(srv.tools)
        return out

    def all_resources(self) -> list[mcp_types.Resource]:
        out: list[mcp_types.Resource] = []
        for srv in self._servers.values():
            out.extend(srv.resources)
        return out

    def all_prompts(self) -> list[mcp_types.Prompt]:
        out: list[mcp_types.Prompt] = []
        for srv in self._servers.values():
            out.extend(srv.prompts)
        return out

    def session_for_tool(self, name: str) -> ClientSession:
        label = self._tool_routes.get(name)
        if label is None:
            raise KeyError(f"No upstream exposes tool '{name}'")
        return self._servers[label].session

    def session_for_resource(self, uri: str) -> ClientSession:
        label = self._resource_routes.get(uri)
        if label is None:
            raise KeyError(f"No upstream exposes resource '{uri}'")
        return self._servers[label].session

    def session_for_prompt(self, name: str) -> ClientSession:
        label = self._prompt_routes.get(name)
        if label is None:
            raise KeyError(f"No upstream exposes prompt '{name}'")
        return self._servers[label].session

    # ------------------------------------------------------------------ #
    # Startup
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Connect to every configured upstream and run discovery.

        Failures are surfaced as `UpstreamConnectError` so the CLI can
        print a useful message and exit with a non-zero code rather
        than leaving Claude Desktop talking to a half-broken proxy.
        """
        if self._started:
            return

        for label, server_cfg in self._config.servers.items():
            try:
                server = await self._connect_one(label, server_cfg)
            except Exception as exc:  # noqa: BLE001
                # Re-raise with context. The AsyncExitStack will clean
                # up any previously-connected upstreams during teardown.
                raise UpstreamConnectError(
                    f"Failed to connect to upstream '{label}': {exc}"
                ) from exc
            self._servers[label] = server

        # Capability-aware discovery: only call list_resources /
        # list_prompts on upstreams that advertise the capability.
        # Otherwise some servers raise "Method not found".
        for label, server in self._servers.items():
            await self._discover(label, server)

        self._check_collisions()
        self._started = True
        logger.info(
            "UpstreamManager started: %d server(s), %d tool(s), %d resource(s), %d prompt(s)",
            len(self._servers),
            sum(len(s.tools) for s in self._servers.values()),
            sum(len(s.resources) for s in self._servers.values()),
            sum(len(s.prompts) for s in self._servers.values()),
        )

    async def _connect_one(
        self, label: str, cfg: UpstreamConfig,
    ) -> UpstreamServer:
        """Open transport + ClientSession + initialize handshake."""
        if isinstance(cfg, StdioServerConfig):
            # An upstream variable given by reference is read from the gateway's environment now, before the
            # upstream is spawned; an unset name fails the start, naming it (HTL-22 row 157).
            referenced = cfg.referenced_env(label, os.environ)
            params = StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env={**(cfg.env or {}), **referenced} if referenced else cfg.env,
                cwd=cfg.cwd,
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif isinstance(cfg, SseServerConfig):
            # A header given by reference is read from the gateway's environment now, before the transport opens; an
            # unset name fails the start, naming it (HTL-23 row 214).
            referenced = cfg.referenced_headers(label, os.environ)
            # SSE transport is bundled with the `mcp` package (httpx-sse
            # is a hard dep), so this import is always available. The
            # try/except remains as a defensive guard in case the SDK
            # ever restructures.
            try:
                from mcp.client.sse import sse_client
            except ImportError as exc:
                raise UpstreamConnectError(
                    f"SSE upstream '{label}' failed to load mcp.client.sse "
                    f"(unexpected — httpx-sse should be installed with mcp). "
                    f"Underlying error: {exc}"
                ) from exc
            read, write = await self._stack.enter_async_context(
                sse_client(
                    cfg.url,
                    headers={**(cfg.headers or {}), **referenced},
                    timeout=cfg.connect_timeout_seconds,
                )
            )
        else:
            raise UpstreamConnectError(
                f"Unknown upstream transport for '{label}': {type(cfg).__name__}"
            )

        session = await self._stack.enter_async_context(ClientSession(read, write))
        init_result = await session.initialize()
        capabilities = init_result.capabilities
        return UpstreamServer(
            label=label, session=session, capabilities=capabilities,
        )

    async def _discover(self, label: str, server: UpstreamServer) -> None:
        """Run list_tools / list_resources / list_prompts, gated by capabilities.

        Catches per-method failures so one broken handler in one upstream
        doesn't block the rest of the proxy from coming up.
        """
        # Tools — most upstreams advertise these.
        try:
            tools_result = await server.session.list_tools()
            server.tools = list(tools_result.tools)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Upstream '%s': list_tools failed (%s) — proxy will expose no tools from this server",
                label, exc,
            )

        caps = server.capabilities
        # Resources.
        if caps and getattr(caps, "resources", None) is not None:
            try:
                resources_result = await server.session.list_resources()
                server.resources = list(resources_result.resources)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Upstream '%s': list_resources failed (%s) — skipping resources",
                    label, exc,
                )

        # Prompts.
        if caps and getattr(caps, "prompts", None) is not None:
            try:
                prompts_result = await server.session.list_prompts()
                server.prompts = list(prompts_result.prompts)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Upstream '%s': list_prompts failed (%s) — skipping prompts",
                    label, exc,
                )

    def _check_collisions(self) -> None:
        """Verify no two upstreams expose the same tool / resource / prompt.

        Per Block 3a: fail loud at startup. The user fixes their config
        before anything runs.
        """
        self._tool_routes = self._build_route_table(
            "tool",
            ((srv.label, [t.name for t in srv.tools]) for srv in self._servers.values()),
            ToolCollisionError,
        )
        self._resource_routes = self._build_route_table(
            "resource",
            ((srv.label, [str(r.uri) for r in srv.resources]) for srv in self._servers.values()),
            ResourceCollisionError,
        )
        self._prompt_routes = self._build_route_table(
            "prompt",
            ((srv.label, [p.name for p in srv.prompts]) for srv in self._servers.values()),
            PromptCollisionError,
        )

    @staticmethod
    def _build_route_table(
        kind: str,
        per_server: Iterable[tuple[str, list[str]]],
        error_cls: type[Exception],
    ) -> dict[str, str]:
        """Build a name → label table, raising on collisions with a useful message."""
        seen: dict[str, str] = {}
        for label, names in per_server:
            for name in names:
                if name in seen:
                    raise error_cls(
                        f"{kind.capitalize()} name collision: '{name}' is exposed "
                        f"by both upstream '{seen[name]}' and upstream '{label}'. "
                        "Rename one or remove the duplicate dependency in your hiitl-mcp config."
                    )
                seen[name] = label
        return seen
