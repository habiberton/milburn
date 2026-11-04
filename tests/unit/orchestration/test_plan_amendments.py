"""Plan-amendment command, event, and coordinator contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from milburn.domain.amendments import (
    ActiveAttempt,
    ActiveWorkImpact,
    AmendmentApproval,
    AmendmentCommandType,
    AmendmentEventType,
    AmendmentStatus,
    GitHubAmendmentEffect,
    ImpactClassification,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
)
from milburn.orchestration.plan_amendments import (
    AmendmentCommandConflictError,
    AmendmentConcurrencyError,
    PlanAmendmentCoordinator,
)
from milburn.persistence.amendment_projections import AmendmentProjectionError


NOW = datetime(2026, 11, 3, tzinfo=UTC)


class MemoryAmendmentStore:
    def __init__(self) -> None:
        self.events: dict[str, tuple[PlanAmendmentEvent, ...]] = {}

    def read_stream(self, amendment_id: str) -> tuple[PlanAmendmentEvent, ...]:
        return self.events.get(amendment_id, ())

    def append(
        self,
        amendment_id: str,
        expected_version: int,
        events: tuple[PlanAmendmentEvent, ...],
    ) -> tuple[PlanAmendmentEvent, ...]:
        current = self.events.get(amendment_id, ())
        actual = current[-1].sequence if current else -1
        if actual != expected_version:
            raise AmendmentConcurrencyError("concurrent amendment write")
        self.events[amendment_id] = (*current, *events)
        return events


def coordinator(store: MemoryAmendmentStore) -> PlanAmendmentCoordinator:
    ids = (f"event-{number}" for number in range(1, 20))
    return PlanAmendmentCoordinator(
        store, clock=lambda: NOW, event_ids=lambda: next(ids)
    )


def request(*, command_id: str = "request-1") -> PlanAmendmentCommand:
    return PlanAmendmentCommand(
        command_id=command_id,
        amendment_id="amend-1",
        command_type=AmendmentCommandType.REQUEST,
        expected_version=-1,
        authority="direct user instruction",
        requested_change="Add one task and gate dispatch.",
        affected_tasks=("MB-007", "MB-008"),
    )


def active_attempt() -> ActiveAttempt:
    return ActiveAttempt(
        task_id="MB-007",
        attempt_id="attempt-7",
        owner="builder-7",
        generation=2,
    )


def assessment(attempt: ActiveAttempt | None = None) -> PlanAmendmentCommand:
    impacts = ()
    if attempt is not None:
        impacts = (
            ActiveWorkImpact(
                attempt=attempt,
                classification=ImpactClassification.UNAFFECTED,
                instruction="Continue without changing ownership or generation.",
            ),
        )
    return PlanAmendmentCommand(
        command_id="assess-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.ASSESS_IMPACT,
        expected_version=0,
        impacts=impacts,
    )


def approval() -> AmendmentApproval:
    return AmendmentApproval(
        approved_by="direct user instruction",
        expected_planning_revision="planning-v4",
        specification_revision="spec-digest-4",
        registry_revision="registry-digest-4",
        github_effects=(
            GitHubAmendmentEffect(
                effect_id="github-effect-1",
                description="Add dependency notice to issue 7.",
                remote_reference="issue-7-comment-1",
            ),
        ),
    )


def command(
    command_type: AmendmentCommandType,
    expected_version: int,
    **changes: object,
) -> PlanAmendmentCommand:
    values: dict[str, object] = {
        "command_id": f"{command_type.value}-1",
        "amendment_id": "amend-1",
        "command_type": command_type,
        "expected_version": expected_version,
    }
    values.update(changes)
    return PlanAmendmentCommand(**values)  # type: ignore[arg-type]


def test_versioned_command_and_event_round_trip_strictly() -> None:
    store = MemoryAmendmentStore()
    event = coordinator(store).handle(request())

    assert PlanAmendmentCommand.from_dict(request().to_dict()) == request()
    assert PlanAmendmentEvent.from_dict(event.to_dict()) == event
    invalid = request().to_dict()
    invalid["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        PlanAmendmentCommand.from_dict(invalid)

    with pytest.raises(ValueError, match="request command requires"):
        PlanAmendmentEvent(
            event_id="wrong-event",
            amendment_id="amend-1",
            event_type=AmendmentEventType.APPROVED,
            sequence=0,
            occurred_at=NOW,
            command=request(),
        )

    with pytest.raises(ValueError, match="unrelated fields"):
        command(
            AmendmentCommandType.RESUME_DISPATCH,
            3,
            authority="authority does not belong on resume",
        )


def test_full_lifecycle_binds_revision_and_remote_reconciliation() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    attempt = active_attempt()

    subject.handle(request())
    subject.handle(assessment(attempt), active_attempts=(attempt,))
    subject.handle(
        command(
            AmendmentCommandType.APPROVE,
            1,
            approval=approval(),
        )
    )
    subject.handle(
        command(
            AmendmentCommandType.APPLY,
            2,
            planning_revision="planning-v4",
            effective_revision="effective-commit-4",
            remote_merge_revision="merge-commit-4",
            primary_revision="merge-commit-4",
            remote_effects_reconciled=True,
        )
    )
    subject.handle(command(AmendmentCommandType.RESUME_DISPATCH, 3))

    state = subject.state("amend-1")
    assert state is not None
    assert state.status is AmendmentStatus.EFFECTIVE
    assert state.dispatch_frozen is False
    assert state.impacts["attempt-7"].attempt == attempt
    assert state.effective_revision == "effective-commit-4"
    assert state.remote_merge_revision == "merge-commit-4"


def test_impact_assessment_must_cover_active_attempts_without_mutation() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    attempt = active_attempt()
    subject.handle(request())

    with pytest.raises(AmendmentProjectionError, match="classify every"):
        subject.handle(assessment(), active_attempts=(attempt,))

    changed = ActiveAttempt(
        task_id=attempt.task_id,
        attempt_id=attempt.attempt_id,
        owner="different-owner",
        generation=attempt.generation + 1,
    )
    with pytest.raises(AmendmentProjectionError, match="ownership or generation"):
        subject.handle(assessment(changed), active_attempts=(attempt,))

    assert len(store.events["amend-1"]) == 1


def test_every_active_attempt_is_classified_even_when_its_task_is_unaffected() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    affected = active_attempt()
    unrelated = ActiveAttempt(
        task_id="MB-006",
        attempt_id="attempt-6",
        owner="builder-6",
        generation=3,
    )
    subject.handle(request())

    with pytest.raises(AmendmentProjectionError, match="classify every"):
        subject.handle(assessment(affected), active_attempts=(affected, unrelated))


def test_expected_version_and_stale_planning_revision_are_rejected_before_append() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    subject.handle(request())

    with pytest.raises(AmendmentConcurrencyError, match="version 0"):
        subject.handle(
            command(AmendmentCommandType.ASSESS_IMPACT, -1),
            active_attempts=(),
        )

    subject.handle(assessment(), active_attempts=())
    subject.handle(command(AmendmentCommandType.APPROVE, 1, approval=approval()))
    with pytest.raises(AmendmentProjectionError, match="stale planning revision"):
        subject.handle(
            command(
                AmendmentCommandType.APPLY,
                2,
                planning_revision="planning-v3",
                effective_revision="effective-commit-4",
                remote_merge_revision="merge-commit-4",
                primary_revision="merge-commit-4",
                remote_effects_reconciled=True,
            )
        )

    assert len(store.events["amend-1"]) == 3


def test_approval_must_retain_request_authority() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    subject.handle(request())
    subject.handle(assessment(), active_attempts=())
    mismatched = AmendmentApproval(
        approved_by="inferred coordinator authority",
        expected_planning_revision="planning-v4",
        specification_revision="spec-digest-4",
        registry_revision="registry-digest-4",
    )

    with pytest.raises(AmendmentProjectionError, match="authority"):
        subject.handle(
            command(AmendmentCommandType.APPROVE, 1, approval=mismatched)
        )

    assert len(store.events["amend-1"]) == 2


def test_rejection_requires_completed_impact_assessment() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    subject.handle(request())

    with pytest.raises(AmendmentProjectionError, match="assessed"):
        subject.handle(
            command(
                AmendmentCommandType.REJECT,
                0,
                rejection_reason="The user withdrew the change.",
            )
        )


def test_command_retry_is_idempotent_and_conflicting_reuse_is_rejected() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    original = request()
    first = subject.handle(original)
    repeated = subject.handle(original)

    assert repeated is first
    assert len(store.events["amend-1"]) == 1

    with pytest.raises(AmendmentCommandConflictError, match="conflicting content"):
        subject.handle(request(command_id="request-1").__class__(
            command_id="request-1",
            amendment_id="amend-1",
            command_type=AmendmentCommandType.REQUEST,
            expected_version=-1,
            authority="different authority",
            requested_change="Add one task and gate dispatch.",
            affected_tasks=("MB-007", "MB-008"),
        ))


def test_rejection_remains_frozen_until_explicit_dispatch_resume() -> None:
    store = MemoryAmendmentStore()
    subject = coordinator(store)
    subject.handle(request())
    subject.handle(assessment(), active_attempts=())
    subject.handle(
        command(
            AmendmentCommandType.REJECT,
            1,
            rejection_reason="The user withdrew the requested change.",
        )
    )
    rejected = subject.state("amend-1")
    assert rejected is not None and rejected.dispatch_frozen

    subject.handle(command(AmendmentCommandType.RESUME_DISPATCH, 2))
    resumed = subject.state("amend-1")
    assert resumed is not None
    assert resumed.status is AmendmentStatus.REJECTED
    assert resumed.dispatch_frozen is False
