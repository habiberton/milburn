"""Deterministic in-memory fake for the public worktree-manager boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from milburn.runtime.worktrees import (
    PriorProcessState,
    WorktreeConflictError,
    WorktreeDirtyError,
    WorktreeInspection,
    WorktreeLease,
    WorktreeOwnershipError,
    WorktreeProcessStateError,
    WorktreeRequest,
)


@dataclass(frozen=True, slots=True)
class _FakeWorkspace:
    branch: str
    head_sha: str
    ancestors: frozenset[str]


class FakeWorktreeManager:
    def __init__(self) -> None:
        self._active: dict[Path, WorktreeLease] = {}
        self._retired: dict[Path, WorktreeLease] = {}
        self._workspaces: dict[Path, _FakeWorkspace] = {}
        self._branches: dict[tuple[Path, str], _FakeWorkspace] = {}
        self._dirty: set[Path] = set()
        self.actions: list[tuple[str, str]] = []

    def prepare(self, request: WorktreeRequest) -> WorktreeLease:
        lease = WorktreeLease.from_request(request)
        self._ensure_no_ownership_conflict(lease)
        if lease.worktree in self._workspaces:
            raise WorktreeConflictError("worktree path already exists")
        key = (lease.repository, lease.branch)
        branch = self._branches.get(key)
        if branch is None:
            workspace = _FakeWorkspace(
                lease.branch, lease.base_sha, frozenset({lease.base_sha})
            )
        else:
            retired = [
                prior
                for prior in self._retired.values()
                if prior.repository == lease.repository and prior.branch == lease.branch
            ]
            if not retired:
                raise WorktreeConflictError("issue branch already exists; recover it instead")
            if any(item.branch == lease.branch for item in self._workspaces.values()):
                raise WorktreeConflictError("issue branch is still attached to another worktree")
            if branch.head_sha != lease.base_sha:
                raise WorktreeConflictError(
                    "next attempt base must equal the preserved issue branch head"
                )
            workspace = branch
        self._workspaces[lease.worktree] = workspace
        self._branches[key] = workspace
        self._active[lease.worktree] = lease
        self.actions.append(("prepare", lease.attempt_id))
        return lease

    def register(self, lease: WorktreeLease) -> WorktreeInspection:
        self._ensure_no_ownership_conflict(lease)
        if lease.worktree not in self._workspaces:
            raise WorktreeOwnershipError("durable worktree is missing")
        inspection = self._inspect_raw(lease)
        self._validate_base_ancestry(lease, inspection)
        self._active[lease.worktree] = lease
        self.actions.append(("register", lease.attempt_id))
        return inspection

    def register_retired(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        self._ensure_no_ownership_conflict(lease)
        inspection = self._inspect_raw(lease)
        if inspection.registered or inspection.path_exists:
            raise WorktreeOwnershipError("retired worktree path is still present")
        if any(item.branch == lease.branch for item in self._workspaces.values()):
            raise WorktreeOwnershipError("retired issue branch is still attached")
        branch = self._branches.get((lease.repository, lease.branch))
        if branch is None or lease.base_sha not in branch.ancestors:
            raise WorktreeOwnershipError("recorded base is not an exact repository commit")
        self._retired[lease.worktree] = lease
        self.actions.append(("register_retired", lease.attempt_id))
        return inspection

    def inspect(self, lease: WorktreeLease) -> WorktreeInspection:
        self._require_owned(lease)
        return self._inspect_raw(lease)

    def resume(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        inspection = self.inspect(lease)
        if not inspection.matched:
            raise WorktreeOwnershipError("worktree identity changed before resume")
        self._validate_base_ancestry(lease, inspection)
        self.actions.append(("resume", lease.attempt_id))
        return inspection

    def retire(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        if self._retired.get(lease.worktree) == lease:
            return self._inspect_raw(lease)
        inspection = self.inspect(lease)
        self._validate_base_ancestry(lease, inspection)
        if inspection.clean is not True:
            raise WorktreeDirtyError("dirty worktree evidence must be preserved")
        workspace = self._workspaces.pop(lease.worktree)
        self._branches[(lease.repository, lease.branch)] = workspace
        self._active.pop(lease.worktree)
        self._retired[lease.worktree] = lease
        self.actions.append(("retire", lease.attempt_id))
        return WorktreeInspection(lease, False, False, None, None, None)

    def set_dirty(self, lease: WorktreeLease, dirty: bool = True) -> None:
        self._require_owned(lease)
        if dirty:
            self._dirty.add(lease.worktree)
        else:
            self._dirty.discard(lease.worktree)

    def remove_externally(self, lease: WorktreeLease) -> None:
        self._require_owned(lease)
        self._workspaces.pop(lease.worktree, None)

    def seed_existing(
        self,
        lease: WorktreeLease,
        *,
        head_sha: str | None = None,
        ancestors: tuple[str, ...] = (),
    ) -> None:
        """Seed external Git state without granting controller ownership."""

        head = head_sha or lease.base_sha
        workspace = _FakeWorkspace(
            lease.branch,
            head,
            frozenset({head, lease.base_sha, *ancestors}),
        )
        self._workspaces[lease.worktree] = workspace
        self._branches[(lease.repository, lease.branch)] = workspace

    def seed_preserved_branch(
        self,
        lease: WorktreeLease,
        *,
        head_sha: str | None = None,
        ancestors: tuple[str, ...] = (),
    ) -> None:
        """Seed a branch whose prior controller-created path is absent."""

        head = head_sha or lease.base_sha
        self._branches[(lease.repository, lease.branch)] = _FakeWorkspace(
            lease.branch,
            head,
            frozenset({head, lease.base_sha, *ancestors}),
        )

    def _inspect_raw(self, lease: WorktreeLease) -> WorktreeInspection:
        workspace = self._workspaces.get(lease.worktree)
        if workspace is None:
            return WorktreeInspection(lease, False, False, None, None, None)
        return WorktreeInspection(
            lease=lease,
            registered=True,
            path_exists=True,
            branch=workspace.branch,
            head_sha=workspace.head_sha,
            clean=lease.worktree not in self._dirty,
        )

    def _ensure_no_ownership_conflict(self, lease: WorktreeLease) -> None:
        active = self._active.get(lease.worktree)
        if active is not None and active != lease:
            raise WorktreeConflictError("worktree path has another owner")
        for current in self._active.values():
            if current == lease:
                continue
            if current.repository == lease.repository and current.branch == lease.branch:
                raise WorktreeConflictError("issue branch already has mutating ownership")

    def _validate_base_ancestry(
        self, lease: WorktreeLease, inspection: WorktreeInspection
    ) -> None:
        if inspection.head_sha is None:
            raise WorktreeOwnershipError("worktree has no observable head commit")
        workspace = self._workspaces.get(lease.worktree)
        if workspace is None or lease.base_sha not in workspace.ancestors:
            raise WorktreeOwnershipError("recorded base is not an exact repository commit")

    def _require_owned(self, lease: WorktreeLease) -> None:
        if self._active.get(lease.worktree) != lease:
            raise WorktreeOwnershipError("worktree lease is not active")

    @staticmethod
    def _require_stopped(prior_process: PriorProcessState) -> None:
        if prior_process is not PriorProcessState.STOPPED:
            raise WorktreeProcessStateError("prior process must be proven stopped")
