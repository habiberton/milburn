"""Pure dependency and Coder-capacity scheduling policy."""

from __future__ import annotations

from dataclasses import dataclass

from milburn.domain import AttemptState, IssueState, Role
from milburn.domain.policies import is_active_attempt


@dataclass(frozen=True, slots=True)
class SchedulableIssue:
    issue_number: int
    state: IssueState
    dependencies: tuple[int, ...] = ()
    specs_ready: bool = True
    approvals_ready: bool = True


@dataclass(frozen=True, slots=True)
class ScheduledAttempt:
    attempt_id: str
    issue_number: int
    role: Role
    state: AttemptState


class Scheduler:
    """Select ready issues while preserving dependency and ownership invariants."""

    def __init__(self, *, max_active_coders: int = 1) -> None:
        if (
            not isinstance(max_active_coders, int)
            or isinstance(max_active_coders, bool)
            or max_active_coders < 1
        ):
            raise ValueError("max_active_coders must be a positive integer")
        self._max_active_coders = max_active_coders

    def ready_issues(
        self,
        issues: tuple[SchedulableIssue, ...],
        attempts: tuple[ScheduledAttempt, ...],
        *,
        worktree_slots: int,
    ) -> tuple[SchedulableIssue, ...]:
        if (
            not isinstance(worktree_slots, int)
            or isinstance(worktree_slots, bool)
            or worktree_slots < 0
        ):
            raise ValueError("worktree_slots must be a non-negative integer")

        issue_by_number = {issue.issue_number: issue for issue in issues}
        if len(issue_by_number) != len(issues):
            raise ValueError("issue numbers must be unique")

        active_coders = tuple(
            attempt
            for attempt in attempts
            if attempt.role is Role.CODER and is_active_attempt(attempt.state)
        )
        active_issue_numbers = {attempt.issue_number for attempt in active_coders}
        capacity = min(
            worktree_slots,
            max(0, self._max_active_coders - len(active_coders)),
        )
        if capacity == 0:
            return ()

        ready = []
        for issue in sorted(issues, key=lambda value: value.issue_number):
            if issue.state is not IssueState.READY:
                continue
            if issue.issue_number in active_issue_numbers:
                continue
            if not issue.specs_ready or not issue.approvals_ready:
                continue
            if not all(
                dependency in issue_by_number
                and issue_by_number[dependency].state is IssueState.DONE
                for dependency in issue.dependencies
            ):
                continue
            ready.append(issue)
            if len(ready) == capacity:
                break
        return tuple(ready)
