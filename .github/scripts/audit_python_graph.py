#!/usr/bin/env python3
"""Audit one installed Python graph, retaining the producer's complete evidence.

With `--package`, each advisory is decided against that package's closure (HTL-17 `4d086f19`,
`advisory_gate.py`); without it, the graph is read whole and every advisory in it fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import advisory_gate
from release_evidence import _read, python_audit_coverage


def audit_graph(root, output, python, *, package=None, run=subprocess.run):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"Evidence directory is not empty: {output}")
    commands, errors = [], []

    def invoke(name, command, stdout_file):
        try:
            result = run(command, cwd=root, capture_output=True, text=True)
        except OSError as exc:
            result = subprocess.CompletedProcess(command, None, "", str(exc))
        (output / stdout_file).write_text(result.stdout)
        (output / f"{name}.stderr.txt").write_text(result.stderr)
        commands.append({"name": name, "command": command, "returncode": result.returncode})

    invoke("python-list", [str(python), "-m", "pip", "list", "--format", "json"], "python.installed.json")
    invoke("python-freeze", [str(python), "-m", "pip", "freeze", "--all", "--exclude", "hiitl"], "python.requirements.txt")
    invoke("python-inspect", [str(python), "-m", "pip", "inspect"], "python.inspect.json")
    invoke("python-audit", ["pip-audit", "--requirement", str(output / "python.requirements.txt"),
           "--disable-pip", "--no-deps", "--format", "json", "--output", str(output / "python.audit.json")],
           "python-audit.stdout.txt")
    try:
        installed = json.loads((output / "python.installed.json").read_text())
        audit = json.loads((output / "python.audit.json").read_text())
        coverage = python_audit_coverage(installed, audit)
        (output / "python.coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        if not coverage["complete"]:
            errors.append("Audit does not cover the exact installed nonlocal graph")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    audited = next(command["returncode"] for command in commands if command["name"] == "python-audit")
    subject = advisory_gate.python_subject(_read(output / "python.inspect.json"), _read(output / "python.audit.json"),
                                           audited, package=None if package is None else root / package,
                                           label=str(package) if package is not None else str(python))
    if not advisory_gate.write_record(output, [subject]):
        errors.append("Dependency advisories fail the gate (advisories.md)")
    failed = any(command["returncode"] != 0 for command in commands if command["name"] != "python-audit") or \
        bool(errors)
    record = {"source_commit": os.environ.get("GITHUB_SHA"), "commands": commands,
              "errors": errors, "passed": not failed,
              "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(output.iterdir()) if p.is_file()}}
    (output / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--package", type=Path,
                        help="The published package's directory; its closure decides each advisory. Omitted: read whole.")
    args = parser.parse_args()
    return audit_graph(args.root, args.output, args.python, package=args.package)


if __name__ == "__main__":
    raise SystemExit(main())
