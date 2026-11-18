"""Row 157 (HTL-22): an upstream's environment by reference.

Ruled by Trevor 2026-11-05, on HTL-18: "an upstream's environment may name a gateway environment variable by reference,
in a field of its own (so a literal is never mistaken for a reference), resolved when the gateway starts; an unset name
stops the start and names the variable", by routes.md's `secret_ref`: "Never stored in plaintext … References a secret
manager key or environment variable". The field is `secret_refs`, in routes' form `env:<NAME>`. The exit cell spawns a
real stdio upstream, a Python MCP server, through the real `UpstreamManager`. This is the row's test design.
"""

from __future__ import annotations

import sys
import textwrap

import pytest
from pydantic import ValidationError

from hiitl.mcp_proxy.config import ProxyConfig, StdioServerConfig, load_config
from hiitl.mcp_proxy.tests.test_local_mode import _gateway_configs_the_texts_carry
from hiitl.mcp_proxy.upstream import UpstreamConnectError, UpstreamManager

TOKEN = "token-from-the-gateway-environment-7f3a"     # the value the gateway's environment holds

# An upstream that answers with a variable of its own environment, and marks that it was started
UPSTREAM = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from mcp.server.fastmcp import FastMCP

    Path(sys.argv[1]).touch()
    server = FastMCP("env-reader")

    @server.tool()
    def read_env(name: str) -> str:
        return os.environ.get(name, "<unset>")

    server.run()
""")


def _config(tmp_path, **upstream):
    script = tmp_path / "env_reader.py"
    script.write_text(UPSTREAM, encoding="utf-8")
    started = tmp_path / "started"
    cfg = ProxyConfig(servers={"tokens": StdioServerConfig(command=sys.executable, args=[str(script), str(started)],
                                                           **upstream)})
    return cfg, started


@pytest.mark.asyncio
async def test_a_reference_reaches_the_upstream_as_its_value(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_TOKEN", TOKEN)
    cfg, started = _config(tmp_path, env={"LITERAL": "env:GATEWAY_TOKEN"},
                           secret_refs={"UPSTREAM_TOKEN": "env:GATEWAY_TOKEN"})
    async with UpstreamManager(cfg) as manager:
        await manager.start()
        session = manager.session_for_tool("read_env")

        async def read(name):
            result = await session.call_tool("read_env", {"name": name})
            assert not result.isError, result
            return result.content[0].text

        assert await read("UPSTREAM_TOKEN") == TOKEN, "the reference reaches the upstream as its gateway variable"
        assert await read("LITERAL") == "env:GATEWAY_TOKEN", "a value in env is read as written, never as a reference"
        assert await read("GATEWAY_TOKEN") == "<unset>", "the upstream gets the value it names, not the gateway's environment"
    assert started.exists()


@pytest.mark.asyncio
async def test_an_unset_reference_fails_the_start_naming_it(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    cfg, started = _config(tmp_path, secret_refs={"UPSTREAM_TOKEN": "env:GATEWAY_TOKEN"})
    with pytest.raises(UpstreamConnectError) as e:
        async with UpstreamManager(cfg) as manager:
            await manager.start()
    message = str(e.value)
    assert all(name in message for name in ("GATEWAY_TOKEN", "UPSTREAM_TOKEN", "'tokens'")), message
    assert not started.exists(), "an upstream whose environment cannot be resolved is never spawned"


@pytest.mark.parametrize("ref", ["vault:hiitl/github/token", "GATEWAY_TOKEN", "env:", "${GATEWAY_TOKEN}"])
def test_the_file_refuses_a_reference_the_gateway_cannot_resolve(ref):
    with pytest.raises(ValidationError) as e:
        StdioServerConfig(command="npx", secret_refs={"UPSTREAM_TOKEN": ref})
    assert "UPSTREAM_TOKEN" in str(e.value) and ref in str(e.value), "the message names the entry"

    with pytest.raises(ValidationError) as e:
        StdioServerConfig(command="npx", env={"UPSTREAM_TOKEN": "x"}, secret_refs={"UPSTREAM_TOKEN": "env:A"})
    assert "UPSTREAM_TOKEN" in str(e.value), "one variable has one source"


def test_the_texts_take_an_upstreams_variables_by_reference(tmp_path):
    """"The recipes drop the literal values": every gateway config a text in the repository carries (row 128's walk,
    read by what it is) loads with the gateway's own reader, and none writes an upstream's variables into `env`."""
    configs = _gateway_configs_the_texts_carry()
    by_reference = []
    for i, (path, block) in enumerate(configs):
        cfg = tmp_path / f"{i}.yaml"
        cfg.write_text(block, encoding="utf-8")
        for label, upstream in load_config(cfg, environ={}).servers.items():
            assert not getattr(upstream, "env", None), (
                f"{path}: upstream '{label}' writes its variables into the file; a text shows them by reference, "
                f"in secret_refs")
            by_reference += list(getattr(upstream, "secret_refs", None) or ())
    assert by_reference, "the texts show the reference: the walk found one"
