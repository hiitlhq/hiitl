# hiitl — Python SDK

The control point for AI agents. Python SDK with embedded policy evaluator.

## Install

```bash
pip install hiitl
```

## Quick start

```python
from hiitl import HIITL

# Zero config — observe everything, block nothing
hiitl = HIITL()

decision = hiitl.evaluate("send_email", parameters={
    "to": "user@example.com",
    "subject": "Order update",
})

if decision.allowed:
    send_email(...)
```

## With policy enforcement

```python
hiitl = HIITL(
    agent_id="payment-agent",
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
)

decision = hiitl.evaluate("process_payment", parameters={
    "amount": 5000.00,
    "currency": "USD",
})

if decision.allowed:
    process_payment(...)
elif decision.needs_approval:
    queue_for_review(decision)
elif decision.blocked:
    log_blocked(decision)
```

## Hosted mode

```python
hiitl = HIITL(
    agent_id="payment-agent",
    org_id="org_yourcompany1234567",
    api_key="sk_live_...",
    server_url="https://ecp.hiitl.com",
    environment="prod",
    mode="RESPECT_POLICY",
)

# Same evaluate() call, same Decision object
decision = hiitl.evaluate("process_payment", parameters={"amount": 500})
```

## API

### `HIITL(**kwargs)`

All parameters are keyword-only with defaults. `HIITL()` works with no arguments.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `agent_id` | `"default"` | Agent identifier |
| `environment` | `"dev"` | `dev`, `stage`, or `prod` |
| `mode` | `"OBSERVE_ALL"` | `OBSERVE_ALL` or `RESPECT_POLICY` |
| `policy_path` | `None` | Path to policy file (YAML or JSON) |
| `audit_db_path` | `"./hiitl_audit.db"` | SQLite audit log path |
| `api_key` | `None` | API key for hosted mode |
| `server_url` | `None` | Server URL for hosted mode |

### `hiitl.evaluate(action, **kwargs) -> Decision`

| Parameter | Required | Description |
|-----------|----------|-------------|
| `action` | Yes | Action name (e.g., `"send_email"`) |
| `parameters` | No | Action parameters dict |
| `target` | No | Target resource dict |
| `operation` | No | Operation type (default: `"execute"`) |
| `user_id` | No | User identifier |
| `sensitivity` | No | Sensitivity labels |

### `Decision`

| Property | Type | Description |
|----------|------|-------------|
| `.allowed` | `bool` | Can the action proceed? |
| `.decision` | `str` | Decision type (`ALLOW`, `BLOCK`, etc.) |
| `.reason_codes` | `list[str]` | Why this decision was made |
| `.policy_version` | `str` | Policy version used |
| `.ok` | `bool` | Alias for `.allowed` |
| `.blocked` | `bool` | True if `BLOCK` |
| `.needs_approval` | `bool` | True if `REQUIRE_APPROVAL` |
| `.observed` | `bool` | True if `OBSERVE` mode |
| `.would_be` | `str` | What enforce mode would do (OBSERVE only) |

## Requirements

- Python 3.12+

## Documentation

- [Python Quickstart](../docs/onboarding/quickstart_python.md)
- [Full Documentation](../docs/)
- [Examples](../examples/)

## License

[MIT](../LICENSE)
