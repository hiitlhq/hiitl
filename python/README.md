# hiitl — Python SDK

The control point for AI agents. Python SDK with embedded policy evaluator.

## Install

```bash
pip install hiitl
```

## Quick start

```python
from hiitl import HIITL

# Zero config — observe policy decisions; an audit write failure still blocks
hiitl = HIITL()

decision = hiitl.evaluate("send_email", parameters={
    "to": "user@example.com",
    "subject": "Order update",
})

if decision.allowed:
    send_email(...)
```

With no policy and a successful audit write, a new call comes back `OBSERVE` with `allowed` True and is recorded in the local audit log. A repeated idempotency key within the dedup window reuses its first decision without another row. `would_be` says what enforcement would decide: `BLOCK` with `NO_MATCHING_RULE`, because no rule allows the action yet.

## With policy enforcement

```yaml
# policy.yaml
policy_set:
  name: "payment-controls"
  version: "v1.0.0"
  description: "Payment controls: large payments wait for approval, the largest are refused"
  scope:
    org_id: "org_yourcompany1234567"
    environment: "prod"
  rules:
    - name: "block-over-limit"
      description: "Payments over $10,000 are refused"
      priority: 300
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 10000
      decision: "BLOCK"
      reason_code: "AMOUNT_OVER_LIMIT"
    - name: "review-large-payments"
      description: "Payments over $1,000 need a person's approval"
      priority: 200
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 1000
      decision: "REQUIRE_APPROVAL"
      reason_code: "LARGE_PAYMENT_REVIEW"
    - name: "allow-payments"
      description: "Other payments proceed"
      priority: 10
      conditions:
        field: "action"
        operator: "equals"
        value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"
```

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
    send_for_review(decision)  # your review step; hiitl returns the decision
elif decision.blocked:
    log_blocked(decision)
```

Under `RESPECT_POLICY`, an action no rule matches is blocked (`NO_MATCHING_RULE`), so the policy has an `ALLOW` rule for the payments it lets through.

Without `mode="RESPECT_POLICY"`, the SDK observes. A decision that allows the call comes back as itself. A policy decision that would stop the call comes back `OBSERVE`, with `allowed` True and `would_be` set to the rule's decision. A call past a windowed rate limit comes back `OBSERVE` with `would_be: RATE_LIMIT` under `OBSERVE_ALL`; under `RESPECT_POLICY` it comes back `RATE_LIMIT`. Failures such as an unwritable audit record still block in every mode.

## Hybrid and hosted mode

```python
import os

# Hybrid: an api_key turns on sync. Evaluation stays local and in-process;
# policies, kill switches and audit records sync with the hosted service.
hiitl = HIITL(
    agent_id="payment-agent",
    org_id="org_yourcompany1234567",
    api_key=os.environ["HIITL_API_KEY"],
    environment="prod",
    mode="RESPECT_POLICY",
)

# Hosted: every evaluation is a call to the server (explicit opt-in).
# The server evaluates against the org's active policy.
hiitl = HIITL(
    agent_id="payment-agent",
    org_id="org_yourcompany1234567",
    api_key=os.environ["HIITL_API_KEY"],
    server_url="https://api.hiitl.com",
    evaluation="remote",
    signature_key=os.getenv("HIITL_SIGNATURE_KEY"),  # the API key's signing secret, shown when the key was created
    environment="prod",
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
| `org_id` | `"org_devlocal0000000000"` | Organization ID |
| `mode` | `"OBSERVE_ALL"` | `OBSERVE_ALL` or `RESPECT_POLICY` |
| `policy_path` | `None` | Path to policy file (YAML or JSON). In hybrid mode, the fallback when no synced policy is available |
| `audit_db_path` | `"./hiitl_audit.db"` | SQLite audit log path |
| `enable_rate_limiting` | `True` | Apply the policy's rate limits |
| `routes_path` | `None` | Directory of route config files |
| `signature_key` | `None` | The API key's signing secret: signs every envelope (HMAC-SHA256). Required for hosted evaluation |
| `api_key` | `None` | API key. With it, the SDK runs in hybrid mode: local evaluation with background sync |
| `server_url` | `None` | Server URL. In hybrid mode, the sync target (default `https://api.hiitl.com`). Required for hosted mode |
| `evaluation` | `"local"` | `"remote"` (with `api_key` and `server_url`) for hosted mode |
| `sync` | `True` | `False` keeps a client with an `api_key` in local mode |
| `timeout` | `5.0` | HTTP timeout in seconds |
| `max_retries` | `3` | Retries on transient network failures |
| `cache_dir` | `None` | Hybrid-mode disk cache directory (default `~/.hiitl/cache/`) |
| `sync_config` | `None` | Full `SyncConfig` override |
| `cold_start_behavior` | `"warn-and-observe"` | Hybrid mode, when there is no cache and the first sync fails: `warn-and-observe` (log a warning and continue), `fail-closed` (raise `ColdStartError`), or `observe-silent` (log at INFO) |
| `principal_verifier` | `None` | Function that checks a `principal_token` passed to `evaluate()` and returns its claims |
| `route_client` | `None` | HTTP client used to ask sync routes |

Each setting left unset is read from its `HIITL_<NAME>` environment variable (`HIITL_API_KEY`, `HIITL_POLICY_PATH`, ...; the `HIITL_SYNC_*` variables configure the sync engine), then falls to its default. The mode follows the resolved settings, so `HIITL_API_KEY` alone starts hybrid mode.

### `hiitl.evaluate(action, **kwargs) -> Decision`

| Parameter | Required | Description |
|-----------|----------|-------------|
| `action` | Yes | Action name (e.g., `"send_email"`) |
| `parameters` | No | Action parameters dict |
| `target` | No | Target resource dict |
| `operation` | No | Operation type (default: `"execute"`) |
| `user_id` | No | User identifier |
| `session_id` | No | Session identifier |
| `agent_id` | No | Overrides the `agent_id` set at init |
| `confidence` | No | Agent confidence, 0 to 1 |
| `reason` | No | The agent's reason for the action |
| `sensitivity` | No | Sensitivity labels |
| `cost_estimate` | No | Estimated cost (`tokens`, `dollars`, `api_calls`) |
| `requested_scopes` | No | Permission scopes the call requests |
| `idempotency_key` | No | Idempotency key (generated if omitted) |
| `principal_token` | No | Token for the configured `principal_verifier` |
| `correlation_id` | No | Your own ID tying this action to others, such as a request ID |

The envelope's `trace_id` is the active OpenTelemetry span's when `opentelemetry-api` is installed; it is not a dependency.

### `Decision`

| Property | Type | Description |
|----------|------|-------------|
| `.allowed` | `bool` | Can the action proceed? |
| `.decision` | `str` | Decision type (`ALLOW`, `BLOCK`, etc.) |
| `.reason_codes` | `list[str]` | Why this decision was made |
| `.policy_version` | `str` | Policy version used |
| `.ok` | `bool` | Alias for `.allowed` |
| `.blocked` | `bool` | True if `BLOCK`, `KILL_SWITCH` or `RATE_LIMIT` |
| `.needs_approval` | `bool` | True if `REQUIRE_APPROVAL`, `PAUSE` or `ESCALATE` |
| `.observed` | `bool` | True if the decision is `OBSERVE` |
| `.would_be` | `str` | What enforcement would decide (OBSERVE only) |
| `.would_be_reason_codes` | `list[str]` | The reason codes enforcement would return (OBSERVE only) |
| `.remediation` | `Remediation` | How to fix a blocked call, when the rule defines it |
| `.timing` | `Timing` | `ingest_ms`, `evaluation_ms`, `total_ms` |

## Requirements

- Python 3.10+

## Documentation

- [Python Quickstart](https://github.com/hiitlhq/hiitl/blob/main/docs/onboarding/quickstart_python.md)
- [Full Documentation](https://github.com/hiitlhq/hiitl/tree/main/docs)
- [Examples](https://github.com/hiitlhq/hiitl/tree/main/examples)

## License

[Apache-2.0](https://github.com/hiitlhq/hiitl/blob/main/LICENSE)
