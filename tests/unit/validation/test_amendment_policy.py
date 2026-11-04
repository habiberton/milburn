"""Dispatch and continuation preflight policy tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain.amendments import (
    AmendmentCommandType,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
    AmendmentEventType,
)
from milburn.persistence.amendment_projections import project_amendment_events
from milburn.validation.amendment_policy import (
    DispatchFrozenError,
    PlanChangeKind,
    ensure_agent_launch_allowed,
    plan_amendment_preflight,
    requires_plan_amendment,
)


def pending_state():
    command = PlanAmendmentCommand(
        command_id="request-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.REQUEST,
        expected_version=-1,
        authority="direct user instruction",
        requested_change="Change task dependencies.",
        affected_tasks=("MB-007",),
    )
    state = project_amendment_events(
        (
            PlanAmendmentEvent(
                event_id="event-1",
                amendment_id="amend-1",
                event_type=AmendmentEventType.REQUESTED,
                sequence=0,
                occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
                command=command,
            ),
        )
    )
    assert state is not None
    return state


@pytest.mark.parametrize("change_kind", list(PlanChangeKind))
def test_every_authorized_plan_change_kind_requires_an_amendment(
    change_kind: PlanChangeKind,
) -> None:
    assert requires_plan_amendment(change_kind)


def test_unknown_plan_change_kind_is_not_silently_accepted() -> None:
    with pytest.raises(ValueError, match="known PlanChangeKind"):
        requires_plan_amendment("task")  # type: ignore[arg-type]


def test_pending_amendment_blocks_launch_before_effect() -> None:
    effects: list[str] = []
    with pytest.raises(DispatchFrozenError, match="amend-1"):
        ensure_agent_launch_allowed((pending_state(),))
        effects.append("launch")

    assert effects == []


def test_dirty_coordinator_planning_files_block_launch_without_amendment() -> None:
    with pytest.raises(DispatchFrozenError, match="bootstrap/tasks.json"):
        ensure_agent_launch_allowed(
            (), dirty_planning_paths=("bootstrap/tasks.json",)
        )


def test_startup_and_final_response_preflight_explain_every_blocker() -> None:
    preflight = plan_amendment_preflight(
        (pending_state(),),
        dirty_planning_paths=("PRD.md", "bootstrap/tasks.json"),
    )

    assert preflight.dispatch_allowed is False
    assert preflight.pending_amendments == ("amend-1",)
    assert preflight.dirty_planning_paths == ("PRD.md", "bootstrap/tasks.json")
    assert preflight.blockers == (
        "plan amendment amend-1 still freezes dispatch",
        "coordinator planning files are uncommitted: PRD.md, bootstrap/tasks.json",
    )


def test_clear_preflight_allows_dispatch() -> None:
    preflight = plan_amendment_preflight(())
    assert preflight.dispatch_allowed
    ensure_agent_launch_allowed(())
