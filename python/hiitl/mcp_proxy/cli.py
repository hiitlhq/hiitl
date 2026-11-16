"""hiitl-mcp-proxy CLI entry point.

Usage:
    hiitl-mcp-proxy --config path/to/hiitl-mcp.yaml

The CLI is intentionally tiny: parse args, load config, run the proxy.
Logging goes to stderr (stdout is reserved for MCP protocol traffic).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from hiitl.mcp_proxy.config import GatewaySettings, ProxyConfig, load_config
from hiitl.mcp_proxy.proxy import run_proxy
from hiitl.settings import read_variables, unread_variables

# The gateway's family and the names its settings read: an unread name of the family, set, stops it (row 222)
FAMILIES = (GatewaySettings.model_config["env_prefix"],)
READ_VARIABLES = read_variables(GatewaySettings)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hiitl-mcp-proxy",
        description=(
            "Drop-in MCP proxy that governs every tool call via hiitl. "
            "Spawns upstream MCP servers as child processes and exposes "
            "their tools to Claude Desktop (or any MCP client) under "
            "their original names."
        ),
    )
    p.add_argument(
        "--config",
        type=Path,
        required=False,
        help=(
            "Path to a hiitl-mcp.yaml config. Defaults to "
            "$HIITL_MCP_CONFIG, or ./hiitl-mcp.yaml in the current dir."
        ),
    )
    p.add_argument(
        "--log-level",
        help=(
            "Log level for proxy diagnostics (stderr only): a level name "
            "Python's logging defines. Defaults to $HIITL_MCP_LOG_LEVEL, "
            "or INFO."
        ),
    )
    return p


def _configure_logging(level_name: str) -> None:
    """Logs go to stderr only. stdout is the MCP protocol channel."""
    logging.basicConfig(
        level=level_name,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log = logging.getLogger("hiitl-mcp-proxy")

    # An unread name of the gateway's family is refused, never ignored (row 222)
    unread = unread_variables(os.environ, FAMILIES, READ_VARIABLES)
    if unread:
        log.error("%s\n\nAn HIITL_MCP_* variable no setting reads stops the proxy (the README, \"CLI\").", unread)
        return 2
    # Each setting is its argument, else its variable, else its default
    given = {name: getattr(args, name) for name in GatewaySettings.model_fields if getattr(args, name) is not None}
    try:
        settings = GatewaySettings(**given)
    except ValidationError as exc:
        log.error("%s", "\n".join(error["msg"] for error in exc.errors()))
        return 2
    _configure_logging(settings.log_level)

    config_path = settings.config or Path.cwd() / "hiitl-mcp.yaml"
    if not config_path.is_file():
        log.error(
            "Config file not found at %s. Pass --config or set HIITL_MCP_CONFIG.",
            config_path,
        )
        return 2

    try:
        config: ProxyConfig = load_config(config_path)
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to load config %s: %s", config_path, exc)
        return 2

    if not config.servers:
        log.error(
            "Config at %s declares no upstream servers. Add at least one "
            "entry under `servers:` before starting the proxy.",
            config_path,
        )
        return 2

    log.info(
        "Starting hiitl-mcp-proxy: %d upstream server(s) configured "
        "(env=%s, agent_id=%s, api_key_set=%s, policy=%s, routes=%s)",
        len(config.servers),
        config.environment,
        config.agent_id,
        config.api_key is not None,
        config.policy_path,
        config.routes_path,
    )

    try:
        asyncio.run(run_proxy(config))
    except KeyboardInterrupt:
        log.info("Interrupted; shutting down.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.exception("Proxy crashed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
