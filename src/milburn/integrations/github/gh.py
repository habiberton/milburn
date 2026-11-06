"""GitHub pull-request effects through the ``gh`` CLI (ARCH §5, §13 item 1).

Only the ``milburn`` CLI calls this, with the user's own ``gh`` login; role
agents never get GitHub write authority (PRD R6, R39). Each method is one
``gh`` call with JSON output. Reads are safe to repeat; the caller journals
every mutation and reconciles against these reads before retrying (PRD R41).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Sequence

PASSING_BUCKETS = frozenset({"pass", "skipping"})


class GhError(RuntimeError):
    """A ``gh`` call failed or returned something unexpected."""


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    url: str
    state: str  # OPEN, CLOSED, MERGED
    head_ref: str
    head_sha: str
    base_ref: str
    body: str
    merge_commit: str | None


@dataclass(frozen=True, slots=True)
class ChecksReport:
    passing: bool
    pending: tuple[str, ...]
    failing: tuple[str, ...]
    required: int


_PR_FIELDS = "number,url,state,headRefName,headRefOid,baseRefName,body,mergeCommit"


class GhClient:
    def __init__(self, repository: Path, *, executable: str = "gh", timeout: float = 120) -> None:
        if not executable or any(c.isspace() for c in executable):
            raise ValueError("gh executable must be one command name or path")
        self._repository = repository
        self._executable = executable
        self._timeout = timeout

    def _run(self, arguments: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GH_PROMPT_DISABLED"] = "1"
        env["NO_COLOR"] = "1"
        try:
            completed = subprocess.run(
                (self._executable, *arguments), cwd=self._repository, capture_output=True,
                text=True, timeout=self._timeout, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GhError(f"gh {' '.join(arguments[:2])} could not run: {error}") from error
        if check and completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip().splitlines()
            raise GhError(f"gh {' '.join(arguments[:2])} failed: {message[-1] if message else completed.returncode}")
        return completed

    @staticmethod
    def _pr(data: dict[str, Any]) -> PullRequest:
        merge = data.get("mergeCommit")
        return PullRequest(
            number=int(data["number"]), url=str(data["url"]), state=str(data["state"]),
            head_ref=str(data["headRefName"]), head_sha=str(data["headRefOid"]),
            base_ref=str(data["baseRefName"]), body=str(data.get("body") or ""),
            merge_commit=merge.get("oid") if isinstance(merge, dict) else None,
        )

    def find_pr(self, head_branch: str, marker: str) -> PullRequest | None:
        """The PR for this head branch whose body carries the marker, in any state."""

        completed = self._run(("pr", "list", "--head", head_branch, "--state", "all",
                               "--json", _PR_FIELDS, "--limit", "20"))
        try:
            items = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            raise GhError("gh pr list returned invalid JSON") from error
        matches = [self._pr(item) for item in items if marker in str(item.get("body") or "")]
        if len(matches) > 1:
            raise GhError(f"{len(matches)} pull requests carry marker {marker}; resolve by hand")
        return matches[0] if matches else None

    def view_pr(self, number: int) -> PullRequest:
        completed = self._run(("pr", "view", str(number), "--json", _PR_FIELDS))
        try:
            return self._pr(json.loads(completed.stdout))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise GhError("gh pr view returned invalid JSON") from error

    def create_pr(self, *, head: str, base: str, title: str, body: str) -> None:
        self._run(("pr", "create", "--head", head, "--base", base, "--title", title,
                   "--body", body))

    def required_checks(self, number: int) -> ChecksReport:
        completed = self._run(("pr", "checks", str(number), "--required", "--json", "name,bucket"),
                              check=False)
        text = completed.stdout.strip()
        if not text:
            # gh exits non-zero and prints a notice when nothing is required.
            if "no required checks" in (completed.stderr or "").lower():
                return ChecksReport(True, (), (), 0)
            raise GhError(f"gh pr checks failed: {(completed.stderr or '').strip()[:200]}")
        try:
            checks = json.loads(text)
        except json.JSONDecodeError as error:
            raise GhError("gh pr checks returned invalid JSON") from error
        pending = tuple(sorted(c["name"] for c in checks if c.get("bucket") == "pending"))
        failing = tuple(sorted(
            c["name"] for c in checks if c.get("bucket") not in PASSING_BUCKETS | {"pending"}
        ))
        return ChecksReport(not pending and not failing, pending, failing, len(checks))

    def merge_pr(self, number: int, *, head_sha: str, subject: str) -> None:
        """Merge with a merge commit, only if the PR head is still ``head_sha``."""

        self._run(("pr", "merge", str(number), "--merge", "--match-head-commit", head_sha,
                   "--subject", subject))
