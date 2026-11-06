"""GitHub pull-request effects through the ``gh`` CLI (ARCH §5, §13 item 1).

Only the ``milburn`` CLI calls this, with the user's own ``gh`` login; role
agents never get GitHub write authority (PRD R6, R39). Every call names its
repository explicitly (``--repo`` / ``repos/<owner>/<name>``): ``gh``'s own
repository resolution (``GH_REPO``, ``gh repo set-default``, remote priority)
is never trusted. Reads are safe to repeat; the caller journals every mutation
and reconciles against these reads before retrying (PRD R41).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

PASSING_BUCKETS = frozenset({"pass", "skipping"})
PR_STATES = frozenset({"OPEN", "CLOSED", "MERGED"})
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_HOST = re.compile(r"[A-Za-z0-9.-]+")


class GhError(RuntimeError):
    """A ``gh`` call failed or returned something unexpected."""


@dataclass(frozen=True, slots=True)
class GitHubRepo:
    host: str
    name: str  # owner/repo

    def __post_init__(self) -> None:
        if not _HOST.fullmatch(self.host) or not _REPO.fullmatch(self.name):
            raise ValueError(f"invalid GitHub repository {self.host}/{self.name}")

    @property
    def slug(self) -> str:
        return self.name if self.host == "github.com" else f"{self.host}/{self.name}"


def repo_from_url(url: str) -> GitHubRepo | None:
    """Parse a GitHub remote URL (https or ssh); None when it is not one."""

    url = url.strip()
    patterns = (
        r"https://(?:[^@/]+@)?(?P<host>[^/:]+)/(?P<name>[^/]+/[^/]+?)(?:\.git)?/?",
        r"ssh://git@(?P<host>[^/:]+)(?::\d+)?/(?P<name>[^/]+/[^/]+?)(?:\.git)?/?",
        r"git@(?P<host>[^:]+):(?P<name>[^/]+/[^/]+?)(?:\.git)?/?",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, url)
        if match:
            try:
                return GitHubRepo(match["host"], match["name"])
            except ValueError:
                return None
    return None


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
    cross_repository: bool


@dataclass(frozen=True, slots=True)
class ChecksReport:
    passing: bool
    pending: tuple[str, ...]
    failing: tuple[str, ...]
    missing: tuple[str, ...]
    required: tuple[str, ...]


_PR_FIELDS = (
    "number,url,state,headRefName,headRefOid,baseRefName,body,mergeCommit,isCrossRepository"
)
# Network Git and gh must never wait for a prompt, and must keep the user's
# credential helpers; GH_REPO/GH_HOST would redirect calls, so they go.
_DROPPED_ENV = ("GH_REPO", "GH_HOST")


def tool_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _DROPPED_ENV}
    env.update(GH_PROMPT_DISABLED="1", NO_COLOR="1", GIT_TERMINAL_PROMPT="0")
    return env


class GhClient:
    def __init__(
        self, repository: Path, repo: GitHubRepo, *, executable: str = "gh", timeout: float = 120
    ) -> None:
        if not executable or any(c.isspace() for c in executable):
            raise ValueError("gh executable must be one command name or path")
        self._repository = repository
        self.repo = repo
        self._executable = executable
        self._timeout = timeout

    def _run(self, arguments: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                (self._executable, *arguments), cwd=self._repository, capture_output=True,
                text=True, timeout=self._timeout, env=tool_env(), stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GhError(f"gh {' '.join(arguments[:2])} could not run: {error}") from error
        if check and completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip().splitlines()
            raise GhError(f"gh {' '.join(arguments[:2])} failed: {message[-1] if message else completed.returncode}")
        return completed

    def _json(self, completed: subprocess.CompletedProcess[str], what: str) -> Any:
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise GhError(f"{what} returned invalid JSON") from error

    def _pr(self, data: Any) -> PullRequest:
        try:
            merge = data.get("mergeCommit")
            pr = PullRequest(
                number=int(data["number"]), url=str(data["url"]), state=str(data["state"]),
                head_ref=str(data["headRefName"]), head_sha=str(data["headRefOid"]),
                base_ref=str(data["baseRefName"]), body=str(data.get("body") or ""),
                merge_commit=merge.get("oid") if isinstance(merge, dict) else None,
                cross_repository=bool(data["isCrossRepository"]),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise GhError(f"gh returned a malformed pull request: {error}") from error
        if pr.state not in PR_STATES:
            raise GhError(f"pull request #{pr.number} has unknown state {pr.state!r}")
        return pr

    def find_pr(self, head_branch: str, base: str, marker: str) -> PullRequest | None:
        """Milburn's PR: same repository, this head and base, carrying the marker."""

        completed = self._run(("pr", "list", "--repo", self.repo.slug, "--head", head_branch,
                               "--state", "all", "--json", _PR_FIELDS, "--limit", "100"))
        items = self._json(completed, "gh pr list")
        if not isinstance(items, list):
            raise GhError("gh pr list did not return a list")
        prs = [self._pr(item) for item in items]
        matches = [
            pr for pr in prs
            if not pr.cross_repository and pr.base_ref == base and marker in pr.body
        ]
        if len(matches) > 1:
            numbers = ", ".join(f"#{pr.number}" for pr in matches)
            raise GhError(f"pull requests {numbers} all carry this work item's marker; resolve by hand")
        return matches[0] if matches else None

    def view_pr(self, number: int) -> PullRequest:
        completed = self._run(("pr", "view", str(number), "--repo", self.repo.slug,
                               "--json", _PR_FIELDS))
        return self._pr(self._json(completed, "gh pr view"))

    def create_pr(self, *, head: str, base: str, title: str, body: str) -> None:
        self._run(("pr", "create", "--repo", self.repo.slug, "--head", head, "--base", base,
                   "--title", title, "--body", body))

    def required_contexts(self, branch: str) -> tuple[str, ...]:
        """Required status checks for ``branch`` from protection and rulesets.

        Fails closed: a response that cannot be read (403, 5xx) is an error,
        never "nothing required". Only "branch not protected" (404) and an
        empty ruleset list mean no requirement from that source.
        """

        host = ("--hostname", self.repo.host)
        required: set[str] = set()
        protection = self._run(("api", *host,
                                f"repos/{self.repo.name}/branches/{branch}/protection/required_status_checks"),
                               check=False)
        if protection.returncode == 0:
            data = self._json(protection, "branch protection")
            for context in data.get("contexts") or []:
                required.add(str(context))
            for check in data.get("checks") or []:
                if isinstance(check, dict) and check.get("context"):
                    required.add(str(check["context"]))
        elif "branch not protected" not in (protection.stderr or "").lower():
            # Only GitHub's explicit "not protected" means no requirement; a
            # permission 404 or any other error fails closed.
            raise GhError(f"cannot read branch protection: {(protection.stderr or '').strip()[:200]}")
        rules = self._run(("api", *host, "--paginate", "--slurp",
                           f"repos/{self.repo.name}/rules/branches/{branch}"))
        pages = self._json(rules, "branch rules")
        if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
            raise GhError("branch rules did not return a list of pages")
        data = [rule for page in pages for rule in page]
        for rule in data:
            if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
                for check in (rule.get("parameters") or {}).get("required_status_checks") or []:
                    if isinstance(check, dict) and check.get("context"):
                        required.add(str(check["context"]))
        return tuple(sorted(required))

    def checks(self, number: int, required: Sequence[str]) -> ChecksReport:
        """Every required context must have reported on the PR head and passed."""

        completed = self._run(("pr", "checks", str(number), "--repo", self.repo.slug,
                               "--json", "name,bucket"), check=False)
        text = completed.stdout.strip()
        if text:
            reported = self._json(completed, "gh pr checks")
            if not isinstance(reported, list):
                raise GhError("gh pr checks did not return a list")
        elif "no checks reported" in (completed.stderr or "").lower():
            reported = []
        else:
            raise GhError(f"gh pr checks failed: {(completed.stderr or '').strip()[:200]}")
        buckets: dict[str, list[str]] = {}
        for check in reported:
            if isinstance(check, dict) and "name" in check:
                buckets.setdefault(str(check["name"]), []).append(str(check.get("bucket")))
        pending, failing, missing = [], [], []
        for name in required:
            states = buckets.get(name)
            if not states:
                missing.append(name)
            elif any(state == "pending" for state in states):
                pending.append(name)
            elif any(state not in PASSING_BUCKETS for state in states):
                failing.append(name)
        return ChecksReport(
            not (pending or failing or missing), tuple(pending), tuple(failing),
            tuple(missing), tuple(required),
        )

    def merge_pr(self, number: int, *, head_sha: str, subject: str) -> None:
        """Merge with a merge commit, only if the PR head is still ``head_sha``."""

        self._run(("pr", "merge", str(number), "--repo", self.repo.slug, "--merge",
                   "--match-head-commit", head_sha, "--subject", subject))
