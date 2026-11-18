# Migrating to Hosted Evaluation

How to migrate from local evaluation to hosted evaluation with the ECP server.

## When to Migrate

**Local evaluation is ideal for:**
- Single-instance applications
- SQLite audit is sufficient
- Need < 10ms latency
- Offline environments

**Hosted evaluation is ideal for:**
- Multi-instance deployments
- Persistent rate limiting across instances
- Centralized audit log (PostgreSQL)
- Team collaboration (dashboard)
- Compliance audit trail

## How Mode Detection Works

The SDK determines evaluation mode from its resolved settings: a constructor argument, else its `HIITL_*` environment variable (see [Step 6](#step-6-update-environment-variables)). Both SDKs use the same table.

| Settings | Evaluation Mode | Description |
|----------|-----------------|-------------|
| no `api_key` | **Local** | In-process evaluation against local policy files |
| `api_key` + `server_url` + remote evaluation | **Hosted** | Evaluation delegated to the hosted service |
| `api_key` (with or without `server_url`) | **Hybrid** | In-process evaluation against policies synced from the hosted service |
| `api_key` + `sync` false | **Local (forced)** | Local evaluation even with a key at hand |

The switch for hosted evaluation is the `evaluation` setting: `"local"` by default, `"remote"` for hosted (`evaluation="remote"` in Python, `evaluation: 'remote'` in TypeScript, or `HIITL_EVALUATION=remote`). In hybrid mode, `server_url` sets the address the SDK syncs with (default `https://api.hiitl.com`).

## Migration Overview

Migration requires adding `api_key`, `server_url` and remote evaluation to your constructor or its environment. Your `evaluate()` calls stay the same; in TypeScript, `await` every call, because hosted and hybrid evaluation return a Promise.

| Component | Local | Hosted | Migration Effort |
|-----------|-------|--------|------------------|
| **SDK Code** | `policy_path` only | Add `api_key` + `server_url` + `evaluation` remote | 3 parameters |
| **Policy** | YAML file | API-managed | Low |
| **Audit Log** | SQLite (local) | PostgreSQL (hosted) | Automatic |
| **Rate Limiting** | In-memory | Hosted database (shared) | Automatic |
| **API Key** | None | Required | Sign up |

**Time required**: 15-30 minutes

---

## Step-by-Step Migration

### Step 1: Sign Up for Hosted hiitl

1. Go to https://app.hiitl.com and sign up (your organization is created with your account)
2. Under **Settings → API Keys**, create a key for the environment you are migrating (`dev`, `stage` or `prod`). A key holds one environment and the scopes you pick: hosted evaluation needs `evaluate`; uploading policies needs `admin`
3. Copy your API key and org ID

**Environment variables**:
```bash
export HIITL_API_KEY="sk_prod_..."
export HIITL_SERVER_URL="https://api.hiitl.com"
export HIITL_ORG_ID="org_abc123..."  # From dashboard
```

---

### Step 2: Update SDK Configuration

#### Python

**Before (local evaluation)**:
```python
from hiitl import HIITL

hiitl = HIITL(
    environment="dev",
    agent_id="my-agent",
    policy_path="./policy.yaml",
    audit_db_path="./hiitl_audit.db",
)
```

**After (hosted evaluation)**:
```python
import os
from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),  # Hosted service endpoint
    evaluation="remote",                       # Triggers hosted evaluation
    signature_key=os.getenv("HIITL_SIGNATURE_KEY"),  # the API key's signing secret, shown when the key was created
    environment="prod",  # Or "dev"/"stage"
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID"),  # Real org ID from dashboard
    # No policy_path needed - managed via the API
    # No audit_db_path needed - managed by hosted service
)
```

#### TypeScript

**Before (local evaluation)**:
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'dev',
  agent_id: 'my-agent',
  policy_path: './policy.yaml',
  audit_db_path: './hiitl_audit.db',
});
```

**After (hosted evaluation)**:
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY,
  server_url: process.env.HIITL_SERVER_URL, // Hosted service endpoint
  signature_key: process.env.HIITL_SIGNATURE_KEY, // the API key's signing secret, shown when the key was created
  evaluation: 'remote',                     // Triggers hosted evaluation
  environment: 'prod',  // Or 'dev'/'stage'
  agent_id: 'my-agent',
  org_id: process.env.HIITL_ORG_ID,  // Real org ID from dashboard
  // No policy_path needed - managed via the API
  // No audit_db_path needed - managed by hosted service
});
```

Hosted mode in TypeScript requires `environment`, `agent_id` and `org_id`.

**That's it!** Your `evaluate()` calls stay the same (in TypeScript, make sure each one is awaited). Python selects hosted mode from `api_key` with `evaluation="remote"` (and needs `server_url`); TypeScript selects it from `api_key` with `server_url`. Leave out `evaluation="remote"` (Python) or `server_url` (TypeScript) and the SDK runs in hybrid mode instead: see Option C below.

---

### Step 3: Upload Your Policy

#### Option A: Dashboard

The dashboard's **Policies** page (https://app.hiitl.com) lists the policies you have uploaded. It does not create them: upload through the API (Option B).

#### Option B: Upload via API

```bash
curl -X POST https://api.hiitl.com/v1/policies \
  -H "Authorization: Bearer $HIITL_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "policy_set": {
    "name": "my-policy",
    "version": "v1.0.0",
    "scope": {
      "org_id": "$HIITL_ORG_ID",
      "environment": "prod"
    },
    "rules": [...]
  }
}
EOF
```

The body is JSON, so convert your YAML file first. The upload needs a key with the `admin` scope, and its change record names that key; for hosted evaluation, give your agents a separate `evaluate` key. `scope.org_id` and `scope.environment` must be the key's own organization and environment, or the upload is refused with `400 POLICY_VALIDATION_ERROR`. Each upload becomes the active policy for that organization and environment.

#### Option C: Hybrid Mode (Keep Evaluating In-Process)

With an `api_key` and no hosted switch (no `evaluation="remote"` in Python, no `server_url` in TypeScript), the SDK runs in hybrid mode: it evaluates in-process against policies it syncs from the hosted service. A `policy_path` is a fallback, not an override:

```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    policy_path="./policy.yaml",  # Fallback while no synced policy is available
    ...
)
```

- **Policy source**: a synced policy takes precedence. Python reads the file only when the first sync fails and there is no cached policy on disk; TypeScript reads it whenever the cache holds no policy.
- **What syncs**: the SDK pulls policies and routes (every 300 seconds by default) and uploads the not-yet-uploaded records in its current audit file (every 30 seconds by default). The Python SDK also uploads telemetry; the TypeScript SDK does not.
- **Cache**: synced policies are kept on disk in `cache_dir` (default `~/.hiitl/cache/`), so a restart evaluates from the cache before its first sync.
- **Cold start**: with no cache and no fallback file, if the first sync fails or times out, `cold_start_behavior` decides: `"warn-and-observe"` (default) logs a warning and carries on with no policy until a sync succeeds (under the default `OBSERVE_ALL` mode, every action is observed), `"observe-silent"` does the same without the warning, and `"fail-closed"` raises `ColdStartError` (Python from the constructor, TypeScript from the first `evaluate()`).
- **Rate limits**: counted in memory, per process, as in local mode.

**Trade-off**:
- API: Centralized, versioned, team collaboration
- File: Simple, no network dependency, works offline

---

### Step 4: Update Policy Scope

**Important**: A policy you upload must name your real org ID and the environment of the key you upload it with. Every set names a well-formed scope (an `org_id` in the envelope's form, `org_` and 16 or more letters and digits, and one of `dev`, `stage`, `prod`); the local SDK does not compare it with the call, so in a local file the SDK's own default org, `org_devlocal0000000000`, will do.

**Before** (`policy.yaml` for local evaluation):
```yaml
policy_set:
  name: "payments-policy"
  version: "v1.0.0"
  description: "Payment controls"
  scope:
    org_id: "org_devlocal0000000000"  # Local testing value
    environment: "dev"
  rules:
    - name: "allow-payments"
      description: "Payments proceed"
      priority: 100
      conditions:
        field: "action"
        operator: "equals"
        value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"
```

**After** (for hosted evaluation):
```yaml
policy_set:
  name: "payments-policy"
  version: "v1.0.0"
  description: "Payment controls"
  scope:
    org_id: "org_8f3a2c1d9e7b4a60"  # Real org ID from dashboard
    environment: "prod"  # Or "dev"/"stage"
  rules:
    - name: "allow-payments"
      description: "Payments proceed"
      priority: 100
      conditions:
        field: "action"
        operator: "equals"
        value: "process_payment"
      decision: "ALLOW"
      reason_code: "PAYMENT_ALLOWED"
```

---

### Step 5: Keep Your Local Audit Logs (Optional)

If you need the audit records from before the migration:

#### Export from SQLite

```bash
sqlite3 hiitl_audit.db <<EOF
.mode json
.output audit_export.json
SELECT * FROM audit_log;
.quit
EOF
```

#### Archive the Export

The hosted service has no endpoint for importing audit records. Keep `audit_export.json` (or the SQLite file itself) as the record of your local period. From the migration on, hosted evaluation records each decision in the hosted audit log, and a hybrid-mode SDK uploads the records it writes.

**Note**: This is optional. Most use cases don't need the historical data.

---

### Step 6: Update Environment Variables

Both SDKs read their settings from `HIITL_*` variables when the constructor leaves them unset, and the mode follows: `HIITL_API_KEY` alone is hybrid mode, and with `HIITL_SERVER_URL` and `HIITL_EVALUATION=remote` it is hosted. Set the variables per deployment and the same constructor serves each one (see [Mixed-Environment Deployment](#mixed-environment-deployment)).

**Development** (`.env.dev`):
```bash
# No HIITL_API_KEY - evaluation is local
HIITL_ENVIRONMENT=dev
```

**Staging** (`.env.stage`):
```bash
HIITL_API_KEY=sk_stag_...
HIITL_SERVER_URL=https://api.hiitl.com
HIITL_EVALUATION=remote
HIITL_ORG_ID=org_abc123...
HIITL_ENVIRONMENT=stage
```

**Production** (`.env.prod` or secrets manager):
```bash
HIITL_API_KEY=sk_prod_...
HIITL_SERVER_URL=https://api.hiitl.com
HIITL_EVALUATION=remote
HIITL_ORG_ID=org_abc123...
HIITL_ENVIRONMENT=prod
```

---

### Step 7: Test in Staging

Before deploying to production:

1. Upload a `stage` policy with a `stage` key (Step 3, Option B)
2. Set staging env vars with `HIITL_API_KEY`, `HIITL_SERVER_URL` and `HIITL_EVALUATION=remote`
3. Run integration tests
4. Verify audit logs appear in dashboard
5. Check rate limiting works across instances

```python
# Staging test
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    evaluation="remote",
    signature_key=os.getenv("HIITL_SIGNATURE_KEY"),  # the API key's signing secret, shown when the key was created
    environment="stage",
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID"),
)

decision = hiitl.evaluate(
    "test_action",
    operation="execute",
    target={"test_id": "migration_test"},
    parameters={"test": True}
)

assert decision.allowed
print("Hosted evaluation working!")
```

---

### Step 8: Deploy to Production

1. Update production environment variables (add `HIITL_API_KEY`, `HIITL_SERVER_URL` and `HIITL_EVALUATION=remote`)
2. Deploy code (no code changes needed if you used env vars)
3. Monitor latency (expect < 50ms vs < 10ms for local)
4. Verify audit logs in dashboard

---

## Key Differences

### Latency

| Evaluation Mode | Latency | Notes |
|-----------------|---------|-------|
| **Local** | < 10ms (avg: 0.75-4ms) | In-process evaluation, no network |
| **Hosted** | < 50ms (avg: 20-30ms) | Network round-trip to API |

**If latency is critical** (< 10ms required), keep using local evaluation.

### Rate Limiting

| Evaluation Mode | Persistence | Coordination |
|-----------------|-------------|--------------|
| **Local** | In-memory (lost on restart) | Per-instance (not shared) |
| **Hybrid** | In-memory (lost on restart) | Per-instance (not shared) |
| **Hosted** | Hosted database (persistent) | Shared across instances |

**Example**:
```python
# Local evaluation: Each instance has separate counters
# Instance A: 10 requests
# Instance B: 10 requests
# Total: 20 requests (even if limit is 10!)

# Hosted evaluation: Shared counter across instances
# Instance A: 5 requests
# Instance B: 5 requests
# Total: 10 requests (enforced globally)
```

### Audit Log

| Evaluation Mode | Storage | Query | Retention |
|-----------------|---------|-------|-----------|
| **Local** | SQLite (local file) | Direct SQL or SDK | Manual |
| **Hosted** | PostgreSQL (managed) | Dashboard + API | Automatic |

### Policy Management

| Evaluation Mode | Update Process | Versioning | Collaboration |
|-----------------|----------------|------------|---------------|
| **Local** | Edit file (picked up on the next call) | Git | File-based |
| **Hosted** | API upload | Built-in | Dashboard (view) |

Hosted evaluation uses a newly uploaded policy from the next call. A hybrid-mode SDK picks it up at its next policy sync (every 300 seconds by default).

---

## Rollback Plan

If you need to rollback to local evaluation:

1. Remove `api_key` and `server_url` from your constructor (or, if your code passes them from environment variables, unset `HIITL_API_KEY` and `HIITL_SERVER_URL`)
2. Add back `policy_path` (and `audit_db_path` if needed)
3. Re-deploy

```python
# Rollback to local evaluation
hiitl = HIITL(
    environment="dev",
    agent_id="my-agent",
    policy_path="./policy.yaml",
    audit_db_path="./hiitl_audit.db",
)
```

**No data loss** -- hosted audit logs remain accessible via the dashboard.

---

## Mixed-Environment Deployment

You can run local evaluation in some environments and hosted in others. The SDK reads `HIITL_API_KEY`, `HIITL_SERVER_URL`, `HIITL_EVALUATION`, `HIITL_SIGNATURE_KEY`, `HIITL_ENVIRONMENT` and `HIITL_ORG_ID` itself when the constructor leaves them unset, so the constructor names only what is the same everywhere:

```python
from hiitl import HIITL

# - HIITL_API_KEY, HIITL_SERVER_URL, HIITL_SIGNATURE_KEY and HIITL_EVALUATION=remote set: hosted evaluation
# - none of them set: local evaluation (requires policy_path)
hiitl = HIITL(
    agent_id="my-agent",
    policy_path="./policy.yaml",  # Used for local; ignored when hosted
    mode="RESPECT_POLICY",
)
```

```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  agent_id: 'my-agent',
  policy_path: './policy.yaml',  // Used for local; ignored when hosted
  mode: 'RESPECT_POLICY',
});
```

The same constructor works for both modes: set the right environment variables per deployment target.

### Forcing Local Evaluation

If you have a key at hand but want local evaluation (e.g., for testing), pass `sync=False` (Python) or `sync: false` (TypeScript), or set `HIITL_SYNC=false`; the key is kept and nothing connects:

```typescript
const hiitl = new HIITL({
  api_key: process.env.HIITL_API_KEY,
  sync: false,  // Forces local evaluation even with a key present
  environment: 'dev',
  agent_id: 'my-agent',
  policy_path: './policy.yaml',
});
```

---

## Cost Considerations

### Local Evaluation
- **Infrastructure**: Your own compute + storage
- **Cost**: Marginal (< 1ms CPU time per evaluation)
- **Scaling**: Horizontal (more instances = more cost)

### Hosted Evaluation
- **Infrastructure**: Managed by hiitl
- **Cost**: Usage-based pricing (per evaluation)
- **Scaling**: Automatic (managed by hiitl)

**See**: https://hiitl.com/pricing for current hosted pricing

---

## Troubleshooting Migration

### "Invalid API key" Error

**Symptoms**:
```
ServerError: ECP server error (401): [UNKNOWN_ERROR] Invalid or inactive API key
```

**Solution**:
1. Verify API key is correct: `echo $HIITL_API_KEY`
2. Check key format: `sk_dev_...`, `sk_stag_...` or `sk_prod_...`
3. Ensure key is for correct environment

### "Policy not found" Error

**Symptoms**: `evaluate()` returns `POLICY_ERROR` with reason code `POLICY_NOT_FOUND`, and `error.message` reads:
```
No active policy found for org_id=..., environment=.... Create a policy via POST /v1/policies before evaluating envelopes.
```

**Solution**:
1. Verify policy exists in dashboard
2. The hosted service evaluates against the active policy for the API key's organization and environment (not the `org_id` and `environment` passed to the SDK). Upload the policy with a key for that environment (Step 3, Option B):
   ```yaml
   scope:
     org_id: "org_8f3a2c1d9e7b4a60"  # Must be the API key's org
     environment: "prod"    # Must be the API key's environment
   ```

### High Latency (> 100ms)

**Symptoms**:
- Evaluation taking > 100ms
- Much slower than local evaluation

**Solutions**:
1. Check network latency to API:
   ```bash
   curl -w "@-" -o /dev/null -s https://api.hiitl.com/health <<< "
   time_total: %{time_total}s\n"
   ```
2. Ensure using correct API region (coming soon: multi-region)
3. Consider staying on local evaluation for ultra-low latency requirements

### Rate Limits Not Syncing Across Instances

**Symptoms**:
- Rate limits not enforced globally
- Each instance has separate counters

**Solution**:
- Verify the SDK is in hosted mode (`hiitl.mode` is `"hosted"`): pass `api_key` and `server_url` (and, in Python, `evaluation="remote"`). Hybrid mode counts in memory, per process
- Check dashboard shows activity from all instances

---

## Migration Checklist

### Pre-Migration

- [ ] Sign up for hiitl hosted account
- [ ] Create API keys (an `evaluate` key per environment; an `admin` key for policy uploads)
- [ ] Copy API key and server URL to secrets manager
- [ ] Upload policy through the API
- [ ] Test in staging environment

### Code Changes

- [ ] Add `api_key` parameter (read from `HIITL_API_KEY` in your code)
- [ ] Add `server_url` parameter (read from `HIITL_SERVER_URL` in your code) and, in Python, `evaluation="remote"`
- [ ] Set `org_id` to your real org ID
- [ ] Remove `policy_path` (if using API-managed policies)
- [ ] Remove `audit_db_path`

### Deployment

- [ ] Update environment variables (dev, stage, prod)
- [ ] Deploy to staging first
- [ ] Run integration tests
- [ ] Verify audit logs in dashboard
- [ ] Deploy to production
- [ ] Monitor latency and errors

### Post-Migration

- [ ] Archive local SQLite audit logs (optional)
- [ ] Document new policy update process (API upload vs Git)
- [ ] Train team on dashboard features

---

## Summary

**Migration is straightforward**:
1. Sign up for hosted account
2. Add `api_key` and `server_url` to your constructor (and, in Python, `evaluation="remote"`)
3. Upload policy through the API (or run hybrid mode with a local fallback file)
4. Deploy

**Total time**: 15-30 minutes

**Rollback**: Remove `api_key` and `server_url`, add back `policy_path`, and redeploy.

---

**See also**:
- [Python Quickstart](quickstart_python.md)
- [TypeScript Quickstart](quickstart_typescript.md)
- [Troubleshooting Guide](troubleshooting.md)
- [Performance Tuning Guide](performance.md)
- [Deployment modes](../../docs-site/concepts/deployment-modes.mdx)
