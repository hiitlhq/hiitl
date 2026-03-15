#!/usr/bin/env python3
"""Fix conformance test cases to comply with strict schema validation."""

import json
from pathlib import Path

# Path to test cases
CASES_DIR = Path(__file__).parent / "cases"

def fix_test_case(test_file: Path) -> None:
    """Fix a single test case file."""
    with open(test_file, 'r', encoding='utf-8') as f:
        test_case = json.load(f)

    envelope = test_case.get("envelope", {})
    policy_set = test_case.get("policy_set", {})

    # Fix envelope
    # 1. Fix environment values (production -> prod, development -> dev, staging -> stage)
    env_map = {
        "production": "prod",
        "development": "dev",
        "staging": "stage"
    }
    if envelope.get("environment") in env_map:
        envelope["environment"] = env_map[envelope["environment"]]

    # 2. Fix action_id (must be 20+ chars after act_, no underscores allowed in suffix)
    if "action_id" in envelope:
        action_id = envelope["action_id"]
        if action_id.startswith("act_"):
            suffix = action_id[4:]  # Remove act_ prefix
            # Remove underscores from suffix (not allowed by pattern)
            suffix = suffix.replace("_", "")
            # Ensure suffix is at least 20 chars (alphanumeric only)
            if len(suffix) < 20:
                envelope["action_id"] = f"act_{suffix}{'0' * (20 - len(suffix))}"
            else:
                envelope["action_id"] = f"act_{suffix}"

    # 3. Add required fields if missing
    if "idempotency_key" not in envelope:
        envelope["idempotency_key"] = f"idem_{test_case['test_id']}"

    if "target" not in envelope:
        envelope["target"] = {}

    if "signature" not in envelope:
        envelope["signature"] = "0" * 64  # 64-char hex string

    # Fix policy rules
    if "rules" in policy_set:
        for rule in policy_set["rules"]:
            # Add description if missing
            if "description" not in rule:
                rule["description"] = f"Rule: {rule['name']}"

            # Fix decision value (REQUEST_APPROVAL -> REQUIRE_APPROVAL)
            if rule.get("decision") == "REQUEST_APPROVAL":
                rule["decision"] = "REQUIRE_APPROVAL"

            # Fix environment values in conditions
            fix_conditions(rule.get("conditions", {}))

    # Fix expected_decision
    expected = test_case.get("expected_decision", {})
    if expected.get("decision") == "REQUEST_APPROVAL":
        expected["decision"] = "REQUIRE_APPROVAL"

    # Write back
    with open(test_file, 'w', encoding='utf-8') as f:
        json.dump(test_case, f, indent=2)

    print(f"Fixed: {test_file.name}")


def fix_conditions(conditions):
    """Recursively fix environment values in conditions."""
    env_map = {
        "production": "prod",
        "development": "dev",
        "staging": "stage"
    }

    if isinstance(conditions, dict):
        # Check if this is an atomic condition with environment field
        if conditions.get("field") == "environment" and conditions.get("value") in env_map:
            conditions["value"] = env_map[conditions["value"]]

        # Recursively fix logical conditions
        for key in ["all_of", "any_of", "none_of"]:
            if key in conditions and isinstance(conditions[key], list):
                for cond in conditions[key]:
                    fix_conditions(cond)

def main():
    """Fix all test case files."""
    count = 0
    for test_file in sorted(CASES_DIR.rglob("*.json")):
        fix_test_case(test_file)
        count += 1

    print(f"\nFixed {count} test cases")

if __name__ == "__main__":
    main()
