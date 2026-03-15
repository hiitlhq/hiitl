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
- Team collaboration (UI, webhooks, alerts)
- Compliance audit trail

## How Mode Detection Works

The SDK automatically determines evaluation mode based on which parameters you provide:

| Parameters Provided | Evaluation Mode | Description |
|---------------------|-----------------|-------------|
| `policy_path` only (no `api_key`) | **Local** | In-process evaluation against local policy files |
| `api_key` + `server_url` | **Hosted** | Evaluation delegated to the ECP server |
| `api_key` only (no `server_url`) | **Hybrid** | Local evaluation now, sync support in a future release |
| `api_key` + `server_url` + `sync=False` | **Local (forced)** | Local evaluation even with credentials present |

There is no explicit `mode` parameter. The SDK infers the right behavior from your configuration.

## Migration Overview

Migration requires adding two parameters to your constructor. No code changes to your `evaluate()` calls.

| Component | Local | Hosted | Migration Effort |
|-----------|-------|--------|------------------|
| **SDK Code** | `policy_path` only | Add `api_key` + `server_url` | 2 parameters |
| **Policy** | YAML file | API-managed or file | Low |
| **Audit Log** | SQLite (local) | PostgreSQL (hosted) | Automatic |
| **Rate Limiting** | In-memory | Redis (hosted) | Automatic |
| **API Key** | None | Required | Sign up |

**Time required**: 15-30 minutes

---

## Step-by-Step Migration

### Step 1: Sign Up for Hosted HIITL

1. Go to https://hiitl.ai
2. Create an account
3. Create an organization
4. Copy your API key and server URL

**Environment variables**:
```bash
export HIITL_API_KEY="sk_live_..."
export HIITL_SERVER_URL="https://api.hiitl.ai"
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
    org_id="org_local",
    policy_path="./policy.yaml",
    audit_db_path="./hiitl_audit.db",
)
```

**After (hosted evaluation)**:
```python
import os
from hiitl import HIITL

hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),       # Triggers hosted evaluation
    server_url=os.getenv("HIITL_SERVER_URL"),  # ECP server endpoint
    environment="prod",  # Or "dev"/"stage"
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID"),  # Real org ID from dashboard
    # No policy_path needed - managed via API/dashboard
    # No audit_db_path needed - managed by hosted service
)
```

#### TypeScript

**Before (local evaluation)**:
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  environment: 'dev',
  agentId: 'my-agent',
  orgId: 'org_local',
  policyPath: './policy.yaml',
  auditDbPath: './hiitl_audit.db',
});
```

**After (hosted evaluation)**:
```typescript
import { HIITL } from '@hiitl/sdk';

const hiitl = new HIITL({
  apiKey: process.env.HIITL_API_KEY,       // Triggers hosted evaluation
  serverUrl: process.env.HIITL_SERVER_URL, // ECP server endpoint
  environment: 'prod',  // Or 'dev'/'stage'
  agentId: 'my-agent',
  orgId: process.env.HIITL_ORG_ID,  // Real org ID from dashboard
  // No policyPath needed - managed via API/dashboard
  // No auditDbPath needed - managed by hosted service
});
```

**That's it!** Your `evaluate()` calls stay exactly the same. The SDK detects hosted mode automatically from the presence of `api_key` and `server_url`.

---

### Step 3: Upload Your Policy

#### Option A: Upload via Dashboard (Easiest)

1. Log in to https://hiitl.ai
2. Navigate to **Policies**
3. Click **Create Policy**
4. Paste your YAML file contents
5. Click **Save**

#### Option B: Upload via API

```bash
curl -X POST https://api.hiitl.ai/v1/policies \
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

#### Option C: Hybrid Mode (Keep Local Policy File)

If you want hosted connectivity but still load policies from a file, provide both `api_key` and `policy_path`:

```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    policy_path="./policy.yaml",  # Local file takes precedence
    ...
)
```

**Trade-off**:
- Dashboard/API: Centralized, versioned, team collaboration
- File: Simple, no network dependency, works offline

---

### Step 4: Update Policy Scope

**Important**: Change `org_id` from `"org_local"` to your real org ID.

**Before** (`policy.yaml` for local evaluation):
```yaml
policy_set:
  scope:
    org_id: "org_local"  # Local testing value
    environment: "dev"
  rules: [...]
```

**After** (for hosted evaluation):
```yaml
policy_set:
  scope:
    org_id: "org_abc123..."  # Real org ID from dashboard
    environment: "prod"  # Or "dev"/"stage"
  rules: [...]
```

---

### Step 5: Migrate Audit Logs (Optional)

If you need historical audit records in hosted mode:

#### Export from SQLite

```bash
sqlite3 hiitl_audit.db <<EOF
.mode json
.output audit_export.json
SELECT * FROM audit_log;
.quit
EOF
```

#### Import to Hosted (via API)

```python
import json
import requests

with open('audit_export.json') as f:
    records = json.load(f)

for record in records:
    requests.post(
        'https://api.hiitl.ai/v1/audit/import',
        headers={'Authorization': f'Bearer {api_key}'},
        json=record
    )
```

**Note**: This is optional. Most use cases don't need historical data migrated.

---

### Step 6: Update Environment Variables

The SDK auto-detects evaluation mode from the environment. If `HIITL_API_KEY` and `HIITL_SERVER_URL` are both set, hosted evaluation is used. If neither is set, local evaluation is used.

**Development** (`.env.dev`):
```bash
# No HIITL_API_KEY or HIITL_SERVER_URL - local evaluation is used automatically
HIITL_ENVIRONMENT=dev
```

**Staging** (`.env.stage`):
```bash
HIITL_API_KEY=sk_stage_...
HIITL_SERVER_URL=https://api.hiitl.ai
HIITL_ORG_ID=org_abc123...
HIITL_ENVIRONMENT=stage
```

**Production** (`.env.prod` or secrets manager):
```bash
HIITL_API_KEY=sk_live_...
HIITL_SERVER_URL=https://api.hiitl.ai
HIITL_ORG_ID=org_abc123...
HIITL_ENVIRONMENT=prod
```

---

### Step 7: Test in Staging

Before deploying to production:

1. Create a `stage` environment policy in dashboard
2. Set staging env vars with `HIITL_API_KEY` and `HIITL_SERVER_URL`
3. Run integration tests
4. Verify audit logs appear in dashboard
5. Check rate limiting works across instances

```python
# Staging test
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    environment="stage",
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID"),
)

decision = hiitl.evaluate(
    tool="test_action",
    operation="execute",
    target={"test_id": "migration_test"},
    parameters={"test": True}
)

assert decision.allowed
print("Hosted evaluation working!")
```

---

### Step 8: Deploy to Production

1. Update production environment variables (add `HIITL_API_KEY` and `HIITL_SERVER_URL`)
2. Deploy code (no code changes needed if you used env vars)
3. Monitor latency (expect < 50ms vs < 10ms for local)
4. Verify audit logs in dashboard
5. Set up alerts (dashboard -> Alerts -> Create)

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
| **Hosted** | Redis (persistent) | Shared across instances |

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
| **Local** | Edit file, restart app | Git | File-based |
| **Hosted** | Dashboard/API (instant) | Built-in | Team UI |

---

## Rollback Plan

If you need to rollback to local evaluation:

1. Remove `api_key` and `server_url` from your constructor (or unset `HIITL_API_KEY` and `HIITL_SERVER_URL` env vars)
2. Add back `policy_path` (and `audit_db_path` if needed)
3. Re-deploy

```python
# Rollback to local evaluation
hiitl = HIITL(
    environment="dev",
    agent_id="my-agent",
    org_id="org_local",
    policy_path="./policy.yaml",
    audit_db_path="./hiitl_audit.db",
)
```

**No data loss** -- hosted audit logs remain accessible via the dashboard.

---

## Mixed-Environment Deployment

You can run local evaluation in some environments and hosted in others. The SDK auto-detects based on which environment variables are present:

```python
import os
from hiitl import HIITL

# The SDK auto-detects the evaluation mode:
# - If HIITL_API_KEY and HIITL_SERVER_URL are set: hosted evaluation
# - If neither is set: local evaluation (requires policy_path)
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),          # None in dev = local evaluation
    server_url=os.getenv("HIITL_SERVER_URL"),     # None in dev = local evaluation
    environment=os.getenv("HIITL_ENVIRONMENT", "dev"),
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID", "org_local"),
    policy_path="./policy.yaml",  # Used for local; ignored when hosted
)
```

```typescript
import { HIITL } from '@hiitl/sdk';

// Same auto-detection in TypeScript
const hiitl = new HIITL({
  apiKey: process.env.HIITL_API_KEY,            // undefined in dev = local evaluation
  serverUrl: process.env.HIITL_SERVER_URL,      // undefined in dev = local evaluation
  environment: process.env.HIITL_ENVIRONMENT ?? 'dev',
  agentId: 'my-agent',
  orgId: process.env.HIITL_ORG_ID ?? 'org_local',
  policyPath: './policy.yaml',  // Used for local; ignored when hosted
});
```

No branching logic required. The same constructor works for both modes -- just set the right environment variables per deployment target.

### Forcing Local Evaluation

If you have `api_key` and `server_url` set but want to force local evaluation (e.g., for testing), use `sync=False`:

```python
hiitl = HIITL(
    api_key=os.getenv("HIITL_API_KEY"),
    server_url=os.getenv("HIITL_SERVER_URL"),
    sync=False,  # Forces local evaluation even with credentials present
    environment="dev",
    agent_id="my-agent",
    org_id=os.getenv("HIITL_ORG_ID"),
    policy_path="./policy.yaml",
)
```

---

## Cost Considerations

### Local Evaluation
- **Infrastructure**: Your own compute + storage
- **Cost**: Marginal (< 1ms CPU time per evaluation)
- **Scaling**: Horizontal (more instances = more cost)

### Hosted Evaluation
- **Infrastructure**: Managed by HIITL
- **Cost**: Usage-based pricing (per evaluation)
- **Scaling**: Automatic (managed by HIITL)

**See**: https://hiitl.ai/pricing for current hosted pricing

---

## Troubleshooting Migration

### "Invalid API key" Error

**Symptoms**:
```
ConfigurationError: Invalid API key
```

**Solution**:
1. Verify API key is correct: `echo $HIITL_API_KEY`
2. Check key format: `sk_live_...` or `sk_dev_...`
3. Ensure key is for correct environment

### "Policy not found" Error

**Symptoms**:
```
PolicyLoadError: No policy found for org_id=..., environment=...
```

**Solution**:
1. Verify policy exists in dashboard
2. Check policy scope matches SDK config:
   ```yaml
   scope:
     org_id: "org_abc123"  # Must match SDK org_id
     environment: "prod"    # Must match SDK environment
   ```

### High Latency (> 100ms)

**Symptoms**:
- Evaluation taking > 100ms
- Much slower than local evaluation

**Solutions**:
1. Check network latency to API:
   ```bash
   curl -w "@-" -o /dev/null -s https://api.hiitl.ai/health <<< "
   time_total: %{time_total}s\n"
   ```
2. Ensure using correct API region (coming soon: multi-region)
3. Consider staying on local evaluation for ultra-low latency requirements

### Rate Limits Not Syncing Across Instances

**Symptoms**:
- Rate limits not enforced globally
- Each instance has separate counters

**Solution**:
- Verify both `HIITL_API_KEY` and `HIITL_SERVER_URL` are set (so the SDK uses hosted evaluation)
- Check dashboard shows activity from all instances

---

## Migration Checklist

### Pre-Migration

- [ ] Sign up for HIITL hosted account
- [ ] Create organization
- [ ] Copy API key and server URL to secrets manager
- [ ] Upload policy to dashboard
- [ ] Test in staging environment

### Code Changes

- [ ] Add `api_key` parameter (or set `HIITL_API_KEY` env var)
- [ ] Add `server_url` parameter (or set `HIITL_SERVER_URL` env var)
- [ ] Change `org_id` from `"org_local"` to real org ID
- [ ] Remove `policy_path` (if using dashboard-managed policies)
- [ ] Remove `audit_db_path`

### Deployment

- [ ] Update environment variables (dev, stage, prod)
- [ ] Deploy to staging first
- [ ] Run integration tests
- [ ] Verify audit logs in dashboard
- [ ] Deploy to production
- [ ] Monitor latency and errors
- [ ] Set up alerts in dashboard

### Post-Migration

- [ ] Archive local SQLite audit logs (optional)
- [ ] Document new policy update process (dashboard vs Git)
- [ ] Train team on dashboard features
- [ ] Set up webhooks for critical events

---

## Summary

**Migration is straightforward**:
1. Sign up for hosted account
2. Add `api_key` and `server_url` to your constructor
3. Upload policy to dashboard (or keep local file for hybrid)
4. Deploy

**Total time**: 15-30 minutes

**Rollback**: Remove `api_key` and `server_url`, add back `policy_path`, and redeploy.

---

**See also**:
- [Python Quickstart](quickstart_python.md)
- [TypeScript Quickstart](quickstart_typescript.md)
- [Troubleshooting Guide](troubleshooting.md)
- [Performance Tuning Guide](performance.md)
- [HIITL Hosted Documentation](https://docs.hiitl.ai/hosted)
