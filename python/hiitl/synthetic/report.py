"""Report generation — JSON output and console summary.

Produces two output formats:
1. JSON report: Full RunReport, consumable by UI Testing page
2. Console summary: Human-readable pass/fail with grading stats
"""

import json
import sys
from datetime import datetime, timezone
from typing import IO, List, Optional
from uuid import uuid4

from .types import GradingReport, RunReport, ScenarioResult


def build_run_report(
    scenarios: List[ScenarioResult],
    grading: Optional[GradingReport] = None,
    mode: str = "local",
) -> RunReport:
    """Build a complete RunReport from scenario results and optional grading."""
    total_passed = sum(1 for s in scenarios if s.status == "passed")
    total_failed = sum(1 for s in scenarios if s.status in ("failed", "error"))
    total_assertions = sum(s.total_assertions for s in scenarios)
    assertions_passed = sum(s.assertions_passed for s in scenarios)
    total_latency = sum(s.total_latency_ms for s in scenarios)

    return RunReport(
        run_id=f"run_{uuid4().hex[:12]}",
        mode=mode,
        timestamp=datetime.now(timezone.utc),
        scenarios=scenarios,
        grading=grading,
        summary={
            "total_scenarios": len(scenarios),
            "passed": total_passed,
            "failed": total_failed,
            "total_assertions": total_assertions,
            "assertions_passed": assertions_passed,
            "assertions_failed": total_assertions - assertions_passed,
            "total_latency_ms": round(total_latency, 3),
        },
    )


def write_json_report(report: RunReport, output: IO) -> None:
    """Write JSON report to a file handle (or stdout)."""
    data = report.model_dump(mode="json")
    json.dump(data, output, indent=2, default=str)
    output.write("\n")


def print_console_summary(report: RunReport, file: IO = sys.stdout) -> None:
    """Print human-readable summary to console."""
    print("", file=file)
    print("=== HIITL Synthetic Test Results ===", file=file)
    print("", file=file)

    for scenario in report.scenarios:
        _print_scenario(scenario, file)

    print("=== Summary ===", file=file)
    s = report.summary
    status_icon = "PASSED" if s["failed"] == 0 else "FAILED"
    print(
        f"  Scenarios: {s['passed']} passed, {s['failed']} failed ({status_icon})",
        file=file,
    )
    print(
        f"  Assertions: {s['assertions_passed']} passed, {s['assertions_failed']} failed",
        file=file,
    )
    print(f"  Total time: {s['total_latency_ms']}ms", file=file)
    print("", file=file)

    if report.grading:
        _print_grading(report.grading, file)


def _print_scenario(scenario: ScenarioResult, file: IO) -> None:
    """Print a single scenario result."""
    icon = "PASSED" if scenario.status == "passed" else "FAILED"
    print(f"  Scenario: {scenario.scenario_name} [{icon}]", file=file)

    for step in scenario.steps:
        if step.status == "skipped":
            print(
                f"    Step {step.step}: {step.name} ... SKIPPED",
                file=file,
            )
        elif step.status == "passed":
            latency = f" ({step.latency_ms}ms)" if step.latency_ms else ""
            print(
                f"    Step {step.step}: {step.name} ... PASSED{latency}",
                file=file,
            )
        elif step.status == "failed":
            latency = f" ({step.latency_ms}ms)" if step.latency_ms else ""
            print(
                f"    Step {step.step}: {step.name} ... FAILED{latency}",
                file=file,
            )
            for a in step.assertions:
                if not a.passed:
                    print(f"      - {a.error_message}", file=file)
        elif step.status == "error":
            print(
                f"    Step {step.step}: {step.name} ... ERROR: {step.error}",
                file=file,
            )

    evaluate_steps = [s for s in scenario.steps if s.action == "evaluate"]
    skipped_steps = [s for s in scenario.steps if s.status == "skipped"]
    passed_evaluate = sum(1 for s in evaluate_steps if s.status == "passed")
    print(
        f"    Result: {icon} ({passed_evaluate}/{len(evaluate_steps)} evaluate steps passed"
        + (f", {len(skipped_steps)} skipped" if skipped_steps else "")
        + ")",
        file=file,
    )
    print("", file=file)


def _print_grading(grading: GradingReport, file: IO) -> None:
    """Print grading section."""
    print("  Policy Grading:", file=file)
    print(
        f"    Coverage: {grading.coverage_pct}% ({grading.rules_matched}/{grading.total_rules} rules matched)",
        file=file,
    )

    if grading.rules_unmatched > 0:
        unmatched = [
            g.details.get("rule_name", "?")
            for g in grading.gaps
            if g.gap_type == "unmatched_rule"
        ]
        print(f"    Unmatched rules: {', '.join(unmatched)}", file=file)

    uncovered = [g for g in grading.gaps if g.gap_type == "uncovered_action"]
    print(f"    Uncovered actions: {len(uncovered)}", file=file)

    if grading.decision_distribution:
        dist_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(grading.decision_distribution.items())
        )
        print(f"    Decisions: {dist_str}", file=file)

    print("", file=file)
