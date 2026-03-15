# Observe-First Example

Zero-config observation mode. See what your agents are doing before writing any policies.

## Run

```bash
pip install hiitl
python main.py
```

## What this demonstrates

- `HIITL()` with no arguments — zero config
- `OBSERVE_ALL` mode (default) — everything is logged, nothing is blocked
- `decision.observed` flag
- `decision.would_be` — what enforcement mode would have done
- How observation data helps you write better policies
