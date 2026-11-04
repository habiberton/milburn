"""Deterministic in-memory fake for the public worktree-manager boundary."""

from __future__ import annotations

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


class FakeWorktreeManager:
    def __init__(self) -> None:
        self._active: dict[object, WorktreeLease] = {}
        self._dirty: set[object] = set()
        self._missing: set[object] = set()
        self.actions: list[tuple[str, str]] = []

    def prepare(self, request: WorktreeRequest) -> WorktreeLease:
        lease = WorktreeLease.from_request(request)
        for active in self._active.values():
            if active.repository == lease.repository and active.branch == lease.branch:
                raise WorktreeConflictError("issue branch already has mutating ownership")
        if lease.worktree in self._active:
            raise WorktreeConflictError("worktree path already exists")
        self._active[lease.worktree] = lease
        self.actions.append(("prepare", lease.attempt_id))
        return lease

    def register(self, lease: WorktreeLease) -> WorktreeInspection:
        active = self._active.get(lease.worktree)
        if active is not None and active != lease:
            raise WorktreeConflictError("worktree path has another owner")
        if lease.worktree in self._missing:
            raise WorktreeOwnershipError("durable worktree is missing")
        self._active[lease.worktree] = lease
        self.actions.append(("register", lease.attempt_id))
        return self.inspect(lease)

    def inspect(self, lease: WorktreeLease) -> WorktreeInspection:
        self._require_owned(lease)
        exists = lease.worktree not in self._missing
        return WorktreeInspection(
            lease=lease,
            registered=exists,
            path_exists=exists,
            branch=lease.branch if exists else None,
            head_sha=lease.base_sha if exists else None,
            clean=lease.worktree not in self._dirty if exists else None,
        )

    def resume(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        inspection = self.inspect(lease)
        if not inspection.matched:
            raise WorktreeOwnershipError("worktree identity changed before resume")
        self.actions.append(("resume", lease.attempt_id))
        return inspection

    def retire(
        self, lease: WorktreeLease, prior_process: PriorProcessState
    ) -> WorktreeInspection:
        self._require_stopped(prior_process)
        inspection = self.inspect(lease)
        if inspection.clean is not True:
            raise WorktreeDirtyError("dirty worktree evidence must be preserved")
        self._missing.add(lease.worktree)
        self._active.pop(lease.worktree)
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
        self._missing.add(lease.worktree)

    def _require_owned(self, lease: WorktreeLease) -> None:
        if self._active.get(lease.worktree) != lease:
            raise WorktreeOwnershipError("worktree lease is not active")

    @staticmethod
    def _require_stopped(prior_process: PriorProcessState) -> None:
        if prior_process is not PriorProcessState.STOPPED:
            raise WorktreeProcessStateError("prior process must be proven stopped")
