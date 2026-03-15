# Troubleshooting

Common issues and fixes.

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Policy Loading Problems](#policy-loading-problems)
3. [SQLite / Audit Log Issues](#sqlite--audit-log-issues)
4. [Performance Issues](#performance-issues)
5. [Rate Limiting Problems](#rate-limiting-problems)
6. [Evaluation Not Working as Expected](#evaluation-not-working-as-expected)
7. [TypeScript-Specific Issues](#typescript-specific-issues)
8. [Python-Specific Issues](#python-specific-issues)

---

## Installation Issues

### `ModuleNotFoundError: No module named 'hiitl'`

```
ModuleNotFoundError: No module named 'hiitl'
```

**Fix**:
```bash
pip install hiitl
```

If using a virtual environment, activate it first:
```bash
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### `Cannot find module '@hiitl/sdk'`

```
Error: Cannot find module '@hiitl/sdk'
```

**Fix**:
```bash
npm install @hiitl/sdk
```

If that doesn't work, clear and reinstall:
```bash
rm -rf node_modules package-lock.json
npm install
```

### `better-sqlite3` build errors

```
Error: Cannot find module 'better-sqlite3'
gyp ERR! build error
```

**Fix**: Install build tools:
```bash
# macOS
xcode-select --install

# Ubuntu/Debian
sudo apt-get install build-essential python3

# Windows
npm install --global windows-build-tools
```

Then rebuild:
```bash
npm rebuild better-sqlite3
```

---

## Policy Loading Problems

### Policy File Not Found

**Symptoms**:
```python
PolicyLoadError: Policy file not found: ./policy.yaml
```

**Solutions**:
1. Check file path is relative to current working directory:
   ```python
   import os
   policy_path = os.path.join(os.path.dirname(__file__), "policy.yaml")
   hiitl = HIITL(policy_path=policy_path, ...)
   ```

2. Use absolute paths for clarity:
   ```python
   policy_path = "/absolute/path/to/policy.yaml"
   ```

3. Verify file exists:
   ```bash
   ls -la policy.yaml
   ```

### Policy Syntax Errors

**Symptoms**:
```
PolicyLoadError: Invalid policy format: ...
```

**Solutions**:
1. Validate YAML syntax:
   ```bash
   # Install yamllint
   pip install yamllint
   yamllint policy.yaml
   ```

2. Check against policy_format.md spec:
   - `policy_set.scope.org_id` must match SDK config
   - `policy_set.scope.environment` must match SDK config
   - All required fields present

3. Common mistakes:
   ```yaml
   # WRONG - missing scope
   policy_set:
     rules: [...]

   # CORRECT
   policy_set:
     scope:
       org_id: "org_local"
       environment: "dev"
     rules: [...]
   ```

### Policy Not Applying (Always ALLOW)

**Symptoms**:
- All actions return `ALLOW` decision
- Policy rules never match

**Solutions**:
1. **Check scope matching**:
   ```python
   # SDK config
   hiitl = HIITL(org_id="org_local", environment="dev", ...)

   # Policy MUST match
   policy_set:
     scope:
       org_id: "org_local"  # Must match SDK
       environment: "dev"    # Must match SDK
   ```

2. **Verify policy_path is set**:
   ```python
   # WRONG - no policy loaded
   hiitl = HIITL(environment="dev", agent_id="test", org_id="org_local")

   # CORRECT
   hiitl = HIITL(
       environment="dev",
       agent_id="test",
       org_id="org_local",
       policy_path="./policy.yaml"  # Policy loaded
   )
   ```

3. **Check rule priority order** (higher priority = evaluated first):
   ```yaml
   rules:
     - name: "specific-rule"
       priority: 100  # Evaluated first
       ...

     - name: "default-allow"
       priority: 1    # Evaluated last (fallback)
       ...
   ```

---

## SQLite / Audit Log Issues

### Permission Denied

**Symptoms**:
```
AuditLogError: unable to open database file
PermissionError: [Errno 13] Permission denied: './hiitl_audit.db'
```

**Solutions**:
1. Check directory permissions:
   ```bash
   ls -la .
   chmod 755 .  # Ensure directory is writable
   ```

2. Specify a writable path:
   ```python
   hiitl = HIITL(
       ...
       audit_db_path="./data/hiitl_audit.db"  # Ensure ./data/ exists and is writable
   )
   ```

3. For serverless/Lambda, use `/tmp/`:
   ```python
   audit_db_path="/tmp/hiitl_audit.db"  # /tmp is writable in Lambda
   ```

### Database Locked

**Symptoms**:
```
sqlite3.OperationalError: database is locked
```

**Causes**:
- Multiple processes accessing same DB
- Long-running transactions
- NFS/network filesystem (not recommended for SQLite)

**Solutions**:
1. Use separate DB per process:
   ```python
   import os
   audit_db_path = f"./hiitl_audit_{os.getpid()}.db"
   ```

2. Enable WAL mode (Write-Ahead Logging) for better concurrency:
   ```python
   # SQLite automatically uses WAL mode if beneficial
   # Or manually enable in DB:
   # PRAGMA journal_mode=WAL;
   ```

3. Don't use SQLite on network filesystems (NFS, SMB)
   - Use local filesystem only
   - For multi-instance, use hosted mode instead

### Audit Database Growing Too Large

**Symptoms**:
- `hiitl_audit.db` file is very large (> 1GB)
- Slow queries

**Solutions**:
1. Archive old records periodically:
   ```python
   import sqlite3

   conn = sqlite3.connect("hiitl_audit.db")
   # Archive records older than 30 days
   conn.execute("DELETE FROM audit_log WHERE timestamp < datetime('now', '-30 days')")
   conn.execute("VACUUM")  # Reclaim space
   conn.close()
   ```

2. Rotate DB files:
   ```python
   from datetime import datetime
   audit_db_path = f"./audit_{datetime.now().strftime('%Y%m')}.db"
   ```

3. Consider hosted mode for long-term audit retention

---

## Performance Issues

### Latency > 10ms

**Symptoms**:
- Evaluation taking longer than expected
- `decision.timing.total_ms > 10`

**Diagnostics**:
```python
decision = hiitl.evaluate(...)
print(f"Total: {decision.timing['total_ms']}ms")
print(f"  Policy load: {decision.timing.get('policy_load_ms', 0)}ms")
print(f"  Evaluation: {decision.timing.get('evaluation_ms', 0)}ms")
print(f"  Audit write: {decision.timing.get('audit_write_ms', 0)}ms")
```

**Solutions**:

1. **Policy caching is working**:
   - First call: ~5-10ms (loads policy)
   - Subsequent calls: < 1ms (cached)
   - If all calls are slow, caching may not be working

2. **Simplify policy**:
   ```yaml
   # SLOW - many complex conditions
   rules:
     - conditions:
         all_of:
           - field: "parameters.deeply.nested.value"
             operator: "contains"
             value: "complex_regex_.*"

   # FAST - simple flat conditions
   rules:
     - conditions:
         all_of:
           - field: "tool"
             operator: "equals"
             value: "payment"
   ```

3. **Check disk I/O** (SQLite writes):
   - Use SSD instead of HDD
   - Ensure `/tmp` is on tmpfs (RAM disk) if possible

4. **Disable features if not needed**:
   ```python
   hiitl = HIITL(
       ...
       enable_rate_limiting=False,  # Disable if not using rate limits
   )
   ```

See: [Performance Tuning Guide](performance.md) for detailed optimization strategies

---

## Rate Limiting Problems

### Rate Limits Not Working

**Symptoms**:
- Actions not being rate limited when they should be
- `decision.decision` never equals `"RATE_LIMIT"`

**Solutions**:
1. **Check rate limiting is enabled**:
   ```python
   hiitl = HIITL(
       ...
       enable_rate_limiting=True,  # Must be True
   )
   ```

2. **Verify policy has rate_limit metadata**:
   ```yaml
   rules:
     - name: "rate-limit-payments"
       enabled: true
       priority: 100
       conditions:
         all_of:
           - field: "tool"
             operator: "equals"
             value: "payment"
       decision: "ALLOW"
       metadata:
         rate_limit:
           scope: "user_id"  # or "org", "tool", "user:tool"
           window: "hour"    # or "minute", "day"
           limit: 10
   ```

3. **Check scope key is present**:
   ```python
   # If scope is "user_id", envelope MUST have user_id
   decision = hiitl.evaluate(
       tool="payment",
       user_id="user_123",  # Required for user_id scope
       ...
   )
   ```

### Rate Limits Resetting Unexpectedly

**Symptoms**:
- Rate limits reset when process restarts
- Counters not persisting

**Cause**:
- Local mode uses **in-memory** rate limiting
- Counters are lost on process restart

**Solutions**:
1. This is expected behavior for local mode
2. For persistent rate limits, use hosted mode
3. For production with rate limiting, use hosted mode with Redis

---

## Evaluation Not Working as Expected

### Decision is BLOCK but Should be ALLOW

**Debug Steps**:

1. **Check matched rules**:
   ```python
   decision = hiitl.evaluate(...)
   print(f"Decision: {decision.decision}")
   print(f"Matched rules: {decision.matched_rules}")
   print(f"Reason codes: {decision.reason_codes}")
   ```

2. **Verify rule priority order**:
   - Higher priority rules are evaluated first
   - First matching rule wins

3. **Check condition operators**:
   ```yaml
   # Common mistakes
   - field: "parameters.amount"
     operator: "greater_than"
     value: 100  # NOTE: value is numeric, not string "100"

   - field: "tool"
     operator: "equals"  # NOT "equal"
     value: "payment"
   ```

4. **Inspect envelope**:
   ```python
   # Enable debug logging to see envelope
   import logging
   logging.basicConfig(level=logging.DEBUG)

   decision = hiitl.evaluate(...)
   # Logs will show: "Evaluating envelope: {...}"
   ```

---

## TypeScript-Specific Issues

### Module Resolution Errors

**Symptoms**:
```
Cannot find module '@hiitl/core' or its corresponding type declarations
```

**Solutions**:
1. Ensure `@hiitl/core` is installed:
   ```bash
   npm install @hiitl/core
   ```

2. Check `tsconfig.json`:
   ```json
   {
     "compilerOptions": {
       "module": "ESNext",
       "moduleResolution": "node",
       "esModuleInterop": true
     }
   }
   ```

### `evaluate()` not awaited

**Symptoms**:
```typescript
const decision = hiitl.evaluate(...);  // Missing await
if (decision.allowed) { ... }  // TypeError: decision is a Promise
```

**Solution**:
```typescript
const decision = await hiitl.evaluate(...);  // Add await
```

### Type Errors with `snake_case` vs `camelCase`

**Symptoms**:
```
Property 'agent_id' does not exist. Did you mean 'agentId'?
```

**Solution**:
The SDK uses `snake_case` to match the spec:
```typescript
const hiitl = new HIITL({
  agent_id: 'test',  // snake_case (correct)
  org_id: 'org_local',
  policy_path: './policy.yaml',
});
```

---

## Python-Specific Issues

### YAML Parsing Errors

**Symptoms**:
```
yaml.scanner.ScannerError: mapping values are not allowed here
```

**Solutions**:
1. Check YAML indentation (must use spaces, not tabs):
   ```yaml
   # WRONG - uses tabs or inconsistent indentation
   policy_set:
   	scope:
     	org_id: "test"

   # CORRECT - consistent 2-space indentation
   policy_set:
     scope:
       org_id: "test"
   ```

2. Quote special characters:
   ```yaml
   # WRONG
   reason_code: Payment: too high

   # CORRECT
   reason_code: "Payment: too high"
   ```

---

## Still Having Issues?

If you've tried the above solutions and are still experiencing problems:

1. **Enable debug logging**:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Check versions**:
   ```bash
   pip show hiitl  # Python
   npm list @hiitl/sdk  # TypeScript
   ```

3. **Review specs**:
   - [Envelope Schema](../specs/envelope_schema.json)
   - [Policy Format](../specs/policy_format.md)
   - [Decision Response](../specs/decision_response.md)

4. **Get help**:
   - GitHub Issues: [hiitlhq/hiitl](https://github.com/hiitlhq/hiitl/issues)
   - Documentation: https://docs.hiitl.ai
   - Discord: https://discord.gg/hiitl

---

**See also**:
- [Performance Tuning Guide](performance.md)
- [Local → Hosted Migration Guide](local_to_hosted_migration.md)
- [Python Quickstart](quickstart_python.md)
- [TypeScript Quickstart](quickstart_typescript.md)
