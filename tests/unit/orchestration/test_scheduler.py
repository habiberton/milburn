"""Scheduler policy tests cover dependencies, capacity, and active ownership."""

from __future__ import annotations

import pytest

from milburn.domain import AttemptState, IssueState, Role
from milburn.orchestration.scheduler import (
    ScheduledAttempt,
    SchedulableIssue,
    Scheduler,
)


def issue(
    number: int,
    state: IssueState = IssueState.READY,
    *,
    dependencies: tuple[int, ...] = (),
    specs_ready: bool = True,
    approvals_ready: bool = True,
) -> SchedulableIssue:
    return SchedulableIssue(
        number, state, dependencies, specs_ready, approvals_ready
    )


def attempt(
    issue_number: int,
    state: AttemptState,
    *,
    role: Role = Role.CODER,
) -> ScheduledAttempt:
    return ScheduledAttempt(
        f"attempt-{issue_number}-{state.value}", issue_number, role, state
    )


def test_scheduler_selects_ready_issue_after_dependencies_are_done() -> None:
    dependency = issue(1, IssueState.DONE)
    candidate = issue(2, dependencies=(1,))

    assert Scheduler().ready_issues((candidate, dependency), (), worktree_slots=1) == (
        candidate,
    )


@pytest.mark.parametrize("dependency_state", [IssueState.READY, IssueState.PASSED])
def test_scheduler_waits_until_every_dependency_is_done(
    dependency_state: IssueState,
) -> None:
    dependency = issue(1, dependency_state)
    candidate = issue(2, dependencies=(1,))

    selected = Scheduler().ready_issues(
        (dependency, candidate), (), worktree_slots=2
    )

    assert candidate not in selected


def test_scheduler_rejects_missing_dependencies() -> None:
    candidate = issue(2, dependencies=(99,))

    assert Scheduler().ready_issues((candidate,), (), worktree_slots=1) == ()


@pytest.mark.parametrize(
    "state",
    [
        AttemptState.STARTING,
        AttemptState.BUSY,
        AttemptState.IDLE,
        AttemptState.WAITING,
        AttemptState.WAITING_USER,
        AttemptState.UNKNOWN,
    ],
)
def test_active_coder_attempt_prevents_duplicate_for_same_issue(
    state: AttemptState,
) -> None:
    candidate = issue(4)

    assert Scheduler(max_active_coders=2).ready_issues(
        (candidate,), (attempt(4, state),), worktree_slots=1
    ) == ()


@pytest.mark.parametrize("state", [AttemptState.STOPPED, AttemptState.FAILED])
def test_observed_terminal_attempt_releases_issue(state: AttemptState) -> None:
    candidate = issue(4)

    assert Scheduler().ready_issues(
        (candidate,), (attempt(4, state),), worktree_slots=1
    ) == (candidate,)


def test_default_repository_policy_allows_only_one_active_coder() -> None:
    candidate = issue(5)

    assert Scheduler().ready_issues(
        (candidate,), (attempt(4, AttemptState.BUSY),), worktree_slots=2
    ) == ()


def test_non_coder_attempt_does_not_consume_coder_capacity() -> None:
    candidate = issue(5)

    assert Scheduler().ready_issues(
        (candidate,),
        (attempt(4, AttemptState.BUSY, role=Role.TESTER),),
        worktree_slots=1,
    ) == (candidate,)


@pytest.mark.parametrize(
    "candidate",
    [
        issue(4, IssueState.BLOCKED),
        issue(4, specs_ready=False),
        issue(4, approvals_ready=False),
    ],
)
def test_scheduler_requires_ready_state_specs_and_approvals(
    candidate: SchedulableIssue,
) -> None:
    assert Scheduler().ready_issues((candidate,), (), worktree_slots=1) == ()


def test_scheduler_is_deterministic_and_respects_available_capacity() -> None:
    issues = (issue(8), issue(3), issue(5))

    assert Scheduler(max_active_coders=3).ready_issues(
        issues, (), worktree_slots=2
    ) == (issue(3), issue(5))
