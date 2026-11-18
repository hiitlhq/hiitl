# Python Quickstart

## Install

```bash
pip install hiitl
```

## Local Evaluation (No API Key Needed)

When no `api_key` is provided, the SDK automatically runs evaluation in-process with no external dependencies. With no policy loaded, every action is observed: it is recorded and allowed.

Create `example.py`:

```python
from hiitl import HIITL

hiitl = HIITL(agent_id="my-first-agent")

def process_payment(account_id: str, amount: float):
    print(f"Processing ${amount} payment for account {account_id}")
    return {"status": "success", "transaction_id": "txn_123"}

decision = hiitl.evaluate(
    "process_payment",
    target={"account_id": "acct_123"},
    parameters={"amount": 150.00, "currency": "usd"},
)

if decision.allowed:
    result = process_payment("acct_123", 150.00)
    print(f"✓ Payment processed: {result}")
else:
    print(f"✗ Blocked: {decision.reason_codes}")
```

The payment goes through. `decision.decision` is `OBSERVE`, and `decision.would_be` says what enforcement would have decided: `BLOCK`, with `NO_MATCHING_RULE` in `decision.would_be_reason_codes`, because no rule allows the action yet.

## Add a Policy

Create `policy.yaml`. An action no rule matches is blocked once you enforce, so the policy allows payments and blocks the large ones. Every rule needs a `description`:

```yaml
policy_set:
  name: "payment-controls"
  version: "v1.0.0"
  description: "Payment controls for the quickstart agent"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"
  rules:
    - name: "block-high-value-payments"
      description: "Payments over $500 are refused"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "BLOCK"
      reason_code: "PAYMENT_TOO_HIGH"
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

Update `example.py` to load the policy and enforce it. The default mode, `OBSERVE_ALL`, only records what the policy would do; `mode="RESPECT_POLICY"` enforces it:

```python
from hiitl import HIITL

hiitl = HIITL(
    agent_id="my-first-agent",
    policy_path="./policy.yaml",  # Load policy
    mode="RESPECT_POLICY",        # Enforce it
)

# Try a payment over $500
decision = hiitl.evaluate(
    "process_payment",
    target={"account_id": "acct_456"},
    parameters={"amount": 1000.00, "currency": "usd"},  # Over the limit!
)

if decision.allowed:
    print("✓ Payment allowed")
else:
    print(f"✗ Payment blocked: {decision.reason_codes}")
```

Run it:
```bash
python example.py
```

Expected output:
```
✗ Payment blocked: ['PAYMENT_TOO_HIGH']
```

**The policy worked!** Payments over $500 are now blocked.

Without `mode="RESPECT_POLICY"`, the same call comes back as `OBSERVE`, with `would_be` `BLOCK` and `would_be_reason_codes` `['PAYMENT_TOO_HIGH']`. That lets you watch what a policy would do before you enforce it.

---

## What Just Happened?

1. **Envelope Creation**: The SDK created a structured envelope with all required metadata
2. **Policy Evaluation**: Your policy was evaluated against the envelope
3. **Deterministic Decision**: The rule matched (amount > 500) → BLOCK decision
4. **Audit Trail**: An audit record was written to `./hiitl_audit.db` (the default `audit_db_path`), with a SHA-256 hash of its content

---

## Key Concepts

### Auto-Detected Evaluation Mode

The SDK automatically determines how to evaluate based on the configuration you provide:

| Configuration | Evaluation | Latency | Storage | Use Case |
|---------------|-----------|---------|---------|----------|
| No `api_key` (optional `policy_path`) | Local | < 10ms | SQLite | Development, edge, single-instance |
| `api_key`, with or without `server_url` | Hybrid | Same as local (in-process) | SQLite, synced to hosted | Production: local evaluation with policy and audit sync |
| `api_key` + `server_url` + `evaluation="remote"` | Hosted | < 50ms | PostgreSQL | Teams that want no local state |

**Local evaluation** runs in-process. No API key required. Provide a `policy_path` and evaluation happens entirely locally.

**Hybrid evaluation** evaluates in-process too, against policies synced from the hosted service, and syncs the audit trail up in the background. Provide an `api_key`; `server_url` defaults to `https://api.hiitl.com`.

**Hosted evaluation** sends every envelope to the hiitl server. Provide `api_key`, `server_url` and `evaluation="remote"`.

### Envelopes

`evaluate()` creates an envelope with:
- Identifiers: org_id, environment, agent_id, action_id
- Action: action, operation, target, parameters
- Risk signals: sensitivity, cost_estimate (optional)
- Metadata: reason, timestamps

Action ID, idempotency key and timestamps are auto-generated.

### Decisions

| Decision | `allowed` | Meaning |
|----------|-----------|---------|
| `ALLOW` | `true` | Safe to proceed |
| `OBSERVE` | `true` | Recorded, not enforced (`OBSERVE_ALL` mode); `would_be` holds the enforced decision |
| `BLOCK` | `false` | Denied by policy |
| `REQUIRE_APPROVAL` | `false` | Needs human review before execution |
| `PAUSE` | `false` | Held for later processing |
| `ESCALATE` | `false` | Escalated to a higher authority |
| `ROUTE` | `false` | A sync route was asked and has not answered |
| `RATE_LIMIT` | `false` | Too many requests — wait and retry |
| `KILL_SWITCH` | `false` | Emergency stop — do not retry |
| `SANDBOX` | `true` | Allowed in isolated environment |

Under `OBSERVE_ALL`, an ALLOW or SANDBOX comes back as itself; every other decision comes back as `OBSERVE`. A windowed `RATE_LIMIT` rule still refuses the call past its limit in either mode.

---

## Common Patterns

### Pattern 1: Simple Action Protection

```python
decision = hiitl.evaluate(
    "send_email",
    operation="execute",
    target={"email": "customer@example.com"},
    parameters={"subject": "Welcome", "body": "Hello..."}
)

if decision.allowed:
    send_email_via_provider(...)
```

### Pattern 2: Sensitive Actions

```python
decision = hiitl.evaluate(
    "grant_access",
    operation="create",
    target={"user_id": "user_123"},
    parameters={"role": "admin"},
    sensitivity=["permissions", "irreversible"]  # Flag as sensitive
)

if decision.allowed:
    grant_database_access(...)
```

### Pattern 3: High-Cost Actions

```python
decision = hiitl.evaluate(
    "run_batch_job",
    operation="execute",
    target={"job_id": "job_456"},
    parameters={"records": 1000000},
    cost_estimate={"dollars": 50.00, "tokens": 100000}  # Estimated cost
)

if decision.allowed:
    start_expensive_job(...)
```

### Pattern 4: Handling Rate Limits

A rate limit is a `RATE_LIMIT` rule with a window, such as `rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}`. The call past the limit comes back as `RATE_LIMIT`, with the counter state in `decision.rate_limit`:

```python
decision = hiitl.evaluate("send_email", parameters={"to": "customer@example.com"})

if decision.decision == "RATE_LIMIT":
    reset_time = decision.rate_limit.reset_at
    print(f"Rate limited. Retry after {reset_time}")
elif decision.allowed:
    execute_action(...)
```

---

## Debugging & Observability

### See Timing Metadata

```python
decision = hiitl.evaluate("process_payment", parameters={"amount": 50.00})
print(f"Evaluation took {decision.timing.total_ms}ms")
```

**Target latency**:
- Local evaluation: < 10ms
- Hosted evaluation: < 50ms

### View Audit Log (Local Evaluation)

The Python SDK has no audit query method. In local and hybrid mode the trail is a SQLite file (`audit_db_path`, default `./hiitl_audit.db`) that you can read directly:

```python
import sqlite3

con = sqlite3.connect("hiitl_audit.db")
rows = con.execute(
    "SELECT timestamp, action, decision_type FROM audit_log "
    "WHERE agent_id = ? AND decision_type = ? ORDER BY timestamp DESC LIMIT 10",
    ("my-first-agent", "BLOCK"),
)

for timestamp, action, decision in rows:
    print(f"{timestamp}: {action} {decision}")
```

The `action` column holds the action name, as the envelope does (`tool_name` in a store written before record format 2.0, renamed when the store opens).

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now hiitl logs sync and cache activity (hybrid mode) in detail.
# Evaluation logs warnings only; there is no step-by-step evaluation log.
```

---

## Next Steps

### 1. Add More Policies

Create policies for:
- Rate limiting: a `RATE_LIMIT` rule with `rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}`
- Kill switches: `KILL_SWITCH` rules you switch on and off with `lifecycle_stage` (`active` / `disabled`)
- Approval workflows: `decision: "REQUIRE_APPROVAL"` for high-stakes actions. The decision comes back to your code; nothing is queued unless a review case is opened

See: [Policy Cookbook](policy_cookbook.md)

### 2. Integrate with Your Framework

hiitl works with any Python code, but we have examples for:
- LangChain agents
- OpenAI Agents SDK
- Custom agent loops

See: [Integration Examples](integration_examples.md)

### 3. Deploy to Production

When ready:
1. Sign up for hosted ECP at https://hiitl.com
2. Create an API key for the `prod` environment
3. Add the key to your SDK config. An `api_key` turns on hybrid mode: evaluation stays in-process, and policies and the audit trail sync with the hosted service in the background:
   ```python
   import os

   hiitl = HIITL(
       api_key=os.getenv("HIITL_API_KEY"),
       environment="prod",
       agent_id="my-agent",
       policy_path="./policy.yaml",  # Used until the first policy sync
       mode="RESPECT_POLICY",
   )
   ```
   For hosted evaluation, where every call goes to the server, add `server_url=os.getenv("HIITL_SERVER_URL")` and `evaluation="remote"`.
4. Deploy policies through the API (`POST /v1/policies`, admin scope). The dashboard shows them

### 4. Monitor & Observe

- View audit trail in dashboard
- Query audit logs through the API (`GET /v1/audit`, read scope) for compliance

---

## Troubleshooting

### Import Error: `ModuleNotFoundError: No module named 'hiitl'`

**Solution**: Install the SDK: `pip install hiitl`

### Policy Not Loading

**Solution**: Check file path. Use absolute path or relative to current directory:
```python
import os
policy_path = os.path.join(os.path.dirname(__file__), "policies/my-policy.yaml")
hiitl = HIITL(policy_path=policy_path, ...)
```

### Decision Always OBSERVE (Policy Not Enforcing)

**Solution**: The default mode, `OBSERVE_ALL`, records what the policy would decide and enforces nothing: a BLOCK comes back as `OBSERVE`, with the rule's decision in `would_be`. Pass `mode="RESPECT_POLICY"` to enforce:
```python
hiitl = HIITL(policy_path="./policy.yaml", mode="RESPECT_POLICY")
```

### Every Action Blocked with `NO_MATCHING_RULE`

**Solution**: Under `RESPECT_POLICY`, an action no rule matches is blocked. Add an `ALLOW` rule, at a lower priority than your BLOCK rules, for each action you mean to let through.

---

## SDK Reference

### `HIITL` Configuration

```python
# Local evaluation (no api_key → auto-detected as local)
hiitl = HIITL(
    environment="dev",                     # "dev", "stage", or "prod"
    agent_id="my-agent",                   # Stable agent identifier
    org_id="org_devlocal0000000000",       # Organization ID (default shown; must match ^org_[a-zA-Z0-9]{16,}$)
    policy_path="./policy.yaml",           # Path to policy file (required with mode="RESPECT_POLICY")
    mode="OBSERVE_ALL",                    # Default; "RESPECT_POLICY" enforces the policy
    audit_db_path="./hiitl_audit.db",      # SQLite audit log path (default shown)
    enable_rate_limiting=True,             # Enable in-memory rate limiting (default: True)
    signature_key=None,                    # Optional locally: HMAC signature key; required for hosted evaluation
)

# Hybrid evaluation (api_key → hybrid, with or without server_url)
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),    # An api_key turns on hybrid evaluation
    environment="prod",
    agent_id="my-agent",
    policy_path="./policy.yaml",           # Fallback until the first policy sync
    mode="RESPECT_POLICY",
)

# Hosted evaluation (api_key + server_url + evaluation="remote")
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    evaluation="remote",                   # Every evaluate() is a call to the server
    signature_key=os.getenv("HIITL_SIGNATURE_KEY"),  # the API key's signing secret, shown when the key was created
    environment="prod",
    agent_id="my-agent",
)
```

**Where evaluation runs is auto-detected** from what you pass:
- No `api_key` provided → local evaluation
- `api_key`, with or without `server_url` → hybrid evaluation
- `api_key` + `server_url` + `evaluation="remote"` → hosted evaluation

Pass `api_key` and `server_url` as arguments, as above. Setting `HIITL_API_KEY` or `HIITL_SERVER_URL` in the environment does not change where evaluation runs.

### evaluate() Parameters

```python
decision = hiitl.evaluate(
    action="action_name",              # Required: Action name (or the first positional argument)
    operation="execute",               # Optional: read/write/create/update/delete/execute (default: execute)
    target={},                         # Optional: Resource identifiers (default: {})
    parameters={},                     # Optional: Action parameters (default: {})
    sensitivity=[],                    # Optional: Risk flags
    cost_estimate={},                  # Optional: Cost metadata (tokens, dollars, api_calls)
    user_id=None,                      # Optional: End-user ID
    session_id=None,                   # Optional: Session ID
    reason=None,                       # Optional: Brief reason string
)
```

### Decision Object

```python
decision.allowed          # bool: True if ALLOW, SANDBOX or OBSERVE
decision.decision         # str: Decision type (ALLOW, BLOCK, OBSERVE, etc.)
decision.reason_codes     # list[str]: Reason codes
decision.would_be         # str|None: The enforced decision, when decision is OBSERVE
decision.would_be_reason_codes  # list[str]|None: Its reason codes
decision.policy_version   # str: Policy version used
decision.timing           # Timing: ingest_ms, evaluation_ms, total_ms
decision.rate_limit       # RateLimit|None: scope, window, limit, current, reset_at (on RATE_LIMIT)
decision.remediation      # Remediation|None: Guidance from the rule, on a BLOCK
decision.ok               # Same as allowed
decision.blocked          # BLOCK, KILL_SWITCH or RATE_LIMIT
decision.needs_approval   # REQUIRE_APPROVAL, PAUSE or ESCALATE
decision.observed         # OBSERVE
```

---

## Getting Help

- **Documentation**: the `docs-site/` directory of https://github.com/hiitlhq/hiitl
- **Examples**: the `examples/` directory of https://github.com/hiitlhq/hiitl
- **Issues**: https://github.com/hiitlhq/hiitl/issues

---

**You're now ready to add deterministic control to your AI agents! 🚀**
