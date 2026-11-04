"""Deterministic in-memory fake for the public worktree-manager boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from milburn.runtime.worktrees import (
    PriorProcessState,
    RetiredWorktreeEvidence,
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
    ancestry: frozenset[tuple[str, str]]


class FakeWorktreeManager:
    def __init__(self) -> None:
        self._active: dict[Path, WorktreeLease] = {}
        self._retired: dict[Path, RetiredWorktreeEvidence] = {}
        self._retired_branches: dict[
            tuple[Path, str], RetiredWorktreeEvidence
        ] = {}
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
                lease.branch,
                lease.base_sha,
                frozenset({(lease.base_sha, lease.base_sha)}),
            )
        else:
            evidence = self._retired_branches.get((lease.repository, lease.branch))
            if evidence is None:
                raise WorktreeConflictError("issue branch already exists; recover it instead")
            if any(item.branch == lease.branch for item in self._workspaces.values()):
                raise WorktreeConflictError("issue branch is still attached to another worktree")
            if branch.head_sha != lease.base_sha:
                raise WorktreeConflictError(
                    "next attempt base must equal the preserved issue branch head"
                )
            if not self._is_ancestor(branch, evidence.head_sha, branch.head_sha):
                raise WorktreeOwnershipError(
                    "preserved branch no longer descends from retired worktree head"
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
        self, evidence: RetiredWorktreeEvidence, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        lease = evidence.lease
        self._require_stopped(prior_process)
        self._ensure_no_ownership_conflict(lease)
        inspection = self._inspect_raw(lease)
        if inspection.registered or inspection.path_exists:
            raise WorktreeOwnershipError("retired worktree path is still present")
        if any(item.branch == lease.branch for item in self._workspaces.values()):
            raise WorktreeOwnershipError("retired issue branch is still attached")
        branch = self._branches.get((lease.repository, lease.branch))
        if branch is None:
            raise WorktreeOwnershipError("preserved issue branch is unavailable")
        if not self._is_ancestor(branch, lease.base_sha, evidence.head_sha):
            raise WorktreeOwnershipError(
                "retired worktree head no longer descends from recorded base"
            )
        if not self._is_ancestor(branch, evidence.head_sha, branch.head_sha):
            raise WorktreeOwnershipError(
                "preserved branch no longer descends from retired worktree head"
            )
        self._retired[lease.worktree] = evidence
        self._retired_branches[(lease.repository, lease.branch)] = evidence
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
    ) -> RetiredWorktreeEvidence:
        self._require_stopped(prior_process)
        retired = self._retired.get(lease.worktree)
        if retired is not None and retired.lease == lease:
            return retired
        inspection = self.inspect(lease)
        self._validate_base_ancestry(lease, inspection)
        if inspection.clean is not True:
            raise WorktreeDirtyError("dirty worktree evidence must be preserved")
        workspace = self._workspaces.pop(lease.worktree)
        evidence = RetiredWorktreeEvidence(lease, workspace.head_sha)
        self._branches[(lease.repository, lease.branch)] = workspace
        self._active.pop(lease.worktree)
        self._retired[lease.worktree] = evidence
        self._retired_branches[(lease.repository, lease.branch)] = evidence
        self.actions.append(("retire", lease.attempt_id))
        return evidence

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
        ancestors: tuple[str, ...] | None = None,
        relations: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Seed external Git state without granting controller ownership."""

        head = head_sha or lease.base_sha
        workspace = _FakeWorkspace(
            lease.branch,
            head,
            self._ancestry(
                head,
                ancestors if ancestors is not None else (lease.base_sha,),
                relations,
            ),
        )
        self._workspaces[lease.worktree] = workspace
        self._branches[(lease.repository, lease.branch)] = workspace

    def seed_preserved_branch(
        self,
        lease: WorktreeLease,
        *,
        head_sha: str | None = None,
        ancestors: tuple[str, ...] | None = None,
        relations: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Seed a branch whose prior controller-created path is absent."""

        head = head_sha or lease.base_sha
        self._branches[(lease.repository, lease.branch)] = _FakeWorkspace(
            lease.branch,
            head,
            self._ancestry(
                head,
                ancestors if ancestors is not None else (lease.base_sha,),
                relations,
            ),
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
        if (
            workspace is None
            or not self._is_ancestor(workspace, lease.base_sha, inspection.head_sha)
        ):
            raise WorktreeOwnershipError("recorded base is not an exact repository commit")

    @staticmethod
    def _ancestry(
        head_sha: str,
        ancestors: tuple[str, ...],
        relations: tuple[tuple[str, str], ...],
    ) -> frozenset[tuple[str, str]]:
        commits = {head_sha, *ancestors}
        for ancestor, descendant in relations:
            commits.add(ancestor)
            commits.add(descendant)
        closure = {(commit, commit) for commit in commits}
        closure.update((ancestor, head_sha) for ancestor in ancestors)
        closure.update(relations)
        changed = True
        while changed:
            changed = False
            additions = {
                (left, right)
                for left, middle in closure
                for candidate, right in closure
                if middle == candidate and (left, right) not in closure
            }
            if additions:
                closure.update(additions)
                changed = True
        return frozenset(closure)

    @staticmethod
    def _is_ancestor(
        workspace: _FakeWorkspace, ancestor_sha: str, descendant_sha: str
    ) -> bool:
        return (ancestor_sha, descendant_sha) in workspace.ancestry

    def _require_owned(self, lease: WorktreeLease) -> None:
        if self._active.get(lease.worktree) != lease:
            raise WorktreeOwnershipError("worktree lease is not active")

    @staticmethod
    def _require_stopped(prior_process: PriorProcessState) -> None:
        if prior_process is not PriorProcessState.STOPPED:
            raise WorktreeProcessStateError("prior process must be proven stopped")
