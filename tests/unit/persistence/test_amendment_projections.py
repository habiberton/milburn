"""Deterministic amendment replay and operator projection tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain.amendments import (
    ActiveAttempt,
    ActiveWorkImpact,
    AmendmentApproval,
    AmendmentCommandType,
    AmendmentEventType,
    AmendmentStatus,
    ImpactClassification,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
)
from milburn.persistence.amendment_projections import (
    AmendmentProjectionError,
    operator_view,
    project_amendment_events,
)


NOW = datetime(2026, 11, 3, tzinfo=UTC)


def events() -> tuple[PlanAmendmentEvent, ...]:
    request = PlanAmendmentCommand(
        command_id="request-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.REQUEST,
        expected_version=-1,
        authority="direct user instruction",
        requested_change="Add MB-022 and freeze dispatch.",
        affected_tasks=("MB-005", "MB-007"),
    )
    impact = ActiveWorkImpact(
        attempt=ActiveAttempt(
            task_id="MB-005",
            attempt_id="attempt-5",
            owner="builder-5",
            generation=1,
        ),
        classification=ImpactClassification.UNAFFECTED,
        instruction="Continue the already active attempt.",
    )
    assess = PlanAmendmentCommand(
        command_id="assess-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.ASSESS_IMPACT,
        expected_version=0,
        impacts=(impact,),
    )
    approve = PlanAmendmentCommand(
        command_id="approve-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.APPROVE,
        expected_version=1,
        approval=AmendmentApproval(
            approved_by="direct user instruction",
            expected_planning_revision="planning-v1",
            specification_revision="spec-v1",
            registry_revision="registry-v1",
        ),
    )
    apply = PlanAmendmentCommand(
        command_id="apply-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.APPLY,
        expected_version=2,
        planning_revision="planning-v1",
        effective_revision="effective-commit",
        remote_merge_revision="merge-commit",
        primary_revision="merge-commit",
        remote_effects_reconciled=True,
    )
    resume = PlanAmendmentCommand(
        command_id="resume-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.RESUME_DISPATCH,
        expected_version=3,
    )
    commands = (request, assess, approve, apply, resume)
    types = (
        AmendmentEventType.REQUESTED,
        AmendmentEventType.IMPACT_ASSESSED,
        AmendmentEventType.APPROVED,
        AmendmentEventType.APPLIED,
        AmendmentEventType.DISPATCH_RESUMED,
    )
    return tuple(
        PlanAmendmentEvent(
            event_id=f"event-{index}",
            amendment_id="amend-1",
            event_type=event_type,
            sequence=index - 1,
            occurred_at=NOW,
            command=command,
        )
        for index, (command, event_type) in enumerate(zip(commands, types), start=1)
    )


def test_replay_is_deterministic_and_exact_duplicates_are_idempotent() -> None:
    history = events()
    expected = project_amendment_events(history)

    assert project_amendment_events((*history[:2], history[1], *history[2:])) == expected
    serialized = tuple(
        PlanAmendmentEvent.from_dict(item.to_dict()) for item in history
    )
    assert project_amendment_events(serialized) == expected
    assert expected is not None
    assert expected.status is AmendmentStatus.EFFECTIVE


def test_conflicting_duplicate_or_sequence_gap_is_rejected() -> None:
    history = events()
    conflict_payload = history[0].to_dict()
    conflict_payload["command"]["requested_change"] = "Different change."
    conflict = PlanAmendmentEvent.from_dict(conflict_payload)

    with pytest.raises(AmendmentProjectionError, match="different content"):
        project_amendment_events((history[0], conflict))
    with pytest.raises(AmendmentProjectionError, match="does not follow"):
        project_amendment_events((history[0], history[2]))


def test_operator_view_explains_authority_impact_revision_and_dispatch() -> None:
    applied = project_amendment_events(events()[:-1])
    assert applied is not None
    view = operator_view(applied)

    assert view.authority == "direct user instruction"
    assert view.affected_tasks == ("MB-005", "MB-007")
    assert view.active_work_impacts[0].classification is ImpactClassification.UNAFFECTED
    assert view.effective_revision == "effective-commit"
    assert view.remote_merge_revision == "merge-commit"
    assert view.dispatch_frozen is True
    assert "remotely reconciled" in view.dispatch_reason

    effective = project_amendment_events(events())
    assert effective is not None
    assert operator_view(effective).dispatch_frozen is False


def test_projection_impact_mapping_is_immutable() -> None:
    state = project_amendment_events(events()[:2])
    assert state is not None
    with pytest.raises(TypeError):
        state.impacts["new"] = state.impacts["attempt-5"]  # type: ignore[index]
