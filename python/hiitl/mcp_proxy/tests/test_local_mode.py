"""The MCP gateway in local mode: a policy file and route files, no API key, and the gateway enforces (HTL-18).
Design: TEST_DESIGN_local_mode.md (G1-G10).

Every cell builds the real SDK client the way `run_proxy` does: `load_config` → `hiitl_kwargs` → `HIITL`. The
upstream is an in-memory MCP server. The route is a real HTTPS endpoint on 127.0.0.1, served from its own thread: the
SDK asks it synchronously, so a server on the gateway's event loop could never answer. It serves a self-signed
certificate the test trusts with SSL_CERT_FILE, as routes.md tells a deployment to (an endpoint is an https URL,
loopback included; HTL-29, row 140).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import ipaddress
import sqlite3
import ssl
import threading
import time
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from hiitl.core.canonical import envelope_verifies
from hiitl.core.redaction import value_hash
from hiitl.sdk.hash_key import key_path
from hiitl.mcp_proxy.config import API_KEY_VAR, ProxyConfig, load_config
from hiitl.mcp_proxy.proxy import build_proxy_server, hiitl_kwargs
from hiitl.mcp_proxy.tests.test_proxy_integration import _manager_with_fake_upstreams
from hiitl.sdk.client import HIITL

POLICY = """
version: "v1.0.0"
description: "The agent never deletes a repository"
scope:
  org_id: org_devlocal0000000000
  environment: dev
name: gateway_local
rules:
  - name: no-repo-deletes
    priority: 900
    conditions: {field: action, operator: equals, value: delete_repo}
    decision: BLOCK
    reason_code: DESTRUCTIVE_ACTION
    description: The agent never deletes a repository
  - name: high-value-asks-finance
    priority: 500
    conditions:
      all_of:
        - {field: action, operator: equals, value: pay}
        - {field: parameters.amount, operator: greater_than, value: 500}
    decision: ROUTE
    reason_code: HIGH_VALUE_PAYMENT
    route: finance-review
    description: A payment over 500 asks finance first
  - name: finance-denied
    priority: 800
    conditions: {field: external.finance-review.decision, operator: in, value: [deny]}
    decision: BLOCK
    reason_code: FINANCE_DENIED
    description: A payment finance denies does not run
  - name: allow-otherwise
    priority: 1
    conditions: {field: action, operator: exists, value: true}
    decision: ALLOW
    reason_code: ALLOWED
    description: Everything else
"""


def _route(endpoint: str) -> dict:
    return {
        "name": "finance-review", "version": "v1.0.0", "description": "Finance answers for a high-value payment",
        "direction": "bidirectional", "timing": "sync", "purpose": ["review"], "endpoint": endpoint, "protocol": "http",
        "context": {"fields": [{"field_path": "parameters.amount"}], "include_policy_ref": True},
        "response_schema": {"decision_options": ["approve", "deny"], "required_fields": ["decision"],
                            "optional_fields": ["reason"]},
        "sla": {"timeout": "5s", "timeout_action": "fail_closed"},
    }


def _self_signed(directory: Path) -> tuple[Path, Path]:
    """A certificate for 127.0.0.1 and its key, the way a deployment serves https on its own machine."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path_ = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path_.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    return cert_path, key_path_


class _RouteEndpoint:
    """A reviewer endpoint of the deployment's own: records each request and answers with `answer(body)`."""

    def __init__(self, cert: Path, key: Path) -> None:
        self.seen: list[dict] = []
        self.answer = lambda body: (200, {"decision": "approve"})
        self.answered_at: list[float] = []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                endpoint.seen.append(body)
                status, out = endpoint.answer(body)
                raw = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                endpoint.answered_at.append(time.monotonic())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}/finance"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def route(tmp_path, monkeypatch):
    cert, key = _self_signed(tmp_path / "tls")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    r = _RouteEndpoint(cert, key)
    yield r
    r.close()


@pytest.fixture
def deployment(tmp_path, route, monkeypatch):
    """A local-mode deployment's files: the policy, the routes directory, the gateway's YAML (no api_key), and no
    HIITL_API_KEY in the gateway's environment (the gateway would read it: G9)."""
    monkeypatch.delenv(API_KEY_VAR, raising=False)
    (tmp_path / "policy.yaml").write_text(POLICY)
    (tmp_path / "routes").mkdir()
    (tmp_path / "routes" / "finance-review.json").write_text(json.dumps(_route(route.url)))
    cfg = tmp_path / "hiitl-mcp.yaml"
    cfg.write_text(
        "agent_id: gateway-test\n"
        f"policy_path: {tmp_path / 'policy.yaml'}\n"
        f"routes_path: {tmp_path / 'routes'}\n"
        f"audit_db_path: {tmp_path / 'audit.db'}\n"
        "servers:\n  tools:\n    command: never-spawned-in-tests\n", encoding="utf-8")
    return cfg


_CALLED: list[tuple[str, dict]] = []
_TOOLS = [{"name": n, "handler": (lambda name: lambda args: _CALLED.append((name, args)) or f"{name} ran")(n)}
          for n in ("delete_repo", "pay", "read_file")]


async def _gateway(stack: AsyncExitStack, cfg_path: Path) -> ClientSession:
    """The gateway as `run_proxy` builds it, over an in-memory upstream; returns the MCP client's session."""
    _CALLED.clear()
    config = load_config(cfg_path)
    client = HIITL(**hiitl_kwargs(config))
    mgr = await _manager_with_fake_upstreams(stack, {"tools": _TOOLS})
    session = await stack.enter_async_context(
        create_connected_server_and_client_session(build_proxy_server(config, mgr, client)))
    await session.initialize()
    return session


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def _records(db: Path) -> list[dict]:
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY rowid")]


@pytest.mark.asyncio
async def test_g1_a_block_rule_in_the_policy_file_binds_at_the_gateway(deployment):
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, deployment)
        result = await session.call_tool("delete_repo", {"repo": "hiitl"})
    assert result.isError, "no api_key, a policy file: the gateway enforces"
    assert "blocked by hiitl policy" in _text(result).lower() and "DESTRUCTIVE_ACTION" in _text(result)
    assert _CALLED == [], "the upstream is never called"
    db = deployment.parent / "audit.db"
    assert db.is_file(), "the record is where the config says"
    (row,) = _records(db)
    assert (row["action"], row["decision_type"]) == ("delete_repo", "BLOCK")


@pytest.mark.asyncio
async def test_g2_a_route_rule_asks_its_route_and_the_answer_decides(deployment, route):
    route.answer = lambda body: (200, {"decision": "deny", "reason": "over budget"})
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, deployment)
        denied = await session.call_tool("pay", {"amount": 900, "to": "acme"})
        assert denied.isError and "FINANCE_DENIED" in _text(denied)
        assert _CALLED == [], "a denied payment never reaches the upstream"
        assert route.seen == [{"route": "finance-review", "rule": "high-value-asks-finance", "action": "pay",
                               "fields": {"parameters.amount": 900}}], "the route is asked its declared fields"
        route.answer = lambda body: (200, {"decision": "approve"})
        approved = await session.call_tool("pay", {"amount": 900, "to": "acme"})
        small = await session.call_tool("pay", {"amount": 20, "to": "acme"})
    assert not approved.isError and _CALLED[0] == ("pay", {"amount": 900, "to": "acme"}), "the approval forwards"
    assert not small.isError and len(route.seen) == 2, "a payment the ROUTE rule does not match asks nobody"
    rows = _records(deployment.parent / "audit.db")
    assert [r["decision_type"] for r in rows] == ["BLOCK", "ALLOW", "ALLOW"]
    asked = json.loads(rows[0]["decision"])
    assert [(r["route"], r["outcome"]) for r in asked["routes"]] == [("finance-review", "answered")]
    assert asked["enrichment"] == {"finance-review": {"decision": "deny", "reason": "over budget"}}


@pytest.mark.asyncio
async def test_g3_a_route_that_does_not_answer_fails_closed_at_the_gateway(deployment, route):
    route.answer = lambda body: (503, {"error": "down"})
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, deployment)
        result = await session.call_tool("pay", {"amount": 900})
    assert result.isError and "ROUTE decision" in _text(result) and "ROUTE_UNANSWERED" in _text(result)
    assert _CALLED == [] and len(route.seen) == 1


# Row 139: the gateway always tells the SDK which arguments its record holds as given; none, unless the config says
HASHED = {"recorded_parameters": {}}


def test_g4_the_gateway_passes_the_sdks_own_configuration(deployment):
    d = deployment.parent
    paths = {"policy_path": str(d / "policy.yaml"), "routes_path": str(d / "routes"),
             "audit_db_path": str(d / "audit.db")}
    base = {"agent_id": "gateway-test", "environment": "dev", **HASHED}
    assert hiitl_kwargs(load_config(deployment)) == {**base, **paths, "mode": "RESPECT_POLICY"}, \
        "a policy file and no api_key: its rules bind"
    observed = ProxyConfig.model_validate({**load_config(deployment).model_dump(), "mode": "OBSERVE_ALL"})
    assert hiitl_kwargs(observed)["mode"] == "OBSERVE_ALL", "a mode the config sets wins"
    zero = ProxyConfig.model_validate({"agent_id": "gateway-test", "servers": {"t": {"command": "x"}}})
    assert hiitl_kwargs(zero) == base, "no policy file: the SDK's zero-config default, nothing restated"


@pytest.mark.asyncio
async def test_g5_the_signature_key_comes_from_the_environment_never_the_file(deployment, monkeypatch):
    monkeypatch.setenv("HIITL_SIGNATURE_KEY", "k3y-from-the-environment")
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, deployment)
        await session.call_tool("read_file", {"path": "README.md"})
    env = json.loads(_records(deployment.parent / "audit.db")[0]["envelope"])
    # The signature is over the call as made, through the one signed form (row 127); the record holds each
    # argument hashed under the store's key (rows 139, 163), so it verifies with the argument put back
    key = key_path(deployment.parent / "audit.db").read_bytes()
    assert env["signature"] != "0" * 64 and env["parameters"] == {"path": value_hash("README.md", key)}
    assert not envelope_verifies("k3y-from-the-environment", env)
    assert envelope_verifies("k3y-from-the-environment", {**env, "parameters": {"path": "README.md"}})
    with pytest.raises(Exception, match="signature_key"):
        ProxyConfig.model_validate({"signature_key": "in-the-file", "servers": {"t": {"command": "x"}}})


def test_g6_hybrid_is_unchanged_when_no_local_field_is_set():
    cfg = ProxyConfig.model_validate({"api_key": "sk_x", "server_url": "https://127.0.0.1:8765",
                                      "servers": {"t": {"command": "x"}}})
    assert hiitl_kwargs(cfg) == {"agent_id": "mcp-proxy", "environment": "dev", "api_key": "sk_x",
                                 "mode": "RESPECT_POLICY", "server_url": "https://127.0.0.1:8765",
                                 **HASHED}


def test_g7_a_mode_that_is_not_one_of_the_two_is_a_config_error():
    with pytest.raises(Exception) as exc:
        ProxyConfig.model_validate({"mode": "observe", "servers": {"t": {"command": "x"}}})
    assert "OBSERVE_ALL" in str(exc.value) and "RESPECT_POLICY" in str(exc.value)


@pytest.mark.asyncio
async def test_g8_a_routes_wait_does_not_stall_the_gateway(deployment, route):
    """Row 126, ruled 2026-11-04: evaluate runs off the event loop, so a route's wait holds its own call only."""
    def slow(body):
        time.sleep(1.5)
        return 200, {"decision": "approve"}
    route.answer = slow
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, deployment)
        paying = asyncio.create_task(session.call_tool("pay", {"amount": 900}))
        await asyncio.sleep(0.2)
        await session.list_tools()
        listed_at = time.monotonic()
        paid = await paying
    assert listed_at < route.answered_at[0], "list_tools answers while the route is still deciding"
    assert not paid.isError and _CALLED == [("pay", {"amount": 900})], "and the call the route approved still runs"


def test_g9_the_gateway_reads_hiitl_api_key_when_the_file_sets_none(tmp_path):
    """Row 128, ruled 2026-11-04: by the same "by environment" the signature key takes. One read, at the loader, so
    the SDK client and the review flow hold the same key."""
    keyless, keyed = tmp_path / "keyless.yaml", tmp_path / "keyed.yaml"
    keyless.write_text("server_url: https://127.0.0.1:8765\nservers:\n  t:\n    command: x\n", encoding="utf-8")
    keyed.write_text("api_key: sk_from_the_file\nservers:\n  t:\n    command: x\n", encoding="utf-8")
    env = {"HIITL_API_KEY": "sk_from_the_environment"}
    from_env = load_config(keyless, environ=env)
    assert from_env.api_key == "sk_from_the_environment", "the review flow reads this field: the same key"
    assert hiitl_kwargs(from_env) == {
        "agent_id": "mcp-proxy", "environment": "dev", "api_key": "sk_from_the_environment",
        "server_url": "https://127.0.0.1:8765", "mode": "RESPECT_POLICY", **HASHED}, "the environment's key: hybrid"
    assert load_config(keyed, environ=env).api_key == "sk_from_the_file", "a key the file sets wins"
    for unset in ({}, {"HIITL_API_KEY": ""}):
        local = load_config(keyless, environ=unset)
        assert local.api_key is None and "api_key" not in hiitl_kwargs(local), "neither: local"


def _gateway_configs_the_texts_carry() -> list[tuple[str, str]]:
    """Every gateway config a text in the repository tells someone to write: a YAML file, or a fenced YAML block,
    whose top-level `servers` is a map of upstreams (each a `command` or a `url`), read by what it is."""
    root = Path(__file__).resolve().parents[4]
    fence = re.compile(r"^```ya?ml[^\n]*\n(.*?)^```", re.S | re.M)
    found = []
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_")) and d not in ("node_modules", "dist")]
        for name in files:
            if not name.endswith((".md", ".mdx", ".yaml", ".yml")):
                continue
            path = Path(here) / name
            text = path.read_text(encoding="utf-8", errors="replace")
            for block in ([text] if name.endswith((".yaml", ".yml")) else fence.findall(text)):
                try:
                    doc = yaml.safe_load(block)
                except yaml.YAMLError:
                    continue
                servers = doc.get("servers") if isinstance(doc, dict) else None
                if isinstance(servers, dict) and servers and all(
                        isinstance(v, dict) and ("command" in v or "url" in v) for v in servers.values()):
                    found.append((str(path.relative_to(root)), block))
    return found


def _values(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _values(v)
    else:
        yield node


def test_g10_every_gateway_config_a_text_carries_loads_to_the_mode_it_names(tmp_path):
    """Row 128: the loader reads values as written, so a `${VAR}` in a text's config would reach the gateway as that
    string (an API key of `${HIITL_API_KEY}` starts hybrid mode with a fake key). Every config the texts carry loads,
    carries no such literal, and runs local without HIITL_API_KEY and hybrid with it."""
    configs = _gateway_configs_the_texts_carry()
    here = {"python/hiitl/mcp_proxy/README.md", "python/hiitl/mcp_proxy/recipes/claude_desktop.md",
            "python/hiitl/mcp_proxy/recipes/cursor.md"}
    assert here <= {path for path, _ in configs}, "the package's own texts are read: the walk found them"
    for i, (path, block) in enumerate(configs):
        literal = [v for v in _values(yaml.safe_load(block)) if isinstance(v, str) and "${" in v]
        assert not literal, f"{path}: {literal} would load as written"
        cfg = tmp_path / f"{i}.yaml"
        cfg.write_text(block, encoding="utf-8")
        env = {"HIITL_API_KEY": "sk_from_the_environment"}
        assert "api_key" not in hiitl_kwargs(load_config(cfg, environ={})), f"{path}: local without it"
        assert hiitl_kwargs(load_config(cfg, environ=env))["api_key"] == "sk_from_the_environment", \
            f"{path}: hybrid with it"
