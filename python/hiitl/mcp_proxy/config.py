"""hiitl-mcp-proxy config — YAML schema and loader.

A config file declares the hiitl API key (optional — defaults to env
HIITL_API_KEY / local-mode when absent) and a list of upstream MCP
servers to proxy. Each upstream is either a `command` + `args` (stdio
transport — proxy spawns the process) or a `url` (SSE transport — proxy
connects to a running server).

Example config:

    api_key: "sk-hiitl-..."
    timeout_seconds: 30
    servers:
      email:
        command: npx
        args: ["email-mcp-server"]
      database:
        command: npx
        args: ["postgres-mcp-server"]
      remote-github:
        url: "https://mcp.example.com/github/sse"
        # Optional headers for SSE auth.
        headers:
          Authorization: "Bearer ghp_xxx"

The `servers` map's keys are human-friendly labels used in logs and
error messages. They are NOT used to namespace tool names — per Block 3a
design, tool names are re-exposed verbatim and a collision across
servers is a startup error (see `upstream.py`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hiitl.core.routing import SECRET_REF_SCHEME
from hiitl.core.transport import https_refusal
from hiitl.sdk.config import LocalModeConfig
from hiitl.settings import variable

# The SDK's own name for its API key setting: its environment prefix and the field. The gateway reads it when the
# file sets no key (HTL-18, ruled 2026-11-04), as it reads the signature key (`proxy.py`).
API_KEY_VAR = f"{LocalModeConfig.model_config['env_prefix']}API_KEY"

# routes.md's `secret_ref` names an environment variable as `env:<NAME>` (`hiitl.core.routing`'s SECRET_REF_SCHEME).
# It is the one form the gateway resolves: a secret manager's reference has no reader here.


def level_names() -> dict[str, int]:
    """The level names Python's `logging` defines, read from its own registry (`getLevelNamesMapping`, Python 3.11;
    on 3.10 the record that function copies)."""
    mapping = getattr(logging, "getLevelNamesMapping", None)
    return mapping() if mapping else dict(logging._nameToLevel)


class GatewaySettings(BaseSettings):
    """The gateway's own settings (its README, "CLI"), each read from its `HIITL_MCP_*` variable and outranked by its
    argument. These fields are the one list of the names the gateway reads: any other `HIITL_MCP_*` variable, set,
    stops the gateway at start-up, naming the names read (`hiitl.settings.unread_variables`; row 222). A variable set
    to the empty string carries no value."""

    config: Optional[Path] = Field(default=None, description="The config file (--config); ./hiitl-mcp.yaml when unset")
    log_level: str = Field(default="INFO", description="A level name Python's logging defines (--log-level)")

    model_config = SettingsConfigDict(env_prefix="HIITL_MCP_", case_sensitive=False, env_ignore_empty=True)

    @field_validator("log_level")
    @classmethod
    def _a_defined_level(cls, v: str) -> str:
        names = level_names()
        if v.upper() not in names:
            raise ValueError(f"log_level ({variable(cls, 'log_level')}, --log-level) is a level name Python's logging "
                             f"defines: {', '.join(sorted(names, key=names.get))}; got {v!r}")
        return v.upper()


def _check_references(refs: Mapping[str, str] | None, written: Mapping[str, str] | None, field: str, noun: str, *,
                      fold: bool) -> None:
    """The one check of an upstream's references, either transport's (HTL-23 row 214): each is `env:<NAME>`, and a
    name has one source, a value written in `field` or a reference in `secret_refs`. `fold` compares names
    case-insensitively, as an HTTP header's name is (RFC 9110 §5.1); an environment variable's name is not."""
    for name, ref in (refs or {}).items():
        scheme, colon, var = ref.partition(":")
        if scheme != SECRET_REF_SCHEME or not colon or not var:
            raise ValueError(
                f"secret_refs[{name!r}] is {ref!r}. The gateway resolves a reference to a variable of its own "
                f"environment, written '{SECRET_REF_SCHEME}:<NAME>' as a route's secret_ref is (routes.md), "
                f"e.g. {name}: \"{SECRET_REF_SCHEME}:{name}\".")
    same = str.casefold if fold else str
    referenced = {same(name) for name in refs or {}}
    both = sorted(name for name in written or {} if same(name) in referenced)
    if both:
        raise ValueError(f"{', '.join(both)} is named in both {field} and secret_refs. An upstream {noun} has one "
                         f"source: a value written in {field}, or a reference in secret_refs.")


def _resolved(label: str, refs: Mapping[str, str] | None, environ: Mapping[str, str]) -> dict[str, str]:
    """Each reference's value, read from the gateway's environment. Raises ValueError naming every reference whose
    variable is unset."""
    resolved, unset = {}, []
    for name, ref in (refs or {}).items():
        var = ref.partition(":")[2]
        if var in environ:
            resolved[name] = environ[var]
        else:
            unset.append(f"{var} (for {name})")
    if unset:
        raise ValueError(
            f"Upstream '{label}' names {', '.join(unset)} in secret_refs, and the gateway's environment does not "
            f"set it. Set it in the gateway's environment (the `env` of its entry in the MCP client's config), "
            f"or drop the reference.")
    return resolved


class StdioServerConfig(BaseModel):
    """Stdio-transport upstream — proxy spawns the process and talks over its
    stdin/stdout. The MCP standard transport for local servers.
    """

    command: str = Field(..., min_length=1)
    args: list[str] = Field(default_factory=list)
    # The upstream's environment, read as written (plus the MCP client library's PATH, HOME and the like).
    env: dict[str, str] | None = None
    # Upstream variables whose values are the gateway's own environment variables, by reference: {upstream name:
    # "env:<GATEWAY_NAME>"}, routes.md's `secret_ref` ("Never stored in plaintext … References a secret manager key or
    # environment variable"). Resolved when the gateway starts; an unset name fails the start (HTL-22 row 157, ruled
    # 2026-11-05). A field of its own, so a value in `env` is never read as a reference.
    secret_refs: dict[str, str] | None = None
    cwd: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _references_the_gateway_resolves(self) -> "StdioServerConfig":
        _check_references(self.secret_refs, self.env, "env", "variable", fold=False)
        return self

    def referenced_env(self, label: str, environ: Mapping[str, str]) -> dict[str, str]:
        """Each `secret_refs` entry's value, read from the gateway's environment. Raises ValueError naming every
        reference whose variable is unset."""
        return _resolved(label, self.secret_refs, environ)


class SseServerConfig(BaseModel):
    """SSE-transport upstream — proxy connects to an HTTP endpoint. The MCP
    standard transport for remote servers.
    """

    # An https URL naming a host: it carries the upstream's headers and every tool call's arguments (HTL-29 row 238,
    # ruled 2026-11-09: "https, refused at config load naming it", by "TLS everywhere. No exceptions.").
    url: str = Field(..., min_length=1)
    # Headers sent as written.
    headers: dict[str, str] | None = None
    # Headers whose values are the gateway's own environment variables, by reference: {header name:
    # "env:<GATEWAY_NAME>"}, as stdio's `secret_refs` (HTL-23 row 214, ruled 2026-11-06: "`headers` take `secret_refs`
    # in the same `env:<NAME>` form"). Resolved when the gateway starts; an unset name fails the start.
    secret_refs: dict[str, str] | None = None
    # Optional connection-establishment timeout (seconds). Distinct from
    # per-call timeout, which lives at the proxy level.
    connect_timeout_seconds: float = Field(default=10.0, gt=0)

    model_config = ConfigDict(extra="forbid")

    @field_validator("url")
    @classmethod
    def _sent_over_https(cls, v: str) -> str:
        refusal = https_refusal(v, "url")
        if refusal:
            raise ValueError(refusal)
        return v

    @model_validator(mode="after")
    def _references_the_gateway_resolves(self) -> "SseServerConfig":
        _check_references(self.secret_refs, self.headers, "headers", "header", fold=True)
        return self

    def referenced_headers(self, label: str, environ: Mapping[str, str]) -> dict[str, str]:
        """Each `secret_refs` entry's value, read from the gateway's environment. Raises ValueError naming every
        reference whose variable is unset."""
        return _resolved(label, self.secret_refs, environ)


UpstreamConfig = StdioServerConfig | SseServerConfig


def _parse_upstream(label: str, raw: dict[str, Any]) -> UpstreamConfig:
    """Pick the right transport variant based on which keys are present.

    Stdio (command/args) and SSE (url) are mutually exclusive. Anything
    else is a config error.
    """
    has_command = "command" in raw
    has_url = "url" in raw
    if has_command and has_url:
        raise ValueError(
            f"Server '{label}': cannot specify both 'command' and 'url'. "
            "Pick stdio (command+args) OR SSE (url)."
        )
    if has_command:
        return StdioServerConfig(**raw)
    if has_url:
        return SseServerConfig(**raw)
    raise ValueError(
        f"Server '{label}': must specify either 'command' (stdio) or 'url' (SSE)."
    )


class ProxyConfig(BaseModel):
    """Top-level proxy config."""

    # hiitl SDK API key. When the file sets none, `load_config` reads
    # HIITL_API_KEY from the gateway's environment; with neither, the SDK
    # runs locally (no hosted sync). Values are read as written: a
    # `${VAR}` here is that string, not the variable.
    api_key: Optional[str] = None

    # hiitl backend URL — required, with api_key, for the review flow
    # (review case API + SSE). When unset, PAUSE / REQUIRE_APPROVAL /
    # ESCALATE are refused with an MCP error saying no reviewer could
    # be asked.
    server_url: Optional[str] = None

    @field_validator("server_url")
    @classmethod
    def _sent_over_https(cls, v: Optional[str]) -> Optional[str]:
        """The URL the API key goes to: an https URL naming a host (sync_engine.md section 8; row 140)."""
        refusal = None if v is None else https_refusal(v, "server_url")
        if refusal:
            raise ValueError(refusal)
        return v

    # Per-tool-call timeout for forwarding to upstream + evaluate. Keeps a
    # slow upstream from hanging Claude Desktop indefinitely.
    timeout_seconds: float = Field(default=30.0, gt=0)

    # The longest a review case may sit pending. A route `sla.timeout`
    # within it is the case's wait, and the case takes the route's
    # `timeout_action`; otherwise the case waits this long and records
    # fail_closed (routes.md 1.3). Should be coordinated with the MCP
    # client's own request timeout (MCP_timeout > review_timeout).
    # Default 5 min.
    review_timeout_seconds: int = Field(default=300, ge=10, le=3600)

    # Map of human label → upstream transport config. Labels are for
    # diagnostics only; tool names live on the tools themselves.
    servers: dict[str, UpstreamConfig] = Field(default_factory=dict)

    # Optional environment override for the hiitl SDK's `environment`
    # field on every envelope (dev | stage | prod). Defaults to "dev"
    # since most proxy usage is on a developer's laptop.
    environment: str = Field(default="dev")

    # Optional agent_id override. Defaults to "mcp-proxy"; production
    # users will typically override per-agent so audit trails are clean.
    agent_id: str = Field(default="mcp-proxy")

    # Local mode: the SDK's own configuration, passed through unchanged
    # (HTL-18). With a policy file and no api_key, the SDK evaluates the
    # file in-process and its rules bind. Paths resolve against the
    # process's working directory, so write them absolute.
    policy_path: Optional[str] = None

    # Directory of route files. A ROUTE rule's sync route is asked by the
    # SDK and its answer re-enters evaluation (routes.md).
    routes_path: Optional[str] = None

    # The SDK's mode. Unset: RESPECT_POLICY when there is an api_key or a
    # policy file, the SDK's zero-config default otherwise. OBSERVE_ALL
    # records what the policy would decide and blocks nothing.
    mode: Optional[Literal["OBSERVE_ALL", "RESPECT_POLICY"]] = None

    # Where the SDK writes its local audit record. Unset: the SDK's default.
    audit_db_path: Optional[str] = None

    # The arguments the audit record holds as given, per tool: `{tool: [argument names]}`. Every other argument is
    # recorded by its name with an HMAC-SHA256 hash of its value, under the key beside the audit store (event_format.md
    # §Redaction; HTL-20 row 139: "the gateway records argument names with hashed values unless a field is declared";
    # HTL-22 row 163(c), ruled on HTL-20: "the gateway's hash is keyed (HMAC)"). Evaluation sees every argument.
    recorded_arguments: dict[str, list[str]] = Field(default_factory=dict)

    # The envelope signature key is never a config field: the gateway
    # reads it from the environment (HIITL_SIGNATURE_KEY, `proxy.py`).

    model_config = ConfigDict(extra="forbid")

    @field_validator("environment")
    @classmethod
    def _check_env(cls, v: str) -> str:
        if v not in ("dev", "stage", "prod"):
            raise ValueError(
                f"environment must be one of dev | stage | prod, got '{v}'"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _normalize_servers(cls, values: Any) -> Any:
        """Convert raw server dicts into the right StdioServerConfig /
        SseServerConfig variant before per-field validation runs.

        Pydantic's Union dispatch is name-based and would happily accept
        a malformed mix; this explicit dispatch produces clearer errors.
        """
        if not isinstance(values, dict):
            return values
        raw_servers = values.get("servers")
        if not isinstance(raw_servers, dict):
            return values
        parsed: dict[str, UpstreamConfig] = {}
        for label, raw in raw_servers.items():
            if isinstance(raw, (StdioServerConfig, SseServerConfig)):
                parsed[label] = raw
                continue
            if not isinstance(raw, dict):
                raise ValueError(
                    f"Server '{label}' must be a mapping, got {type(raw).__name__}."
                )
            parsed[label] = _parse_upstream(label, raw)
        values["servers"] = parsed
        return values


def load_config(path: str | Path, environ: Optional[Mapping[str, str]] = None) -> ProxyConfig:
    """Read a YAML file from `path` and return a validated `ProxyConfig`.

    Values are read as written (no `${VAR}` expansion). The one value taken from the environment here is the API key,
    and only when the file sets none: `HIITL_API_KEY`, the SDK's own setting (HTL-18, ruled 2026-11-04). An
    upstream's `secret_refs` are read from the environment when the gateway starts (`upstream.py`, row 157). Every reader of
    the key — the SDK client and the review flow — reads it here, once."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"Config file '{p}' must contain a top-level mapping, got "
            f"{type(raw).__name__}."
        )
    environ = os.environ if environ is None else environ
    if not raw.get("api_key") and environ.get(API_KEY_VAR):
        raw = {**raw, "api_key": environ[API_KEY_VAR]}
    return ProxyConfig(**raw)
