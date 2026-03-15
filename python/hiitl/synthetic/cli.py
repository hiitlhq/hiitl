"""CLI for HIITL synthetic test runner.

Usage:
    python -m hiitl.synthetic run <scenario-name>
    python -m hiitl.synthetic run --all
    python -m hiitl.synthetic list
    python -m hiitl.synthetic generate <agent-id> -n 100
    python -m hiitl.synthetic grade <policy-path> --agent <agent-id> -n 1000
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import PolicySet

from .agent_loader import AgentLoader
from .envelope_factory import EnvelopeFactory
from .executor import ScenarioExecutor
from .grader import PolicyGrader
from .report import build_run_report, print_console_summary, write_json_report
from .scenario_loader import ScenarioLoader


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="hiitl-synthetic",
        description="HIITL Synthetic Test Runner — validate policies, generate test data, grade coverage",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run scenario(s)")
    run_parser.add_argument(
        "scenario", nargs="?", help="Scenario name (e.g., basic-allow-block)"
    )
    run_parser.add_argument("--all", action="store_true", help="Run all scenarios")
    run_parser.add_argument("--policy", required=False, help="Path to policy file (JSON/YAML)")
    run_parser.add_argument("--output", help="Write JSON report to file")
    run_parser.add_argument("--json", action="store_true", help="JSON output to stdout")
    run_parser.add_argument("--seed", type=int, help="Random seed for determinism")
    run_parser.add_argument(
        "--org-id", default="org_synthetictest00001", help="Org ID for envelopes"
    )
    run_parser.add_argument(
        "--environment", default="dev", help="Environment (dev, stage, prod)"
    )
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    run_parser.add_argument("--scenarios-dir", help="Override scenarios directory")
    run_parser.add_argument("--agents-dir", help="Override agents directory")

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List available scenarios")
    list_parser.add_argument("--scenarios-dir", help="Override scenarios directory")

    # --- generate ---
    gen_parser = subparsers.add_parser(
        "generate", help="Generate envelopes from agent persona"
    )
    gen_parser.add_argument("agent_id", help="Agent persona ID (e.g., payment-agent)")
    gen_parser.add_argument(
        "-n", "--count", type=int, default=10, help="Number of envelopes (default: 10)"
    )
    gen_parser.add_argument("--seed", type=int, help="Random seed for determinism")
    gen_parser.add_argument("--output", help="Output file (JSONL format)")
    gen_parser.add_argument(
        "--org-id", default="org_synthetictest00001", help="Org ID"
    )
    gen_parser.add_argument("--environment", default="dev", help="Environment")
    gen_parser.add_argument("--agents-dir", help="Override agents directory")

    # --- grade ---
    grade_parser = subparsers.add_parser("grade", help="Grade a policy using generated envelopes")
    grade_parser.add_argument("policy", help="Path to policy file (JSON/YAML)")
    grade_parser.add_argument(
        "--agent", required=True, help="Agent persona ID for envelope generation"
    )
    grade_parser.add_argument(
        "-n", "--count", type=int, default=1000, help="Number of envelopes (default: 1000)"
    )
    grade_parser.add_argument("--seed", type=int, help="Random seed for determinism")
    grade_parser.add_argument("--json", action="store_true", help="JSON output")
    grade_parser.add_argument("--output", help="Output file")
    grade_parser.add_argument(
        "--org-id", default="org_synthetictest00001", help="Org ID"
    )
    grade_parser.add_argument("--environment", default="dev", help="Environment")
    grade_parser.add_argument("--agents-dir", help="Override agents directory")

    return parser


def _load_policy(policy_path: str) -> PolicySet:
    """Load a policy from a JSON or YAML file."""
    path = Path(policy_path)
    if not path.exists():
        print(f"Error: Policy file not found: {path}", file=sys.stderr)
        sys.exit(2)

    try:
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(text)
            except ImportError:
                print(
                    "Error: PyYAML is required for YAML policy files. Install with: pip install pyyaml",
                    file=sys.stderr,
                )
                sys.exit(2)
        else:
            data = json.loads(text)
        return PolicySet(**data)
    except Exception as e:
        print(f"Error loading policy '{path}': {e}", file=sys.stderr)
        sys.exit(2)


def _resolve_policy(
    cli_policy: Optional[str], scenario_policy_path: Optional[str], scenario_policy_set: Optional[dict]
) -> PolicySet:
    """Resolve policy from CLI arg, scenario file path, or inline policy.

    Precedence: CLI --policy > scenario.policy_path > scenario.policy_set
    """
    if cli_policy:
        return _load_policy(cli_policy)

    if scenario_policy_path:
        # Resolve relative to synthetic/scenarios/ directory
        path = Path(scenario_policy_path)
        if not path.is_absolute():
            scenarios_dir = Path(__file__).parent.parent.parent.parent / "synthetic" / "scenarios"
            path = (scenarios_dir / scenario_policy_path).resolve()
        return _load_policy(str(path))

    if scenario_policy_set:
        return PolicySet(**scenario_policy_set)

    print(
        "Error: No policy specified. Use --policy <path>, or add policy_path/policy_set to the scenario file.",
        file=sys.stderr,
    )
    sys.exit(2)


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the 'run' subcommand."""
    loader = ScenarioLoader(args.scenarios_dir)

    if args.all:
        scenarios = loader.load_all()
        if not scenarios:
            print("No scenarios found.", file=sys.stderr)
            return 2
    elif args.scenario:
        try:
            scenarios = [loader.load(args.scenario)]
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
    else:
        print("Error: Specify a scenario name or use --all", file=sys.stderr)
        return 2

    evaluator = PolicyEvaluator()
    all_results = []

    for scenario in scenarios:
        policy = _resolve_policy(
            getattr(args, "policy", None),
            scenario.policy_path,
            scenario.policy_set,
        )
        grader = PolicyGrader(policy)
        executor = ScenarioExecutor(
            evaluator=evaluator,
            policy=policy,
            grader=grader,
            org_id=args.org_id,
            environment=args.environment,
        )
        result = executor.run(scenario)
        all_results.append((result, grader.grade()))

    scenario_results = [r for r, _ in all_results]
    # Merge grading from all scenarios
    combined_grading = all_results[0][1] if len(all_results) == 1 else all_results[0][1]

    report = build_run_report(scenario_results, grading=combined_grading)

    if args.json:
        write_json_report(report, sys.stdout)
    elif args.output:
        with open(args.output, "w") as f:
            write_json_report(report, f)
        print(f"Report written to {args.output}")
    else:
        print_console_summary(report)

    # Exit code: 0 if all passed, 1 if any failed
    return 0 if report.summary["failed"] == 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    """Execute the 'list' subcommand."""
    loader = ScenarioLoader(args.scenarios_dir)
    available = loader.list_available()

    if not available:
        print("No scenarios found.")
        return 0

    print("Available scenarios:")
    for name in available:
        try:
            scenario = loader.load(name)
            print(f"  {name} — {scenario.description}")
        except Exception:
            print(f"  {name} — (failed to load)")

    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Execute the 'generate' subcommand."""
    agent_loader = AgentLoader(args.agents_dir)

    try:
        agent = agent_loader.load(args.agent_id)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    factory = EnvelopeFactory(
        agent=agent,
        org_id=args.org_id,
        environment=args.environment,
        seed=args.seed,
    )

    envelopes = factory.generate_batch(args.count)

    # Output as JSONL
    output = open(args.output, "w") if args.output else sys.stdout
    try:
        for env in envelopes:
            line = env.model_dump_json()
            output.write(line + "\n")
    finally:
        if args.output:
            output.close()
            print(f"Generated {args.count} envelopes to {args.output}", file=sys.stderr)

    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    """Execute the 'grade' subcommand."""
    policy = _load_policy(args.policy)
    agent_loader = AgentLoader(args.agents_dir)

    try:
        agent = agent_loader.load(args.agent)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    factory = EnvelopeFactory(
        agent=agent,
        org_id=args.org_id,
        environment=args.environment,
        seed=args.seed,
    )
    evaluator = PolicyEvaluator()
    grader = PolicyGrader(policy)

    envelopes = factory.generate_batch(args.count)
    for env in envelopes:
        decision = evaluator.evaluate(env, policy)
        grader.record(decision)

    grading = grader.grade()

    if args.json:
        data = grading.model_dump(mode="json")
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    elif args.output:
        with open(args.output, "w") as f:
            data = grading.model_dump(mode="json")
            json.dump(data, f, indent=2, default=str)
        print(f"Grading report written to {args.output}")
    else:
        print("")
        print("=== Policy Grading Report ===")
        print(f"  Policy: {policy.name} v{policy.version}")
        print(f"  Agent: {agent.name} ({agent.agent_id})")
        print(f"  Envelopes evaluated: {grading.total_evaluations}")
        print("")
        print(f"  Coverage: {grading.coverage_pct}% ({grading.rules_matched}/{grading.total_rules} rules matched)")
        if grading.rules_unmatched > 0:
            unmatched = [
                g.details.get("rule_name", "?")
                for g in grading.gaps
                if g.gap_type == "unmatched_rule"
            ]
            print(f"  Unmatched rules: {', '.join(unmatched)}")

        uncovered = [g for g in grading.gaps if g.gap_type == "uncovered_action"]
        print(f"  Uncovered actions: {len(uncovered)}")

        if grading.decision_distribution:
            dist_str = ", ".join(
                f"{k}: {v}" for k, v in sorted(grading.decision_distribution.items())
            )
            print(f"  Decisions: {dist_str}")

        print("")
        # Per-rule breakdown
        if grading.rule_effectiveness:
            print("  Rule Effectiveness:")
            for rule in sorted(grading.rule_effectiveness, key=lambda r: r.matched_count, reverse=True):
                bar = "#" * min(40, int(rule.effectiveness_pct / 2.5))
                print(
                    f"    {rule.rule_name}: {rule.matched_count}/{rule.total_evaluations} "
                    f"({rule.effectiveness_pct:.1f}%) {bar}"
                )
            print("")

    return 0


def main(argv: Optional[list] = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "run": cmd_run,
        "list": cmd_list,
        "generate": cmd_generate,
        "grade": cmd_grade,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 0
