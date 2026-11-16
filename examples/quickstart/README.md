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
node main.ts
```

The SDK requires Node.js 22 or later. Node.js 22.18 or later runs `main.ts` directly; on earlier Node.js 22 releases, compile it with `tsc` first. The SDK is an ES module, so compile to ES modules, not CommonJS.

## What this demonstrates

- Zero-config initialization (`HIITL()` with no arguments)
- Single `evaluate()` call
- Checking `decision.allowed` before executing
- OBSERVE mode (default) — policy refusals are observed; audit write failures still block
