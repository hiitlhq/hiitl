# TEST_DESIGN.md — Synthetic Test Runner

## Purpose

Validate the synthetic test runner's core components: assertion engine, envelope generation, policy grading, scenario execution, and CLI.

## Critical Behaviors

| Behavior | Validated By | Status |
|----------|-------------|--------|
| Field path resolution (dot notation, array index) | test_assertions.py | PROVEN |
| All assertion operators (equals, exists, gt, lt, contains) | test_assertions.py | PROVEN |
| Deterministic envelope generation (seed reproducibility) | test_envelope_factory.py | PROVEN |
| Distribution sampling (exponential, categorical, pattern) | test_envelope_factory.py | PROVEN |
| Generated envelopes pass Pydantic validation | test_envelope_factory.py | PROVEN |
| Grading coverage % calculation | test_grader.py | PROVEN |
| Gap identification (unmatched rules, uncovered actions) | test_grader.py | PROVEN |
| Strategy pattern (pluggable grading) | test_grader.py | PROVEN |
| Scenario execution with assertion validation | test_executor.py | PROVEN |
| Phase 2 step skipping | test_executor.py | PROVEN |
| CLI commands (list, run, generate, grade) | test_cli.py | PROVEN |

## Test Design Approach

- Tests designed from the runner's requirements, not implementation details
- All tests use inline data (no file system dependencies except CLI tests)
- Envelope factory tests verify determinism with fixed seeds
- Grading tests verify mathematical correctness of coverage calculation
- Executor tests use minimal policies and scenarios

## Gaps

- No hosted mode testing (Phase 1 is local-only)
- No anomaly pattern generation testing (future enhancement)
- No LLM grading strategy testing (Phase 2+)
