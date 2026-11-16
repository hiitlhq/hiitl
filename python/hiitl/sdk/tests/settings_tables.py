"""The settings tables the specs declare, read at their producer for the settings cells (HTL-23 rows 207-209).

Each table is the first markdown table after its heading; a row is its cells. No name is listed here.
"""

from __future__ import annotations

import re
from pathlib import Path

SPECS = Path(__file__).resolve().parents[4] / "docs" / "specs"


def table(spec: str, heading: str) -> list[list[str]]:
    """The rows of the first table after `heading` in `spec`, each its cells, the header and its rule left out."""
    text = (SPECS / spec).read_text(encoding="utf-8")
    lines = text[text.index(heading):].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]])
    return rows


def code(cell: str) -> str:
    """The first code span of a cell, its quotes left off."""
    return re.search(r"`([^`]*)`", cell).group(1).strip('"')


SYNC = table("sync_engine.md", "### Configuration Table")
TELEMETRY = table("telemetry_schema.md", "**The telemetry family")
EARLIER = {code(earlier): code(replacement)
           for earlier, replacement in table("telemetry_schema.md", "**Names earlier releases read.**")}
HOSTED = table("decision_response.md", "**The hosted client's settings.**")

# Each family the SDK's specs give it, and the variables its tables name (row 207)
FAMILIES = {
    "HIITL_SYNC_": [code(row[2]) for row in SYNC if code(row[2]).startswith("HIITL_SYNC_")],
    "HIITL_TELEMETRY_": [code(row[2]) for row in TELEMETRY],
}
