# hiitl — TypeScript SDK

The control point for AI agents. TypeScript SDK with embedded policy evaluator.

## Install

```bash
npm install @hiitl/sdk
```

## Quick start

```typescript
import { HIITL } from '@hiitl/sdk';

// Zero config — observe policy decisions; an audit write failure still blocks
const hiitl = new HIITL();

const decision = await hiitl.evaluate({
  action: 'send_email',
  parameters: { to: 'user@example.com', subject: 'Order update' },
});

if (decision.allowed) {
  await sendEmail(...);
}
```

With no policy and a successful audit write, a new call comes back `OBSERVE` with `allowed` true and is recorded in the local audit log. A repeated idempotency key within the dedup window reuses its first decision without another row. `would_be` says what enforcement would decide: `BLOCK` with `NO_MATCHING_RULE`, because no rule allows the action yet.

`evaluate()` returns a `Decision` in local mode and a `Promise<Decision>` in hybrid and hosted mode. `await` it in every mode.

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

```typescript
const hiitl = new HIITL({
  agent_id: 'payment-agent',
  policy_path: './policy.yaml',
  mode: 'RESPECT_POLICY',
});

const decision = await hiitl.evaluate({
  action: 'process_payment',
  parameters: { amount: 5000.00, currency: 'USD' },
});

if (decision.allowed) {
  await processPayment(...);
} else if (decision.decision === 'REQUIRE_APPROVAL') {
  await sendForReview(decision); // your review step; hiitl returns the decision
} else if (decision.decision === 'BLOCK') {
  logBlocked(decision);
}
```

Under `RESPECT_POLICY`, an action no rule matches is blocked (`NO_MATCHING_RULE`), so the policy has an `ALLOW` rule for the payments it lets through.

Without `mode: 'RESPECT_POLICY'`, the SDK observes. A decision that allows the call comes back as itself. A policy decision that would stop the call comes back `OBSERVE`, with `allowed` true and `would_be` set to the rule's decision. A call past a windowed rate limit comes back `OBSERVE` with `would_be: RATE_LIMIT` under `OBSERVE_ALL`; under `RESPECT_POLICY` it comes back `RATE_LIMIT`. Failures such as an unwritable audit record still block in every mode.

## Hybrid and hosted mode

```typescript
// Hybrid: an api_key alone turns on sync. Evaluation stays local and
// in-process; policies, kill switches and audit records sync with the
// hosted service.
const hiitl = new HIITL({
  agent_id: 'payment-agent',
  org_id: 'org_yourcompany1234567',
  api_key: process.env.HIITL_API_KEY,
  environment: 'prod',
  mode: 'RESPECT_POLICY',
});

// Hosted: remote evaluation is an explicit opt-in. The SDK signs each
// request to the server, which evaluates against the org's active policy.
const hosted = new HIITL({
  agent_id: 'payment-agent',
  org_id: 'org_yourcompany1234567',
  api_key: process.env.HIITL_API_KEY,
  server_url: 'https://api.hiitl.com',
  signature_key: process.env.HIITL_SIGNATURE_KEY,
  evaluation: 'remote',
  environment: 'prod',
});

// Same evaluate() call, same Decision object
const decision = await hiitl.evaluate({
  action: 'process_payment',
  parameters: { amount: 500 },
});
```

## API

### `new HIITL(options?)`

All options are optional. `new HIITL()` works with no arguments.

| Option | Default | Description |
|--------|---------|-------------|
| `agent_id` | `'default'` | Agent identifier |
| `environment` | `'dev'` | `dev`, `stage`, or `prod` |
| `org_id` | `'org_devlocal0000000000'` | Organization ID (`org_` and 18 or more lowercase letters or digits) |
| `mode` | `'OBSERVE_ALL'` | `OBSERVE_ALL` or `RESPECT_POLICY` |
| `policy_path` | `undefined` | Path to policy file (YAML or JSON). In hybrid mode, the fallback when no synced policy is available |
| `audit_db_path` | `'./hiitl_audit.db'` | SQLite audit log path |
| `enable_rate_limiting` | `true` | Apply the policy's rate limits |
| `routes_path` | `undefined` | Directory of route config files |
| `signature_key` | `undefined` | The API key's signing secret (HMAC-SHA256); required for hosted evaluation |
| `api_key` | `undefined` | API key. Alone, it turns on hybrid mode: local evaluation with background sync to `https://api.hiitl.com` |
| `server_url` | `undefined` | HTTPS service URL. In hybrid mode, the sync target; required for hosted evaluation |
| `evaluation` | `'local'` | Set `'remote'` with `api_key`, `signature_key` and `server_url` for hosted evaluation |
| `timeout` | `5` | Hosted-mode request timeout in seconds, from 0.1 to 30 |
| `max_retries` | `3` | Hosted-mode retries on transient failures |
| `sync` | `true` | Set `false` to stay in local mode when an `api_key` is set |
| `cache_dir` | `undefined` | Hybrid-mode disk cache directory (default `~/.hiitl/cache/`) |
| `sync_init_timeout` | `10` | Hybrid-mode first-sync timeout in seconds |
| `cold_start_behavior` | `'warn-and-observe'` | Hybrid mode, when there is no cache and the first sync fails: `warn-and-observe` (log a warning and continue), `fail-closed` (the first `evaluate()` throws `ColdStartError`), or `observe-silent` (log at INFO) |
| `principal_verifier` | `undefined` | Function that checks a `principal_token` passed to `evaluate()` and returns its claims |
| `route_fetch` | global `fetch` | The `fetch` used to ask sync routes |

### `hiitl.evaluate(options): Decision | Promise<Decision>`

| Option | Required | Description |
|--------|----------|-------------|
| `action` | Yes | Action name (e.g., `'send_email'`) |
| `parameters` | No | Action parameters object |
| `target` | No | Target resource object |
| `operation` | No | Operation type (default: `'execute'`) |
| `user_id` | No | User identifier |
| `session_id` | No | Session identifier |
| `agent_id` | No | Overrides the `agent_id` set at init |
| `confidence` | No | Agent confidence, 0 to 1 |
| `reason` | No | The agent's reason for the action |
| `sensitivity` | No | Sensitivity labels |
| `cost_estimate` | No | Estimated cost |
| `requested_scopes` | No | Permission scopes the call requests |
| `idempotency_key` | No | Idempotency key (generated if omitted) |
| `principal_token` | No | Token for the configured `principal_verifier` |

### `Decision`

| Property | Type | Description |
|----------|------|-------------|
| `.allowed` | `boolean` | Can the action proceed? |
| `.decision` | `string` | Decision type (`ALLOW`, `BLOCK`, etc.) |
| `.reason_codes` | `string[]` | Why this decision was made |
| `.policy_version` | `string` | Policy version used |
| `.would_be` | `string` | What enforcement would decide (OBSERVE only) |
| `.would_be_reason_codes` | `string[]` | The reason codes enforcement would return (OBSERVE only) |
| `.remediation` | `object` | How to fix a blocked call, when the rule defines it |
| `.timing` | `object` | `{ ingest_ms, evaluation_ms, total_ms }` |

The TypeScript `Decision` is a plain object. Test `decision.allowed`, or compare `decision.decision` with a decision type such as `'BLOCK'`.

## Packages

This SDK consists of two packages:

- **`@hiitl/core`** — Policy evaluator and types (used internally)
- **`@hiitl/sdk`** — Developer-facing SDK (install this one)

## Requirements

- Node.js 22+

## Documentation

- [TypeScript Quickstart](../docs/onboarding/quickstart_typescript.md)
- [Full Documentation](../docs/)
- [Examples](../examples/)

## License

[Apache-2.0](../LICENSE)
