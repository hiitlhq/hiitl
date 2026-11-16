# Policy Cookbook - hiitl ECP

Practical policy examples for common scenarios. Copy, customize, and deploy.

Every rule needs a `description`. A rule is switched on and off with `lifecycle_stage`: `active` is the default and `disabled` skips the rule. `enabled` and a per-rule `mode` are refused when the policy loads. A snippet that shows a single rule goes in a policy set's `rules:` list.

These policies enforce only when the client is created with `mode="RESPECT_POLICY"` (TypeScript: `mode: 'RESPECT_POLICY'`). Under the default, `OBSERVE_ALL`, a BLOCK, approval or kill switch comes back as `OBSERVE`, with the rule's decision in `would_be`. Under `RESPECT_POLICY`, an action no rule matches is `BLOCK` with `NO_MATCHING_RULE`, so an enforcing policy carries ALLOW rules for what should go through.

```python
hiitl = HIITL(policy_path="./policy.yaml", mode="RESPECT_POLICY")
```

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
  description: "Simple Amount Threshold"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "require-approval-high-value"
      description: "Payments over $500 wait for a finance approver"
      priority: 100
      conditions:
        all_of:
          - field: "action"
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
      description: "Other payments proceed"
      priority: 1
      conditions:
        all_of:
          - field: "action"
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
  description: "Tiered Approval Thresholds"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "executive-approval-required"
      description: "Payments over $10,000 need the CFO"
      priority: 200
      conditions:
        all_of:
          - field: "action"
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
      description: "Payments over $1,000 need a finance manager"
      priority: 150
      conditions:
        all_of:
          - field: "action"
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
      description: "Payments over $500 need a team lead"
      priority: 100
      conditions:
        all_of:
          - field: "action"
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
      description: "Payments of $500 or less proceed"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "SMALL_PAYMENT_AUTO_APPROVED"
```

### Example 3: Amount + Confidence Threshold

Require approval for high-value OR low-confidence payments.

```yaml
- name: "require-approval-risky-payment"
  description: "Payments over $5,000, or over $1,000 at confidence below 0.8, need risk review"
  priority: 100
  conditions:
    all_of:
      - field: "action"
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

A rate limit is a `RATE_LIMIT` rule with a window: `rate_limit: {limit, window_seconds, scope}`. The scope is `action` (the default), `agent`, `user`, `org` or `user_action`. The rule never binds on its own. After evaluation, when the decision is ALLOW, the limiter reads each windowed rule that matched before it counts any. When one is over its limit, it returns `RATE_LIMIT` with reason code `RATE_LIMIT_EXCEEDED` and the rule's own remediation, and the call is counted in no window. Otherwise the call is counted in all of them. A blocked or escalated action is never counted. The limiter counts in every mode: under `OBSERVE_ALL`, a call past a limit is `OBSERVE` with `would_be: RATE_LIMIT`.

A policy set's `metadata.rate_limits`, the earlier set-level form, still loads: each entry is compiled to a rule like these. New policies write the rule.

### Example 4: Per-Agent Rate Limit

Limit each agent to 100 actions per hour.

```yaml
policy_set:
  name: "agent-rate-limited-policy"
  version: "v1.0.0"
  description: "Per-Agent Rate Limit"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "allow-payments"
      description: "Payments proceed"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"

    - name: "actions-per-agent-hour"
      description: "At most 100 actions an hour per agent"
      priority: 0
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "RATE_LIMIT"
      reason_code: "AGENT_RATE"
      rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}
```

When an action is ALLOW'd by the rules, the rate limiter checks if the agent has exceeded 100 actions in the current hour. If so, the decision is overridden to `RATE_LIMIT` with reason code `RATE_LIMIT_EXCEEDED`, and `decision.rate_limit` carries the scope, window, limit, current count and `reset_at`.

### Example 5: Per-User Rate Limit

Limit each end-user to 10 emails per day.

```yaml
policy_set:
  name: "user-email-limit"
  version: "v1.0.0"
  description: "Per-User Rate Limit"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "allow-emails"
      description: "Emails go out"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"

    - name: "emails-per-user-day"
      description: "At most 10 emails a day per user"
      priority: 0
      conditions:
        field: "action"
        operator: "equals"
        value: "send_email"
      decision: "RATE_LIMIT"
      reason_code: "EMAIL_RATE"
      rate_limit: {limit: 10, window_seconds: 86400, scope: "user"}
```

The `user` scope counts by the `user_id` passed to `evaluate()`.

### Example 6: Org-Wide Global Rate Limit

Limit all agents combined to 1000 database queries per minute.

```yaml
- name: "db-queries-per-org-minute"
  description: "At most 1,000 database queries a minute across the org"
  priority: 0
  conditions:
    field: "action"
    operator: "equals"
    value: "query_database"
  decision: "RATE_LIMIT"
  reason_code: "DB_QUERY_RATE"
  rate_limit: {limit: 1000, window_seconds: 60, scope: "org"}
```

### Example 7: Multiple Simultaneous Limits

Apply both per-agent and org-wide limits. The first limit exceeded wins.

```yaml
- name: "actions-per-agent-minute"
  description: "At most 60 actions a minute per agent"
  priority: 0
  conditions:
    field: "action"
    operator: "exists"
    value: true
  decision: "RATE_LIMIT"
  reason_code: "AGENT_BURST"
  rate_limit: {limit: 60, window_seconds: 60, scope: "agent"}

- name: "actions-per-org-hour"
  description: "At most 5,000 actions an hour across the org"
  priority: 0
  conditions:
    field: "action"
    operator: "exists"
    value: true
  decision: "RATE_LIMIT"
  reason_code: "ORG_HOURLY"
  rate_limit: {limit: 5000, window_seconds: 3600, scope: "org"}
```

This allows bursting up to 60 per agent per minute while capping the organization at 5000 per hour total.

---

## Permission Escalation

### Example 8: Admin Permission Grants

Require approval for granting admin permissions.

```yaml
- name: "require-approval-admin-grants"
  description: "Granting an admin, superuser or root role needs security review"
  priority: 200
  conditions:
    all_of:
      - field: "action"
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
  description: "Production scopes are never granted from dev"
  priority: 900
  conditions:
    all_of:
      - field: "environment"
        operator: "equals"
        value: "dev"
      - field: "action"
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
  description: "Roles other than read_only and basic_user go to security ops"
  priority: 150
  conditions:
    all_of:
      - field: "action"
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
  description: "Emergency stop for every payment"
  lifecycle_stage: "disabled"  # Set to "active" when an incident is declared
  priority: 1000  # Highest priority
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "process_payment"
  decision: "KILL_SWITCH"
  reason_code: "KILL_SWITCH_PAYMENTS_ACTIVE"
```

### Example 12: Kill Switch for Specific Agent

Stop one agent that's behaving abnormally.

```yaml
- name: "kill-switch-agent-123"
  description: "Stops agent-123"
  lifecycle_stage: "disabled"  # Set to "active" when the agent needs to be stopped
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
  description: "Stops every database delete"
  lifecycle_stage: "disabled"
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

A kill switch is turned on by setting its `lifecycle_stage` to `active`. A matching `KILL_SWITCH` rule binds before every other rule, whatever its priority.

- **Local policy file:** the next `evaluate()` reads the edited file.
- **Hosted service:** `POST /v1/kill-switches/{rule_name}/activate` (admin scope) saves a new policy version with the rule active. Hosted evaluation applies it from the next evaluation. An SDK in hybrid mode picks it up with its next policy sync, every 5 minutes by default.

See the [Kill Switch Runbook](kill_switch_runbook.md).

---

## Environment-Based Controls

### Example 14: Sandbox All Actions in Dev

Route all actions to sandbox endpoints in development.

```yaml
- name: "sandbox-all-in-dev"
  description: "Every dev action goes to the sandbox"
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

`SANDBOX` comes back with `allowed` true. Your code checks `decision.decision == "SANDBOX"` and sends the action to its sandbox.

### Example 15: Block Irreversible Actions in Dev

Don't allow irreversible actions in development.

```yaml
- name: "block-irreversible-in-dev"
  description: "Irreversible actions are refused in dev"
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

Lower rate limits in production for safety. Use separate policy sets per environment, each with its own windowed `RATE_LIMIT` rule.

```yaml
policy_set:
  name: "prod-email-policy"
  version: "v1.0.0"
  description: "Stricter Limits in Production"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    - name: "allow-emails"
      description: "Emails go out"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "send_email"
      decision: "ALLOW"
      reason_code: "EMAIL_ALLOWED"

    - name: "emails-per-agent-hour"
      description: "At most 50 emails an hour per agent"
      priority: 0
      conditions:
        field: "action"
        operator: "equals"
        value: "send_email"
      decision: "RATE_LIMIT"
      reason_code: "EMAIL_RATE"
      rate_limit: {limit: 50, window_seconds: 3600, scope: "agent"}  # Conservative in prod (dev might use 100)
```

---

## Cost-Based Budgets

### Example 17: Dollar Spend Limit

Block actions if estimated cost exceeds budget.

```yaml
- name: "block-over-budget"
  description: "Calls estimated above $100 are refused"
  priority: 100
  conditions:
    all_of:
      - field: "cost_estimate.dollars"
        operator: "greater_than"
        value: 100
  decision: "BLOCK"
  reason_code: "COST_EXCEEDS_BUDGET"
```

The caller supplies the estimate: `hiitl.evaluate("generate_report", cost_estimate={"dollars": 120.0})`, or `cost_estimate: { dollars: 120 }` in TypeScript. The estimate is the envelope's own (`tokens`, `dollars`, `api_calls`); a key it does not define is refused, naming it.

### Example 18: Token Budget per Agent (Not built)

> **Note**: A budget that counts tokens or dollars over a window is not built. A rate limit counts calls. A key a rate limit does not define, such as `dimension`, is refused when the policy loads. To cap the cost of a single call, use Example 17.

### Example 19: Approval for Expensive Actions

Require approval for actions estimated to cost > $10.

```yaml
- name: "require-approval-expensive"
  description: "Calls estimated above $10 need an ops lead"
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
  description: "Actions marked both money and identity go to fraud prevention"
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
  description: "Regulated-data actions in dev and stage go to the sandbox"
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
  description: "Only the customer-service and compliance agents touch PII"
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
  description: "Comprehensive Payment Policy"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    # Layer 1: Kill switch (emergency stop)
    - name: "kill-switch-all-payments"
      description: "Emergency stop for every payment"
      lifecycle_stage: "disabled"
      priority: 1000
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "KILL_SWITCH"
      reason_code: "PAYMENTS_KILL_SWITCH_ACTIVE"

    # Layer 2: Block suspended agents
    - name: "block-suspended-agents"
      description: "Suspended agents cannot pay"
      priority: 900
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "agent_id"
            operator: "in"
            value: ["legacy-payout-agent"]  # Add an agent here to suspend it
      decision: "BLOCK"
      reason_code: "AGENT_SUSPENDED"

    # Layer 3: Approval workflows
    - name: "require-approval-high-value"
      description: "Payments over $1,000 wait for a finance approver"
      priority: 100
      conditions:
        all_of:
          - field: "action"
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
      description: "Payments over $500 at confidence below 0.8 need risk review"
      priority: 90
      conditions:
        all_of:
          - field: "action"
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
      description: "Other payments proceed"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "STANDARD_PAYMENT"

    # Rate limit: counted after evaluation, on ALLOW decisions
    - name: "payments-per-agent-hour"
      description: "At most 100 payments an hour per agent"
      priority: 0
      conditions:
        field: "action"
        operator: "equals"
        value: "process_payment"
      decision: "RATE_LIMIT"
      reason_code: "PAYMENT_RATE"
      rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}
```

**How rate limiting interacts**: Rules are evaluated first (kill switch → blocks → approvals → allow). Only actions that receive an ALLOW decision are then counted against the windowed `RATE_LIMIT` rule. Blocked or escalated actions never count against rate limits.

---

## Time-Based Rules

A condition does not read the clock. The caller passes the time facts a rule needs as parameters, in its own timezone. For a fixed window of dates, a rule's `valid_from` and `valid_to` (ISO 8601) skip it outside that window.

### Example 24: After-Hours Approval

Require approval for high-value actions outside business hours.

```yaml
- name: "after-hours-approval"
  description: "Payments over $500 outside 9 AM - 5 PM need the on-call approver"
  priority: 120
  conditions:
    all_of:
      - field: "action"
        operator: "equals"
        value: "process_payment"
      - field: "parameters.amount"
        operator: "greater_than"
        value: 500
      - field: "parameters.hour_of_day"
        operator: "not_in"
        value: [9, 10, 11, 12, 13, 14, 15, 16, 17]  # 9 AM - 5 PM
  decision: "REQUIRE_APPROVAL"
  reason_code: "AFTER_HOURS_PAYMENT"
  metadata:
    sla_hours: 12
    reviewer_role: "on_call_approver"
```

The caller passes the hour: `parameters={"amount": 900, "currency": "usd", "hour_of_day": 22}`.

### Example 25: Weekend Restrictions

Block sensitive operations on weekends.

```yaml
- name: "block-sensitive-on-weekends"
  description: "Regulated actions are refused on weekends"
  priority: 900
  conditions:
    all_of:
      - field: "sensitivity"
        operator: "contains"
        value: "regulated"
      - field: "parameters.day_of_week"
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
  description: "Trusted Agent Exemption"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"

  rules:
    # Trusted agent skips approval for higher amounts
    - name: "trusted-agent-allow-high-value"
      description: "The trusted payment agent pays without approval"
      priority: 110  # Higher than approval rule
      conditions:
        all_of:
          - field: "agent_id"
            operator: "equals"
            value: "trusted-payment-agent"
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "TRUSTED_AGENT_ALLOWED"

    # Other agents need approval for high-value
    - name: "require-approval-high-value"
      description: "Payments over $1,000 from other agents need approval"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 1000
      decision: "REQUIRE_APPROVAL"
      reason_code: "HIGH_VALUE_PAYMENT"

    - name: "allow-standard-payments"
      description: "Other payments proceed"
      priority: 1
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "process_payment"
      decision: "ALLOW"
      reason_code: "STANDARD_PAYMENT"

    - name: "actions-per-agent-hour"
      description: "At most 100 actions an hour per agent"
      priority: 0
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "RATE_LIMIT"
      reason_code: "AGENT_RATE"
      rate_limit: {limit: 100, window_seconds: 3600, scope: "agent"}
```

> **Note**: A rate limit applies to every call its rule's conditions match. For a different limit per agent group, write one windowed rule per group, with an `agent_id` condition (`operator: "in"`, the group's agents).

The trusted agent's ALLOW binds over the approval rule because both are in the same class and it has the higher priority. A matching `BLOCK` or `KILL_SWITCH` rule would still bind over it.

### Example 27: Experimental Agent Sandbox

Route experimental agent to sandbox.

```yaml
- name: "sandbox-experimental-agent"
  description: "The experimental agent runs against the sandbox"
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

When using hiitl in local mode (embedded evaluator, SQLite, in-memory rate limiting), there are some important considerations to keep in mind when designing policies.

### Local Mode Behavior

| Feature | Local Mode | Hybrid Mode | Hosted Mode |
|---------|-----------|-------------|-------------|
| **Evaluation** | In-process (< 1ms) | In-process | API call (~20-30ms) |
| **Audit Log** | SQLite (./hiitl_audit.db) | SQLite (./hiitl_audit.db), uploaded to the hosted service in the background | PostgreSQL (managed) |
| **Rate Limiting** | In-memory (per-instance) | In-memory (per-instance) | PostgreSQL (shared across instances) |
| **Policy Storage** | File (`policy_path`) | Synced from the hosted service; `policy_path` is the fallback | The org's active policy on the hosted service |

### Example 28: Local Mode Policy Template

Policy optimized for local mode usage.

```yaml
policy_set:
  name: "local-mode-policy"
  version: "v1.0.0"
  description: "Local Mode Policy Template"
  scope:
    org_id: "org_devlocal0000000000"  # Local mode does not read the set's scope; the hosted service requires your org_id here
    environment: "dev"

  rules:
    # Use simple, fast conditions for optimal performance
    - name: "block-high-risk-actions"
      description: "Irreversible actions over $1,000 are refused"
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
      description: "Everything else proceeds"
      priority: 1
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"

    # Rate limiting (per-instance counters in local mode)
    - name: "actions-per-agent-minute"
      description: "At most 10 actions a minute per agent"
      priority: 0
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "RATE_LIMIT"
      reason_code: "AGENT_RATE"
      rate_limit: {limit: 10, window_seconds: 60, scope: "agent"}
      # NOTE: Counter resets on process restart in local mode
```

### Example 29: Performance-Optimized Policy

Minimize latency with fast conditions.

```yaml
# OPTIMIZED for < 1ms evaluation time
policy_set:
  name: "performance-optimized"
  version: "v1.0.0"
  description: "Rules ordered so the common call matches first"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"
  rules:
    # Fast: Simple equality check (priority first)
    - name: "block-specific-tool"
      description: "dangerous_tool is never run"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"  # Fast: one equality comparison
            value: "dangerous_tool"
      decision: "BLOCK"
      reason_code: "TOOL_BLOCKED"

    # Medium: Numeric comparison
    - name: "block-high-amounts"
      description: "Amounts over $5,000 are refused"
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

**Important**: Local mode rate limiting is **per-instance** and **in-memory**. Hybrid mode counts the same way: counters are not synced.

**Implications**:
1. **Not shared across instances**: Each instance has separate counters
2. **Lost on restart**: Counters reset when process restarts
3. **No persistence**: Not suitable for strict budget enforcement

**Example scenario**:
```yaml
# Rate limit rule: 10 requests per hour per agent
- name: "actions-per-agent-hour"
  description: "At most 10 actions an hour per agent"
  priority: 0
  conditions: {field: "action", operator: "exists", value: true}
  decision: "RATE_LIMIT"
  reason_code: "AGENT_RATE"
  rate_limit: {limit: 10, window_seconds: 3600, scope: "agent"}

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
3. Use hosted evaluation for production rate limiting

### Example 30: Local-Friendly Rate Limiting

Conservative rate limits for local mode.

```yaml
# Rate limit rule: conservative for local mode
- name: "calls-per-action-minute"
  description: "At most 5 calls a minute per action, per instance"
  priority: 0
  conditions: {field: "action", operator: "exists", value: true}
  decision: "RATE_LIMIT"
  reason_code: "ACTION_RATE"
  rate_limit: {limit: 5, window_seconds: 60, scope: "action"}  # Conservative: 5 per instance = 10-20 total with 2-4 instances
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
    policy_path="./policy.yaml",
    mode="RESPECT_POLICY",
    audit_db_path="./data/hiitl_audit.db",  # The SDK creates ./data/ if it is missing
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

   Both SDKs read `HIITL_POLICY_PATH` when no `policy_path` is passed, so an enforcing client needs only its mode:

   ```python
   hiitl = HIITL(mode="RESPECT_POLICY")  # policy_path from HIITL_POLICY_PATH
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
  version: "v0.1.0"
  description: "Local Mode Development Workflow"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"

  rules:
    # Kill switch for quick disabling during debugging
    - name: "dev-kill-switch"
      description: "Stops every action while debugging"
      lifecycle_stage: "disabled"  # Set to "active" while debugging
      priority: 1000
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "KILL_SWITCH"
      reason_code: "DEV_DEBUGGING"

    # Log everything in dev (no rate limits)
    - name: "allow-all-log-everything"
      description: "Everything proceeds in dev"
      priority: 1
      conditions:
        field: "action"
        operator: "exists"
        value: true
      decision: "ALLOW"
      reason_code: "DEV_MODE_ALLOW_ALL"
```

### Migration to Hosted Mode

When ready for production, migrate from local → hosted:

**Changes needed**:
1. Set the policy set's `scope.org_id` to your real org ID. The hosted service refuses a policy whose `scope` does not match the API key's org and environment.
2. Update `environment` to `"prod"` (or `"stage"`)
3. SDK change:
   - Python: an `api_key` gives hybrid mode (local evaluation, policies synced from the hosted service). Hosted evaluation needs `server_url` and `evaluation="remote"` as well.
   - TypeScript: an `api_key` alone gives hybrid mode; `api_key` + `server_url` gives hosted evaluation.

**Policy remains the same.** The hosted service takes the policy set as JSON: `POST /v1/policies` with `{"policy_set": {...}}` and an admin-scope key; the change is recorded under that key. It becomes the one active policy for that org and environment, and the previous one is deactivated.

See: [Local → Hosted Migration Guide](local_to_hosted_migration.md)

---

## Policy Composition Tips

### 1. Use Priority Wisely

- **1000+**: Kill switches (emergency stop)
- **900-999**: Deny rules (blocks, suspensions)
- **100-399**: Threshold checks, approval requirements
- **1-99**: Allow rules, default behaviors

Precedence is DENY wins: a matching `KILL_SWITCH` rule binds over everything, a matching `BLOCK` over every other decision, whatever their priorities. Priority orders rules within each class, then the order they are written in.

> **Note**: A windowed `RATE_LIMIT` rule never binds on its own, wherever its priority puts it. It is counted after evaluation, on ALLOW decisions only.

### 2. Start with Allow-All, Layer Restrictions

Begin with a permissive policy and add restrictions incrementally:

```yaml
policy_set:
  name: "layered-restrictions"
  version: "v1.0.0"
  description: "Allow everything, then layer restrictions on top"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "prod"
  rules:
    # Start permissive
    - name: "allow-all-default"
      description: "Everything not caught below proceeds"
      priority: 1
      conditions: {field: "action", operator: "exists", value: true}
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"

    # Add restrictions layer by layer
    - name: "approval-layer"
      description: "Refunds over $500 wait for approval"
      priority: 100
      conditions:
        all_of:
          - field: "action"
            operator: "equals"
            value: "issue_refund"
          - field: "parameters.amount"
            operator: "greater_than"
            value: 500
      decision: "REQUIRE_APPROVAL"
      reason_code: "LARGE_REFUND"
```

### 3. Use Metadata for Context

A rule's `metadata` is free-form: it travels with the rule and is not copied into the decision. Use it to record:
- SLA expectations
- Reviewer roles
- Sandbox endpoints
- Escalation teams

What a reviewer is sent (endpoint, SLA timeout, response options) lives on the route the rule names in `route:`. That route fills `decision.escalation_context`.

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
- [Pattern Repository](../../patterns/README.md) for starter policies by domain
- [GitHub](https://github.com/hiitlhq/hiitl) for questions and issues
