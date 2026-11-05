"""Validate a Coder candidate against its assigned Git worktree and progress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
        if self._git(lease, "ls-tree", "--name-only", "HEAD", "--", progress_path) != progress_path:
            raise CoderProtocolError("progress file is not committed on the issue branch")
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
    def __init__(self, git: GitCoderProbe) -> None:
        self._git = git

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
        if not result.test_claims or not any(claim.outcome == "passed" for claim in result.test_claims):
            raise CoderProtocolError("candidate has no passing test evidence")
        if not any(re.match(r"^- .+: passed(?:;|$)", line, re.I)
                   for line in progress.sections["Validation"].splitlines()):
            raise CoderProtocolError("progress has no passing validation record")
        commits, changed = self._git.inspect(lease, result.head_sha, expected_path)
        if (result.commits != commits or len(set(result.files_changed)) != len(result.files_changed)
            or set(result.files_changed) != set(changed)):
            raise CoderProtocolError("reported commits or changed files do not match Git")
        return result
