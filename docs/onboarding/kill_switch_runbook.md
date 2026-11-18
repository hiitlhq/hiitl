# Kill Switch Runbook

Kill switches are the highest-priority enforcement mechanism in ECP. They are KILL_SWITCH rules within policies that block all matching actions while they are active.

## When to Use Kill Switches

- **Active incident**: Fraudulent activity, compromised credentials, data breach in progress
- **Runaway agent**: Agent executing unintended actions at scale
- **Regulatory halt**: Compliance requires immediate cessation of specific operations
- **Deployment rollback**: New agent behavior is causing harm, need a fast stop

## How Kill Switches Work

Kill switches are regular policy rules with `decision: "KILL_SWITCH"`. A matching kill switch binds over a matching rule of any other decision, whatever their priorities: DENY wins (KILL_SWITCH, then BLOCK, then every other decision). Priority orders rules with the same decision.

When the rule's `lifecycle_stage` is `active`, the evaluator matches the rule and returns `KILL_SWITCH` with `allowed: false`. When it is `disabled`, the rule is skipped and the other rules evaluate normally.

The kill switch blocks only where policy is enforced: hosted evaluation, or an SDK running with `mode="RESPECT_POLICY"` (TypeScript: `mode: 'RESPECT_POLICY'`). Under the SDK's default mode, `OBSERVE_ALL`, a matching kill switch comes back `OBSERVE` with `allowed: true` and `would_be: "KILL_SWITCH"`. It is recorded, not applied.

No new tables, models, or evaluation logic — just toggling a rule's `lifecycle_stage` within existing policy infrastructure.

## Local Mode

Edit the policy file directly:

```yaml
policy_set:
  name: "payments-kill-switches"
  version: "v1.0.0"
  description: "Payment kill switches for local mode"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"
  rules:
    - name: kill-switch-payments
      description: "Emergency stop for all payment processing"
      priority: 1000
      lifecycle_stage: active   # Toggle this: active / disabled
      conditions:
        field: action
        operator: equals
        value: process_payment
      decision: KILL_SWITCH
      reason_code: KILL_SWITCH_PAYMENTS
```

The SDK checks the file's modification time on each `evaluate()` call, so the first call after you save the file uses the new policy. No restart needed.

In hybrid mode the policy file is only a fallback: a policy synced from the hosted service takes precedence. Toggle the kill switch through the API instead.

## Hosted and Hybrid Mode

These calls change the policy held by the hosted service. Hosted evaluation applies the change from the next evaluation. An SDK in hybrid mode picks it up with its next policy sync, every 5 minutes by default; until a sync succeeds, it evaluates against the policy it already has.

### List Kill Switches

```bash
curl -H "Authorization: Bearer $API_KEY" \
  https://api.hiitl.com/v1/kill-switches
```

Each kill switch in the response has `enabled: true` when its rule's `lifecycle_stage` is `active`. The dashboard sidebar lists the active kill switches; activating and deactivating are done through the API.

### Activate a Kill Switch

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Fraud detected in payment processing"}' \
  https://api.hiitl.com/v1/kill-switches/kill-switch-payments/activate
```

### Deactivate a Kill Switch

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Incident resolved, payments safe to resume"}' \
  https://api.hiitl.com/v1/kill-switches/kill-switch-payments/deactivate
```

### Verify via Audit Trail

```bash
curl -H "Authorization: Bearer $READ_API_KEY" \
  https://api.hiitl.com/v1/policies/changes
```

Look for `change_type: "KILL_SWITCH_ACTIVATED"` or `"KILL_SWITCH_DEACTIVATED"` in the most recent entries. Each record's `changed_by`, and the kill switch's `activated_by` or `deactivated_by`, is the API key that made the call, read from the key the service authenticated; a body naming someone (`activated_by`, `deactivated_by`) is refused with `422`, naming the field.

## Common Scenarios

### Scenario 1: Emergency Payment Stop

1. Alert: fraudulent transactions detected
2. Activate: `POST /v1/kill-switches/kill-switch-payments/activate`
3. Verify: payment evaluations return `KILL_SWITCH` (hosted evaluation from the next call; hybrid SDKs after their next policy sync)
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
- A kill switch binds over other decisions whatever its priority. By convention, give it priority 1000+; priority orders kill switches among themselves
- Pre-create kill switches as `lifecycle_stage: disabled` so they're ready to activate when you need them
- Use specific conditions to limit blast radius (action-specific, agent-specific)
