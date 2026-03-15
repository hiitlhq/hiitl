# Quickstart Example

Minimal hiitl integration — evaluate a single action.

## Python

```bash
pip install hiitl
python main.py
```

## TypeScript

```bash
npm install @hiitl/sdk
npx ts-node main.ts
```

## What this demonstrates

- Zero-config initialization (`HIITL()` with no arguments)
- Single `evaluate()` call
- Checking `decision.allowed` before executing
- OBSERVE mode (default) — everything is logged, nothing is blocked
