#!/usr/bin/env python3
"""Decide each dependency advisory by what the package installs and what is fixed (HTL-17 `4d086f19`).

Design and cells: `.github/public/TEST_DESIGN_advisory_gate.md`. Every advisory is a finding:
in what ships it fails; outside, with a fixed release or a fix that could not be read, it fails;
outside with no fixed release it passes and is written into the record with its chain.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

RULING = ("the gate still fails on any vulnerability in what a published package installs, and on any vulnerability "
          "anywhere that has a fixed release. An unfixed advisory outside what ships is written into the release's "
          "public advisory record with its reach, and fails the gate the day a fix exists.")
EDGES = ("dependencies", "optionalDependencies", "peerDependencies")
GHSA_URL = re.compile(r"https://github\.com/advisories/(GHSA(?:-[23456789cfghjmpqrvwx]{4}){3})")
API_VERSION = "2026-03-10"


class Unread(Exception):
    """A fact the decision needs could not be read; the gate fails on it."""


# --- What an npm package installs ------------------------------------------------------------------------------

def npm_resolve(packages, location, name):
    """Node's lookup: the requiring location's own node_modules, then each ancestor directory's."""
    parts = location.split("/") if location else []
    for depth in range(len(parts), -1, -1):
        if depth and parts[depth - 1] == "node_modules":
            continue
        prefix = "/".join(parts[:depth])
        candidate = f"{prefix}/node_modules/{name}" if prefix else f"node_modules/{name}"
        if candidate in packages:
            return candidate
    return None


def _edges(entry, kinds=EDGES):
    """Each dependency an entry declares, and whether its absence is allowed (an optional or optional peer)."""
    required = {}
    meta = entry.get("peerDependenciesMeta") or {}
    for kind in kinds:
        for name in entry.get(kind) or {}:
            optional_peer = kind == "peerDependencies" and bool((meta.get(name) or {}).get("optional"))
            required[name] = required.get(name, False) or (kind != "optionalDependencies" and not optional_peer)
    optional = set(entry.get("optionalDependencies") or {}) if "optionalDependencies" in kinds else set()
    return [(name, name in optional or not needed) for name, needed in required.items()]


def _inside(resolved):
    return not (resolved == ".." or resolved.startswith("../") or resolved.startswith("/"))


def npm_closure(manifest, packages):
    """The lock locations a published package installs: its runtime edges from `package.json`, as Node resolves them."""
    closure, seen = set(), set()
    queue = [("", manifest)]
    while queue:
        location, entry = queue.pop(0)
        for name, optional in _edges(entry):
            found = npm_resolve(packages, location, name)
            if found is None:
                if optional:
                    continue
                raise Unread(f"{location or 'the package'} requires {name}, which the lock does not resolve")
            if found in seen:
                continue
            seen.add(found)
            closure.add(found)
            item = packages[found]
            if item.get("link"):
                target = item.get("resolved")
                if not isinstance(target, str) or target not in packages:
                    raise Unread(f"link {found} names no lock entry for its target")
                closure.add(target)
                if _inside(target) and target not in seen:
                    seen.add(target)
                    queue.append((target, packages[target]))
            else:
                queue.append((found, item))
    return closure


def _npm_label(packages, location):
    item = packages[location]
    name = item.get("name") or location.rsplit("node_modules/", 1)[-1]
    if item.get("link"):
        item = packages.get(item.get("resolved"), {})
    return f"{name}@{item.get('version')}"


def npm_chains(manifest, packages):
    """The shortest path from the package to each lock location over every edge, `devDependencies` included."""
    chains = {"": [f"{manifest.get('name')}@{manifest.get('version')}"]}
    development = EDGES + ("devDependencies",)
    queue = [("", manifest, development)]
    while queue:
        location, entry, kinds = queue.pop(0)
        for name, _ in _edges(entry, kinds):
            found = npm_resolve(packages, location, name)
            if found is None or found in chains:
                continue
            chains[found] = chains[location] + [_npm_label(packages, found)]
            item = packages[found]
            if item.get("link"):
                target = item.get("resolved")
                if isinstance(target, str) and target in packages and target not in chains:
                    chains[target] = chains[found]
                    if _inside(target):
                        queue.append((target, packages[target], development))
            else:
                queue.append((found, item, EDGES))
    return chains


def npm_advisories(text, returncode, packages):
    """npm's audit report v2, read whole: each GitHub advisory with its package entry's nodes."""
    if returncode not in (0, 1):
        raise Unread(f"npm audit exited {returncode}")
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise Unread(f"npm audit report is not JSON: {exc}") from exc
    if not isinstance(document, dict) or "error" in document:
        raise Unread("npm audit reported an error, not a report")
    if document.get("auditReportVersion") != 2:
        raise Unread(f"npm audit report version {document.get('auditReportVersion')!r} is not 2")
    vulnerabilities = document.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise Unread("npm audit report has no vulnerabilities object")
    if returncode == 1 and not vulnerabilities:
        raise Unread("npm audit exited 1 with no vulnerabilities")
    found, unread, named = {}, [], {}
    for key, item in vulnerabilities.items():
        via = item.get("via") if isinstance(item, dict) else None
        nodes = item.get("nodes") if isinstance(item, dict) else None
        if not isinstance(via, list) or not via:
            unread.append(f"{key}: no advisory or dependency names it vulnerable")
            continue
        if not isinstance(nodes, list) or not nodes or not all(isinstance(n, str) and n in packages for n in nodes):
            unread.append(f"{key}: its nodes {nodes!r} are not lock entries")
            continue
        named[key] = [cause for cause in via if isinstance(cause, str)]
        for cause in via:
            if isinstance(cause, str):
                if cause not in vulnerabilities:
                    unread.append(f"{key}: via {cause!r} names no entry")
                continue
            match = GHSA_URL.fullmatch(cause.get("url") or "") if isinstance(cause, dict) else None
            if not isinstance(cause, dict) or cause.get("name") != key or not match or \
                    not isinstance(cause.get("range"), str) or not cause["range"]:
                unread.append(f"{key}: an advisory without its package, GitHub advisory and range: {cause!r}")
                continue
            found.setdefault((match.group(1), key), {
                "id": match.group(1), "url": cause["url"], "title": cause.get("title"),
                "severity": cause.get("severity"), "range": cause["range"], "package": key,
                "nodes": sorted(nodes), "versions": sorted({str(packages[n].get("version")) for n in nodes})})
    # `ccdd1fd0` H2: an entry is read only when its `via` names reach an entry that carries a GitHub advisory.
    reaches = {key for _, key in found}
    while grown := {key for key, names in named.items() if key not in reaches and reaches.intersection(names)}:
        reaches |= grown
    unread += [f"{key}: its via reaches no advisory" for key in named if key not in reaches]
    return [found[key] for key in sorted(found)], unread


# --- Has a fixed release, read at the advisory -----------------------------------------------------------------

def _fetch(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.loads(response.read())


def github_advisory(ghsa, *, fetch=None, environ=None):
    environ = os.environ if environ is None else environ
    base = (environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION,
               "User-Agent": "hiitl-advisory-gate"}
    if environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {environ['GITHUB_TOKEN']}"
    try:
        record = (fetch or _fetch)(f"{base}/advisories/{ghsa}", headers)
    except Exception as exc:  # any failure to read the advisory is unread, never unfixed
        raise Unread(f"{ghsa}: the advisory could not be read: {exc}") from exc
    if not isinstance(record, dict) or record.get("ghsa_id") != ghsa:
        raise Unread(f"{ghsa}: the answer is not that advisory")
    return record


def ghsa_patched(ghsa, package, npm_range, *, fetch=None, environ=None):
    """The vulnerable package's own patched versions, from its one matching entry, and the advisory's aliases."""
    record = github_advisory(ghsa, fetch=fetch, environ=environ)

    def squash(value):
        return re.sub(r"[\s,]+", "", value)

    entries = record.get("vulnerabilities")
    matches = [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("package"), dict)
               and entry["package"].get("ecosystem") == "npm" and entry["package"].get("name") == package
               and isinstance(entry.get("vulnerable_version_range"), str)
               and squash(entry["vulnerable_version_range"]) == squash(npm_range)] if isinstance(entries, list) else []
    if len(matches) != 1:
        raise Unread(f"{ghsa}: {len(matches)} entries name npm {package} {npm_range}")
    if "first_patched_version" not in matches[0]:
        raise Unread(f"{ghsa}: its {package} entry states no first patched version")
    patched = matches[0]["first_patched_version"]
    if patched is not None and not (isinstance(patched, str) and patched):
        raise Unread(f"{ghsa}: its first patched version {patched!r} is not a version")
    aliases = [i["value"] for i in record.get("identifiers") or []
               if isinstance(i, dict) and i.get("type") != "GHSA" and isinstance(i.get("value"), str)]
    return ([] if patched is None else [patched]), aliases


# --- What a Python package installs ----------------------------------------------------------------------------

def _packaging():
    try:
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.version import InvalidVersion, Version
    except ImportError as exc:
        raise Unread(f"packaging is not importable: {exc}") from exc
    return Requirement, InvalidRequirement, Version, InvalidVersion


def _normal(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _inspected(inspect):
    """pip's inspect report, version 1: each installed distribution by normalised name, and the marker environment."""
    if not isinstance(inspect, dict) or inspect.get("version") != "1":
        raise Unread("pip inspect report is not version 1")
    installed, environment = inspect.get("installed"), inspect.get("environment")
    if not isinstance(installed, list) or not isinstance(environment, dict):
        raise Unread("pip inspect report has no installed list or environment")
    dists = {}
    for row in installed:
        metadata = row.get("metadata") if isinstance(row, dict) else None
        if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) or \
                not isinstance(metadata.get("version"), str):
            raise Unread(f"pip inspect names a distribution without a name and version: {row!r}")
        name = _normal(metadata["name"])
        if name in dists:
            raise Unread(f"pip inspect names {name} twice")
        dists[name] = {"name": metadata["name"], "version": metadata["version"],
                       "requires": list(metadata.get("requires_dist") or []),
                       "extras": list(metadata.get("provides_extra") or []), "requested": row.get("requested") is True}
    return dists, environment


def _active(dists, environment, roots, *, strict):
    """Each reached distribution's extras and its requirement lines that apply, to a fixed point."""
    Requirement, InvalidRequirement, _, _ = _packaging()
    extras = {name: set(chosen) for name, chosen in roots.items()}
    edges = {}
    changed = True
    while changed:
        changed = False
        for name in sorted(extras):
            lines = []
            for line in dists[name]["requires"]:
                try:
                    requirement = Requirement(line)
                except InvalidRequirement as exc:
                    raise Unread(f"{name} declares an unreadable requirement {line!r}: {exc}") from exc
                if requirement.marker is not None and not any(
                        requirement.marker.evaluate({**environment, "extra": extra}) for extra in extras[name]):
                    continue
                target = _normal(requirement.name)
                if target not in dists:
                    if strict:
                        raise Unread(f"{dists[name]['name']} requires {requirement.name}, which is not installed")
                    continue
                lines.append(target)
                wanted = {""} | set(requirement.extras)
                if not wanted <= extras.setdefault(target, set()):
                    extras[target] |= wanted
                    changed = True
            edges[name] = lines
    return edges


def _project_name(package):
    try:
        import tomllib
        with open(Path(package) / "pyproject.toml", "rb") as handle:
            return _normal(tomllib.load(handle)["project"]["name"])
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        raise Unread(f"{package}: no readable [project].name: {exc}") from exc


def python_closure(inspect, package):
    """The distributions the package installs: its runtime closure, its declared extras included."""
    dists, environment = _inspected(inspect)
    root = _project_name(package)
    if root not in dists:
        raise Unread(f"{root} is not installed in the inspected environment")
    return set(_active(dists, environment, {root: {""} | set(dists[root]["extras"])}, strict=True)) | {root}


def python_chains(dists, environment, root=None):
    """The shortest path from a requested distribution to each installed one, over the closure's edges."""
    roots = {name: {""} for name, dist in dists.items() if dist["requested"]}
    if root in dists:
        roots[root] = {""} | set(dists[root]["extras"])
    edges = _active(dists, environment, roots, strict=False)
    label = {name: f"{dist['name']}=={dist['version']}" for name, dist in dists.items()}
    chains = {name: [label[name]] for name in sorted(roots)}
    queue = sorted(roots)
    while queue:
        name = queue.pop(0)
        for target in edges.get(name, []):
            if target not in chains:
                chains[target] = chains[name] + [label[target]]
                queue.append(target)
    return chains


def python_advisories(audit_text, returncode):
    """pip-audit's JSON: each advisory of each audited distribution. Unaudited rows are the coverage reader's."""
    if returncode not in (0, 1):
        raise Unread(f"pip-audit exited {returncode}")
    if audit_text is None:
        raise Unread("pip-audit wrote no report")
    try:
        document = json.loads(audit_text)
    except (TypeError, ValueError) as exc:
        raise Unread(f"pip-audit report is not JSON: {exc}") from exc
    rows = document.get("dependencies") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise Unread("pip-audit report has no dependency list")
    found, unread = [], []
    for row in rows:
        if not isinstance(row, dict):
            unread.append(f"pip-audit row {row!r} is not a distribution")
            continue
        if "skip_reason" in row or not isinstance(row.get("vulns"), list):
            continue
        name, version = row.get("name"), row.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            unread.append(f"pip-audit row without a name and version: {row!r}")
            continue
        for item in row["vulns"]:
            fixes = item.get("fix_versions") if isinstance(item, dict) else None
            aliases = item.get("aliases", []) if isinstance(item, dict) else None
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(fixes, list) or \
                    not all(isinstance(f, str) for f in fixes) or not isinstance(aliases, list) or \
                    not all(isinstance(a, str) for a in aliases):
                unread.append(f"{name}: an advisory without its id, fix versions and aliases: {item!r}")
                continue
            found.append({"id": item["id"], "aliases": aliases, "package": _normal(name), "name": name,
                          "version": version, "fixes": fixes, "description": item.get("description")})
    if returncode == 1 and not found and not unread:
        raise Unread("pip-audit exited 1 with no vulnerability")
    return found, unread


# --- The decision and the record -------------------------------------------------------------------------------

def _decide(finding, ships, patched_reader):
    """In what ships: fails. Outside: fails on a fixed release or an unread fix; records with no fixed release."""
    finding["ships"] = ships
    if ships is None:
        return {**finding, "patched": None, "decision": "fails", "reason": "unread: what the package installs"}
    if ships:
        return {**finding, "patched": None, "decision": "fails", "reason": "in what the package installs"}
    try:
        patched, aliases = patched_reader()
    except Unread as exc:
        return {**finding, "patched": None, "decision": "fails", "reason": f"unread: {exc}"}
    if aliases:
        finding["aliases"] = sorted(set(finding["aliases"]) | set(aliases))
    if patched:
        return {**finding, "patched": patched, "decision": "fails",
                "reason": f"outside what ships; fixed in {', '.join(patched)}"}
    return {**finding, "patched": [], "decision": "recorded", "reason": "outside what ships; no fixed release"}


def npm_subject(package_dir, report_text, returncode, *, fetch=None, label=None, environ=None):
    package_dir = Path(package_dir)
    subject = {"subject": label or str(package_dir), "package": None, "ecosystem": "npm", "whole": None,
               "closure": None, "installed": None, "returncode": returncode, "findings": [], "unread": []}
    try:
        manifest = json.loads((package_dir / "package.json").read_text())
        packages = json.loads((package_dir / "package-lock.json").read_text())["packages"]
        if not isinstance(manifest, dict) or not isinstance(packages, dict):
            raise TypeError("package.json or its lock is not an object")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        subject["unread"].append(f"{package_dir}: package.json and package-lock.json could not be read: {exc}")
        return subject
    whole = manifest.get("private") is True
    subject.update(package=manifest.get("name"), whole=whole, installed=len([k for k in packages if k]))
    closure = None
    if not whole:
        try:
            closure = npm_closure(manifest, packages)
            subject["closure"] = len(closure)
        except Unread as exc:
            subject["unread"].append(str(exc))
    try:
        found, unread = npm_advisories(report_text, returncode, packages)
    except Unread as exc:
        subject["unread"].append(str(exc))
        return subject
    subject["unread"] += unread
    chains = npm_chains(manifest, packages)
    for item in found:
        missing = [node for node in item["nodes"] if node not in chains]
        if missing:
            subject["unread"].append(f"{item['id']}: no chain from the package to {', '.join(missing)}")
        ships = True if whole else (None if closure is None else any(n in closure for n in item["nodes"]))
        finding = {"subject": subject["subject"], "ecosystem": "npm", "id": item["id"], "aliases": [],
                   "package": item["package"], "versions": item["versions"], "severity": item["severity"],
                   "title": item["title"], "url": item["url"], "range": item["range"],
                   "chains": [chains[node] for node in item["nodes"] if node in chains]}
        subject["findings"].append(_decide(finding, ships, lambda item=item: ghsa_patched(
            item["id"], item["package"], item["range"], fetch=fetch, environ=environ)))
    return subject


def python_subject(inspect_text, audit_text, returncode, *, package=None, label=None):
    whole = package is None
    subject = {"subject": label or (str(package) if package else "python"), "package": None, "ecosystem": "PyPI",
               "whole": whole, "closure": None, "installed": None, "returncode": returncode, "findings": [],
               "unread": []}
    dists = environment = closure = root = None
    try:
        inspect = json.loads(inspect_text)
        dists, environment = _inspected(inspect)
        subject["installed"] = len(dists)
        if not whole:
            root = _project_name(package)
            subject["package"] = root
            closure = python_closure(inspect, package)
            subject["closure"] = len(closure)
    except (TypeError, ValueError, Unread) as exc:
        subject["unread"].append(f"pip inspect: {exc}")
    try:
        found, unread = python_advisories(audit_text, returncode)
    except Unread as exc:
        subject["unread"].append(str(exc))
        return subject
    subject["unread"] += unread
    try:
        chains = python_chains(dists, environment, root) if dists is not None else {}
        _, _, Version, InvalidVersion = _packaging()
    except Unread as exc:
        subject["unread"].append(str(exc))
        return subject
    for item in found:
        if item["package"] not in chains:
            subject["unread"].append(f"{item['id']}: no chain from a requested distribution to {item['name']}")
        ships = True if whole else (None if closure is None else item["package"] in closure)

        def fixed(item=item):
            # `ccdd1fd0` H1: every declared fix version is a fixed release, above the installed version or not.
            try:
                for fix in item["fixes"]:
                    Version(fix)
            except InvalidVersion as exc:
                raise Unread(f"{item['name']}: its fix versions {item['fixes']} are not versions: {exc}") from exc
            return list(item["fixes"]), []

        finding = {"subject": subject["subject"], "ecosystem": "PyPI", "id": item["id"], "aliases": item["aliases"],
                   "package": item["package"], "versions": [item["version"]], "severity": None,
                   "title": item["description"], "url": None, "range": None,
                   "chains": [chains[item["package"]]] if item["package"] in chains else []}
        subject["findings"].append(_decide(finding, ships, fixed))
    return subject


def advisory_record(subjects, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    findings = [finding for subject in subjects for finding in subject["findings"]]
    unread = [f"{subject['subject']}: {reason}" for subject in subjects for reason in subject["unread"]]
    return {"read_at": now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ruling": "HTL-17 4d086f19",
            "subjects": [{k: v for k, v in subject.items() if k not in ("findings", "unread")} for subject in subjects],
            "findings": findings, "unread": unread,
            "passed": not unread and all(finding["decision"] == "recorded" for finding in findings)}


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def _advisory_link(finding):
    return f"[{finding['id']}]({finding['url']})" if finding["url"] else finding["id"]


def advisory_markdown(record):
    lines = ["# Dependency advisory record", "",
             f"Read {record['read_at']} under {record['ruling']}: \"{RULING}\"", "",
             "## Subjects", "", "| Subject | Package | Ecosystem | Read | Closure | Installed |", "|---|---|---|---|---|---|"]
    for s in record["subjects"]:
        lines.append(f"| {_cell(s['subject'])} | {_cell(s['package'])} | {s['ecosystem']} | "
                     f"{'whole' if s['whole'] else 'package closure'} | {s['closure']} | {s['installed']} |")
    recorded = [f for f in record["findings"] if f["decision"] == "recorded"]
    lines += ["", "## Unfixed advisories outside what ships", ""]
    if recorded:
        lines += ["| Subject | Advisory | Aliases | Package | Installed | Severity | Reach |",
                  "|---|---|---|---|---|---|---|"]
        for f in recorded:
            reach = "; ".join(" → ".join(chain) for chain in f["chains"])
            lines.append(f"| {_cell(f['subject'])} | {_advisory_link(f)} | {_cell(', '.join(f['aliases']))} | "
                         f"{_cell(f['package'])} | {_cell(', '.join(f['versions']))} | {_cell(f['severity'] or '')} | "
                         f"{_cell(reach)} |")
    else:
        lines.append("None.")
    failing = [f for f in record["findings"] if f["decision"] == "fails"]
    lines += ["", "## Failing", ""]
    if failing:
        lines += ["| Subject | Advisory | Package | Installed | Reason |", "|---|---|---|---|---|"]
        for f in failing:
            lines.append(f"| {_cell(f['subject'])} | {_advisory_link(f)} | {_cell(f['package'])} | "
                         f"{_cell(', '.join(f['versions']))} | {_cell(f['reason'])} |")
    else:
        lines.append("None.")
    lines += ["", "## Unread", ""] + ([f"- {_cell(reason)}" for reason in record["unread"]] or ["None."])
    lines += ["", f"**Result:** {'passed' if record['passed'] else 'failed'}."]
    return "\n".join(lines) + "\n"


def write_record(output, subjects, *, now=None):
    record = advisory_record(subjects, now=now)
    output = Path(output)
    (output / "advisories.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    (output / "advisories.md").write_text(advisory_markdown(record))
    return record["passed"]


def gate_npm(package_dir, output, *, run=subprocess.run, fetch=None, environ=None, now=None, label=None):
    """Run `npm audit --json` in the package, keep its raw bytes, and write the decided record beside them."""
    package_dir, output = Path(package_dir).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"Evidence directory is not empty: {output}")
    command = ["npm", "audit", "--json"]
    try:
        result = run(command, cwd=package_dir, capture_output=True, text=True)
    except OSError as exc:
        result = subprocess.CompletedProcess(command, None, "", str(exc))
    (output / "audit.json").write_text(result.stdout)
    (output / "audit.stderr.txt").write_text(result.stderr)
    subject = npm_subject(package_dir, result.stdout, result.returncode, fetch=fetch, environ=environ,
                          label=label or str(package_dir))
    return 0 if write_record(output, [subject], now=now) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="ecosystem", required=True)
    npm = commands.add_parser("npm", help="audit one npm package's locked graph and decide each advisory")
    npm.add_argument("--package", type=Path, required=True)
    npm.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return gate_npm(args.package, args.output, label=str(args.package))


if __name__ == "__main__":
    raise SystemExit(main())
