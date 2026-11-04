#!/usr/bin/env python3
"""Validate bootstrap amendment records and dispatch preflight state."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


AMENDMENT_FILE = re.compile(r"^AMEND-\d{3}\.md$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
PR = re.compile(r"^(?:#\d+|https://github\.com/[^/]+/[^/]+/pull/\d+)")
REQUIRED_HEADINGS = (
    "## Authority",
    "## Requested change",
    "## Affected tasks",
    "## Active-work impact",
    "## Registry and specification changes",
    "## Effectiveness",
)
EFFECTIVENESS_FIELDS = (
    "Planning commit",
    "Effective remote PR",
    "Effective merge commit",
    "Dispatch status",
    "Resolution status",
)
PLANNING_PATHS = (
    "AGENTS.md",
    "PRD.md",
    "ARCH.md",
    "bootstrap/ROOT_PROMPT.md",
    "bootstrap/README.md",
    "bootstrap/tasks.json",
    "bootstrap/decisions.md",
    "bootstrap/amendments",
)


def validate_records(repo_root: Path) -> list[str]:
    """Return deterministic errors for every durable amendment record."""

    repo_root = repo_root.resolve()
    directory = repo_root / "bootstrap" / "amendments"
    errors: list[str] = []
    amendment_paths = sorted(directory.glob("*.md"))
    for path in amendment_paths:
        source = str(path.relative_to(repo_root))
        if not AMENDMENT_FILE.fullmatch(path.name):
            errors.append(f"{source}: invalid amendment filename")
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        expected_title = f"# {path.stem} — "
        if not lines or not lines[0].startswith(expected_title):
            errors.append(f"{source}: title must begin {expected_title!r}")
        indexes = []
        for heading in REQUIRED_HEADINGS:
            try:
                indexes.append(lines.index(heading))
            except ValueError:
                errors.append(f"{source}: missing required heading {heading}")
        if len(indexes) == len(REQUIRED_HEADINGS) and indexes != sorted(indexes):
            errors.append(f"{source}: required headings are out of order")
        values = _bullet_values(lines)
        for field in EFFECTIVENESS_FIELDS:
            if field not in values:
                errors.append(f"{source}: missing effectiveness field {field}")
        planning_commit = values.get("Planning commit", "").strip("`")
        merge_commit = values.get("Effective merge commit", "").strip("`")
        if planning_commit and not COMMIT.fullmatch(planning_commit):
            errors.append(f"{source}: Planning commit must be a commit SHA")
        if merge_commit and not COMMIT.fullmatch(merge_commit):
            errors.append(f"{source}: Effective merge commit must be a commit SHA")
        remote_pr = values.get("Effective remote PR", "")
        if remote_pr and not PR.match(remote_pr):
            errors.append(f"{source}: Effective remote PR must identify a pull request")
        for required_phrase in (
            "Source:",
            "Authorized task:",
            "Registry",
            "specification",
            "GitHub",
        ):
            if required_phrase.casefold() not in text.casefold():
                errors.append(f"{source}: missing {required_phrase.rstrip(':')} evidence")
    if not amendment_paths:
        errors.append("bootstrap/amendments: no amendment records found")
    return sorted(errors)


def preflight_errors(
    repo_root: Path, *, dirty_paths: tuple[str, ...] | None = None
) -> list[str]:
    """Detect unresolved amendments and uncommitted coordinator planning state."""

    repo_root = repo_root.resolve()
    errors = validate_records(repo_root)
    for path in sorted((repo_root / "bootstrap" / "amendments").glob("AMEND-*.md")):
        values = _bullet_values(path.read_text(encoding="utf-8").splitlines())
        status = values.get("Resolution status", "").casefold()
        if not (
            status.startswith("effective and reconciled")
            or status.startswith("rejected and reconciled")
        ):
            errors.append(
                f"{path.relative_to(repo_root)}: unresolved amendment blocks dispatch"
            )
    observed_dirty = dirty_paths
    if observed_dirty is None:
        observed_dirty = _git_dirty_planning_paths(repo_root)
    if observed_dirty:
        errors.append(
            "uncommitted coordinator planning files block dispatch: "
            + ", ".join(sorted(set(observed_dirty)))
        )
    return sorted(errors)


def _bullet_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"- ([^:]+): (.+)", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _git_dirty_planning_paths(repo_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *PLANNING_PATHS],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(value)
    return tuple(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="also reject unresolved amendments and dirty planning files",
    )
    args = parser.parse_args(argv)
    errors = (
        preflight_errors(args.repo_root)
        if args.preflight
        else validate_records(args.repo_root)
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    count = len(list((args.repo_root / "bootstrap" / "amendments").glob("AMEND-*.md")))
    suffix = " and preflight clear" if args.preflight else ""
    print(f"Bootstrap amendments: {count} record(s) valid{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
