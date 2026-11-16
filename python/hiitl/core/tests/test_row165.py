"""Row 165 (HTL-22): every policy set the repository carries loads.

policy_format.md's Policy Set Fields: `version` (semver, `v{major}.{minor}.{patch}`), `description` and `scope` are
required. R-0872: "no field is ever silently dropped". A set is found by what it is, not by a list of files: a mapping
with a `name` and a `rules` list whose every member loads as a rule, in a tracked JSON or YAML file or in a fenced
`json`/`yaml` block of a Markdown page. A refusal case's set is refused on purpose and is read by the conformance
runners, which hold each refusal to its one path. Design: the HTL-22 test design, row 165, behavior 7.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hiitl.core.types import PolicySet, Rule
from hiitl.core.tests.conformance_roles import is_refusal_case

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())
FENCE = re.compile(r"^[ \t]*```(json|yaml|yml)[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)


def _rule(r) -> bool:
    try:
        Rule.model_validate(r)
        return True
    except ValidationError:
        return False


def _sets(node, where: str):
    if isinstance(node, dict):
        # The corpus explicitly carries an executable refusal and its positive
        # control. Recognize that whole case form, never a filename or a loose
        # metadata flag, and leave only its refused input to the case runner.
        refusal_case = is_refusal_case(node)
        rules = node.get("rules")
        if "name" in node and isinstance(rules, list) and (rules or "version" in node) and all(
                isinstance(r, dict) and _rule(r) for r in rules):
            yield where, node
        for k, v in node.items():
            if refusal_case and k == 'input':
                continue
            yield from _sets(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _sets(v, f"{where}[{i}]")


def _documents(rel: str, text: str):
    if rel.endswith((".md", ".mdx")):
        for k, m in enumerate(FENCE.finditer(text)):
            try:
                yield f"{rel}#block{k}", (json.loads if m.group(1) == "json" else yaml.safe_load)(m.group(2))
            except (ValueError, yaml.YAMLError):
                continue
    else:
        try:
            yield rel, json.loads(text) if rel.endswith(".json") else yaml.safe_load(text)
        except (ValueError, yaml.YAMLError):
            return


def _carried() -> list[tuple[str, dict]]:
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True,
                             check=True).stdout.split("\0")
    found = []
    for rel in tracked:
        if not rel.endswith((".json", ".yaml", ".yml", ".md", ".mdx")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for name, doc in _documents(rel, text):
            if isinstance(doc, dict) and "expected_refusal" in doc:
                continue
            found += [(name + ("" if where == "$" else f" {where}"), s) for where, s in _sets(doc, "$")]
    return found


CARRIED = _carried()


def test_every_set_the_repository_carries_loads():
    refused = []
    for name, s in CARRIED:
        try:
            PolicySet.model_validate(s)
        except ValidationError as e:
            refused.append(f"{name}: {[('.'.join(map(str, x['loc'])), x['type']) for x in e.errors()]}")
    assert not refused, f"{len(refused)} of {len(CARRIED)} sets do not load:\n" + "\n".join(refused)


def test_the_walk_reaches_every_conformance_case():
    """The walk is not vacuous: each conformance case that carries a set (and is not a refusal) is among those found."""
    cases = {str(p.relative_to(ROOT)) for p in (ROOT / "tests/conformance/cases").rglob("*.json")
             if "policy_set" in (d := json.loads(p.read_text(encoding="utf-8"))) and "expected_refusal" not in d}
    reached = {name.split(" ")[0] for name, _ in CARRIED}
    assert cases and not cases - reached, f"cases the walk misses: {sorted(cases - reached)}"
    assert any(n.endswith((".md", ".mdx")) or "#block" in n for n in reached), "the walk reads the docs' fences"
