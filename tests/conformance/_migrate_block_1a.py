"""One-shot migration: drop `enabled` and `mode` from conformance test cases.

Maps:
  enabled: true  → (no field needed; lifecycle_stage defaults to "active")
  enabled: false → lifecycle_stage: "disabled"
  mode: "observe" → lifecycle_stage: "staged"
  mode: "enforce" → (drop; default is "enforce" semantics via lifecycle_stage="active")

If a rule has BOTH `enabled: false` and `mode: "observe"`, "disabled" wins
(enabled=false was the hard short-circuit before; staged would still evaluate).

After running this, the conformance suite should pass against the new schema.
"""

import json
from pathlib import Path


CASES_DIR = Path(__file__).parent / "cases"


def migrate_rule(rule: dict) -> dict:
    """Convert a rule's enabled/mode fields to lifecycle_stage."""
    enabled = rule.pop("enabled", True)
    mode = rule.pop("mode", "enforce")

    if not enabled:
        rule["lifecycle_stage"] = "disabled"
    elif mode == "observe":
        rule["lifecycle_stage"] = "staged"
    # else: default lifecycle_stage="active" — no field needed
    return rule


def migrate_case(case_data: dict) -> tuple[dict, bool]:
    """Migrate a test case's policy_set rules. Returns (data, changed)."""
    changed = False
    policy_set = case_data.get("policy_set")
    if not policy_set:
        return case_data, False

    for rule in policy_set.get("rules", []):
        if "enabled" in rule or "mode" in rule:
            migrate_rule(rule)
            changed = True
    return case_data, changed


def main() -> None:
    cases = list(CASES_DIR.rglob("*.json"))
    migrated = 0
    untouched = 0

    for case_path in cases:
        with case_path.open() as f:
            data = json.load(f)
        data, changed = migrate_case(data)
        if changed:
            with case_path.open("w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            migrated += 1
        else:
            untouched += 1

    print(f"Migrated: {migrated}")
    print(f"Untouched: {untouched}")
    print(f"Total: {len(cases)}")


if __name__ == "__main__":
    main()
