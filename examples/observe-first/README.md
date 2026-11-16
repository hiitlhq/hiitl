# Observe-First Example

Zero-config observation mode. See what your agents are doing before writing any policies.

## Run

```bash
pip install hiitl
python main.py
```

## What this demonstrates

- `HIITL()` with no arguments — zero config
- `OBSERVE_ALL` mode (default) — with no policy, everything is logged and nothing is blocked
- `decision.observed` flag
- `decision.would_be` and `decision.would_be_reason_codes` — what enforcement would have decided (`BLOCK`, `NO_MATCHING_RULE`, until a rule allows the action)
- How observation data helps you write better policies
