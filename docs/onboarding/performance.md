# Performance Tuning

How to optimize hiitl local mode.

## Performance

| Metric | Target | TypeScript | Python |
|--------|--------|------------|--------|
| Average latency | < 10ms | 0.75ms | 3-4ms |
| P95 latency | < 10ms | 2.91ms | ~5ms |
| Cache hit | < 1ms | 0.24ms | ~0.5ms |
| Throughput | 1000+ ops/sec | 4,121 ops/sec | ~3,000 ops/sec |

---

## Table of Contents

1. [Understanding Latency Breakdown](#understanding-latency-breakdown)
2. [Policy Optimization](#policy-optimization)
3. [Caching Strategies](#caching-strategies)
4. [SQLite Performance](#sqlite-performance)
5. [Rate Limiting Optimization](#rate-limiting-optimization)
6. [Envelope Construction](#envelope-construction)
7. [Deployment Best Practices](#deployment-best-practices)
8. [Benchmarking & Monitoring](#benchmarking--monitoring)

---

## Latency Breakdown

```
Total latency = Policy Load + Evaluation + Rate Limit Check + Audit Write

First call:  5-10ms = 3ms (policy load) + 0.1ms (eval) + 0.1ms (rate limit) + 2ms (audit)
Cached call: 0.5-1ms = 0ms (cached) + 0.1ms (eval) + 0.1ms (rate limit) + 0.5ms (audit)
```

### Measuring Latency

**Python**:
```python
import time

start = time.perf_counter()
decision = hiitl.evaluate(...)
elapsed_ms = (time.perf_counter() - start) * 1000

print(f"Total: {elapsed_ms:.2f}ms")
print(f"SDK reports: {decision.timing.total_ms:.2f}ms")
```

**TypeScript**:
```typescript
const start = performance.now();
const decision = await hiitl.evaluate({ ... });
const elapsed_ms = performance.now() - start;

console.log(`Total: ${elapsed_ms.toFixed(2)}ms`);
console.log(`SDK reports: ${decision.timing.total_ms.toFixed(2)}ms`);
```

`decision.timing` reports envelope validation and rule evaluation (`ingest_ms`, `evaluation_ms`, `total_ms`). The policy load, the rate-limit check and the audit write fall outside it, so the time you measure around the call is the larger figure.

| Component | Target |
|-----------|--------|
| Policy load (first) | < 5ms |
| Policy load (cached) | < 0.1ms |
| Evaluation | < 0.5ms |
| Rate limit | < 0.1ms |
| Audit write | < 3ms |

---

## Policy Optimization

### Minimize Rules

Keep rules under 50. More rules = slower evaluation.

```yaml
# SLOW - a call that matches late, or not at all, is checked against every rule before it
policy_set:
  name: "one-rule-per-action"
  version: "v1.0.0"
  description: "One rule per action, each matching on the action first"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"
  rules:
    - name: "rule-1"
      description: "Allow action_1"
      priority: 100
      conditions: {field: "action", operator: "equals", value: "action_1"}
      decision: "ALLOW"
      reason_code: "ACTION_1"
    - name: "rule-2"
      description: "Allow action_2"
      priority: 99
      conditions: {field: "action", operator: "equals", value: "action_2"}
      decision: "ALLOW"
      reason_code: "ACTION_2"
    # ... 98 more rules like these
```

```yaml
# FAST - high-priority rules match quickly
policy_set:
  name: "few-broad-rules"
  version: "v1.0.0"
  description: "Broad rules that every call is checked against"
  scope:
    org_id: "org_devlocal0000000000"
    environment: "dev"
  rules:
    - name: "block-high-risk"
      description: "Irreversible actions are refused"
      priority: 1000  # Evaluated first
      conditions:
        all_of:
          - field: "sensitivity"
            operator: "contains"
            value: "irreversible"
      decision: "BLOCK"
      reason_code: "IRREVERSIBLE_ACTION"

    - name: "default-allow"
      description: "Everything else proceeds"
      priority: 1
      conditions: {field: "action", operator: "exists", value: true} # Always matches (fallback)
      decision: "ALLOW"
      reason_code: "DEFAULT_ALLOW"
```

Evaluation stops at the first active rule that matches. `KILL_SWITCH` rules are checked first, then `BLOCK` rules, then all others, whatever their priority; priority orders the rules within each of those groups.

**Guideline**: Keep total rules < 50 for sub-millisecond evaluation

### 2. Use Flat Conditions

**Problem**: Deeply nested JSON path traversal is slow

```yaml
# SLOW - deep nesting
conditions:
  all_of:
    - field: "parameters.payment.details.amount.value.usd"
      operator: "greater_than"
      value: 1000
```

**Solution**: Flatten envelope structure

```yaml
# FAST - flat field access
conditions:
  all_of:
    - field: "parameters.amount"
      operator: "greater_than"
      value: 1000
```

**When passing envelope**:
```python
# SLOW
hiitl.evaluate(
    "process_payment",
    parameters={
        "payment": {
            "details": {
                "amount": {"value": {"usd": 1500}}
            }
        }
    }
)

# FAST
hiitl.evaluate(
    "process_payment",
    parameters={"amount": 1500, "currency": "usd"}
)
```

### 3. Optimize Condition Operators

**Operator Performance** (fastest → slowest):
1. `equals` (direct comparison)
2. `greater_than`, `less_than` (numeric comparison)
3. `in` (membership in the listed values)
4. `contains` (substring search)

```yaml
# SLOWER - substring search
- field: "action"
  operator: "contains"
  value: "payment_"

# FAST - exact match or `in` operator
- field: "action"
  operator: "in"
  value: ["payment_transfer", "payment_refund", "payment_void"]
```

### 4. Order Conditions by Selectivity

**Problem**: Checking expensive conditions first

```yaml
# SLOW - complex condition checked first
all_of:
  - field: "parameters.description"
    operator: "contains"
    value: "suspicious"  # Expensive string search
  - field: "action"
    operator: "equals"
    value: "payment"  # Fast, but checked second
```

**Solution**: Check cheap conditions first (short-circuit)

```yaml
# FAST - cheap condition first (may skip expensive check)
all_of:
  - field: "action"
    operator: "equals"
    value: "payment"  # Fast check first
  - field: "parameters.description"
    operator: "contains"
    value: "suspicious"  # Only if action matches
```

---

## Caching Strategies

### Policy Caching (Automatic)

hiitl automatically caches policies using file modification time (mtime).

**How it works**:
1. First load: Read file, parse YAML/JSON, validate schema (~3-5ms). Python loads the file on the first `evaluate()`; TypeScript loads it in the constructor.
2. Subsequent loads: Check mtime, return cached if unchanged (~0.1ms)

**Cache hit ratio**:
- Development: ~95% (policy rarely changes)
- Production: ~99.9% (policy changes are deployments)

**To verify caching**:
```python
for i in range(100):
    start = time.perf_counter()
    decision = hiitl.evaluate(...)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"Call {i}: {elapsed:.2f}ms")

# Output:
# Call 0: 8.5ms  ← first call (policy load)
# Call 1: 0.6ms  ← cached
# Call 2: 0.5ms  ← cached
# ...
```

### Disable Caching (Not Recommended)

Hot-reloading needs nothing extra: the mtime check runs on every `evaluate()`, so an edited policy file takes effect on the next call. If you need to force a reload anyway:
```python
# Python - drop the cached policy; the next evaluate() re-reads the file
hiitl._policy_loader.invalidate_cache()
```

---

## SQLite Performance

### 1. Use Local Filesystem (Not NFS/Network)

**Problem**: Network filesystems add 10-100ms latency

**Solution**: Always use local disk
- ✅ `/tmp/hiitl_audit.db` (local tmpfs)
- ✅ `./hiitl_audit.db` (local disk)
- ❌ `/mnt/nfs/hiitl_audit.db` (network filesystem)

### 2. Use SSD Over HDD

**Impact**:
- HDD: 5-10ms write latency
- SSD: 0.5-2ms write latency
- NVMe: 0.1-0.5ms write latency

### 3. WAL Mode (Opt-In)

The SDK opens the audit database in SQLite's default journal mode; it does not turn on WAL (Write-Ahead Logging). WAL:
- Allows concurrent reads during writes
- Reduces lock contention
- Improves write performance

To use it, set it once on the database file. SQLite stores the setting in the file, and the SDK keeps writing to it:

```bash
sqlite3 hiitl_audit.db "PRAGMA journal_mode=WAL;"
```

### 4. Batch Audit Writes (Advanced)

For extremely high throughput (> 10,000 ops/sec), batch writes:

```python
# Not yet implemented - future enhancement
# This would batch multiple audit records into single transaction
```

### 5. Rotate the Audit Database

The audit database grows with every evaluation. To keep each file small, rotate: point `audit_db_path` at a new file on a schedule and archive the old file whole.

```python
from datetime import datetime
audit_db_path = f"./audit_{datetime.now().strftime('%Y%m')}.db"
```

In hybrid mode the SDK uploads records only from the file it is currently writing.

---

## Rate Limiting Optimization

### In-Memory Performance

Local mode uses in-memory rate limiting (no database):
- Map lookup: ~0.01ms
- Cleanup of expired events: ~0.1ms (amortized)

**Performance impact**: Negligible (< 0.1ms)

### Scope Selection

**Scope Performance** (fastest → slowest):
1. `org` - Single counter for entire org
2. `action` - Counter per action name
3. `user` - Counter per user
4. `user_action` - Counter per (user, action) pair

These are the values of a `RATE_LIMIT` rule's `rate_limit.scope` (`agent`, a counter per agent, is the fifth).

**Trade-off**:
- Narrow scope (user_action) = more counters = more memory
- Broad scope (org) = fewer counters = less memory

**Recommendation**: Use narrowest scope that meets requirements

### Cleanup Strategy

Expired events are cleaned up automatically during `checkAndIncrement()`:
- Only events within window are kept
- Old events removed before check

**Memory usage**:
```
Memory = (events per window) × (scope keys) × (event size)

Example:
  100 events/hour × 1000 users × 50 bytes = ~5MB
```

---

## Envelope Construction

### Auto-Generated Fields

hiitl auto-generates these fields (you don't need to provide them):
- `action_id`: `act_` + the first 20 hex characters of a UUID
- `timestamp`: Current ISO timestamp
- `idempotency_key`: `idem_` + a UUID's 32 hex characters
- `signature`: HMAC-SHA256 (if signature_key provided)

**Performance**: ~0.1ms for all auto-generation

### Minimize Envelope Size

**Problem**: Large envelopes slow down serialization and audit writes

```python
# SLOW - huge envelope
hiitl.evaluate(
    "upload_document",
    parameters={
        "document": "<massive 1MB PDF base64 string>",
        "metadata": { ... 10KB of metadata ... }
    }
)
```

**Solution**: Store large data separately, reference by ID

```python
# FAST - small envelope with reference
hiitl.evaluate(
    "upload_document",
    parameters={
        "document_id": "doc_abc123",  # Reference, not data
        "document_size_bytes": 1048576,
    }
)
```

---

## Deployment Best Practices

### Serverless / Lambda

**Challenge**: Cold starts can add latency

**Optimization**:
1. Keep policy file small (< 50KB)
2. Use `/tmp/` for SQLite (tmpfs, faster than EFS)
3. Pre-warm with dummy call in init phase

```python
import os

# Global - initialized once per container
hiitl = HIITL(
    environment=os.getenv("ENV"),
    agent_id="lambda-agent",
    org_id=os.getenv("ORG_ID"),
    policy_path="./policy.yaml",
    audit_db_path="/tmp/hiitl_audit.db",  # Use /tmp, not EFS
)

def lambda_handler(event, context):
    # Hot path - sub-millisecond
    decision = hiitl.evaluate(...)
    ...
```

### Docker / Containers

**Optimization**:
1. Bundle policy in Docker image (fast load)
2. Mount audit DB to persistent volume
3. Use multi-stage builds to minimize image size

```dockerfile
FROM python:3.11-slim

# Copy policy at build time
COPY policy.yaml /app/policy.yaml

# Runtime
CMD ["python", "app.py"]
```

### Edge / CDN Workers

**Cloudflare Workers / Vercel Edge**:
- ❌ The TypeScript SDK does not run on edge runtimes: it needs Node.js 22+ with a filesystem, because new evaluations are recorded in its SQLite audit database through `better-sqlite3` (a native module), and the audit write has no off switch
- Solution: run the SDK in a Node.js runtime (on Vercel, the Node.js runtime rather than Edge)

---

## Benchmarking & Monitoring

### Measure P50, P95, P99

Don't just measure average - measure percentiles:

```python
import time
import statistics

latencies = []
for i in range(1000):
    start = time.perf_counter()
    hiitl.evaluate(...)
    latencies.append((time.perf_counter() - start) * 1000)

print(f"P50 (median): {statistics.median(latencies):.2f}ms")
print(f"P95: {statistics.quantiles(latencies, n=20)[18]:.2f}ms")
print(f"P99: {statistics.quantiles(latencies, n=100)[98]:.2f}ms")
```

### Load Testing

Simulate realistic load:

```python
import concurrent.futures
import time

def evaluate_action(i):
    start = time.perf_counter()
    decision = hiitl.evaluate(
        "test_action",
        operation="execute",
        target={"id": f"target_{i}"},
        parameters={"value": i}
    )
    return (time.perf_counter() - start) * 1000

# Concurrent load test
wall_start = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(evaluate_action, i) for i in range(1000)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
wall_s = time.perf_counter() - wall_start

print(f"Average: {sum(results) / len(results):.2f}ms")
print(f"Throughput: {len(results) / wall_s:.0f} ops/sec")
```

### Production Monitoring

Track these metrics:
- `decision.timing.total_ms` (evaluator time; time the call yourself for end-to-end latency)
- Policy cache hit ratio
- Audit DB size
- Error rate (decisions with `error` set: `POLICY_ERROR`, `AUDIT_WRITE_FAILED`)

---

## Performance Checklist

### Pre-Deployment

- [ ] Policy has < 50 rules
- [ ] Conditions are flat (not deeply nested)
- [ ] High-priority rules use fast operators (`equals`, `in`)
- [ ] Policy file is < 50KB
- [ ] Benchmarked under realistic load (p95 < 10ms)

### Deployment

- [ ] Using SSD/NVMe storage (not HDD)
- [ ] SQLite on local filesystem (not NFS)
- [ ] For serverless: audit DB in `/tmp/`
- [ ] For containers: audit DB on persistent volume
- [ ] Policy bundled in deployment artifact (fast loading)

### Monitoring

- [ ] Tracking p95/p99 latency (not just average)
- [ ] Alerting on latency > 10ms
- [ ] Monitoring audit DB size
- [ ] Tracking error rates

---

## Expected Performance

### Development (MacBook Pro M1)

- **First call**: 5-8ms (policy load + evaluation + audit)
- **Cached call**: 0.5-1ms (cached policy + evaluation + audit)
- **Throughput**: 3,000-5,000 ops/sec (single-threaded)

### Production (AWS t3.medium)

- **First call**: 8-12ms (policy load + evaluation + audit)
- **Cached call**: 1-2ms (cached policy + evaluation + audit)
- **Throughput**: 2,000-3,000 ops/sec (single-threaded)

### Serverless (AWS Lambda 512MB)

- **Cold start**: +50-100ms (first invocation)
- **Warm**: 1-3ms per evaluation
- **Throughput**: 1,000-2,000 ops/sec (per container)

---

## When to Switch to Hosted Mode

Consider hosted mode if you need:
- **Persistent rate limiting** across restarts/instances
- **Centralized audit log** (PostgreSQL, not SQLite)
- **Multi-instance coordination** (multiple servers/containers)
- **Team collaboration** (policy management UI, webhooks, alerts)

**Trade-off**:
- Local mode: < 10ms latency, no external dependencies
- Hosted mode: < 50ms latency, managed infrastructure

---

## Summary

| Optimization | Impact | Effort |
|--------------|--------|--------|
| Use < 50 rules | ⚡⚡⚡ High | Low |
| Flatten envelope structure | ⚡⚡ Medium | Medium |
| Use SSD storage | ⚡⚡ Medium | Low (infrastructure) |
| Order conditions by selectivity | ⚡ Low | Low |
| Minimize envelope size | ⚡ Low | Medium |

**Focus on high-impact, low-effort optimizations first.**

---

**See also**:
- [Troubleshooting Guide](troubleshooting.md)
- [Local → Hosted Migration Guide](local_to_hosted_migration.md)
- [Python Quickstart](quickstart_python.md)
- [TypeScript Quickstart](quickstart_typescript.md)
