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
PR = re.compile(
    r"^(?:#\d+(?: \(https://github\.com/[^/]+/[^/]+/pull/\d+\))?"
    r"|https://github\.com/[^/]+/[^/]+/pull/\d+)$"
)
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
IMPACT_CLASSIFICATIONS = {
    "unaffected",
    "needs_steering",
    "must_pause",
    "must_stop",
}
DISPATCH_STATES = {"frozen", "resumed", "unchanged"}
RESOLUTION_STATES = {
    "pending",
    "effective and reconciled",
    "rejected and reconciled",
}
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
        if not lines or not re.fullmatch(
            rf"# {re.escape(path.stem)} — \S.*", lines[0]
        ):
            errors.append(f"{source}: title must identify {path.stem}")
        sections, section_errors = _parse_sections(lines, source)
        errors.extend(section_errors)
        if section_errors:
            continue
        errors.extend(_validate_sections(sections, source))
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
        sections, section_errors = _parse_sections(
            path.read_text(encoding="utf-8").splitlines(),
            str(path.relative_to(repo_root)),
        )
        if section_errors:
            continue
        values, _ = _section_values(
            sections["## Effectiveness"],
            str(path.relative_to(repo_root)),
            "Effectiveness",
        )
        resolution = values.get("Resolution status", "").casefold()
        dispatch = values.get("Dispatch status", "").casefold()
        if resolution not in {
            "effective and reconciled",
            "rejected and reconciled",
        }:
            errors.append(
                f"{path.relative_to(repo_root)}: unresolved amendment blocks dispatch"
            )
        elif dispatch == "frozen":
            errors.append(
                f"{path.relative_to(repo_root)}: amendment record still freezes dispatch"
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


def _parse_sections(
    lines: list[str], source: str
) -> tuple[dict[str, list[str]], list[str]]:
    errors: list[str] = []
    heading_positions: list[tuple[str, int]] = []
    for heading in REQUIRED_HEADINGS:
        positions = [index for index, line in enumerate(lines) if line == heading]
        if not positions:
            errors.append(f"{source}: missing required heading {heading}")
        elif len(positions) > 1:
            errors.append(f"{source}: duplicate required heading {heading}")
        else:
            heading_positions.append((heading, positions[0]))
    if errors:
        return {}, errors
    if [position for _, position in heading_positions] != sorted(
        position for _, position in heading_positions
    ):
        return {}, [f"{source}: required headings are out of order"]
    all_section_positions = sorted(
        index for index, line in enumerate(lines) if line.startswith("## ")
    )
    sections: dict[str, list[str]] = {}
    for heading, start in heading_positions:
        end = next(
            (position for position in all_section_positions if position > start),
            len(lines),
        )
        sections[heading] = lines[start + 1 : end]
    return sections, []


def _validate_sections(sections: dict[str, list[str]], source: str) -> list[str]:
    errors: list[str] = []
    for heading in ("## Requested change", "## Affected tasks"):
        if not _has_content(sections[heading]):
            errors.append(f"{source}: {heading[3:]} section must be nonempty")

    authority, authority_errors = _section_values(
        sections["## Authority"], source, "Authority"
    )
    errors.extend(authority_errors)
    for field in ("Source", "Authorized task"):
        if field not in authority:
            errors.append(f"{source}: Authority section missing {field}")

    errors.extend(_validate_active_work(sections["## Active-work impact"], source))

    changes, change_errors = _section_values(
        sections["## Registry and specification changes"],
        source,
        "Registry and specification changes",
    )
    errors.extend(change_errors)
    for field in ("Registry changes", "Specification changes", "GitHub changes"):
        if field not in changes:
            errors.append(f"{source}: change section missing {field}")

    effectiveness, effectiveness_errors = _section_values(
        sections["## Effectiveness"], source, "Effectiveness"
    )
    errors.extend(effectiveness_errors)
    for field in EFFECTIVENESS_FIELDS:
        if field not in effectiveness:
            errors.append(f"{source}: missing effectiveness field {field}")
    if all(field in effectiveness for field in EFFECTIVENESS_FIELDS):
        errors.extend(_validate_effectiveness(effectiveness, source))
    return errors


def _validate_active_work(lines: list[str], source: str) -> list[str]:
    nonblank = [line.strip() for line in lines if line.strip()]
    if nonblank == ["- No active work."]:
        return []
    table_rows = [line for line in nonblank if line.startswith("|")]
    data_rows = [
        row
        for row in table_rows
        if not re.fullmatch(r"\|[-| ]+\|", row)
        and "| Work | Classification |" not in row
    ]
    if not data_rows:
        return [
            f"{source}: Active-work impact requires classified rows or "
            "'- No active work.'"
        ]
    errors: list[str] = []
    for row in data_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) != 3 or not cells[0] or not cells[2]:
            errors.append(f"{source}: malformed active-work impact row {row!r}")
            continue
        if cells[1] not in IMPACT_CLASSIFICATIONS:
            errors.append(
                f"{source}: unknown active-work classification {cells[1]!r}"
            )
    return errors


def _validate_effectiveness(values: dict[str, str], source: str) -> list[str]:
    errors: list[str] = []
    resolution = values["Resolution status"].casefold()
    dispatch = values["Dispatch status"].casefold()
    if resolution not in RESOLUTION_STATES:
        errors.append(f"{source}: invalid Resolution status {resolution!r}")
    if dispatch not in DISPATCH_STATES:
        errors.append(f"{source}: invalid Dispatch status {dispatch!r}")
    if resolution == "pending":
        if dispatch != "frozen":
            errors.append(f"{source}: pending amendment must freeze dispatch")
        for field in (
            "Planning commit",
            "Effective remote PR",
            "Effective merge commit",
        ):
            if values[field].casefold() != "pending":
                errors.append(f"{source}: pending amendment requires pending {field}")
        return errors
    if resolution in {"effective and reconciled", "rejected and reconciled"}:
        planning_commit = values["Planning commit"].strip("`")
        merge_commit = values["Effective merge commit"].strip("`")
        if not COMMIT.fullmatch(planning_commit):
            errors.append(f"{source}: Planning commit must be a commit SHA")
        if not COMMIT.fullmatch(merge_commit):
            errors.append(f"{source}: Effective merge commit must be a commit SHA")
        if not PR.fullmatch(values["Effective remote PR"]):
            errors.append(
                f"{source}: Effective remote PR must exactly identify a pull request"
            )
    return errors


def _section_values(
    lines: list[str], source: str, section_name: str
) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors: list[str] = []
    for line in lines:
        match = re.fullmatch(r"- ([^:]+): (\S.*)", line)
        if not match:
            continue
        field, value = match.groups()
        if field in values:
            errors.append(f"{source}: duplicate {section_name} field {field}")
        values[field] = value
    return values, errors


def _has_content(lines: list[str]) -> bool:
    return any(
        re.search(r"[A-Za-z0-9]", line) and not line.strip().startswith("<!--")
        for line in lines
    )


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
