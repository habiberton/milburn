from dataclasses import replace
from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path

import pytest

from milburn.agents.briefs import BriefRenderer
from milburn.domain import AgentAttempt, AttemptState, IssueState, Role, SkillBinding
from milburn.integrations.github.contracts import Issue, RepositoryId
from milburn.orchestration.coder import CoderAssignment, CoderCoordinator, CoderStartupError, CODER_ROLE_RULES
from milburn.runtime.worktrees import PriorProcessState, WorktreeLease, WorktreeRequest
from tests.fakes.worktrees import FakeWorktreeManager

BASE = "a" * 40
REPOSITORY = RepositoryId("acme", "milburn")


def assignment(tmp_path, **changes):
    repository = tmp_path / "repo"; repository.mkdir()
    root = tmp_path / "worktrees"; root.mkdir()
    request = WorktreeRequest(repository, root, "task-13", 13, "attempt-1", BASE)
    lease = WorktreeLease.from_request(request)
    binding = SkillBinding(skill_name="milburn-long-running-coder", version="1",
                           root_digest="abc", resource_digests=(),
                           workspace_path=".agents/skills/milburn-long-running-coder",
                           validated_at=datetime(2026, 11, 4, tzinfo=UTC))
    attempt = AgentAttempt(attempt_id="attempt-1", generation=0, role=Role.CODER,
                           feature_id="feature-1", issue_number=13, endpoint="window-1",
                           worktree=str(request.worktree), branch=request.branch, base_sha=BASE,
                           rules_digest=sha256(CODER_ROLE_RULES.encode()).hexdigest(), skill_bindings=(binding,), status=AttemptState.STARTING)
    issue = Issue(RepositoryId("acme", "milburn"), 13, "Build it", "Objective and tests",
                  "open", ("milburn:task", "milburn:ready"))
    values = dict(issue=issue, state=IssueState.READY, attempt=attempt,
                  lease=lease, dependencies=((12, IssueState.DONE),),
                  comments=("Recent blocker resolved",), acceptance=("It works",),
                  spec_refs=("PRD.md:204-294", "ARCH.md:536-591"),
                  repository_instructions="Read AGENTS.md")
    values.update(changes)
    return CoderAssignment(**values)


def command_runner(item, tmp_path, *, max_excerpt_chars=2000):
    from milburn.runtime.commands import BoundedCommandRunner
    manager = FakeWorktreeManager()
    lease = item.lease
    manager.prepare(WorktreeRequest(lease.repository, lease.worktree_root,
                                    lease.task_id, lease.issue_number,
                                    lease.attempt_id, lease.base_sha))
    return BoundedCommandRunner(tmp_path / "logs", worktrees=manager,
                                max_excerpt_chars=max_excerpt_chars)


@pytest.mark.parametrize("change", [
    {"state": IssueState.DONE}, {"dependencies": ((12, IssueState.READY),)},
    {"comments": ("",)}, {"acceptance": ()},
])
def test_rejects_nonready_or_incomplete_assignment_before_launch(tmp_path, change):
    item = assignment(tmp_path, **change)
    manager = FakeWorktreeManager()
    with pytest.raises(CoderStartupError):
        CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(item)
    assert not manager.actions


def test_rejects_mismatched_attempt_or_worktree(tmp_path):
    item = assignment(tmp_path)
    for changed in (replace(item.attempt, issue_number=14),
                    replace(item.attempt, worktree="/elsewhere"),
                    replace(item.attempt, role=Role.TESTER)):
        manager = FakeWorktreeManager()
        with pytest.raises(CoderStartupError):
            CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(replace(item, attempt=changed))
        assert not manager.actions


def test_rejects_issue_from_another_configured_repository(tmp_path):
    item = assignment(tmp_path)
    with pytest.raises(CoderStartupError):
        CoderCoordinator(FakeWorktreeManager(), BriefRenderer(),
                         repository_id=RepositoryId("other", "project"), repository_path=item.lease.repository).prepare(item)


def test_rejects_attempt_with_wrong_recorded_rules_digest(tmp_path):
    item = assignment(tmp_path)
    manager = FakeWorktreeManager()
    lease = item.lease
    manager.prepare(WorktreeRequest(lease.repository, lease.worktree_root,
                                    lease.task_id, lease.issue_number,
                                    lease.attempt_id, lease.base_sha))
    with pytest.raises(CoderStartupError, match="rules digest"):
        CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(
            replace(item, attempt=replace(item.attempt, rules_digest="wrong")))


def test_rejects_conflicting_ready_labels_and_malformed_dependency_records(tmp_path):
    item = assignment(tmp_path)
    for changed in (
        replace(item, issue=replace(item.issue, labels=("milburn:task", "milburn:ready", "milburn:done"))),
        replace(item, dependencies=(([], IssueState.DONE),)),
    ):
        with pytest.raises(CoderStartupError):
            CoderCoordinator(FakeWorktreeManager(), BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(changed)


def test_launch_brief_contains_full_startup_sequence_and_boundary_questions(tmp_path):
    item = assignment(tmp_path)
    manager = FakeWorktreeManager()
    manager.prepare(WorktreeRequest(item.lease.repository, item.lease.worktree_root,
                                    item.lease.task_id, item.lease.issue_number,
                                    item.lease.attempt_id, item.lease.base_sha))
    prepared = CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(item)
    for token in ("Issue #13", "attempt-1", "AGENTS.md", "progress.txt", "Git status",
                  "[#13]", "diff", "smoke", "acceptance criteria", "dependencies",
                  "recent comments", "what could pass", "every field", "bypass",
                  "unique", "preconditions", "test double"):
        assert token.lower() in prepared.content.lower()
    assert "milburn-long-running-coder" in prepared.content


def test_replacement_requires_observed_stopped_process(tmp_path):
    item = assignment(tmp_path)
    manager = FakeWorktreeManager()
    manager.prepare(WorktreeRequest(item.lease.repository, item.lease.worktree_root,
                                    item.lease.task_id, item.lease.issue_number,
                                    item.lease.attempt_id, item.lease.base_sha))
    service = CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository)
    with pytest.raises(CoderStartupError):
        service.resume(item, PriorProcessState.UNKNOWN)


def test_bounded_command_runner_rejects_missing_command_and_unowned_path(tmp_path):
    from milburn.runtime.commands import BoundedCommandRunner, CommandExecutionError
    item = assignment(tmp_path)
    with pytest.raises(CommandExecutionError):
        command_runner(item, tmp_path).run(item.lease, ())
    with pytest.raises(CommandExecutionError):
        command_runner(item, tmp_path).run(item.lease, ("python3", "-c", "print('x')"))


def test_bounded_command_runner_keeps_full_output_in_log(tmp_path):
    from milburn.runtime.commands import BoundedCommandRunner
    item = assignment(tmp_path)
    item.lease.worktree.mkdir()
    runner = command_runner(item, tmp_path, max_excerpt_chars=32)
    passed = runner.run(item.lease, ("python3", "-c", "print('x' * 1000)"))
    assert passed.exit_code == 0
    assert passed.excerpt == ""
    assert len(passed.log_ref.read_text().strip()) == 1000
    assert passed.command[0] == "python3"
    failed = runner.run(item.lease, ("python3", "-c", "print('y' * 1000); raise SystemExit(3)"))
    assert failed.exit_code == 3
    assert len(failed.excerpt) <= 32
    assert len(failed.log_ref.read_text()) > len(failed.excerpt)


def test_assignment_and_resume_reject_wrong_input_types_before_effect(tmp_path):
    item = assignment(tmp_path)
    manager = FakeWorktreeManager()
    with pytest.raises(CoderStartupError):
        CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).prepare(replace(item, repository_instructions=None))
    with pytest.raises(CoderStartupError):
        CoderCoordinator(manager, BriefRenderer(), repository_id=REPOSITORY, repository_path=item.lease.repository).resume(item, PriorProcessState.STOPPED,
                                                           manifest="bad", expectation="bad")
    assert not manager.actions


def test_bounded_runner_handles_utf8_failure_excerpt(tmp_path):
    from milburn.runtime.commands import BoundedCommandRunner
    item = assignment(tmp_path)
    item.lease.worktree.mkdir()
    result = command_runner(item, tmp_path, max_excerpt_chars=13).run(
        item.lease, ("python3", "-c", "print('🌍' * 100); raise SystemExit(2)"))
    assert result.exit_code == 2
    assert len(result.excerpt) <= 13
    assert "🌍" in result.log_ref.read_text()


def test_bounded_runner_rejects_existing_but_unregistered_worktree(tmp_path):
    from milburn.runtime.commands import BoundedCommandRunner, CommandExecutionError
    item = assignment(tmp_path)
    item.lease.worktree.mkdir()
    with pytest.raises(CommandExecutionError, match="registered"):
        BoundedCommandRunner(tmp_path / "logs", worktrees=FakeWorktreeManager()).run(
            item.lease, ("python3", "-c", "print('would run')"))


def test_bounded_summary_identifies_exact_test_selection(tmp_path):
    from milburn.runtime.commands import BoundedCommandRunner
    item = assignment(tmp_path)
    item.lease.worktree.mkdir()
    result = command_runner(item, tmp_path).run(
        item.lease, ("python3", "-c", "print('selected')"))
    assert "-c" in result.summary
    assert "selected" in result.summary
