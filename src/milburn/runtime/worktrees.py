"""Validated Git worktree ownership for mutating Coder attempts.

The manager deliberately exposes leases rather than arbitrary filesystem paths.
Every destructive operation revalidates the immutable lease against Git's
worktree registry and requires an explicit, observed process state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Protocol

from .processes import CommandResult, CommandRunner, SubprocessCommandRunner


_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class WorktreeError(RuntimeError):
    """Base class for explicit worktree-boundary failures."""


class WorktreeValidationError(WorktreeError):
    pass


class WorktreeConflictError(WorktreeError):
    pass


class WorktreeCommandError(WorktreeError):
    pass


class WorktreeOwnershipError(WorktreeError):
    pass


class WorktreeProcessStateError(WorktreeError):
    pass


class WorktreeDirtyError(WorktreeError):
    pass


class WorktreePostconditionError(WorktreeError):
    pass


class PriorProcessState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


def _validate_component(value: str, field: str) -> None:
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value):
        raise ValueError(f"{field} must be a safe non-empty identifier")


def _validate_absolute_normal_path(path: Path, field: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError(f"{field} must be an absolute Path")
    if path != path.resolve(strict=False):
        raise ValueError(f"{field} must be normalized and contain no symlink components")


@dataclass(frozen=True, slots=True)
class WorktreeRequest:
    repository: Path
    worktree_root: Path
    task_id: str
    issue_number: int
    attempt_id: str
    base_sha: str

    def __post_init__(self) -> None:
        _validate_absolute_normal_path(self.repository, "repository")
        _validate_absolute_normal_path(self.worktree_root, "worktree_root")
        _validate_component(self.task_id, "task_id")
        _validate_component(self.attempt_id, "attempt_id")
        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            raise ValueError("issue_number must be an integer")
        if self.issue_number <= 0:
            raise ValueError("issue_number must be positive")
        if not isinstance(self.base_sha, str) or not _SHA.fullmatch(self.base_sha):
            raise ValueError("base_sha must be a full lowercase commit SHA")

    @property
    def branch(self) -> str:
        return f"milburn/issue-{self.issue_number}"

    @property
    def worktree(self) -> Path:
        return self.worktree_root / f"issue-{self.issue_number}-{self.attempt_id}"


@dataclass(frozen=True, slots=True)
class WorktreeLease:
    repository: Path
    worktree_root: Path
    worktree: Path
    task_id: str
    issue_number: int
    attempt_id: str
    branch: str
    base_sha: str

    def __post_init__(self) -> None:
        request = WorktreeRequest(
            repository=self.repository,
            worktree_root=self.worktree_root,
            task_id=self.task_id,
            issue_number=self.issue_number,
            attempt_id=self.attempt_id,
            base_sha=self.base_sha,
        )
        if self.worktree != request.worktree:
            raise ValueError("worktree does not match the derived controller path")
        if self.branch != request.branch:
            raise ValueError("branch does not match the issue branch")

    @classmethod
    def from_request(cls, request: WorktreeRequest) -> WorktreeLease:
        return cls(
            repository=request.repository,
            worktree_root=request.worktree_root,
            worktree=request.worktree,
            task_id=request.task_id,
            issue_number=request.issue_number,
            attempt_id=request.attempt_id,
            branch=request.branch,
            base_sha=request.base_sha,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": str(self.repository),
            "worktree_root": str(self.worktree_root),
            "worktree": str(self.worktree),
            "task_id": self.task_id,
            "issue_number": self.issue_number,
            "attempt_id": self.attempt_id,
            "branch": self.branch,
            "base_sha": self.base_sha,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> WorktreeLease:
        expected = {
            "repository", "worktree_root", "worktree", "task_id",
            "issue_number", "attempt_id", "branch", "base_sha",
        }
        if set(value) != expected:
            raise ValueError("invalid worktree lease fields")
        path_fields = ("repository", "worktree_root", "worktree")
        string_fields = ("task_id", "attempt_id", "branch", "base_sha")
        if any(not isinstance(value[field], str) for field in path_fields + string_fields):
            raise ValueError("worktree lease strings are invalid")
        issue_number = value["issue_number"]
        if not isinstance(issue_number, int) or isinstance(issue_number, bool):
            raise ValueError("issue_number must be an integer")
        return cls(
            repository=Path(value["repository"]),  # type: ignore[arg-type]
            worktree_root=Path(value["worktree_root"]),  # type: ignore[arg-type]
            worktree=Path(value["worktree"]),  # type: ignore[arg-type]
            task_id=value["task_id"],  # type: ignore[arg-type]
            issue_number=issue_number,
            attempt_id=value["attempt_id"],  # type: ignore[arg-type]
            branch=value["branch"],  # type: ignore[arg-type]
            base_sha=value["base_sha"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class WorktreeInspection:
    lease: WorktreeLease
    registered: bool
    path_exists: bool
    branch: str | None
    head_sha: str | None
    clean: bool | None

    @property
    def matched(self) -> bool:
        return (
            self.registered
            and self.path_exists
            and self.branch == self.lease.branch
            and self.head_sha is not None
        )


class WorktreeManagerProtocol(Protocol):
    def prepare(self, request: WorktreeRequest) -> WorktreeLease: ...
    def register(self, lease: WorktreeLease) -> WorktreeInspection: ...
    def inspect(self, lease: WorktreeLease) -> WorktreeInspection: ...
    def resume(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection: ...
    def retire(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection: ...


@dataclass(frozen=True, slots=True)
class _GitWorktree:
    path: Path
    head_sha: str
    branch: str | None


class GitWorktreeManager:
    """Create, recover, and safely retire controller-owned Git worktrees."""

    def __init__(self, runner: CommandRunner | None = None, *, git_binary: str = "git") -> None:
        self._runner = runner or SubprocessCommandRunner()
        self._git_binary = git_binary
        self._leases: dict[Path, WorktreeLease] = {}
        self._retired: dict[Path, WorktreeLease] = {}

    def prepare(self, request: WorktreeRequest) -> WorktreeLease:
        self._validate_request_filesystem(request)
        lease = WorktreeLease.from_request(request)
        self._ensure_no_ownership_conflict(lease)
        if lease.worktree.exists() or lease.worktree.is_symlink():
            raise WorktreeConflictError("derived worktree path already exists")
        base = self._git(
            request.repository, "rev-parse", "--verify", f"{request.base_sha}^{{commit}}"
        )
        if base.returncode or base.stdout.strip() != request.base_sha:
            raise WorktreeValidationError("base_sha is not the exact repository commit")
        branch_ref = f"refs/heads/{request.branch}"
        branch = self._git(request.repository, "show-ref", "--verify", "--quiet", branch_ref)
        if branch.returncode == 0:
            raise WorktreeConflictError("issue branch already exists; recover it instead")
        if branch.returncode != 1:
            raise WorktreeCommandError(branch.stderr.strip() or "could not inspect issue branch")

        created = self._git(
            request.repository,
            "worktree", "add", "-b", request.branch,
            str(request.worktree), request.base_sha,
        )
        if created.returncode:
            raise WorktreeCommandError(created.stderr.strip() or "git worktree add failed")

        # Retain ownership even if postcondition inspection fails: the external
        # effect happened and must be reconciled rather than blindly retried.
        self._leases[lease.worktree] = lease
        inspection = self._inspect_lease(lease)
        if (
            not inspection.matched
            or inspection.branch != lease.branch
            or inspection.head_sha != lease.base_sha
            or inspection.clean is not True
        ):
            raise WorktreePostconditionError("created worktree failed identity postconditions")
        return lease

    def register(self, lease: WorktreeLease) -> WorktreeInspection:
        """Restore an immutable lease from durable state after controller restart."""

        self._validate_lease_filesystem(lease)
        self._ensure_no_ownership_conflict(lease)
        inspection = self._inspect_lease(lease)
        if not inspection.matched or inspection.branch != lease.branch:
            raise WorktreeOwnershipError("durable lease does not match Git worktree identity")
        self._leases[lease.worktree] = lease
        return inspection

    def inspect(self, lease: WorktreeLease) -> WorktreeInspection:
        self._require_owned(lease)
        return self._inspect_lease(lease)

    def resume(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        self._require_owned(lease)
        inspection = self._inspect_lease(lease)
        if not inspection.matched or inspection.branch != lease.branch:
            raise WorktreeOwnershipError("worktree identity changed before resume")
        return inspection

    def retire(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        if self._retired.get(lease.worktree) == lease:
            return self._inspect_lease(lease)
        self._require_owned(lease)
        inspection = self._inspect_lease(lease)
        if not inspection.matched or inspection.branch != lease.branch:
            raise WorktreeOwnershipError("worktree identity changed before retirement")
        if inspection.clean is not True:
            raise WorktreeDirtyError("dirty worktree evidence must be preserved")
        removed = self._git(lease.repository, "worktree", "remove", "--", str(lease.worktree))
        if removed.returncode:
            raise WorktreeCommandError(removed.stderr.strip() or "git worktree remove failed")
        after = self._inspect_lease(lease)
        if after.registered or after.path_exists:
            raise WorktreePostconditionError("worktree removal postcondition was not observed")
        self._leases.pop(lease.worktree)
        self._retired[lease.worktree] = lease
        return after

    def _validate_request_filesystem(self, request: WorktreeRequest) -> None:
        if request.repository.is_symlink() or not request.repository.is_dir():
            raise WorktreeValidationError("repository must be an existing real directory")
        if request.worktree_root.is_symlink() or not request.worktree_root.is_dir():
            raise WorktreeValidationError("worktree_root must be an existing real directory")
        top = self._git(request.repository, "rev-parse", "--show-toplevel")
        if top.returncode:
            raise WorktreeValidationError("repository is not a Git worktree")
        try:
            observed = Path(top.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise WorktreeValidationError("repository top-level path is invalid") from error
        if observed != request.repository:
            raise WorktreeValidationError("repository must name the exact Git top level")

    def _validate_lease_filesystem(self, lease: WorktreeLease) -> None:
        request = WorktreeRequest(
            repository=lease.repository,
            worktree_root=lease.worktree_root,
            task_id=lease.task_id,
            issue_number=lease.issue_number,
            attempt_id=lease.attempt_id,
            base_sha=lease.base_sha,
        )
        self._validate_request_filesystem(request)

    def _ensure_no_ownership_conflict(self, lease: WorktreeLease) -> None:
        current = self._leases.get(lease.worktree)
        if current is not None and current != lease:
            raise WorktreeConflictError("worktree path is owned by another attempt")
        for active in self._leases.values():
            if active == lease:
                continue
            if active.repository == lease.repository and active.branch == lease.branch:
                raise WorktreeConflictError("issue branch already has mutating ownership")

    def _require_owned(self, lease: WorktreeLease) -> None:
        if self._leases.get(lease.worktree) != lease:
            raise WorktreeOwnershipError("worktree lease is not active in this controller")

    @staticmethod
    def _require_stopped(prior_process: PriorProcessState) -> None:
        if prior_process is not PriorProcessState.STOPPED:
            raise WorktreeProcessStateError("prior process must be proven stopped")

    def _inspect_lease(self, lease: WorktreeLease) -> WorktreeInspection:
        entries = self._list_worktrees(lease.repository)
        entry = next((item for item in entries if item.path == lease.worktree), None)
        if entry is None:
            return WorktreeInspection(
                lease=lease,
                registered=False,
                path_exists=lease.worktree.exists() or lease.worktree.is_symlink(),
                branch=None,
                head_sha=None,
                clean=None,
            )
        if not lease.worktree.is_dir() or lease.worktree.is_symlink():
            return WorktreeInspection(lease, True, False, entry.branch, entry.head_sha, None)
        status = self._git(lease.worktree, "status", "--porcelain", "--untracked-files=all")
        if status.returncode:
            raise WorktreeCommandError(status.stderr.strip() or "git status failed")
        return WorktreeInspection(
            lease=lease,
            registered=True,
            path_exists=True,
            branch=entry.branch,
            head_sha=entry.head_sha,
            clean=not bool(status.stdout),
        )

    def _list_worktrees(self, repository: Path) -> tuple[_GitWorktree, ...]:
        result = self._git(repository, "worktree", "list", "--porcelain")
        if result.returncode:
            raise WorktreeCommandError(result.stderr.strip() or "git worktree list failed")
        entries: list[_GitWorktree] = []
        fields: dict[str, str] = {}
        for line in (*result.stdout.splitlines(), ""):
            if not line:
                if fields:
                    path = fields.get("worktree")
                    head = fields.get("HEAD")
                    if path is None or head is None:
                        raise WorktreePostconditionError("malformed Git worktree record")
                    branch_ref = fields.get("branch")
                    branch = (
                        branch_ref.removeprefix("refs/heads/")
                        if branch_ref is not None
                        else None
                    )
                    entries.append(_GitWorktree(Path(path).resolve(strict=False), head, branch))
                    fields = {}
                continue
            key, _, value = line.partition(" ")
            fields[key] = value
        return tuple(entries)

    def _git(self, directory: Path, *arguments: str) -> CommandResult:
        return self._runner.run((self._git_binary, "-C", str(directory), *arguments))
