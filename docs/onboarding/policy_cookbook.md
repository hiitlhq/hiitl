# Policy Cookbook - HIITL ECP

Practical policy examples for common scenarios. Copy, customize, and deploy.

---

## Table of Contents

1. [Payment Approval Workflows](#payment-approval-workflows)
2. [Rate Limiting](#rate-limiting)
3. [Permission Escalation](#permission-escalation)
4. [Kill Switches](#kill-switches)
5. [Environment-Based Controls](#environment-based-controls)
6. [Cost-Based Budgets](#cost-based-budgets)
7. [Sensitivity-Based Routing](#sensitivity-based-routing)
8. [Multi-Layer Policies](#multi-layer-policies)
9. [Time-Based Rules](#time-based-rules)
10. [Agent-Specific Overrides](#agent-specific-overrides)
11. [Local Mode Specific Considerations](#local-mode-specific-considerations)

---

## Payment Approval Workflows

### Example 1: Simple Amount Threshold

Require approval for payments over $500.

```yaml
policy_set:
  name: "payment-approval-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  rules:
    - name: "require-approval-high-value"
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
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"
      metadata:
        sla_hours: 4
        reviewer_role: "finance_approver"

    - name: "allow-low-value-payments"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "LOW_VALUE_PAYMENT"
```

### Example 2: Tiered Approval Thresholds

Different approval levels based on amount.

```yaml
policy_set:
  name: "tiered-payment-approval"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  rules:
    - name: "executive-approval-required"
      enabled: true
      priority: 200
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 10000
      decision: "REQUIRE_APPROVAL"
      reason_code: "EXECUTIVE_APPROVAL_REQUIRED"
      metadata:
        sla_hours: 2
        reviewer_role: "cfo"

    - name: "manager-approval-required"
      enabled: true
      priority: 150
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 1000
      decision: "REQUIRE_APPROVAL"
      reason_code: "MANAGER_APPROVAL_REQUIRED"
      metadata:
        sla_hours: 4
        reviewer_role: "finance_manager"

    - name: "supervisor-approval-required"
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
      decision: "REQUIRE_APPROVAL"
      reason_code: "SUPERVISOR_APPROVAL_REQUIRED"
      metadata:
        sla_hours: 8
        reviewer_role: "team_lead"

    - name: "allow-small-payments"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "SMALL_PAYMENT_AUTO_APPROVED"
```

### Example 3: Amount + Confidence Threshold

Require approval for high-value OR low-confidence payments.

```yaml
- name: "require-approval-risky-payment"
  enabled: true
  priority: 100
  conditions:
    all_of:
      - field: "tool"
        operator: "equals"
        value: "process_payment"
      - any_of:
          - field: "parameters.amount"
            operator: "greater_than"
            value: 5000
          - all_of:
              - field: "parameters.amount"
                operator: "greater_than"
                value: 1000
              - field: "confidence"
                operator: "less_than"
                value: 0.8
  decision: "REQUIRE_APPROVAL"
  reason_code: "RISKY_PAYMENT"
  metadata:
    sla_hours: 2
    reviewer_role: "risk_team"
```

---

## Rate Limiting

Rate limiting is configured at the **policy-set level** via `metadata.rate_limits`, not as individual rules. The rate limiter runs **post-evaluation** and only applies to ALLOW decisions — if a rule blocks or escalates an action, it is never counted against a rate limit.

### Example 4: Per-Agent Rate Limit

Limit each agent to 100 actions per hour.

```yaml
policy_set:
  name: "agent-rate-limited-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  metadata:
    rate_limits:
      - scope: "agent_id"
        window: "hour"
        limit: 100

  rules:
    - name: "allow-payments"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"
```

When an action is ALLOW'd by the rules, the rate limiter checks if the agent has exceeded 100 actions in the current hour. If so, the decision is overridden to `RATE_LIMIT` with reason code `RATE_LIMIT_EXCEEDED`.

### Example 5: Per-User Rate Limit

Limit each end-user to 10 emails per day.

```yaml
policy_set:
  name: "user-email-limit"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  metadata:
    rate_limits:
      - scope: "user_id"
        window: "day"
        limit: 10

  rules:
    - name: "allow-emails"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"
```

### Example 6: Org-Wide Global Rate Limit

Limit all agents combined to 1000 database queries per minute.

```yaml
metadata:
  rate_limits:
    - scope: "org"
      window: "minute"
      limit: 1000
```

### Example 7: Multiple Simultaneous Limits

Apply both per-agent and org-wide limits. The first limit exceeded wins.

```yaml
metadata:
  rate_limits:
    - scope: "agent_id"
      window: "minute"
      limit: 60
    - scope: "org"
      window: "hour"
      limit: 5000
```

This allows bursting up to 60 per agent per minute while capping the organization at 5000 per hour total.

---

## Permission Escalation

### Example 8: Admin Permission Grants

Require approval for granting admin permissions.

```yaml
- name: "require-approval-admin-grants"
  enabled: true
  priority: 200
  conditions:
    all_of:
      - field: "tool"
        operator: "equals"
        value: "grant_access"
      - field: "parameters.role"
        operator: "in"
        value: ["admin", "superuser", "root"]
  decision: "REQUIRE_APPROVAL"
  reason_code: "ADMIN_PERMISSION_GRANT"
  metadata:
    sla_hours: 2
    reviewer_role: "security_team"
```

### Example 9: Block Sensitive Permission Grants in Dev

Don't allow production permissions in dev environment.

```yaml
- name: "block-prod-permissions-in-dev"
  enabled: true
  priority: 900
  conditions:
    all_of:
      - field: "environment"
        operator: "equals"
        value: "dev"
      - field: "tool"
        operator: "equals"
        value: "grant_access"
      - field: "parameters.scope"
        operator: "contains"
        value: "production"
  decision: "BLOCK"
  reason_code: "PROD_PERMISSIONS_IN_DEV_BLOCKED"
```

### Example 10: Escalate Unusual Permission Requests

Escalate if agent requests permissions it doesn't normally need.

```yaml
- name: "escalate-unusual-permissions"
  enabled: true
  priority: 150
  conditions:
    all_of:
      - field: "tool"
        operator: "equals"
        value: "grant_access"
      - field: "parameters.role"
        operator: "not_in"
        value: ["read_only", "basic_user"]
  decision: "ESCALATE"
  reason_code: "UNUSUAL_PERMISSION_REQUEST"
  metadata:
    escalation_team: "security_ops"
```

---

## Kill Switches

### Example 11: Kill Switch for All Payments

Emergency stop for all payment processing.

```yaml
- name: "kill-switch-all-payments"
  enabled: false  # Disabled by default, enable when incident declared
  priority: 1000  # Highest priority
  conditions:
    all_of:
      - field: "tool"
        operator: "equals"
        value: "process_payment"
  decision: "KILL_SWITCH"
  reason_code: "KILL_SWITCH_PAYMENTS_ACTIVE"
```

### Example 12: Kill Switch for Specific Agent

Stop one agent that's behaving abnormally.

```yaml
- name: "kill-switch-agent-123"
  enabled: false  # Enable when agent needs to be stopped
  priority: 1000
  conditions:
    all_of:
      - field: "agent_id"
        operator: "equals"
        value: "agent-123"
  decision: "KILL_SWITCH"
  reason_code: "AGENT_SUSPENDED"
```

### Example 13: Kill Switch for Database Deletes

Emergency block for all database delete operations.

```yaml
- name: "kill-switch-database-deletes"
  enabled: false
  priority: 1000
  conditions:
    all_of:
      - field: "operation"
        operator: "equals"
        value: "delete"
      - field: "target.resource_type"
        operator: "equals"
        value: "database"
  decision: "KILL_SWITCH"
  reason_code: "DATABASE_DELETE_KILL_SWITCH"
```

---

## Environment-Based Controls

### Example 14: Sandbox All Actions in Dev

Route all actions to sandbox endpoints in development.

```yaml
- name: "sandbox-all-in-dev"
  enabled: true
  priority: 10
  conditions:
    all_of:
      - field: "environment"
        operator: "equals"
        value: "dev"
  decision: "SANDBOX"
  reason_code: "DEV_ENVIRONMENT_SANDBOX"
  metadata:
    sandbox_endpoint: "https://sandbox-api.example.com"
```

### Example 15: Block Irreversible Actions in Dev

Don't allow irreversible actions in development.

```yaml
- name: "block-irreversible-in-dev"
  enabled: true
  priority: 900
  conditions:
    all_of:
      - field: "environment"
        operator: "equals"
        value: "dev"
      - field: "sensitivity"
        operator: "contains"
        value: "irreversible"
  decision: "BLOCK"
  reason_code: "IRREVERSIBLE_BLOCKED_IN_DEV"
```

### Example 16: Stricter Limits in Production

Lower rate limits in production for safety. Use separate policy sets per environment with different `metadata.rate_limits`.

```yaml
policy_set:
  name: "prod-email-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  metadata:
    rate_limits:
      - scope: "agent_id"
        window: "hour"
        limit: 50  # Conservative in prod (dev might use 100)

  rules:
    - name: "allow-emails"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"
```

---

## Cost-Based Budgets

### Example 17: Dollar Spend Limit

Block actions if estimated cost exceeds budget.

```yaml
- name: "block-over-budget"
  enabled: true
  priority: 100
  conditions:
    all_of:
      - field: "cost_estimate.dollars"
        operator: "greater_than"
        value: 100
  decision: "BLOCK"
  reason_code: "COST_EXCEEDS_BUDGET"
```

### Example 18: Token Budget per Agent (Future)

> **Note**: Cost-based budgets (counting tokens or dollars instead of actions) are a designed extension point. Phase 1 supports action-count rate limiting. Token/cost-based budgets will be available in a future release.

```yaml
# Future: rate_limits will support custom dimensions
metadata:
  rate_limits:
    - scope: "agent_id"
      window: "day"
      limit: 1000000
      dimension: "tokens"  # Not yet supported — counts actions in Phase 1
```

### Example 19: Approval for Expensive Actions

Require approval for actions estimated to cost > $10.

```yaml
- name: "require-approval-expensive"
  enabled: true
  priority: 100
  conditions:
    all_of:
      - field: "cost_estimate.dollars"
        operator: "greater_than"
        value: 10
  decision: "REQUIRE_APPROVAL"
  reason_code: "EXPENSIVE_ACTION"
  metadata:
    sla_hours: 1
    reviewer_role: "ops_lead"
```

---

## Sensitivity-Based Routing

### Example 20: Escalate Money + Identity Actions

Actions involving both money and identity require review.

```yaml
- name: "escalate-money-and-identity"
  enabled: true
  priority: 150
  conditions:
    all_of:
      - field: "sensitivity"
        operator: "contains"
        value: "money"
      - field: "sensitivity"
        operator: "contains"
        value: "identity"
  decision: "ESCALATE"
  reason_code: "MONEY_AND_IDENTITY_RISK"
  metadata:
    escalation_team: "fraud_prevention"
```

### Example 21: Sandbox Regulated Data Actions in Dev

Route regulated data actions to sandbox in dev/stage.

```yaml
- name: "sandbox-regulated-non-prod"
  enabled: true
  priority: 50
  conditions:
    all_of:
      - field: "environment"
        operator: "in"
        value: ["dev", "stage"]
      - field: "sensitivity"
        operator: "contains"
        value: "regulated"
  decision: "SANDBOX"
  reason_code: "REGULATED_DATA_SANDBOX"
  metadata:
    sandbox_endpoint: "https://sandbox-compliance-api.example.com"
```

### Example 22: Block PII Access from Untrusted Agents

Only specific agents can access PII.

```yaml
- name: "block-pii-from-untrusted-agents"
  enabled: true
  priority: 900
  conditions:
    all_of:
      - field: "sensitivity"
        operator: "contains"
        value: "pii"
      - field: "agent_id"
        operator: "not_in"
        value: ["customer-service-agent", "compliance-agent"]
  decision: "BLOCK"
  reason_code: "PII_ACCESS_RESTRICTED"
```

---

## Multi-Layer Policies

### Example 23: Comprehensive Payment Policy

All payment controls in one policy set.

```yaml
policy_set:
  name: "comprehensive-payment-policy"
  version: "v2.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  # Rate limiting applied post-evaluation on ALLOW decisions
  metadata:
    rate_limits:
      - scope: "agent_id"
        window: "hour"
        limit: 100

  rules:
    # Layer 1: Kill switch (emergency stop)
    - name: "kill-switch-all-payments"
      enabled: false
      priority: 1000
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "KILL_SWITCH"
      reason_code: "PAYMENTS_KILL_SWITCH_ACTIVE"

    # Layer 2: Block suspended agents
    - name: "block-suspended-agents"
      enabled: true
      priority: 900
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "agent_id"
            operator: "in"
            value: []  # Empty list, populated when agent suspended
      decision: "BLOCK"
      reason_code: "AGENT_SUSPENDED"

    # Layer 3: Approval workflows
    - name: "require-approval-high-value"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 1000
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"
      metadata:
        sla_hours: 4
        reviewer_role: "finance_approver"

    - name: "require-approval-low-confidence"
      enabled: true
      priority: 90
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
          - field: "confidence"
            operator: "less_than"
            value: 0.8
      decision: "REQUIRE_APPROVAL"
      reason_code: "LOW_CONFIDENCE_PAYMENT"
      metadata:
        sla_hours: 2
        reviewer_role: "risk_team"

    # Layer 4: Default allow (rate limiting applied automatically)
    - name: "allow-standard-payments"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "STANDARD_PAYMENT"
```

**How rate limiting interacts**: Rules are evaluated first (kill switch → blocks → approvals → allow). Only actions that receive an ALLOW decision are then checked against the `metadata.rate_limits`. Blocked or escalated actions never count against rate limits.

---

## Time-Based Rules

### Example 24: After-Hours Approval

Require approval for high-value actions outside business hours.

```yaml
- name: "after-hours-approval"
  enabled: true
  priority: 120
  conditions:
    all_of:
      - field: "tool"
        operator: "equals"
        value: "process_payment"
      - field: "parameters.amount"
        operator: "greater_than"
        value: 500
      - field: "metadata.hour_of_day"
        operator: "not_in"
        value: [9, 10, 11, 12, 13, 14, 15, 16, 17]  # 9 AM - 5 PM
  decision: "REQUIRE_APPROVAL"
  reason_code: "AFTER_HOURS_PAYMENT"
  metadata:
    sla_hours: 12
    reviewer_role: "on_call_approver"
```

### Example 25: Weekend Restrictions

Block sensitive operations on weekends.

```yaml
- name: "block-sensitive-on-weekends"
  enabled: true
  priority: 900
  conditions:
    all_of:
      - field: "sensitivity"
        operator: "contains"
        value: "regulated"
      - field: "metadata.day_of_week"
        operator: "in"
        value: ["Saturday", "Sunday"]
  decision: "BLOCK"
  reason_code: "WEEKEND_RESTRICTED"
```

---

## Agent-Specific Overrides

### Example 26: Trusted Agent Exemption

Allow specific agent to bypass approval requirements.

```yaml
policy_set:
  name: "trusted-agent-overrides"
  version: "v1.0.0"
  scope:
    org_id: "org_abc123"
    environment: "prod"

  metadata:
    rate_limits:
      - scope: "agent_id"
        window: "hour"
        limit: 100

  rules:
    # Trusted agent skips approval for higher amounts
    - name: "trusted-agent-allow-high-value"
      enabled: true
      priority: 110  # Higher than approval rule
      conditions:
        all_of:
          - field: "agent_id"
            operator: "equals"
            value: "trusted-payment-agent"
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "TRUSTED_AGENT_ALLOWED"

    # Other agents need approval for high-value
    - name: "require-approval-high-value"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 1000
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"

    - name: "allow-standard-payments"
      enabled: true
      priority: 1
      conditions:
        all_of:
          - field: "tool"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "STANDARD_PAYMENT"
```

> **Note**: Rate limits apply uniformly to all agents via `metadata.rate_limits`. For different rate limits per agent, use separate policy sets per agent group.

### Example 27: Experimental Agent Sandbox

Route experimental agent to sandbox.

```yaml
- name: "sandbox-experimental-agent"
  enabled: true
  priority: 100
  conditions:
    all_of:
      - field: "agent_id"
        operator: "equals"
        value: "experimental-agent-v2"
  decision: "SANDBOX"
  reason_code: "EXPERIMENTAL_AGENT"
  metadata:
    sandbox_endpoint: "https://sandbox-api.example.com"
```

---

## Local Mode Specific Considerations

When using HIITL in local mode (embedded evaluator, SQLite, in-memory rate limiting), there are some important considerations to keep in mind when designing policies.

### Local Mode Behavior

| Feature | Local Mode | Hosted Mode |
|---------|-----------|-------------|
| **Evaluation** | In-process (< 1ms) | API call (~20-30ms) |
| **Audit Log** | SQLite (./hiitl_audit.db) | PostgreSQL (managed) |
| **Rate Limiting** | In-memory (per-instance) | PostgreSQL (shared across instances) |
| **Policy Storage** | File (./policy.yaml) | API-managed or file |

### Example 28: Local Mode Policy Template

Policy optimized for local mode usage.

```yaml
policy_set:
  name: "local-mode-policy"
  version: "v1.0.0"
  scope:
    org_id: "org_local"  # Use "org_local" for local mode testing
    environment: "dev"

  # Rate limiting (per-instance counters in local mode)
  metadata:
    rate_limits:
      - scope: "agent_id"
        window: "minute"
        limit: 10
        # NOTE: Counter resets on process restart in local mode

  rules:
    # Use simple, fast conditions for optimal performance
    - name: "block-high-risk-actions"
      enabled: true
      priority: 100
      conditions:
        all_of:
          - field: "sensitivity"
            operator: "contains"  # Fast: list membership check
            value: "irreversible"
          - field: "parameters.amount"
            operator: "greater_than"  # Fast: numeric comparison
            value: 1000
      decision: "BLOCK"
      reason_code: "HIGH_RISK_BLOCKED"

    - name: "default-allow"
      enabled: true
      priority: 1
      conditions: {}
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"
```

### Example 29: Performance-Optimized Policy

Minimize latency with fast conditions.

```yaml
# OPTIMIZED for < 1ms evaluation time
rules:
  # Fast: Simple equality check (priority first)
  - name: "block-specific-tool"
    enabled: true
    priority: 100
    conditions:
      all_of:
        - field: "tool"
          operator: "equals"  # Fastest: hash lookup
          value: "dangerous_tool"
    decision: "BLOCK"
    reason_code: "TOOL_BLOCKED"

  # Medium: Numeric comparison
  - name: "block-high-amounts"
    enabled: true
    priority: 90
    conditions:
      all_of:
        - field: "parameters.amount"
          operator: "greater_than"  # Fast: numeric
          value: 5000
    decision: "BLOCK"
    reason_code: "AMOUNT_TOO_HIGH"

  # Avoid expensive operations (regex, deep nesting)
  # This rule would be SLOW:
  # - field: "parameters.deeply.nested.field"
  #   operator: "matches"  # Slow: regex matching
  #   value: "complex_.*_regex"
```

### Rate Limiting Caveats in Local Mode

**Important**: Local mode rate limiting is **per-instance** and **in-memory**.

**Implications**:
1. **Not shared across instances**: Each instance has separate counters
2. **Lost on restart**: Counters reset when process restarts
3. **No persistence**: Not suitable for strict budget enforcement

**Example scenario**:
```yaml
# Policy-level rate limit: 10 requests per hour per agent
metadata:
  rate_limits:
    - scope: "agent_id"
      window: "hour"
      limit: 10

# Local mode behavior:
# Instance A: 10 requests OK
# Instance B: 10 requests OK
# Total: 20 requests (limit not enforced globally!)

# Hosted mode behavior:
# Instance A: 5 requests
# Instance B: 5 requests
# Total: 10 requests (limit enforced via PostgreSQL)
```

**Solutions for local mode**:
1. Accept per-instance limits for development
2. Use conservative limits (divide by expected instance count)
3. Migrate to hosted mode for production rate limiting

### Example 30: Local-Friendly Rate Limiting

Conservative rate limits for local mode.

```yaml
# Policy-level rate limits: conservative for local mode
metadata:
  rate_limits:
    - scope: "tool"     # Broader scope = fewer counters
      window: "minute"
      limit: 5          # Conservative: 5 per instance = 10-20 total with 2-4 instances
```

### SQLite Audit Log Considerations

**Local mode uses SQLite** for audit logging:

**Benefits**:
- ✅ Fast writes (< 2ms)
- ✅ Queryable via SQL
- ✅ No external dependencies

**Limitations**:
- ⚠️ Local file (not shared across instances)
- ⚠️ Grows over time (requires periodic cleanup)
- ⚠️ Not recommended for network filesystems (NFS)

**Best practices**:
```python
# Specify audit DB path explicitly
hiitl = HIITL(
    ...
    audit_db_path="./data/hiitl_audit.db",  # Ensure ./data/ exists
)

# For serverless (Lambda, etc.), use /tmp
audit_db_path="/tmp/hiitl_audit.db"  # Ephemeral, but fast

# For Docker, mount persistent volume
# docker run -v /host/data:/app/data ...
# audit_db_path="/app/data/hiitl_audit.db"
```

### Policy File Location

**Local mode loads policies from files**:

**Tips**:
1. **Use relative paths** for portability:
   ```python
   import os
   policy_path = os.path.join(os.path.dirname(__file__), "policy.yaml")
   ```

2. **Bundle policy in deployment**:
   ```dockerfile
   # Dockerfile
   COPY policy.yaml /app/policy.yaml
   ENV HIITL_POLICY_PATH=/app/policy.yaml
   ```

3. **Version with Git** (policy is code):
   ```bash
   git add policy.yaml
   git commit -m "feat: add payment approval threshold"
   ```

### Example 31: Local Mode Development Workflow

Policy designed for rapid iteration during development.

```yaml
policy_set:
  name: "dev-iteration-policy"
  version: "v0.1.0-dev"
  scope:
    org_id: "org_local"
    environment: "dev"

  rules:
    # Kill switch for quick disabling during debugging
    - name: "dev-kill-switch"
      enabled: false  # Toggle this during debugging
      priority: 1000
      conditions: {}
      decision: "KILL_SWITCH"
      reason_code: "DEV_DEBUGGING"

    # Log everything in dev (no rate limits)
    - name: "allow-all-log-everything"
      enabled: true
      priority: 1
      conditions: {}
      decision: "ALLOW"
      reason_code: "DEV_MODE_ALLOW_ALL"
```

### Migration to Hosted Mode

When ready for production, migrate from local → hosted:

**Changes needed**:
1. Update `org_id` from `"org_local"` to your real org ID
2. Update `environment` to `"prod"` (or `"stage"`)
3. SDK change: Add `api_key` and `server_url` (mode auto-detects to hosted)

**Policy remains the same** (copy-paste your YAML to hosted dashboard).

See: [Local → Hosted Migration Guide](local_to_hosted_migration.md)

---

## Policy Composition Tips

### 1. Use Priority Wisely

- **1000+**: Kill switches (emergency stop)
- **900-999**: Deny rules (blocks, suspensions)
- **100-399**: Threshold checks, approval requirements
- **1-99**: Allow rules, default behaviors

> **Note**: Rate limiting is configured at the policy-set level via `metadata.rate_limits`, not as individual rules with priorities. It applies post-evaluation to ALLOW decisions only.

### 2. Start with Allow-All, Layer Restrictions

Begin with a permissive policy and add restrictions incrementally:

```yaml
rules:
  # Start permissive
  - name: "allow-all-default"
    enabled: true
    priority: 1
    conditions: ...
    decision: "ALLOW"

  # Add restrictions layer by layer
  - name: "approval-layer"
    enabled: true
    priority: 100
    ...
```

### 3. Use Metadata for Context

Include metadata in rules for:
- SLA expectations
- Reviewer roles
- Sandbox endpoints
- Escalation teams

### 4. Test Policies Locally First

Use local mode with synthetic data to validate policies before deploying to production.

### 5. Version Your Policies

Always version policies (v1.0.0, v1.1.0, v2.0.0) to enable rollback and replay.

---

## Policy Deployment Workflow

1. **Write policy locally** (YAML file)
2. **Test with synthetic data** (local mode)
3. **Review with team** (policy is code, use Git)
4. **Deploy to dev** (test with real agent)
5. **Deploy to stage** (validate with production-like traffic)
6. **Deploy to prod** (monitor audit trail closely)
7. **Monitor and iterate** (adjust based on audit data)

---

**Need more examples?** Check:
- [Policy Format Spec](../specs/policy_format.md) for full syntax reference
- [GitHub Policy Templates](https://github.com/hiitlhq/hiitl/tree/main/policies) for industry-specific examples
- [Discord Community](https://discord.gg/hiitl) for questions and discussions
