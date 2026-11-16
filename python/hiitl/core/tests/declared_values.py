"""Read a numeric declaration at its source; a missing or ambiguous declaration fails the cell."""

from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[4]


def declared_number(relative_path: str, anchored_regex: str) -> float:
    path = _ROOT / relative_path
    matches = re.findall(anchored_regex, path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert len(matches) == 1, f"Expected one declaration matching {anchored_regex!r} in {path}; found {matches!r}"
    return float(matches[0])


def pure_local_budget_ms() -> float:
    return declared_number(
        "docs/specs/decision_response.md",
        r"^- \*\*Pure local mode\*\*: Single-digit milliseconds \(< ([\d.]+)ms\)$",
    )


def typical_core_budget_ms() -> float:
    return declared_number(
        "docs/specs/decision_response.md",
        r"^- \*\*Typical core evaluation\*\*: < ([\d.]+)ms for typical policies\.$",
    )
