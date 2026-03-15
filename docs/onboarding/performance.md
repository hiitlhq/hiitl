# Performance Tuning

How to optimize HIITL local mode.

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
print(f"SDK reports: {decision.timing['total_ms']:.2f}ms")
```

**TypeScript**:
```typescript
const start = performance.now();
const decision = hiitl.evaluate(...);
const elapsed_ms = performance.now() - start;

console.log(`Total: ${elapsed_ms.toFixed(2)}ms`);
console.log(`SDK reports: ${decision.timing.total_ms.toFixed(2)}ms`);
```

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
# SLOW - checks all rules even if first matches
rules:
  - name: "rule-1"
    priority: 100
    conditions: { ... }
  - name: "rule-2"
    priority: 99
    conditions: { ... }
  # ... 98 more rules

# FAST - high-priority rules match quickly
rules:
  - name: "block-high-risk"
    priority: 1000  # Evaluated first
    conditions:
      all_of:
        - field: "sensitivity"
          operator: "contains"
          value: "irreversible"
    decision: "BLOCK"

  - name: "default-allow"
    priority: 1
    conditions: {} # Always matches (fallback)
    decision: "ALLOW"
```

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
    parameters={"amount": 1500, "currency": "usd"}
)
```

### 3. Optimize Condition Operators

**Operator Performance** (fastest → slowest):
1. `equals` (hash lookup)
2. `greater_than`, `less_than` (numeric comparison)
3. `in` (set membership)
4. `contains` (substring search)
5. `matches` (regex - avoid if possible)

```yaml
# SLOW - regex matching
- field: "tool"
  operator: "matches"
  value: "payment_.*"

# FAST - exact match or `in` operator
- field: "tool"
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
  - field: "tool"
    operator: "equals"
    value: "payment"  # Fast, but checked second
```

**Solution**: Check cheap conditions first (short-circuit)

```yaml
# FAST - cheap condition first (may skip expensive check)
all_of:
  - field: "tool"
    operator: "equals"
    value: "payment"  # Fast check first
  - field: "parameters.description"
    operator: "contains"
    value: "suspicious"  # Only if tool matches
```

---

## Caching Strategies

### Policy Caching (Automatic)

HIITL automatically caches policies using file modification time (mtime).

**How it works**:
1. First load: Read file, parse YAML/JSON, validate schema (~3-5ms)
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

If you need to force policy reload (e.g., hot-reloading in dev):
```python
# Python - reload policy manually
hiitl._policy_loader.cache.clear()
policy = hiitl._policy_loader.load()
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

### 3. WAL Mode (Enabled by Default)

SQLite WAL (Write-Ahead Logging) mode is automatically enabled:
- Allows concurrent reads during writes
- Reduces lock contention
- Improves write performance

### 4. Batch Audit Writes (Advanced)

For extremely high throughput (> 10,000 ops/sec), batch writes:

```python
# Not yet implemented - future enhancement
# This would batch multiple audit records into single transaction
```

### 5. Periodic VACUUM

SQLite databases can grow over time. Periodically vacuum to reclaim space:

```bash
sqlite3 hiitl_audit.db "VACUUM;"
```

Or programmatically:
```python
import sqlite3
conn = sqlite3.connect("hiitl_audit.db")
conn.execute("DELETE FROM audit_log WHERE timestamp < datetime('now', '-30 days')")
conn.execute("VACUUM")
conn.close()
```

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
2. `tool` - Counter per tool name
3. `user_id` - Counter per user
4. `user:tool` - Counter per (user, tool) pair

**Trade-off**:
- Narrow scope (user:tool) = more counters = more memory
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

HIITL auto-generates these fields (you don't need to provide them):
- `action_id`: `act_{uuid}`
- `timestamp`: Current ISO timestamp
- `idempotency_key`: `idem_{uuid}`
- `signature`: HMAC-SHA256 (if signature_key provided)

**Performance**: ~0.1ms for all auto-generation

### Minimize Envelope Size

**Problem**: Large envelopes slow down serialization and audit writes

```python
# SLOW - huge envelope
hiitl.evaluate(
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
- ✅ Local mode works great (sub-millisecond)
- ❌ No SQLite support (no filesystem)
- Solution: Disable audit logging for edge, log elsewhere

```typescript
// Vercel Edge Runtime
const hiitl = new HIITL({
  environment: 'prod',
  agent_id: 'edge-worker',
  org_id: process.env.ORG_ID,
  policy_path: './policy.json',  // Bundled at build time
  enable_audit: false,  // No filesystem on edge
});
```

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
        tool="test_action",
        operation="execute",
        target={"id": f"target_{i}"},
        parameters={"value": i}
    )
    return (time.perf_counter() - start) * 1000

# Concurrent load test
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(evaluate_action, i) for i in range(1000)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

print(f"Average: {sum(results) / len(results):.2f}ms")
print(f"Throughput: {len(results) / (max(results) / 1000):.0f} ops/sec")
```

### Production Monitoring

Track these metrics:
- `decision.timing.total_ms` (end-to-end latency)
- Policy cache hit ratio
- Audit DB size
- Error rate (PolicyLoadError, AuditLogError)

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
| Avoid regex operators | ⚡⚡ Medium | Low |
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
