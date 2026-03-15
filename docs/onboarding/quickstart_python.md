# Python Quickstart

## Install

```bash
pip install hiitl
```

## Local Evaluation (No API Key Needed)

When no `api_key` is provided, the SDK automatically runs evaluation in-process with no external dependencies.

Create `example.py`:

```python
from hiitl import HIITL

hiitl = HIITL(
    environment="dev",
    agent_id="my-first-agent",
    org_id="org_devlocal000000000",
    policy_path="./policy.yaml"
)

def process_payment(account_id: str, amount: float):
    print(f"Processing ${amount} payment for account {account_id}")
    return {"status": "success", "transaction_id": "txn_123"}

decision = hiitl.evaluate(
    tool="process_payment",
    operation="execute",
    target={"account_id": "acct_123"},
    parameters={"amount": 150.00, "currency": "usd"}
)

if decision.allowed:
    result = process_payment("acct_123", 150.00)
    print(f"✓ Payment processed: {result}")
else:
    print(f"✗ Blocked: {decision.reason_codes}")
```

## Add a Policy

Create `policies/my-policy.yaml`:

```yaml
policy_set:
  name: "my-first-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_devlocal000000000"
    environment: "dev"

  rules:
    - name: "block-high-value-payments"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "BLOCK"
      reason_code: "PAYMENT_TOO_HIGH"

    - name: "allow-all-else"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"
```

Update `example.py` to load the policy:

```python
from hiitl import HIITL

hiitl = HIITL(
    environment="dev",
    agent_id="my-first-agent",
    org_id="org_devlocal000000000",
    policy_path="policies/my-policy.yaml"  # Load policy
)

# Try a payment over $500
decision = hiitl.evaluate(
    tool="process_payment",
    operation="execute",
    target={"account_id": "acct_456"},
    parameters={"amount": 1000.00, "currency": "usd"}  # Over the limit!
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

---

## What Just Happened?

1. **Envelope Creation**: The SDK created a structured envelope with all required metadata
2. **Policy Evaluation**: Your policy was evaluated against the envelope
3. **Deterministic Decision**: The rule matched (amount > 500) → BLOCK decision
4. **Audit Trail**: An immutable audit record was created (check `~/.hiitl/audit.db` for local evaluation)

---

## Key Concepts

### Auto-Detected Evaluation Mode

The SDK automatically determines how to evaluate based on the configuration you provide:

| Configuration | Evaluation | Latency | Storage | Use Case |
|---------------|-----------|---------|---------|----------|
| `policy_path` only (no `api_key`) | Local | < 10ms | SQLite | Development, edge, single-instance |
| `api_key` + `server_url` | Hosted | < 50ms | PostgreSQL | Production, multi-instance, team collaboration |
| `api_key` only (no `server_url`) | Hybrid | Varies | Both | Local evaluation with remote audit/policy sync |

**Local evaluation** runs in-process. No API key required. Provide a `policy_path` and evaluation happens entirely locally.

**Hosted evaluation** sends envelopes to the HIITL server. Provide both `api_key` and `server_url`.

**Hybrid evaluation** evaluates locally but syncs policies and audit data remotely. Provide `api_key` without `server_url`.

### Envelopes

`evaluate()` creates an envelope with:
- Identifiers: org_id, environment, agent_id, action_id
- Action: tool, operation, target, parameters
- Risk signals: sensitivity, cost_estimate (optional)
- Metadata: reason, timestamps

Action ID and timestamps are auto-generated.

### Decisions

| Decision | Meaning | Your Action |
|----------|---------|-------------|
| `ALLOW` | Safe to proceed | Execute the action |
| `BLOCK` | Denied by policy | Do not execute, log reason |
| `REQUIRE_APPROVAL` | Needs human review | Send to approval queue |
| `RATE_LIMIT` | Too many requests | Wait and retry |
| `KILL_SWITCH` | Emergency stop | Alert ops, do not retry |

---

## Common Patterns

### Pattern 1: Simple Action Protection

```python
decision = hiitl.evaluate(
    tool="send_email",
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
    tool="grant_access",
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
    tool="run_batch_job",
    operation="execute",
    target={"job_id": "job_456"},
    parameters={"records": 1000000},
    cost_estimate={"dollars": 50.00, "tokens": 100000}  # Estimated cost
)

if decision.allowed:
    start_expensive_job(...)
```

### Pattern 4: Handling Rate Limits

```python
decision = hiitl.evaluate(...)

if decision.decision == "RATE_LIMIT":
    # SDK provides helper to wait until reset
    reset_time = decision.rate_limit["reset_at"]
    print(f"Rate limited. Retry after {reset_time}")
    # Or use: hiitl.wait_until_reset(decision)
elif decision.allowed:
    execute_action(...)
```

---

## Debugging & Observability

### See Timing Metadata

```python
decision = hiitl.evaluate(...)
print(f"Evaluation took {decision.timing['total_ms']}ms")
```

**Target latency**:
- Local evaluation: < 10ms
- Hosted evaluation: < 50ms

### View Audit Log (Local Evaluation)

```python
from hiitl import HIITL

hiitl = HIITL(environment="dev", agent_id="my-agent", org_id="org_devlocal000000000", policy_path="./policy.yaml")

# Query audit log
events = hiitl.audit.query(
    agent_id="my-first-agent",
    decision="BLOCK",
    limit=10
)

for event in events:
    print(f"{event.timestamp}: {event.decision} - {event.reason_codes}")
```

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now HIITL will log detailed evaluation steps
```

---

## Next Steps

### 1. Add More Policies

Create policies for:
- Rate limiting: `rate_limit: {scope: "agent_id", window: "hour", limit: 100}`
- Kill switches: High-priority rules you can enable/disable instantly
- Approval workflows: `decision: "REQUIRE_APPROVAL"` for high-stakes actions

See: [Policy Cookbook](policy_cookbook.md)

### 2. Integrate with Your Framework

HIITL works with any Python code, but we have examples for:
- LangChain agents
- OpenAI Agents SDK
- Custom agent loops

See: [Integration Examples](integration_examples.md)

### 3. Deploy to Production

When ready:
1. Sign up for hosted ECP at https://hiitl.ai
2. Create production environment
3. Update SDK config -- the SDK auto-detects hosted evaluation when both `api_key` and `server_url` are provided:
   ```python
   hiitl = HIITL(
       api_key=os.getenv("HIITL_API_KEY"),
       server_url=os.getenv("HIITL_SERVER_URL"),
       environment="prod",
       agent_id="my-agent"
   )
   ```
4. Deploy policies via API or dashboard

### 4. Monitor & Observe

- View audit trail in dashboard
- Set up webhook alerts for blocks/kills witches
- Export audit logs for compliance

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

### Decision Always ALLOW (Policy Not Applying)

**Solution**: Check policy scope matches your SDK config:
- Policy `org_id` must match SDK `org_id` (must match pattern `org_[a-z0-9]{18,}`)
- Policy `environment` must match SDK `environment`

### "Signature Invalid" Error

**Solution**: For hosted evaluation, ensure your API key is correct:
```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),  # Check this is set correctly
    server_url=os.getenv("HIITL_SERVER_URL"),
    ...
)
```

---

## SDK Reference

### HIITL Configuration

```python
# Local evaluation (no api_key → auto-detected as local)
hiitl = HIITL(
    environment="dev",                     # "dev", "stage", or "prod"
    agent_id="my-agent",                   # Stable agent identifier
    org_id="org_devlocal000000000",        # Organization ID (must match org_[a-z0-9]{18,})
    policy_path="./policy.yaml",           # Path to policy file (required for local evaluation)
    audit_db_path="./hiitl_audit.db",      # SQLite audit log path (default shown)
    enable_rate_limiting=True,             # Enable in-memory rate limiting (default: True)
    signature_key=None,                    # Optional: HMAC signature key for envelope signing
)

# Hosted evaluation (api_key + server_url → auto-detected as hosted)
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),    # Triggers hosted or hybrid evaluation
    server_url=os.getenv("HIITL_SERVER_URL"),  # With api_key → hosted evaluation
    environment="prod",
    agent_id="my-agent",
)

# Hybrid evaluation (api_key only, no server_url → auto-detected as hybrid)
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),    # api_key without server_url → hybrid
    environment="prod",
    agent_id="my-agent",
    policy_path="./policy.yaml",           # Local evaluation with remote sync
)
```

**Mode is auto-detected** -- you never need to set it explicitly:
- No `api_key` provided → local evaluation
- `api_key` + `server_url` provided → hosted evaluation
- `api_key` without `server_url` → hybrid evaluation

Environment variables `HIITL_API_KEY` and `HIITL_SERVER_URL` are also supported and follow the same auto-detection logic.

### evaluate() Parameters

```python
decision = hiitl.evaluate(
    action="action_name",              # Required: Action name
    operation="execute",               # Required: read/write/create/delete/execute
    target={},                         # Required: Resource identifiers
    parameters={},                     # Required: Action parameters
    sensitivity=[],                    # Optional: Risk flags
    cost_estimate={},                  # Optional: Cost metadata
    user_id=None,                      # Optional: End-user ID
    session_id=None,                   # Optional: Session ID
    reason=None,                       # Optional: Brief reason string
)
```

### Decision Object

```python
decision.allowed          # bool: True if ALLOW or SANDBOX
decision.decision         # str: Decision type (ALLOW, BLOCK, etc.)
decision.reason_codes     # list[str]: Reason codes
decision.policy_version   # str: Policy version used
decision.timing           # dict: Timing metadata
decision.rate_limit       # dict|None: Rate limit state (if applicable)
decision.approval_metadata  # dict|None: Approval workflow data (if applicable)
```

---

## Getting Help

- **Documentation**: https://docs.hiitl.ai
- **Examples**: https://github.com/hiitlhq/hiitl/tree/main/examples
- **Issues**: https://github.com/hiitlhq/hiitl/issues
- **Discord**: https://discord.gg/hiitl

---

**You're now ready to add deterministic control to your AI agents! 🚀**
