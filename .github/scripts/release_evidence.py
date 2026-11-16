#!/usr/bin/env python3
"""Collect the public packages' actual SBOM/audit results; never approve a licence.

Invoked by public CI. The resulting dated directory is downloaded, each distinct
licence is read, and those actual run results are committed in the public PR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def _components(component):
    yield component
    for child in component.get("components", []):
        yield from _components(child)


def licence_inventory(paths):
    components = []
    for path in paths:
        bom = json.loads(path.read_text())
        if bom.get("bomFormat") != "CycloneDX":
            raise ValueError(f"{path.name}: not a CycloneDX document")
        roots = list(bom.get("components", []))
        if bom.get("metadata", {}).get("component"):
            roots.append(bom["metadata"]["component"])
        for root in roots:
            for component in _components(root):
                components.append({"source": path.name, "name": component.get("name"),
                                   "version": component.get("version"),
                                   "bom-ref": component.get("bom-ref"), "purl": component.get("purl"),
                                   "licenses": component.get("licenses", [])})
    components.sort(key=lambda item: json.dumps(item, sort_keys=True))
    declarations = {}
    for component in components:
        for choice in component["licenses"] or [{"undeclared": True}]:
            key = json.dumps(choice, sort_keys=True)
            entry = declarations.setdefault(key, {"declaration": choice,
                "review_status": "requires_review", "components": []})
            entry["components"].append({k: component[k] for k in ("source", "name", "version", "bom-ref", "purl")})
    return {"components": components, "distinct_licenses": [declarations[key] for key in sorted(declarations)]}


def _table_text(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "\\|").replace("\n", " ")


def licence_markdown(inventory):
    lines = ["# Licence review for this CI run", "",
             "Generated from the accompanying CycloneDX files. This is an inventory, not an approval.",
             "Read every distinct licence and record its source, Apache-2.0 compatibility conclusion,",
             "reviewer and date here before committing this run's results. Resolve undeclared licences;",
             "absence of a declaration does not establish permission.", "",
             "| Licence declaration (verbatim data) | Components | Review |", "|---|---|---|"]
    for entry in inventory["distinct_licenses"]:
        declaration = _table_text(json.dumps(entry["declaration"], sort_keys=True))
        components = "; ".join(_table_text(f"{c['source']}: {c['name']}@{c['version']}") for c in entry["components"])
        lines.append(f"| {declaration} | {components} | {entry['review_status']} |")
    return "\n".join(lines) + "\n"


def _run(command, *, evidence_name, **kwargs):
    return subprocess.run(command, **kwargs)


def python_audit_coverage(installed, audit):
    """Compare the auditor's subjects with the measured environment itself."""
    rows = audit["dependencies"]
    if not isinstance(installed, list) or not isinstance(rows, list):
        raise ValueError("Python installed and audited distributions must be lists")

    def subject(row):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("Python distribution has no readable name")
        version = row.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("Python distribution has no readable version")
        return re.sub(r"[-_.]+", "-", row["name"].lower()), version

    expected = [subject(row) for row in installed if subject(row)[0] != "hiitl"]
    reported = [subject(row) for row in rows]
    missing = set(expected) - set(reported)
    unexpected = set(reported) - set(expected)
    unread = [row for row in rows if "skip_reason" in row or not isinstance(row.get("vulns"), list)]
    duplicate_subjects = len(reported) != len(set(reported)) or len(expected) != len(set(expected))

    def ordered(pairs):
        return [list(pair) for pair in sorted(pairs, key=lambda pair: (pair[0], str(pair[1])))]

    return {"installed": ordered(expected), "audited": ordered(reported),
            "missing": ordered(missing), "unexpected": ordered(unexpected), "unread": unread,
            "duplicate_subjects": duplicate_subjects,
            "complete": not (missing or unexpected or unread or duplicate_subjects)}


def collect(root, output, python, *, run=_run):
    """Keep every package's result even when another package's audit fails."""
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"Evidence directory is not empty: {output}")
    commands = []
    errors = []

    def invoke(name, command, cwd, stdout_file=None):
        try:
            result = run(command, evidence_name=name, cwd=cwd, capture_output=True, text=True)
        except OSError as exc:
            result = subprocess.CompletedProcess(command, None, "", str(exc))
        if stdout_file:
            (output / stdout_file).write_text(result.stdout)
        (output / f"{name}.stderr.txt").write_text(result.stderr)
        commands.append({"name": name, "command": command, "cwd": str(cwd.relative_to(root)),
                         "returncode": result.returncode})

    invoke("python-sbom", ["cyclonedx-py", "environment", "--of", "JSON", "--output-file",
                          str(output / "python.cdx.json"), str(python)], root)
    # Audit the exact installed test/runtime/MCP dependency versions, excluding
    # only this unpublished local project (its dependencies remain in freeze).
    invoke("python-list", [str(python), "-m", "pip", "list", "--format", "json"],
           root, "python.installed.json")
    invoke("python-freeze", [str(python), "-m", "pip", "freeze", "--all", "--exclude", "hiitl"],
           root, "python.requirements.txt")
    invoke("python-audit", ["pip-audit", "--requirement", str(output / "python.requirements.txt"),
                           "--disable-pip", "--no-deps", "--format", "json", "--output", str(output / "python.audit.json")], root)
    for package in ("core", "sdk"):
        cwd = root / "typescript/packages" / package
        invoke(f"{package}-sbom", ["npx", "--yes", "@cyclonedx/cyclonedx-npm@6.0.1",
               "--output-format", "JSON", "--output-file", str(output / f"{package}.cdx.json")], cwd)
        invoke(f"{package}-audit", ["npm", "audit", "--json"], cwd, f"{package}.audit.json")

    try:
        coverage = python_audit_coverage(json.loads((output / "python.installed.json").read_text()),
                                         json.loads((output / "python.audit.json").read_text()))
        (output / "python.coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        if not coverage["complete"]:
            errors.append("Python audit does not cover the exact installed nonlocal graph")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))

    try:
        inventory = licence_inventory([output / f"{name}.cdx.json" for name in ("python", "core", "sdk")])
        (output / "licenses.json").write_text(json.dumps(inventory, indent=2) + "\n")
        (output / "license-review.md").write_text(licence_markdown(inventory))
        for name in ("python.audit.json", "core.audit.json", "sdk.audit.json"):
            json.loads((output / name).read_text())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    failed = any(command["returncode"] != 0 for command in commands) or bool(errors)
    artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(output.iterdir()) if p.is_file() and p.name != "run.json"}
    record = {"source_commit": os.environ.get("GITHUB_SHA"),
              "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "run_url": (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                          f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"),
              "commands": commands, "errors": errors, "tools_passed": not failed,
              "licence_review": "requires_review", "sha256": artifacts}
    (output / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="The isolated SDK/MCP/test environment's Python")
    args = parser.parse_args()
    return collect(args.root, args.output, args.python)


if __name__ == "__main__":
    raise SystemExit(main())
