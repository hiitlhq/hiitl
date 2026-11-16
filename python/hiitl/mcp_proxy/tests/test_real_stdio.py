"""The proxy over real stdio, against real multi-tool upstreams in both languages (TICKET-099; TICKET-134).

The `hiitl-mcp-proxy` CLI runs as a subprocess and is driven by the MCP SDK's stdio client. It spawns two real
upstreams over stdio: the official TypeScript filesystem server (`npx -y @modelcontextprotocol/server-filesystem`)
and the official Python git server (`python -m mcp_server_git`). The cell proves:
- the initialize handshake succeeds;
- list_tools returns both servers' tools;
- one call to each round-trips with the upstream's own answer.

The proxy runs in its zero-config local mode, so every call is observed and forwarded. ALLOW / BLOCK / PAUSE under a
synced policy is verified against a running hosted service, outside this suite.

Gated: HIITL_RUN_MCP_INTEGRATION=1, with `npx` on the PATH and `mcp_server_git` importable (the in-memory suite
stays the default). Install the git server under the proxy's own `mcp` range (`pip install "mcp>=1.29.0,<2.0.0"
mcp-server-git`): its newer releases require `mcp` 2.x, which renamed `McpError`, and an unconstrained install
upgrades the proxy's dependency out of its range.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(os.environ.get("HIITL_RUN_MCP_INTEGRATION") != "1",
                       reason="real stdio upstreams: set HIITL_RUN_MCP_INTEGRATION=1"),
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is needed for the TypeScript upstream"),
]

FS_SERVER = "@modelcontextprotocol/server-filesystem"


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "first"], check=True, env=env)
    return path


@pytest.mark.asyncio
async def test_the_proxy_cli_governs_real_ts_and_python_upstreams_over_stdio(tmp_path):
    pytest.importorskip("mcp_server_git")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    files = tmp_path / "files"
    files.mkdir()
    (files / "note.txt").write_text("governed\n")
    repo = _git_repo(tmp_path / "repo")
    cfg = tmp_path / "proxy.yaml"
    cfg.write_text(
        "servers:\n"
        f"  fs:\n    command: npx\n    args: [\"-y\", \"{FS_SERVER}\", \"{files}\"]\n"
        f"  git:\n    command: \"{sys.executable}\"\n    args: [\"-m\", \"mcp_server_git\", \"--repository\", \"{repo}\"]\n"
        "agent_id: real-stdio-test\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("HIITL_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "hiitl.mcp_proxy.cli", "--config", str(cfg)],
                                   env=env, cwd=str(tmp_path))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert {"read_text_file", "write_file", "list_allowed_directories"} <= names, names   # the TS server's
            assert {"git_status", "git_log", "git_commit"} <= names, names                          # the Python server's
            read = await session.call_tool("read_text_file", {"path": str(files / "note.txt")})
            assert not read.isError and "governed" in read.content[0].text
            status = await session.call_tool("git_status", {"repo_path": str(repo)})
            assert not status.isError and "branch" in status.content[0].text.lower()
