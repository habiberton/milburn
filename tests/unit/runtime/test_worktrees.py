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
    RetiredWorktreeEvidence,
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


def create_repository(tmp_path: Path, name: str) -> tuple[Path, Path, str]:
    repo = tmp_path / name
    root = tmp_path / f"{name}-worktrees"
    repo.mkdir()
    root.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Milburn Test")
    git(repo, "config", "user.email", "milburn-test@example.invalid")
    (repo / "README.md").write_text("fixture\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "fixture")
    return repo.resolve(), root.resolve(), git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path, str]:
    return create_repository(tmp_path, "repository")


def request(
    repository: tuple[Path, Path, str],
    *,
    attempt: str = "a01",
    base: str | None = None,
) -> WorktreeRequest:
    repo, root, initial_base = repository
    return WorktreeRequest(repo, root, "MB-009", 9, attempt, base or initial_base)


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

    assert retired.lease == lease
    assert retired.head_sha == lease.base_sha
    assert not lease.worktree.exists()
    assert (sibling / "keep.txt").read_text() == "safe\n"
    assert git(repository[0], "show-ref", "--verify", f"refs/heads/{lease.branch}")


def test_clean_retirement_allows_new_attempt_on_preserved_branch(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    first = manager.prepare(request(repository))
    manager.retire(first, PriorProcessState.STOPPED)

    second = manager.prepare(request(repository, attempt="a02"))

    assert second.worktree != first.worktree
    assert second.branch == first.branch
    assert manager.inspect(second).head_sha == first.base_sha
    assert not first.worktree.exists()
    assert second.worktree.exists()


def test_next_attempt_must_record_preserved_branch_head_as_its_base(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    first = manager.prepare(request(repository))
    (first.worktree / "change.txt").write_text("candidate\n")
    git(first.worktree, "add", "change.txt")
    git(first.worktree, "commit", "-m", "candidate")
    branch_head = git(first.worktree, "rev-parse", "HEAD")
    manager.retire(first, PriorProcessState.STOPPED)

    with pytest.raises(WorktreeConflictError, match="base must equal"):
        manager.prepare(request(repository, attempt="a02"))

    second = manager.prepare(request(repository, attempt="a02", base=branch_head))
    assert manager.inspect(second).head_sha == branch_head


def test_retired_lease_can_be_recovered_before_next_attempt(
    repository: tuple[Path, Path, str],
) -> None:
    original = GitWorktreeManager()
    first = original.prepare(request(repository))
    evidence = original.retire(first, PriorProcessState.STOPPED)
    recovered = GitWorktreeManager()

    observation = recovered.register_retired(evidence, PriorProcessState.STOPPED)
    second = recovered.prepare(request(repository, attempt="a02"))

    assert not observation.registered
    assert recovered.inspect(second).matched


def test_duplicate_clean_retirement_is_idempotent(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))

    first = manager.retire(lease, PriorProcessState.STOPPED)
    duplicate = manager.retire(lease, PriorProcessState.STOPPED)

    assert first == duplicate


def test_older_retired_evidence_cannot_replace_newer_attempt_history(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    first = manager.prepare(request(repository))
    stale = manager.retire(first, PriorProcessState.STOPPED)
    second = manager.prepare(request(repository, attempt="a02"))
    (second.worktree / "second.txt").write_text("newer attempt\n")
    git(second.worktree, "add", "second.txt")
    git(second.worktree, "commit", "-m", "newer attempt")
    manager.retire(second, PriorProcessState.STOPPED)

    with pytest.raises(WorktreeConflictError, match="newer retirement"):
        manager.register_retired(stale, PriorProcessState.STOPPED)


def test_recovered_stale_evidence_cannot_bypass_missing_later_attempt(
    repository: tuple[Path, Path, str],
) -> None:
    original = GitWorktreeManager()
    first = original.prepare(request(repository))
    stale = original.retire(first, PriorProcessState.STOPPED)
    recovered = GitWorktreeManager()
    recovered.register_retired(stale, PriorProcessState.STOPPED)
    second = recovered.prepare(request(repository, attempt="a02"))
    git(repository[0], "worktree", "remove", "--", str(second.worktree))

    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        recovered.register_retired(stale, PriorProcessState.STOPPED)
    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        recovered.prepare(request(repository, attempt="a03"))


def test_deleted_preserved_branch_is_not_recreated(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    first = manager.prepare(request(repository))
    manager.retire(first, PriorProcessState.STOPPED)
    git(repository[0], "branch", "-D", first.branch)
    second_request = request(repository, attempt="a02")

    with pytest.raises(WorktreeOwnershipError, match="preserved issue branch"):
        manager.prepare(second_request)

    assert not second_request.worktree.exists()


def test_duplicate_retirement_detects_deleted_preserved_branch(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    manager.retire(lease, PriorProcessState.STOPPED)
    git(repository[0], "branch", "-D", lease.branch)

    with pytest.raises(WorktreeOwnershipError, match="preserved issue branch"):
        manager.retire(lease, PriorProcessState.STOPPED)


def test_retired_lease_cannot_be_prepared_again(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    manager.retire(lease, PriorProcessState.STOPPED)

    with pytest.raises(WorktreeOwnershipError, match="already retired"):
        manager.prepare(request(repository))

    assert not lease.worktree.exists()


def test_duplicate_retirement_rejects_externally_reappearing_path(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    lease = manager.prepare(request(repository))
    manager.retire(lease, PriorProcessState.STOPPED)
    lease.worktree.mkdir()

    with pytest.raises(WorktreeOwnershipError, match="retired worktree path"):
        manager.retire(lease, PriorProcessState.STOPPED)

    assert lease.worktree.is_dir()


def test_retired_evidence_is_strictly_serializable(
    repository: tuple[Path, Path, str],
) -> None:
    lease = WorktreeLease.from_request(request(repository))
    evidence = RetiredWorktreeEvidence(lease, lease.base_sha)

    assert RetiredWorktreeEvidence.from_dict(evidence.to_dict()) == evidence
    with pytest.raises(ValueError, match="fields"):
        RetiredWorktreeEvidence.from_dict({**evidence.to_dict(), "extra": True})


def test_force_moved_preserved_branch_cannot_authorize_later_attempt(
    repository: tuple[Path, Path, str],
) -> None:
    manager = GitWorktreeManager()
    first = manager.prepare(request(repository))
    evidence = manager.retire(first, PriorProcessState.STOPPED)
    tree = git(repository[0], "rev-parse", f"{first.base_sha}^{{tree}}")
    unrelated = git(repository[0], "commit-tree", tree, "-m", "unrelated")
    git(repository[0], "branch", "-f", first.branch, unrelated)
    second_request = request(repository, attempt="a02", base=unrelated)

    with pytest.raises(WorktreeOwnershipError, match="retired worktree head"):
        manager.prepare(second_request)
    with pytest.raises(WorktreeOwnershipError, match="retired worktree head"):
        GitWorktreeManager().register_retired(evidence, PriorProcessState.STOPPED)

    assert not second_request.worktree.exists()


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


def test_fake_rejects_same_branch_registration_with_active_owner(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    fake.prepare(request(repository))
    conflicting = WorktreeLease.from_request(request(repository, attempt="a02"))

    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        fake.register(conflicting)


def test_fake_recovery_rejects_fabricated_base_like_real_manager(
    repository: tuple[Path, Path, str],
) -> None:
    lease = WorktreeLease.from_request(request(repository))
    fake = FakeWorktreeManager()
    fake.seed_existing(lease)
    fabricated = replace(lease, base_sha="0" * 40)

    with pytest.raises(WorktreeOwnershipError, match="exact repository commit"):
        fake.register(fabricated)


def test_fake_matches_later_attempt_and_duplicate_retirement(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    first = fake.prepare(request(repository))

    retired = fake.retire(first, PriorProcessState.STOPPED)
    duplicate = fake.retire(first, PriorProcessState.STOPPED)
    second = fake.prepare(request(repository, attempt="a02"))

    assert retired == duplicate
    assert second.worktree != first.worktree
    assert fake.inspect(second).matched


def test_fake_older_retired_evidence_cannot_replace_newer_attempt_history(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    first = fake.prepare(request(repository))
    stale = fake.retire(first, PriorProcessState.STOPPED)
    second = fake.prepare(request(repository, attempt="a02"))
    fake.retire(second, PriorProcessState.STOPPED)

    with pytest.raises(WorktreeConflictError, match="newer retirement"):
        fake.register_retired(stale, PriorProcessState.STOPPED)


def test_fake_recovered_stale_evidence_cannot_bypass_missing_later_attempt(
    repository: tuple[Path, Path, str],
) -> None:
    first = WorktreeLease.from_request(request(repository))
    fake = FakeWorktreeManager()
    fake.seed_preserved_branch(first)
    stale = RetiredWorktreeEvidence(first, first.base_sha)
    fake.register_retired(stale, PriorProcessState.STOPPED)
    second = fake.prepare(request(repository, attempt="a02"))
    fake.remove_externally(second)

    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        fake.register_retired(stale, PriorProcessState.STOPPED)
    with pytest.raises(WorktreeConflictError, match="mutating ownership"):
        fake.prepare(request(repository, attempt="a03"))


def test_fake_deleted_preserved_branch_is_not_recreated(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    first = fake.prepare(request(repository))
    fake.retire(first, PriorProcessState.STOPPED)
    fake.remove_preserved_branch_externally(first)

    with pytest.raises(WorktreeOwnershipError, match="preserved issue branch"):
        fake.prepare(request(repository, attempt="a02"))

    with pytest.raises(WorktreeOwnershipError, match="preserved issue branch"):
        fake.retire(first, PriorProcessState.STOPPED)


def test_fake_retired_lease_is_terminal_even_if_workspace_reappears(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    lease = fake.prepare(request(repository))
    fake.retire(lease, PriorProcessState.STOPPED)

    with pytest.raises(WorktreeOwnershipError, match="already retired"):
        fake.prepare(request(repository))

    fake.seed_existing(lease)
    with pytest.raises(WorktreeOwnershipError, match="retired worktree path"):
        fake.retire(lease, PriorProcessState.STOPPED)


def test_fake_branch_attachment_scope_is_repository_local_for_retired_recovery(
    tmp_path: Path,
) -> None:
    first_repository = create_repository(tmp_path, "first")
    second_repository = create_repository(tmp_path, "second")
    fake = FakeWorktreeManager()
    fake.prepare(request(first_repository))
    retired = WorktreeLease.from_request(request(second_repository))
    fake.seed_preserved_branch(retired)
    evidence = RetiredWorktreeEvidence(retired, retired.base_sha)

    fake.register_retired(evidence, PriorProcessState.STOPPED)
    second = fake.prepare(request(second_repository, attempt="a02"))

    assert fake.inspect(second).matched


def test_fake_branch_attachment_scope_is_repository_local_for_prepare(
    tmp_path: Path,
) -> None:
    first_repository = create_repository(tmp_path, "first")
    second_repository = create_repository(tmp_path, "second")
    fake = FakeWorktreeManager()
    second_first = fake.prepare(request(second_repository))
    fake.retire(second_first, PriorProcessState.STOPPED)
    fake.prepare(request(first_repository))

    second = fake.prepare(request(second_repository, attempt="a02"))

    assert fake.inspect(second).matched


def test_fake_next_attempt_requires_preserved_branch_head_as_base(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    first = fake.prepare(request(repository))
    fake.retire(first, PriorProcessState.STOPPED)
    preserved_head = "f" * 40
    fake.seed_preserved_branch(first, head_sha=preserved_head)

    with pytest.raises(WorktreeConflictError, match="base must equal"):
        fake.prepare(request(repository, attempt="a02"))

    second = fake.prepare(request(repository, attempt="a02", base=preserved_head))
    assert fake.inspect(second).head_sha == preserved_head


def test_fake_existing_branch_requires_retirement_recovery(
    repository: tuple[Path, Path, str],
) -> None:
    first = WorktreeLease.from_request(request(repository))
    fake = FakeWorktreeManager()
    fake.seed_preserved_branch(first)

    with pytest.raises(WorktreeConflictError, match="recover"):
        fake.prepare(request(repository, attempt="a02"))


def test_fake_can_restore_retired_evidence_before_later_attempt(
    repository: tuple[Path, Path, str],
) -> None:
    first = WorktreeLease.from_request(request(repository))
    fake = FakeWorktreeManager()
    fake.seed_preserved_branch(first)

    evidence = RetiredWorktreeEvidence(first, first.base_sha)
    fake.register_retired(evidence, PriorProcessState.STOPPED)
    second = fake.prepare(request(repository, attempt="a02"))

    assert fake.inspect(second).matched


def test_fake_rejects_force_moved_preserved_branch_like_real_manager(
    repository: tuple[Path, Path, str],
) -> None:
    fake = FakeWorktreeManager()
    first = fake.prepare(request(repository))
    evidence = fake.retire(first, PriorProcessState.STOPPED)
    unrelated = "e" * 40
    fake.seed_preserved_branch(first, head_sha=unrelated, ancestors=())
    second_request = request(repository, attempt="a02", base=unrelated)

    with pytest.raises(WorktreeOwnershipError, match="retired worktree head"):
        fake.prepare(second_request)

    recovered = FakeWorktreeManager()
    recovered.seed_preserved_branch(first, head_sha=unrelated, ancestors=())
    with pytest.raises(WorktreeOwnershipError, match="retired worktree head"):
        recovered.register_retired(evidence, PriorProcessState.STOPPED)


def test_fake_rejects_independent_base_and_retired_head_merged_into_current_head(
    repository: tuple[Path, Path, str],
) -> None:
    first = WorktreeLease.from_request(request(repository))
    unrelated_retired_head = "b" * 40
    merged_head = "c" * 40
    forged = RetiredWorktreeEvidence(first, unrelated_retired_head)
    fake = FakeWorktreeManager()
    fake.seed_preserved_branch(
        first,
        head_sha=merged_head,
        ancestors=(first.base_sha, unrelated_retired_head),
    )

    with pytest.raises(WorktreeOwnershipError, match="recorded base"):
        fake.register_retired(forged, PriorProcessState.STOPPED)
    with pytest.raises(WorktreeConflictError, match="recover"):
        fake.prepare(request(repository, attempt="a02", base=merged_head))


@pytest.mark.parametrize(
    "relations",
    [
        (("a" * 40, "b" * 40), ("b" * 40, "c" * 40)),
        (
            ("a" * 40, "b" * 40),
            ("a" * 40, "d" * 40),
            ("b" * 40, "c" * 40),
            ("d" * 40, "c" * 40),
        ),
    ],
    ids=("linear", "merge"),
)
def test_fake_accepts_directed_linear_and_merge_ancestry(
    repository: tuple[Path, Path, str],
    relations: tuple[tuple[str, str], ...],
) -> None:
    repo, root, _ = repository
    base = "a" * 40
    retired_head = "b" * 40
    current_head = "c" * 40
    first = WorktreeLease.from_request(
        WorktreeRequest(repo, root, "MB-009", 9, "a01", base)
    )
    evidence = RetiredWorktreeEvidence(first, retired_head)
    fake = FakeWorktreeManager()
    fake.seed_preserved_branch(
        first,
        head_sha=current_head,
        ancestors=(),
        relations=relations,
    )

    fake.register_retired(evidence, PriorProcessState.STOPPED)
    second = fake.prepare(
        WorktreeRequest(repo, root, "MB-009", 9, "a02", current_head)
    )

    assert fake.inspect(second).head_sha == current_head
