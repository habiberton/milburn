#!/usr/bin/env python3
"""Validate concise bootstrap defect feedback briefs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TASK_FILE_RE = re.compile(r"^(MB-\d{3})\.md$")
FEEDBACK_ID_RE = re.compile(r"^(MB-\d{3})-F(?!000)\d{3}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
ATTEMPT_RE = re.compile(r"^a\d{2}$")
GITHUB_REF_RE = re.compile(r"^(?:#\d+|https://github\.com/[^/]+/[^/]+/(?:issues|pull)/\d+)$")
UNAVAILABLE_RE = re.compile(r"^unavailable — \S.*$")

FIELDS = (
    "Discovery phase",
    "Severity",
    "Symptom",
    "Root cause",
    "Resolution",
    "Fix commit",
    "Regression evidence",
    "Lesson",
    "Status",
    "Attempt",
    "Worker candidate",
    "Coordinator integration",
    "GitHub PR",
    "Linked issue",
)
PHASES = {"review", "test", "integration", "recovery", "production"}
SEVERITIES = {"blocking", "meaningful"}
STATUSES = {"resolved", "unresolved", "separately-scoped"}


def _known_task_ids(repo_root: Path) -> set[str]:
    registry = repo_root / "bootstrap" / "tasks.json"
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
        return {task["id"] for task in payload["tasks"]}
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read task registry {registry}: {exc}") from exc


def _parse_fields(lines: list[str], source: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    parsed: list[tuple[str, str]] = []
    for line in lines:
        if not line:
            continue
        match = re.fullmatch(r"- ([^:]+): (.+)", line)
        if not match:
            errors.append(f"{source}: unexpected entry line {line!r}")
            continue
        parsed.append((match.group(1), match.group(2)))

    names = tuple(name for name, _ in parsed)
    if names != FIELDS:
        errors.append(
            f"{source}: fields must appear once in this order: {', '.join(FIELDS)}"
        )
    values = {name: value for name, value in parsed}
    return values, errors


def _validate_entry(
    task_id: str, feedback_id: str, values: dict[str, str], source: str
) -> list[str]:
    errors: list[str] = []
    if not FEEDBACK_ID_RE.fullmatch(feedback_id) or not feedback_id.startswith(
        f"{task_id}-F"
    ):
        errors.append(f"{source}: feedback ID must match {task_id}-F<three digits>")
    if values.get("Discovery phase") not in PHASES:
        errors.append(f"{source}: invalid discovery phase")
    if values.get("Severity") not in SEVERITIES:
        errors.append(f"{source}: invalid severity")
    if values.get("Status") not in STATUSES:
        errors.append(f"{source}: invalid status")

    attempt = values.get("Attempt", "")
    if not (ATTEMPT_RE.fullmatch(attempt) or UNAVAILABLE_RE.fullmatch(attempt)):
        errors.append(f"{source}: attempt must be aNN or explicitly unavailable")

    for field in ("Worker candidate", "Coordinator integration"):
        value = values.get(field, "")
        if not (COMMIT_RE.fullmatch(value) or UNAVAILABLE_RE.fullmatch(value)):
            errors.append(f"{source}: {field} must be a commit or explicitly unavailable")

    pull_request = values.get("GitHub PR", "")
    if not (
        GITHUB_REF_RE.fullmatch(pull_request)
        or UNAVAILABLE_RE.fullmatch(pull_request)
    ):
        errors.append(f"{source}: GitHub PR must be a reference or explicitly unavailable")

    status = values.get("Status")
    fix_commit = values.get("Fix commit", "")
    regression = values.get("Regression evidence", "")
    linked_issue = values.get("Linked issue", "")
    if status == "resolved":
        if not COMMIT_RE.fullmatch(fix_commit):
            errors.append(f"{source}: resolved finding requires a fix commit")
        if UNAVAILABLE_RE.fullmatch(regression) or not re.fullmatch(r".+ — .+", regression):
            errors.append(
                f"{source}: resolved finding requires regression command and result evidence"
            )
        if not (
            GITHUB_REF_RE.fullmatch(linked_issue)
            or UNAVAILABLE_RE.fullmatch(linked_issue)
        ):
            errors.append(f"{source}: linked issue must be a reference or explicitly unavailable")
    elif status in {"unresolved", "separately-scoped"}:
        if not GITHUB_REF_RE.fullmatch(linked_issue):
            errors.append(f"{source}: {status} finding requires a linked GitHub issue")
        if not (COMMIT_RE.fullmatch(fix_commit) or UNAVAILABLE_RE.fullmatch(fix_commit)):
            errors.append(f"{source}: fix commit must be a commit or explicitly unavailable")

    return errors


def validate(repo_root: Path) -> list[str]:
    """Return deterministic validation errors for all task feedback briefs."""

    repo_root = repo_root.resolve()
    feedback_dir = repo_root / "bootstrap" / "feedback"
    errors: list[str] = []
    try:
        known_tasks = _known_task_ids(repo_root)
    except ValueError as exc:
        return [str(exc)]

    seen_ids: dict[str, str] = {}
    for path in sorted(feedback_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        match = TASK_FILE_RE.fullmatch(path.name)
        if not match:
            errors.append(f"{path.relative_to(repo_root)}: invalid brief filename")
            continue
        task_id = match.group(1)
        source = str(path.relative_to(repo_root))
        if task_id not in known_tasks:
            errors.append(f"{source}: unknown task ID {task_id}")

        lines = path.read_text(encoding="utf-8").splitlines()
        expected_prefix = [f"# {task_id} feedback brief", "", "## Findings"]
        if lines[:3] != expected_prefix:
            errors.append(f"{source}: required headings are missing or out of order")
            continue

        body = lines[3:]
        nonblank = [line for line in body if line]
        if nonblank == ["- None recorded."]:
            continue
        if "- None recorded." in nonblank:
            errors.append(f"{source}: empty marker cannot appear with findings")

        headings = [index for index, line in enumerate(body) if line.startswith("### ")]
        if not headings:
            errors.append(f"{source}: findings must contain an entry or the empty marker")
            continue
        if any(line for line in body[: headings[0]]):
            errors.append(f"{source}: unexpected content before first finding")

        for position, start in enumerate(headings):
            end = headings[position + 1] if position + 1 < len(headings) else len(body)
            feedback_id = body[start][4:]
            entry_source = f"{source}:{feedback_id}"
            expected_id = f"{task_id}-F{position + 1:03d}"
            if feedback_id != expected_id:
                errors.append(
                    f"{entry_source}: feedback IDs must start at F001 and be "
                    f"contiguous; expected {expected_id}"
                )
            previous = seen_ids.get(feedback_id)
            if previous is not None:
                errors.append(f"{entry_source}: duplicate feedback ID first used in {previous}")
            else:
                seen_ids[feedback_id] = source
            values, field_errors = _parse_fields(body[start + 1 : end], entry_source)
            errors.extend(field_errors)
            errors.extend(_validate_entry(task_id, feedback_id, values, entry_source))

    return sorted(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    errors = validate(args.repo_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    count = sum(
        path.name != "README.md"
        for path in (args.repo_root / "bootstrap" / "feedback").glob("*.md")
    )
    print(f"Bootstrap feedback: {count} task briefs valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
