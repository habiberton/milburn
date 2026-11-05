"""Validate a Coder candidate against its assigned Git worktree and progress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os
import re
import subprocess

from milburn.domain import CoderOutcome, CoderResult, IssueState
from milburn.runtime.worktrees import WorktreeLease

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HEADERS = ("Issue", "Branch", "Base revision", "Current head", "Last updated", "Agent attempt")
_SECTIONS = ("Goal", "Completed", "In progress", "Next", "Decisions and assumptions",
             "Files changed", "Validation", "Blockers", "Handoff note")


class CoderProtocolError(ValueError):
    """A candidate lacks the durable evidence required for independent QA."""


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    issue_number: int
    branch: str
    base_sha: str
    head_sha: str
    updated_at: datetime
    attempt_id: str
    sections: dict[str, str]


def parse_progress(text: str) -> ProgressRecord:
    if not isinstance(text, str) or not text.strip():
        raise CoderProtocolError("progress must be non-empty text")
    lines = text.splitlines()
    if len(lines) < 8:
        raise CoderProtocolError("progress is incomplete")
    values: dict[str, str] = {}
    for index, key in enumerate(_HEADERS):
        prefix = key + ": "
        if not lines[index].startswith(prefix):
            raise CoderProtocolError(f"progress {key} header is missing or out of order")
        value = lines[index][len(prefix):]
        if not value or value != value.strip():
            raise CoderProtocolError(f"progress {key} is empty or malformed")
        values[key] = value
    if lines[6] != "":
        raise CoderProtocolError("progress must separate headers from sections")
    sections: dict[str, str] = {}
    cursor = 7
    for section in _SECTIONS:
        if cursor >= len(lines) or lines[cursor] != section:
            raise CoderProtocolError(f"progress {section} section is missing or out of order")
        cursor += 1
        start = cursor
        while cursor < len(lines) and lines[cursor] != "":
            cursor += 1
        content = "\n".join(lines[start:cursor]).strip()
        if not content:
            raise CoderProtocolError(f"progress {section} is empty")
        sections[section] = content
        if section != _SECTIONS[-1]:
            cursor += 1
    if any(line.strip() for line in lines[cursor:]):
        raise CoderProtocolError("progress has extra sections or trailing content")
    issue = values["Issue"]
    if re.fullmatch(r"#[1-9][0-9]*", issue) is None:
        raise CoderProtocolError("progress issue must be a positive issue number")
    for key in ("Base revision", "Current head"):
        if _SHA.fullmatch(values[key]) is None:
            raise CoderProtocolError(f"progress {key} must be a full SHA")
    try:
        updated = datetime.fromisoformat(values["Last updated"].replace("Z", "+00:00"))
    except ValueError as error:
        raise CoderProtocolError("progress timestamp is invalid") from error
    if updated.tzinfo is None:
        raise CoderProtocolError("progress timestamp needs a timezone")
    return ProgressRecord(int(issue[1:]), values["Branch"], values["Base revision"],
                          values["Current head"], updated, values["Agent attempt"], sections)


class GitCoderProbe:
    """Read fixed Git facts from one validated lease; no caller-supplied Git command."""

    def _git(self, lease: WorktreeLease, *args: str) -> str:
        completed = subprocess.run(("git", *args), cwd=lease.worktree, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            raise CoderProtocolError(f"Git inspection failed: {' '.join(args)}")
        return completed.stdout.strip()

    def inspect(self, lease: WorktreeLease, candidate: str, progress_path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if self._git(lease, "rev-parse", "--show-toplevel") != str(lease.worktree):
            raise CoderProtocolError("worktree repository identity does not match lease")
        if self._git(lease, "branch", "--show-current") != lease.branch:
            raise CoderProtocolError("worktree branch does not match lease")
        if self._git(lease, "status", "--porcelain"):
            raise CoderProtocolError("candidate worktree is dirty")
        for older, newer in ((lease.base_sha, candidate), (candidate, "HEAD")):
            completed = subprocess.run(("git", "merge-base", "--is-ancestor", older, newer),
                                       cwd=lease.worktree, capture_output=True, check=False)
            if completed.returncode:
                raise CoderProtocolError("candidate head is not reachable from assigned branch and base")
        tree_entry = self._git(lease, "ls-tree", "HEAD", "--", progress_path)
        if not tree_entry.startswith(("100644 blob ", "100755 blob ")):
            raise CoderProtocolError("progress file is not committed on the issue branch")
        if tree_entry.split("\t", 1)[-1] != progress_path:
            raise CoderProtocolError("progress path does not match the committed file")
        trailing = tuple(self._git(lease, "rev-list", "--reverse", f"{candidate}..HEAD").splitlines())
        if not trailing:
            raise CoderProtocolError("progress must be committed after candidate")
        for sha in trailing:
            paths = tuple(self._git(lease, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines())
            if not paths or any(path != progress_path for path in paths):
                raise CoderProtocolError("commits after candidate must change only the progress file")
        commits = tuple(self._git(lease, "rev-list", "--reverse", f"{lease.base_sha}..{candidate}").splitlines())
        if not commits:
            raise CoderProtocolError("candidate has no issue commits")
        marker = f"[#{lease.issue_number}]"
        for sha in commits:
            names = self._git(lease, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
            if any(name != progress_path for name in names):
                if marker not in self._git(lease, "show", "-s", "--format=%s", sha):
                    raise CoderProtocolError("code-changing commit lacks issue marker")
        changed = tuple(self._git(lease, "diff", "--name-only", lease.base_sha, candidate).splitlines())
        return commits, changed


class CoderProtocolGuard:
    def __init__(self, git: GitCoderProbe, *, log_root: Path,
                 required_commands: tuple[str, ...]) -> None:
        if (not isinstance(log_root, Path) or not log_root.is_absolute()
            or not isinstance(required_commands, tuple) or not required_commands
            or len(set(required_commands)) != len(required_commands)
            or any(not isinstance(command, str) or not command.strip() for command in required_commands)):
            raise CoderProtocolError("trusted log root and required test commands are needed")
        self._git = git
        self._log_root = log_root
        self._required_commands = required_commands

    def accept(self, result: CoderResult, lease: WorktreeLease, issue_state: IssueState) -> CoderResult:
        if not isinstance(result, CoderResult) or not isinstance(lease, WorktreeLease):
            raise CoderProtocolError("candidate and lease must use known contracts")
        if not isinstance(issue_state, IssueState) or issue_state not in {IssueState.CODING, IssueState.CHANGES_REQUESTED}:
            raise CoderProtocolError("Coder cannot submit a candidate for this issue state")
        if result.outcome is not CoderOutcome.CANDIDATE:
            raise CoderProtocolError("only candidate outcomes enter candidate acceptance")
        expected_path = f".milburn/issues/{lease.issue_number}/progress.txt"
        if (result.attempt_id != lease.attempt_id or result.issue_number != lease.issue_number
            or result.progress_path != expected_path or _SHA.fullmatch(result.head_sha) is None):
            raise CoderProtocolError("candidate identity, path, or head does not match assignment")
        progress_file = lease.worktree / expected_path
        if progress_file.is_symlink() or not progress_file.resolve(strict=False).is_relative_to(lease.worktree.resolve()):
            raise CoderProtocolError("progress must be a regular file inside the worktree")
        try:
            progress = parse_progress(progress_file.read_text())
        except OSError as error:
            raise CoderProtocolError("progress file is missing") from error
        if (progress.issue_number != lease.issue_number or progress.branch != lease.branch
            or progress.base_sha != lease.base_sha or progress.head_sha != result.head_sha
            or progress.attempt_id != lease.attempt_id):
            raise CoderProtocolError("progress issue, attempt, branch, base, or head does not match")
        if re.search(r"\bself[- ]approv(?:e|ed|al)\b", progress.sections["Blockers"], re.I):
            raise CoderProtocolError("Coder cannot self-approve")
        self._validate_test_evidence(result, progress, lease)
        commits, changed = self._git.inspect(lease, result.head_sha, expected_path)
        if (result.commits != commits or len(set(result.files_changed)) != len(result.files_changed)
            or set(result.files_changed) != set(changed)):
            raise CoderProtocolError("reported commits or changed files do not match Git")
        return result

    def _validate_test_evidence(self, result: CoderResult, progress: ProgressRecord,
                                lease: WorktreeLease) -> None:
        claims = result.test_claims
        if len(claims) != len(self._required_commands) or {item.name for item in claims} != set(self._required_commands):
            raise CoderProtocolError("candidate test evidence omits a required command")
        if not self._log_root.is_dir() or self._log_root.resolve().is_relative_to(lease.worktree.resolve()):
            raise CoderProtocolError("test evidence log root is unavailable or inside worktree")
        validation_lines = set(progress.sections["Validation"].splitlines())
        for item in claims:
            if item.outcome != "passed":
                raise CoderProtocolError("candidate test evidence did not pass")
            try:
                value = json.loads(item.evidence)
            except (json.JSONDecodeError, TypeError) as error:
                raise CoderProtocolError("candidate test evidence is malformed") from error
            if not isinstance(value, dict) or set(value) != {"command", "result", "revision", "log_ref"}:
                raise CoderProtocolError("candidate test evidence fields are incomplete")
            if (value["command"] != item.name or value["revision"] != result.head_sha
                or not isinstance(value["result"], str)
                or re.search(r"\b[1-9][0-9]* passed\b", value["result"]) is None):
                raise CoderProtocolError("candidate test evidence command, result, or revision is invalid")
            if not isinstance(value["log_ref"], str):
                raise CoderProtocolError("candidate test evidence log reference is invalid")
            log_path = Path(value["log_ref"])
            if (not log_path.is_absolute() or log_path.is_symlink()
                or log_path.resolve(strict=False).parent != self._log_root.resolve()
                or not log_path.is_file()):
                raise CoderProtocolError("candidate test evidence log reference is unavailable")
            try:
                with log_path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - 4096))
                    log_tail = stream.read().decode("utf-8", errors="replace")
            except OSError as error:
                raise CoderProtocolError("candidate test evidence log is unreadable") from error
            if not any(line.startswith(value["result"]) and
                       (len(line) == len(value["result"]) or line[len(value["result"])] in " ,")
                       for line in log_tail.splitlines()):
                raise CoderProtocolError("candidate test evidence result is absent from log")
            expected_line = f"- {item.name}: passed; revision:{result.head_sha}; log:{log_path}"
            if expected_line not in validation_lines:
                raise CoderProtocolError("progress validation does not match candidate test evidence")
