from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import importlib.util
import subprocess
import sys

import pytest

from milburn.runtime.worktrees import (
    GitWorktreeManager,
    PriorProcessState,
    WorktreeConflictError,
    WorktreeDirtyError,
    WorktreeLease,
    WorktreeOwnershipError,
    WorktreeProcessStateError,
    WorktreeRequest,
)


_FAKE_SPEC = importlib.util.spec_from_file_location(
    "milburn_test_fake_worktrees",
    Path(__file__).parents[2] / "fakes" / "worktrees.py",
)
assert _FAKE_SPEC is not None and _FAKE_SPEC.loader is not None
_fake_module = importlib.util.module_from_spec(_FAKE_SPEC)
sys.modules[_FAKE_SPEC.name] = _fake_module
_FAKE_SPEC.loader.exec_module(_fake_module)
FakeWorktreeManager = _fake_module.FakeWorktreeManager


def git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(directory), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repository"
    root = tmp_path / "worktrees"
    repo.mkdir()
    root.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Milburn Test")
    git(repo, "config", "user.email", "milburn-test@example.invalid")
    (repo / "README.md").write_text("fixture\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "fixture")
    return repo.resolve(), root.resolve(), git(repo, "rev-parse", "HEAD")


def request(repository: tuple[Path, Path, str], *, attempt: str = "a01") -> WorktreeRequest:
    repo, root, base = repository
    return WorktreeRequest(repo, root, "MB-009", 9, attempt, base)


def test_prepare_records_exact_branch_base_and_worktree(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()

    lease = manager.prepare(request(repository))
    inspection = manager.inspect(lease)

    assert lease.branch == "milburn/issue-9"
    assert lease.worktree == repository[1] / "issue-9-a01"
    assert lease.base_sha == repository[2]
    assert inspection.matched and inspection.clean is True
    assert inspection.head_sha == repository[2]
    assert git(lease.worktree, "branch", "--show-current") == lease.branch


def test_lease_is_strictly_serializable(repository: tuple[Path, Path, str]) -> None:
    lease = WorktreeLease.from_request(request(repository))

    assert WorktreeLease.from_dict(lease.to_dict()) == lease
    with pytest.raises(ValueError, match="fields"):
        WorktreeLease.from_dict({**lease.to_dict(), "unexpected": True})


@pytest.mark.parametrize("state", [PriorProcessState.RUNNING, PriorProcessState.UNKNOWN])
def test_resume_requires_prior_process_proven_stopped(
    repository: tuple[Path, Path, str], state: PriorProcessState
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))

    with pytest.raises(WorktreeProcessStateError, match="proven stopped"):
        manager.resume(lease, state)


def test_restart_registers_and_resumes_exact_lease(
    repository: tuple[Path, Path, str],
) -> None:
    original = GitWorktreeManager()
    lease = original.prepare(request(repository))
    recovered = GitWorktreeManager()

    registered = recovered.register(WorktreeLease.from_dict(lease.to_dict()))
    resumed = recovered.resume(lease, PriorProcessState.STOPPED)

    assert registered.matched
    assert resumed.matched


def test_restart_accepts_committed_progress_descending_from_recorded_base(
    repository: tuple[Path, Path, str],
) -> None:
    original = GitWorktreeManager()
    lease = original.prepare(request(repository))
    (lease.worktree / "progress.txt").write_text("checkpoint\n")
    git(lease.worktree, "add", "progress.txt")
    git(lease.worktree, "commit", "-m", "checkpoint")
    recovered = GitWorktreeManager()

    inspection = recovered.register(lease)

    assert inspection.head_sha != lease.base_sha
    assert recovered.resume(lease, PriorProcessState.STOPPED).matched


def test_restart_rejects_fabricated_durable_base(
    repository: tuple[Path, Path, str],
) -> None:
    original = GitWorktreeManager()
    lease = original.prepare(request(repository))
    fabricated = replace(lease, base_sha="0" * 40)

    with pytest.raises(WorktreeOwnershipError, match="exact repository commit"):
        GitWorktreeManager().register(fabricated)


def test_resume_preserves_and_reports_dirty_work(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    (lease.worktree / "unfinished.txt").write_text("preserve me\n")

    inspection = manager.resume(lease, PriorProcessState.STOPPED)

    assert inspection.matched
    assert inspection.clean is False
    assert (lease.worktree / "unfinished.txt").read_text() == "preserve me\n"


def test_detached_or_changed_identity_cannot_resume(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    git(lease.worktree, "checkout", "--detach")

    with pytest.raises(WorktreeOwnershipError, match="identity changed"):
        manager.resume(lease, PriorProcessState.STOPPED)


def test_simultaneous_mutating_ownership_is_rejected(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    manager.prepare(request(repository))

    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        manager.prepare(request(repository, attempt="a02"))


def test_existing_derived_path_is_never_reused(
    repository: tuple[Path, Path, str],
) -> None:
    requested = request(repository)
    requested.worktree.mkdir()

    with pytest.raises(WorktreeConflictError, match="already exists"):
        GitWorktreeManager().prepare(requested)


def test_existing_issue_branch_requires_recovery_not_recreation(
    repository: tuple[Path, Path, str],
) -> None:
    repo, _, base = repository
    git(repo, "branch", "milburn/issue-9", base)

    with pytest.raises(WorktreeConflictError, match="recover"):
        GitWorktreeManager().prepare(request(repository))


def test_dirty_worktree_cannot_be_retired(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    evidence = lease.worktree / "unfinished.txt"
    evidence.write_text("preserve me\n")

    with pytest.raises(WorktreeDirtyError, match="preserved"):
        manager.retire(lease, PriorProcessState.STOPPED)

    assert evidence.read_text() == "preserve me\n"
    assert manager.inspect(lease).registered


@pytest.mark.parametrize("state", [PriorProcessState.RUNNING, PriorProcessState.UNKNOWN])
def test_retirement_requires_prior_process_proven_stopped(
    repository: tuple[Path, Path, str], state: PriorProcessState
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))

    with pytest.raises(WorktreeProcessStateError, match="proven stopped"):
        manager.retire(lease, state)

    assert lease.worktree.exists()


def test_clean_retirement_removes_only_registered_path_and_preserves_branch(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    sibling = repository[1] / "operator-data"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("safe\n")

    retired = manager.retire(lease, PriorProcessState.STOPPED)

    assert not retired.registered
    assert not lease.worktree.exists()
    assert (sibling / "keep.txt").read_text() == "safe\n"
    assert git(repository[0], "show-ref", "--verify", f"refs/heads/{lease.branch}")


def test_forged_lease_path_is_rejected_before_any_operation(
    repository: tuple[Path, Path, str],
) -> None:
    lease = WorktreeLease.from_request(request(repository))

    with pytest.raises(ValueError, match="derived controller path"):
        replace(lease, worktree=repository[1] / "operator-data")


def test_request_rejects_relative_paths_and_abbreviated_sha(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        WorktreeRequest(Path("repo"), tmp_path.resolve(), "MB-009", 9, "a01", "a" * 40)
    with pytest.raises(ValueError, match="full lowercase"):
        WorktreeRequest(tmp_path.resolve(), tmp_path.resolve(), "MB-009", 9, "a01", "abc123")


def test_fake_matches_ownership_dirty_and_process_gates(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    lease = fake.prepare(request(repository))
    fake.set_dirty(lease)

    assert fake.resume(lease, PriorProcessState.STOPPED).clean is False
    with pytest.raises(WorktreeDirtyError):
        fake.retire(lease, PriorProcessState.STOPPED)
    with pytest.raises(WorktreeProcessStateError):
        fake.resume(lease, PriorProcessState.UNKNOWN)
    assert fake.actions == [("prepare", "a01"), ("resume", "a01")]
