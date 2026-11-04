"""Original mid-run amendment race reproduced through public boundaries."""

from datetime import UTC, datetime

import pytest

from milburn.domain.amendments import (
    ActiveAttempt,
    ActiveWorkImpact,
    AmendmentApproval,
    AmendmentCommandType,
    ImpactClassification,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
)
from milburn.orchestration.plan_amendments import (
    AmendmentConcurrencyError,
    PlanAmendmentCoordinator,
)
from milburn.validation.amendment_policy import DispatchFrozenError


class Store:
    def __init__(self) -> None:
        self.events: tuple[PlanAmendmentEvent, ...] = ()

    def read_stream(self, amendment_id: str) -> tuple[PlanAmendmentEvent, ...]:
        return tuple(event for event in self.events if event.amendment_id == amendment_id)

    def append(self, amendment_id, expected_version, events):
        current = self.read_stream(amendment_id)
        actual = current[-1].sequence if current else -1
        if actual != expected_version:
            raise AmendmentConcurrencyError("stale")
        self.events = (*self.events, *events)
        return events


def command(kind: AmendmentCommandType, version: int, **values):
    payload = dict(
        command_id=f"{kind.value}-1",
        amendment_id="AMEND-001",
        command_type=kind,
        expected_version=version,
    )
    payload.update(values)
    return PlanAmendmentCommand(**payload)


def test_midrun_amendment_preserves_unaffected_worker_and_fences_new_launches() -> None:
    store = Store()
    event_ids = (f"event-{index}" for index in range(1, 10))
    subject = PlanAmendmentCoordinator(
        store,
        clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
        event_ids=lambda: next(event_ids),
    )
    active = ActiveAttempt(
        task_id="MB-005", attempt_id="MB-005-a01", owner="builder-5", generation=1
    )
    subject.handle(
        command(
            AmendmentCommandType.REQUEST,
            -1,
            authority="direct user instruction",
            requested_change="Add MB-022 before more Wave 2 dispatch.",
            affected_tasks=("MB-005", "MB-007"),
        )
    )
    pending = subject.state("AMEND-001")
    assert pending is not None

    launched: list[str] = []
    with pytest.raises(DispatchFrozenError):
        subject.request_agent_launch(
            (pending,), request_effect=lambda: launched.append("MB-007")
        )
    assert launched == []

    subject.handle(
        command(
            AmendmentCommandType.ASSESS_IMPACT,
            0,
            impacts=(
                ActiveWorkImpact(
                    attempt=active,
                    classification=ImpactClassification.UNAFFECTED,
                    instruction="Continue the already active worker.",
                ),
            ),
        ),
        active_attempts=(active,),
    )
    assessed = subject.state("AMEND-001")
    assert assessed is not None
    assert assessed.impacts[active.attempt_id].attempt == active

    subject.handle(
        command(
            AmendmentCommandType.APPROVE,
            1,
            approval=AmendmentApproval(
                approved_by="direct user instruction",
                expected_planning_revision="planning-commit",
                specification_revision="spec-revision",
                registry_revision="registry-revision",
            ),
        )
    )
    subject.handle(
        command(
            AmendmentCommandType.APPLY,
            2,
            planning_revision="planning-commit",
            effective_revision="effective-commit",
            remote_merge_revision="remote-merge",
            primary_revision="remote-merge",
            remote_effects_reconciled=True,
        )
    )
    still_frozen = subject.state("AMEND-001")
    assert still_frozen is not None
    with pytest.raises(DispatchFrozenError):
        subject.request_agent_launch(
            (still_frozen,), request_effect=lambda: launched.append("MB-007")
        )

    subject.handle(command(AmendmentCommandType.RESUME_DISPATCH, 3))
    effective = subject.state("AMEND-001")
    assert effective is not None
    result = subject.request_agent_launch(
        (effective,), request_effect=lambda: launched.append("MB-007") or "requested"
    )

    assert result == "requested"
    assert launched == ["MB-007"]
    assert assessed.impacts[active.attempt_id].attempt.generation == 1
