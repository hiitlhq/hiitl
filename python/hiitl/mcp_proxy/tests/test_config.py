"""Config loader and schema tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiitl.mcp_proxy.config import (
    ProxyConfig,
    SseServerConfig,
    StdioServerConfig,
    load_config,
)


def test_load_minimal_stdio_config(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
servers:
  email:
    command: npx
    args: [email-mcp-server]
""".strip()
    )
    cfg = load_config(path)
    assert isinstance(cfg, ProxyConfig)
    assert cfg.api_key is None  # Optional; falls back to env / local mode.
    assert cfg.environment == "dev"
    assert cfg.agent_id == "mcp-proxy"
    assert len(cfg.servers) == 1
    srv = cfg.servers["email"]
    assert isinstance(srv, StdioServerConfig)
    assert srv.command == "npx"
    assert srv.args == ["email-mcp-server"]


def test_load_sse_config(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
api_key: sk-hiitl-test
servers:
  remote:
    url: https://mcp.example.com/sse
    headers:
      Authorization: Bearer test
""".strip()
    )
    cfg = load_config(path)
    srv = cfg.servers["remote"]
    assert isinstance(srv, SseServerConfig)
    assert srv.url == "https://mcp.example.com/sse"
    assert srv.headers == {"Authorization": "Bearer test"}


def test_mixed_transports_in_one_config(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
servers:
  local:
    command: python
    args: [-m, my_local_server]
  remote:
    url: https://mcp.example.com/sse
""".strip()
    )
    cfg = load_config(path)
    assert isinstance(cfg.servers["local"], StdioServerConfig)
    assert isinstance(cfg.servers["remote"], SseServerConfig)


def test_command_and_url_mutually_exclusive(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
servers:
  broken:
    command: npx
    args: [x]
    url: https://example.com/sse
""".strip()
    )
    with pytest.raises(Exception) as exc:
        load_config(path)
    assert "command" in str(exc.value).lower()
    assert "url" in str(exc.value).lower()


def test_neither_command_nor_url_is_error(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
servers:
  broken:
    args: [oops]
""".strip()
    )
    with pytest.raises(Exception) as exc:
        load_config(path)
    assert "command" in str(exc.value) or "url" in str(exc.value)


def test_bad_environment_rejected(tmp_path: Path):
    path = tmp_path / "hiitl-mcp.yaml"
    path.write_text(
        """
environment: production
servers:
  x:
    command: a
""".strip()
    )
    with pytest.raises(Exception) as exc:
        load_config(path)
    assert "environment" in str(exc.value).lower()


def test_missing_file_raises_useful_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_the_proxy_syncs_with_the_backend_its_config_names():
    """T-134: with an api_key, the configured server_url is the SDK's sync target too (it was the review API's only)."""
    from hiitl.mcp_proxy.config import ProxyConfig
    from hiitl.mcp_proxy.proxy import hiitl_kwargs
    base = {"servers": {"fs": {"command": "npx", "args": ["x"]}}}
    local = hiitl_kwargs(ProxyConfig.model_validate(base))
    assert "server_url" not in local and "mode" not in local, "zero-config local mode: the SDK's default"
    from hiitl.sdk.client import HIITL
    HIITL(**local, audit_db_path=":memory:")                 # it starts (T-134: RESPECT_POLICY without a policy did not)
    k = hiitl_kwargs(ProxyConfig.model_validate({**base, "api_key": "sk_x", "server_url": "https://127.0.0.1:8765"}))
    assert (k.get("api_key"), k.get("server_url"), k.get("mode")) == ("sk_x", "https://127.0.0.1:8765", "RESPECT_POLICY")
