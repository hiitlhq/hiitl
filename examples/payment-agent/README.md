# Payment Agent Example

A payment processing agent with approval policies. Demonstrates policy enforcement, decision handling, and the observe-to-enforce progression.

## Run

```bash
pip install hiitl
python main.py
```

## What this demonstrates

- Policy file with multiple rules (amount thresholds, approval requirements)
- `RESPECT_POLICY` mode — policies are enforced
- Handling different decision types (`ALLOW`, `BLOCK`, `REQUIRE_APPROVAL`)
- Using `decision.needs_approval`, `decision.blocked`, `decision.reason_codes`
- Progressive enrichment (parameters, target, sensitivity)
