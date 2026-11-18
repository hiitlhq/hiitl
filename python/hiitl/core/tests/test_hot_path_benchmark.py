"""Block 1B (10f): hot-path evaluator benchmark.

Measures evaluation latency under representative policy shapes after
Block 1A's scope/temporal/lifecycle additions and Block 1B 9b's
side-by-side evaluation. Retains p50 / p95 / p99 measurements for each
shape without promoting an observed duration into a pass/fail limit.

This file double-duties:
- Pytest: each scenario records structured measurements in its test report.
- Direct benchmark: each scenario prints stats for the dev-loop log.

Scenarios:
- `tiny_active`       : 1 active rule, no scope, no staged.
- `small_active`      : 5 active rules, no scope.
- `medium_with_scope` : 20 active rules, all with scope filters.
- `medium_with_staged`: 20 mixed (10 active + 10 staged) — exercises 9b.
- `large_with_staged` : 100 mixed (50 active + 50 staged) — worst-case shape
                        we care about; this is the one most likely to surface
                        regressions from the side-by-side walk.

Numbers are *per single evaluation* of one envelope. HTL-30 retires the
undeclared p95 headroom limit; declared targets remain in their owning cells.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import Callable
from types import SimpleNamespace

import pytest

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.statistics import percentile
from hiitl.core.tests.measurements import record_measurement
from hiitl.core.types import (
    ENVELOPE_SCHEMA_VERSION,
    Condition,
    ConditionOperator,
    DecisionType,
    Envelope,
    Environment,
    Operation,
    PolicySet,
    Rule,
    RuleScope,
)


ITERATIONS = 1500
WARMUP = 200


def _envelope() -> Envelope:
    return Envelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        org_id="org_test123456789012",
        environment=Environment.DEV,
        agent_id="bench-agent",
        action_id="act_bench0000000000000001",
        idempotency_key="idem_bench",
        action="send_email",
        operation=Operation.EXECUTE,
        target={"to": "alice@example.com"},
        parameters={"subject": "x", "body": "y"},
        timestamp=datetime.now(timezone.utc),
        signature="a" * 64,
    )


def _rule(
    name: str,
    *,
    decision: DecisionType = DecisionType.ALLOW,
    lifecycle_stage: str = "active",
    priority: int = 100,
    field: str = "action",
    value: object = "send_email",
    scope: RuleScope | None = None,
) -> Rule:
    return Rule(
        name=name,
        description=f"benchmark rule {name}",
        priority=priority,
        conditions=Condition(
            field=field, operator=ConditionOperator.EQUALS, value=value,
        ),
        decision=decision,
        reason_code="BENCH_MATCH",
        lifecycle_stage=lifecycle_stage,
        **({"scope": scope} if scope is not None else {}),
    )


# ============================================================================
# Scenarios
# ============================================================================


def _scenario_tiny_active() -> PolicySet:
    return PolicySet(name="tiny", version="v1.0.0", description="The tiny set", scope={"org_id": "org_test123456789012", "environment": "dev"}, rules=[_rule("only")])


def _scenario_small_active() -> PolicySet:
    return PolicySet(
        name="small", version="v1.0.0", description="The small set", scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule(f"r{i}", priority=100 + i, value=f"v{i}")
            for i in range(4)
        ] + [_rule("match", priority=10)],
    )


def _scenario_medium_with_scope() -> PolicySet:
    scope = RuleScope(environments=["dev"], agents=["bench-agent"])
    return PolicySet(
        name="medium_scope", version="v1.0.0", description="The medium_scope set", scope={"org_id": "org_test123456789012", "environment": "dev"},
        rules=[
            _rule(f"r{i}", priority=100 + i, value=f"v{i}", scope=scope)
            for i in range(19)
        ] + [_rule("match", priority=10, scope=scope)],
    )


def _scenario_medium_with_staged() -> PolicySet:
    rules = []
    for i in range(10):
        rules.append(_rule(
            f"a{i}", priority=100 + i, value=f"v{i}",
            lifecycle_stage="active",
        ))
    for i in range(10):
        rules.append(_rule(
            f"s{i}", priority=200 + i, value="send_email",
            decision=DecisionType.BLOCK,
            lifecycle_stage="staged",
        ))
    rules.append(_rule("match", priority=10))
    return PolicySet(name="medium_staged", version="v1.0.0", description="The medium_staged set", scope={"org_id": "org_test123456789012", "environment": "dev"}, rules=rules)


def _scenario_large_with_staged() -> PolicySet:
    rules = []
    for i in range(50):
        rules.append(_rule(
            f"a{i}", priority=100 + i, value=f"v{i}",
            lifecycle_stage="active",
        ))
    for i in range(50):
        rules.append(_rule(
            f"s{i}", priority=500 + i, value="send_email",
            decision=DecisionType.BLOCK,
            lifecycle_stage="staged",
        ))
    rules.append(_rule("match", priority=10))
    return PolicySet(name="large_staged", version="v1.0.0", description="The large_staged set", scope={"org_id": "org_test123456789012", "environment": "dev"}, rules=rules)


SCENARIOS: dict[str, Callable[[], PolicySet]] = {
    "tiny_active": _scenario_tiny_active,
    "small_active": _scenario_small_active,
    "medium_with_scope": _scenario_medium_with_scope,
    "medium_with_staged": _scenario_medium_with_staged,
    "large_with_staged": _scenario_large_with_staged,
}


# ============================================================================
# Benchmark harness
# ============================================================================


def _benchmark(policy: PolicySet) -> dict[str, float]:
    """Run ITERATIONS evaluations and return latency stats in milliseconds."""
    evaluator = PolicyEvaluator()
    env = _envelope()

    # Warmup — first calls trigger JIT-like behavior (model validation
    # cache warming) and skew percentiles.
    for _ in range(WARMUP):
        evaluator.evaluate(env, policy)

    samples = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        evaluator.evaluate(env, policy)
        samples.append((time.perf_counter() - t0) * 1000.0)

    return {
        "iterations": float(ITERATIONS),
        "min_ms": min(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "max_ms": max(samples),
    }


# ============================================================================
# Pytest entry — one parametrized test per scenario.
# ============================================================================


def test_benchmark_percentiles_interpolate_between_samples(monkeypatch):
    """The real benchmark reports the ruled statistic for its measured intervals."""
    clock = iter([0.0, 0.0, 0.0, 0.010])
    monkeypatch.setattr(f"{__name__}.time", SimpleNamespace(perf_counter=lambda: next(clock)))
    monkeypatch.setattr(f"{__name__}.ITERATIONS", 2)
    monkeypatch.setattr(f"{__name__}.WARMUP", 0)

    assert _benchmark(_scenario_tiny_active()) == {
        "iterations": 2.0, "min_ms": 0.0, "p50_ms": 5.0,
        "p95_ms": 9.5, "p99_ms": 9.9, "max_ms": 10.0,
    }


@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
def test_hot_path_latency_record(scenario_name, record_property):
    """Retain each scenario's measured latency distribution, without an invented tier."""
    policy = SCENARIOS[scenario_name]()
    stats = _benchmark(policy)
    print(
        f"\n[benchmark] {scenario_name}: "
        f"p50={stats['p50_ms']:.3f}ms "
        f"p95={stats['p95_ms']:.3f}ms "
        f"p99={stats['p99_ms']:.3f}ms "
        f"max={stats['max_ms']:.3f}ms "
        f"({int(stats['iterations'])} iters)",
        file=sys.stderr,
    )
    record_measurement(record_property, metric=f"core_hot_path.{scenario_name}", unit="ms",
                       source="hiitl.core.evaluator.PolicyEvaluator.evaluate",
                       value={name: value for name, value in stats.items() if name != "iterations"})
    record_measurement(record_property, metric=f"core_hot_path.{scenario_name}.samples", unit="evaluations",
                       source="hiitl.core.tests.test_hot_path_benchmark._benchmark",
                       value={"warmup": WARMUP, "measured": stats["iterations"]})


if __name__ == "__main__":
    # Allow running this file directly: python -m hiitl.core.tests.test_hot_path_benchmark
    for name, builder in SCENARIOS.items():
        stats = _benchmark(builder())
        print(
            f"{name:30s} "
            f"p50={stats['p50_ms']:.3f}ms "
            f"p95={stats['p95_ms']:.3f}ms "
            f"p99={stats['p99_ms']:.3f}ms "
            f"max={stats['max_ms']:.3f}ms"
        )
