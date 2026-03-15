# Kill Switch Runbook

Kill switches are the highest-priority enforcement mechanism in ECP. They are KILL_SWITCH rules within policies (priority 1000+) that block all matching actions when enabled.

## When to Use Kill Switches

- **Active incident**: Fraudulent activity, compromised credentials, data breach in progress
- **Runaway agent**: Agent executing unintended actions at scale
- **Regulatory halt**: Compliance requires immediate cessation of specific operations
- **Deployment rollback**: New agent behavior is causing harm, need instant stop

## How Kill Switches Work

Kill switches are regular policy rules with `decision: "KILL_SWITCH"`. They follow the same first-match-wins priority system — high priority (1000+) ensures they evaluate before ALLOW rules.

When `enabled: true`, the evaluator matches the rule and returns `allowed: false`. When `enabled: false`, the rule is skipped and lower-priority rules evaluate normally.

No new tables, models, or evaluation logic — just toggling a rule's `enabled` field within existing policy infrastructure.

## Local Mode

Edit the policy file directly:

```yaml
rules:
  - name: kill-switch-payments
    priority: 1000
    enabled: true          # Toggle this
    conditions:
      field: action
      operator: equals
      value: process_payment
    decision: KILL_SWITCH
    reason_code: KILL_SWITCH_PAYMENTS
```

The SDK's mtime-based caching detects the file change on the next `evaluate()` call. No restart needed.

## Hosted Mode

### List Kill Switches

```bash
curl -H "Authorization: Bearer $API_KEY" \
  https://api.hiitl.com/v1/kill-switches
```

### Activate a Kill Switch

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Fraud detected in payment processing", "activated_by": "ops_admin@company.com"}' \
  https://api.hiitl.com/v1/kill-switches/kill-switch-payments/activate
```

### Deactivate a Kill Switch

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Incident resolved, payments safe to resume", "deactivated_by": "ops_admin@company.com"}' \
  https://api.hiitl.com/v1/kill-switches/kill-switch-payments/deactivate
```

### Verify via Audit Trail

```bash
curl -H "Authorization: Bearer $READ_API_KEY" \
  https://api.hiitl.com/v1/policies/changes
```

Look for `change_type: "KILL_SWITCH_ACTIVATED"` or `"KILL_SWITCH_DEACTIVATED"` in the most recent entries.

## Common Scenarios

### Scenario 1: Emergency Payment Stop

1. Alert: fraudulent transactions detected
2. Activate: `POST /v1/kill-switches/kill-switch-payments/activate`
3. Verify: all subsequent payment evaluations return `KILL_SWITCH`
4. Investigate root cause
5. Fix and verify
6. Deactivate: `POST /v1/kill-switches/kill-switch-payments/deactivate`
7. Monitor: confirm normal payment flow resumes

### Scenario 2: Agent Misbehavior

1. Alert: agent executing unintended bulk operations
2. Activate agent-specific kill switch (conditions match `agent_id`)
3. Other agents continue operating normally
4. Fix agent configuration/logic
5. Deactivate kill switch

## Error Responses

| Status | Meaning | Action |
|--------|---------|--------|
| 404 | Rule not found | Check rule name matches policy |
| 400 | Not a KILL_SWITCH rule | Only KILL_SWITCH rules can be toggled via this API |
| 400 | Already in state | Kill switch already active/inactive |
| 403 | Insufficient scope | Use an API key with `admin` scope |
| 404 | No active policy | Create a policy first via `POST /v1/policies` |

## Policy Design Tips

- Name kill switches descriptively: `kill-switch-{scope}` (e.g., `kill-switch-all-payments`, `kill-switch-agent-bot-1`)
- Set priority to 1000+ to ensure they evaluate before all other rules
- Pre-create kill switches as `enabled: false` so they're ready to activate instantly
- Use specific conditions to limit blast radius (tool-specific, agent-specific)
