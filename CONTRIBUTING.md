# Contributing to hiitl

Thanks for your interest in contributing to hiitl. This document covers development setup, testing, and the PR process.

## Development setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Git

### Clone and install

```bash
git clone https://github.com/hiitlhq/hiitl.git
cd hiitl
```

**Python SDK + evaluator:**
```bash
cd python
pip install -e ".[dev]"
```

**TypeScript SDK + evaluator:**
```bash
cd typescript/packages/core
npm install

cd ../sdk
npm install
```

## Running tests

### Conformance tests

Both Python and TypeScript evaluators must produce identical decisions. The conformance suite has 75 JSON test cases.

```bash
# Python
cd python
python -m pytest hiitl/core/tests/conformance/

# TypeScript
cd typescript/packages/core
npx vitest run
```

### Unit tests

```bash
# Python evaluator + SDK
cd python
python -m pytest

# TypeScript evaluator + SDK
cd typescript/packages/core && npx vitest run
cd typescript/packages/sdk && npx vitest run
```

### All tests

```bash
# From project root — Python
cd python && python -m pytest && cd ..

# From project root — TypeScript
cd typescript/packages/core && npx vitest run && cd ../../..
```

## Project structure

```
hiitl/
├── python/hiitl/
│   ├── core/           # Policy evaluator + types (Python)
│   └── sdk/            # Python SDK (local + hosted)
├── typescript/packages/
│   ├── core/           # Policy evaluator + types (TypeScript)
│   └── sdk/            # TypeScript SDK (local + hosted)
├── tests/conformance/  # Cross-language conformance test cases (JSON)
├── patterns/           # Action pattern templates (YAML)
├── docs/
│   ├── specs/          # Language-neutral specifications (source of truth)
│   └── onboarding/     # Developer guides
└── examples/           # Standalone runnable examples
```

## Making changes

### Branch naming

```
feat/short-description    # New features
fix/short-description     # Bug fixes
refactor/short-description # Structural changes
```

### Commit conventions

We use [conventional commits](https://www.conventionalcommits.org/):

```
feat(sdk): add rate limit counter to decision response
fix(evaluator): handle empty conditions array in rules
test: add conformance tests for OBSERVE mode
docs: update Python quickstart with new API
```

Scope to the relevant component when applicable: `sdk`, `evaluator`, `decision`, `audit`.

### What to include in a PR

- Clear description of what changed and why
- Which components are affected (Python evaluator, TypeScript SDK, etc.)
- Test coverage for new behavior
- Documentation updates if the change affects the public API
- Conformance test updates if evaluator behavior changes

### Code quality

- **Specs are source of truth.** If the implementation disagrees with a spec in `docs/specs/`, the implementation has a bug.
- **Both evaluators must agree.** Any change to evaluation logic must be mirrored in both Python and TypeScript, validated by conformance tests.
- **Performance matters.** Policy evaluation must complete in single-digit milliseconds locally. Include benchmarks for performance-sensitive changes.
- **Fail-closed by default.** When in doubt, block the action. Fail-open is always opt-in.
- **Helpful errors.** Error messages should explain what went wrong and what to do about it.

### Testing requirements

- New policy evaluation behavior needs conformance test cases (JSON in `tests/conformance/cases/`)
- New SDK features need unit tests in both languages
- Breaking changes to specs need migration documentation

## Architecture overview

hiitl has four internal planes:

1. **SDK / Ingest** — Developer-facing SDKs, envelope construction
2. **Decision** — Deterministic policy evaluation, rate limiting, kill switches
3. **Execution** — Optional adapters for action execution
4. **Audit / Ops** — Immutable logging, policy management

Key design principles:

- **Deterministic enforcement** — No LLM inference at decision time
- **Language-neutral specs** — JSON Schema and markdown define behavior; implementations follow
- **Architecturally neutral** — Works with any agent framework
- **Immutable audit** — Every action produces a record, even if blocked

## Questions?

Open an [issue on GitHub](https://github.com/hiitlhq/hiitl/issues) for questions about contributing.
