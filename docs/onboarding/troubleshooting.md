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
Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@hiitl/sdk' imported from ...
```

**Fix**:
```bash
npm install @hiitl/sdk
```

The SDK is an ES module only: load it with `import`. `require('@hiitl/sdk')` fails even when it is installed (`ERR_PACKAGE_PATH_NOT_EXPORTED`).

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

**Symptoms**: `evaluate()` returns `POLICY_ERROR` with reason code `POLICY_NOT_FOUND` (TypeScript: the constructor throws), and the log reads:
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

**Symptoms**: `evaluate()` returns `POLICY_ERROR` with reason code `POLICY_VALIDATION_ERROR` (TypeScript: the constructor throws), and the log reads:
```
PolicyLoadError: Invalid policy format in ./policy.yaml: ...
PolicyLoadError: Invalid YAML in ./policy.yaml: ...
```

**Solutions**:
1. Validate YAML syntax:
   ```bash
   # Install yamllint
   pip install yamllint
   yamllint policy.yaml
   ```

2. Check against policy_format.md spec:
   - The set has `name`, `version` and `rules`
   - Every rule has `name`, `description`, `priority`, `conditions`, `decision` and `reason_code`
   - Retired keys are refused with their replacement named (for example, `enabled` was replaced by `lifecycle_stage`)
   - `scope` is optional in a local policy file; the local SDK does not compare it with its own configuration

3. Common mistakes: a rule without `description` or `reason_code` is refused with `PolicyLoadError`, and the error names each missing field (`rules.0.description`, `rules.0.reason_code`). Python logs it at the first `evaluate()`, which returns `POLICY_ERROR`; TypeScript throws it from the constructor. A complete rule:
   ```yaml
   policy_set:
     name: "payments"
     version: "v1.0.0"
     description: "Policy Syntax Errors"
     scope:
       org_id: "org_devlocal0000000000"
       environment: "dev"
     rules:
       - name: "block-large-payments"
         description: "Payments over $500 are refused"
         priority: 100
         conditions: {field: "parameters.amount", operator: "greater_than", value: 500}
         decision: "BLOCK"
         reason_code: "PAYMENT_TOO_HIGH"
   ```

### Policy Not Applying (Always ALLOW)

**Symptoms**:
- All actions are allowed (`decision.allowed` is `True`)
- Rules that should block return `OBSERVE`, or policy rules never match

**Solutions**:
1. **Check the mode**: the default `mode="OBSERVE_ALL"` records what a blocking rule would do (`decision.would_be`) and lets the action through. To enforce, set `mode="RESPECT_POLICY"`:
   ```python
   hiitl = HIITL(environment="dev", agent_id="test", policy_path="./policy.yaml", mode="RESPECT_POLICY")
   ```

2. **Verify policy_path is set**:
   ```python
   # WRONG - no policy loaded
   hiitl = HIITL(environment="dev", agent_id="test")

   # CORRECT
   hiitl = HIITL(
       environment="dev",
       agent_id="test",
       policy_path="./policy.yaml",  # Policy loaded
       mode="RESPECT_POLICY",
   )
   ```

3. **Check rule priority order** (higher priority = evaluated first within each group; `KILL_SWITCH` rules come first, then `BLOCK` rules, then the rest, whatever their priority):
   ```yaml
   policy_set:
     name: "payments-policy"
     version: "v1.0.0"
     description: "Policy Not Applying (Always ALLOW)"
     scope:
       org_id: "org_devlocal0000000000"
       environment: "dev"
     rules:
       - name: "specific-rule"
         description: "Payments over $1,000 wait for approval"
         priority: 100  # Evaluated first
         conditions:
           all_of:
             - field: "action"
               operator: "equals"
               value: "payment"
             - field: "parameters.amount"
               operator: "greater_than"
               value: 1000
         decision: "REQUIRE_APPROVAL"
         reason_code: "LARGE_PAYMENT"

       - name: "default-allow"
         description: "Every other action proceeds"
         priority: 1    # Evaluated last (fallback)
         conditions:
           field: "action"
           operator: "exists"
           value: true
         decision: "ALLOW"
         reason_code: "DEFAULT_ALLOW"
   ```

---

## SQLite / Audit Log Issues

### Permission Denied

**Symptoms**:
```
# Python
ConfigurationError: Failed to initialize HIITL components: Failed to initialize audit database hiitl_audit.db: unable to open database file
# TypeScript
AuditLogError: Failed to initialize audit database at ./hiitl_audit.db: unable to open database file
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
       audit_db_path="./data/hiitl_audit.db"  # The SDK creates ./data/ if missing; the location must be writable
   )
   ```

3. For serverless/Lambda, use `/tmp/`:
   ```python
   audit_db_path="/tmp/hiitl_audit.db"  # /tmp is writable in Lambda
   ```

### Database Locked

**Symptoms**: `evaluate()` returns `BLOCK` with `error.code` `AUDIT_WRITE_FAILED`, and the log reads:
```
Audit write failed (fail-closed): Failed to write audit record to hiitl_audit.db: database is locked
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

2. Enable WAL mode (Write-Ahead Logging) for better concurrency. The SDK does not turn it on; set it once on the database file (SQLite stores the setting in the file):
   ```bash
   sqlite3 hiitl_audit.db "PRAGMA journal_mode=WAL;"
   ```

3. Don't use SQLite on network filesystems (NFS, SMB)
   - Use local filesystem only
   - For multi-instance, use hosted mode instead

### Audit Database Growing Too Large

**Symptoms**:
- `hiitl_audit.db` file is very large (> 1GB)
- Slow queries

**Solutions**:
1. Rotate DB files, and archive each old file whole:
   ```python
   from datetime import datetime
   audit_db_path = f"./audit_{datetime.now().strftime('%Y%m')}.db"
   ```
   In hybrid mode the SDK uploads records only from the file it is currently writing.

2. Consider hosted mode for long-term audit retention

---

## Performance Issues

### Latency > 10ms

**Symptoms**:
- Evaluation taking longer than expected
- A timed `evaluate()` call takes > 10ms

**Diagnostics**:
```python
decision = hiitl.evaluate(...)
print(f"Total: {decision.timing.total_ms}ms")
print(f"  Envelope validation: {decision.timing.ingest_ms}ms")
print(f"  Evaluation: {decision.timing.evaluation_ms}ms")
```

`decision.timing` covers the evaluator only. If it is small and the call is slow, the time is in the policy load, the rate-limit check or the audit write: time the call yourself to see the difference.

**Solutions**:

1. **Policy caching is working**:
   - First call: ~5-10ms (loads policy)
   - Subsequent calls: < 1ms (cached)
   - If all calls are slow, caching may not be working

2. **Simplify policy**:
   ```yaml
   # SLOW - many complex conditions
   policy_set:
     name: "regex-on-nested-field"
     version: "v1.0.0"
     description: "A regex on a nested field, matched on every call"
     scope:
       org_id: "org_devlocal0000000000"
       environment: "dev"
     rules:
       - name: "match-nested-pattern"
         description: "A regular expression on a deeply nested parameter"
         priority: 100
         conditions:
           all_of:
             - field: "parameters.deeply.nested.value"
               operator: "matches"
               value: "complex_regex_.*"
         decision: "BLOCK"
         reason_code: "PATTERN_MATCHED"
   ```

   ```yaml
   # FAST - simple flat conditions
   policy_set:
     name: "flat-equality"
     version: "v1.0.0"
     description: "Flat equality on the action, matched first"
     scope:
       org_id: "org_devlocal0000000000"
       environment: "dev"
     rules:
       - name: "allow-payments"
         description: "One equality check on the action name"
         priority: 100
         conditions:
           all_of:
             - field: "action"
               operator: "equals"
               value: "payment"
         decision: "ALLOW"
         reason_code: "PAYMENT_ALLOWED"
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

2. **Verify the policy has a `RATE_LIMIT` rule with a `rate_limit` window, and a rule that allows the call**:
   ```yaml
   policy_set:
     name: "payment-rate-limits"
     version: "v1.0.0"
     description: "Rate Limits Not Working"
     scope:
       org_id: "org_devlocal0000000000"
       environment: "dev"
     rules:
       - name: "rate-limit-payments"
         description: "At most 10 payments an hour per user"
         priority: 100
         conditions:
           all_of:
             - field: "action"
               operator: "equals"
               value: "payment"
         decision: "RATE_LIMIT"
         reason_code: "PAYMENT_RATE"
         rate_limit:
           scope: "user"         # or "org", "agent", "action", "user_action"
           window_seconds: 3600  # one hour
           limit: 10

       - name: "allow-payments"
         description: "Payments proceed (only ALLOW decisions are counted)"
         priority: 10
         conditions:
           all_of:
             - field: "action"
               operator: "equals"
               value: "payment"
         decision: "ALLOW"
         reason_code: "PAYMENT_ALLOWED"
   ```
   A windowed `RATE_LIMIT` rule counts the calls it matches; it does not decide them. Calls are counted only when the decision is `ALLOW`, so the limit never trips on calls another rule blocks, or on calls another window refused. A `metadata.rate_limit` block on a rule is not read: move it to `rate_limit` on a `RATE_LIMIT` rule.

3. **Check scope key is present**:
   ```python
   # If scope is "user", pass user_id: calls without one all share a single counter
   decision = hiitl.evaluate(
       "payment",
       user_id="user_123",
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
1. This is expected behavior for local mode (hybrid mode also counts in memory, per process)
2. For persistent rate limits, use hosted mode
3. For production with rate limiting, use hosted evaluation: the hosted service keeps the counters in its database, shared across instances

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
   - `KILL_SWITCH` rules are evaluated first, then `BLOCK` rules, then the rest, whatever their priority
   - Within each group, higher priority rules are evaluated first
   - The first active matching rule wins

3. **Check condition operators**:
   ```yaml
   # Common mistakes
   - field: "parameters.amount"
     operator: "greater_than"
     value: 100  # NOTE: value is numeric, not string "100"

   - field: "action"
     operator: "equals"  # NOT "equal"
     value: "payment"
   ```

4. **Inspect envelope**:
   ```bash
   # The audit record holds each envelope as it was evaluated
   sqlite3 hiitl_audit.db "SELECT envelope FROM audit_log ORDER BY timestamp DESC LIMIT 1;"
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
if (decision.allowed) { ... }  // error TS2339: Property 'allowed' does not exist on type '... | Promise<...>'
```

**Solution**:
```typescript
const decision = await hiitl.evaluate(...);  // Add await
```

`evaluate()` returns a Promise in hybrid and hosted mode and a decision directly in local mode; its type covers both, so always `await` it.

### Type Errors with `snake_case` vs `camelCase`

**Symptoms**:
```
Object literal may only specify known properties, but 'agentId' does not exist in type 'HIITLConfigInput'. Did you mean to write 'agent_id'?
```

**Solution**:
The SDK uses `snake_case` to match the spec:
```typescript
const hiitl = new HIITL({
  agent_id: 'test',  // snake_case (correct)
  org_id: 'org_devlocal0000000000',
  policy_path: './policy.yaml',
});
```

---

## Python-Specific Issues

### YAML Parsing Errors

**Symptoms**:
```
PolicyLoadError: Invalid YAML in policy.yaml:
mapping values are not allowed here
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
   - Documentation: the `docs-site/` directory of https://github.com/hiitlhq/hiitl
   - Discord: https://discord.gg/hiitl

---

**See also**:
- [Performance Tuning Guide](performance.md)
- [Local → Hosted Migration Guide](local_to_hosted_migration.md)
- [Python Quickstart](quickstart_python.md)
- [TypeScript Quickstart](quickstart_typescript.md)
