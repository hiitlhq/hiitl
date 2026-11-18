"""Row 139 (HTL-20): the gateway records argument names with hashed values unless an argument is declared.

Ruled 2026-11-04: "the gateway records argument names with hashed values unless a field is declared". The contract is
event_format.md §Redaction; this is the row's test design cell 9. Every cell builds the
gateway the way `run_proxy` does (`load_config` → `hiitl_kwargs` → `HIITL`), over an in-memory upstream.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack

import pytest

from hiitl.core.redaction import value_hash
from hiitl.sdk.hash_key import key_path
from hiitl.mcp_proxy.config import API_KEY_VAR
from hiitl.mcp_proxy.tests.test_local_mode import _CALLED, _gateway, _records

POLICY = """
version: "v1.0.0"
description: "Everything runs; the record is what this row reads"
scope:
  org_id: org_devlocal0000000000
  environment: dev
name: gateway_records
rules:
  - name: allow-otherwise
    priority: 1
    conditions: {field: action, operator: exists, value: true}
    decision: ALLOW
    reason_code: ALLOWED
    description: Everything runs; the record is what this row reads
"""

PAY = {"amount": 900, "to": "acme-ltd", "memo": "Q3 retainer, invoice INV-2291"}
READ = {"path": "/srv/payroll/2026-10.csv"}


def _deployment(tmp_path, monkeypatch, recorded: str = "") -> object:
    monkeypatch.delenv(API_KEY_VAR, raising=False)
    (tmp_path / "policy.yaml").write_text(POLICY)
    cfg = tmp_path / "hiitl-mcp.yaml"
    cfg.write_text(
        "agent_id: gateway-test\n"
        f"policy_path: {tmp_path / 'policy.yaml'}\n"
        f"audit_db_path: {tmp_path / 'audit.db'}\n"
        f"{recorded}"
        "servers:\n  tools:\n    command: never-spawned-in-tests\n", encoding="utf-8")
    return cfg


async def _run(cfg):
    async with AsyncExitStack() as stack:
        session = await _gateway(stack, cfg)
        paid = await session.call_tool("pay", dict(PAY))
        read = await session.call_tool("read_file", dict(READ))
    assert not paid.isError and not read.isError
    assert _CALLED == [("pay", PAY), ("read_file", READ)], "the upstream gets the real arguments"
    key_file = key_path(cfg.parent / "audit.db")
    assert key_file.exists(), "the gateway's store hashes an undeclared argument, so it holds its key (row 163(c))"
    return _records(cfg.parent / "audit.db"), key_file.read_bytes()


@pytest.mark.asyncio
async def test_the_gateways_row_holds_no_undeclared_value(tmp_path, monkeypatch):
    cfg = _deployment(tmp_path, monkeypatch, "recorded_arguments:\n  pay: [amount]\n")
    (pay_row, read_row), key = await _run(cfg)

    assert json.loads(pay_row["envelope"])["parameters"] == {
        "amount": 900, "to": value_hash("acme-ltd", key), "memo": value_hash(PAY["memo"], key)}
    assert json.loads(read_row["envelope"])["parameters"] == {"path": value_hash(READ["path"], key)}, \
        "an argument declared for one tool is not recorded for another"
    stored = pay_row["envelope"] + pay_row["decision"] + read_row["envelope"] + read_row["decision"]
    for raw in ("acme-ltd", "Q3 retainer", "payroll"):
        assert raw not in stored, f"the row holds no undeclared value: {raw}"


@pytest.mark.asyncio
async def test_with_nothing_declared_every_argument_is_hashed(tmp_path, monkeypatch):
    (pay_row, read_row), key = await _run(_deployment(tmp_path, monkeypatch))
    assert json.loads(pay_row["envelope"])["parameters"] == {k: value_hash(v, key) for k, v in PAY.items()}
    assert json.loads(read_row["envelope"])["parameters"] == {"path": value_hash(READ["path"], key)}
