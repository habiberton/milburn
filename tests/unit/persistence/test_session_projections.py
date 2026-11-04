"""Deterministic session-generation replay tests."""

from datetime import UTC, datetime, timedelta

import pytest

from milburn.domain.sessions import (
    HandoffManifest,
    ObservationAvailability,
    ObservationFinality,
    SessionGenerationStatus,
    SessionLifecycleEvent,
    SessionLifecycleKind,
    SessionObservation,
    SessionObservationKind,
)
from milburn.domain.states import Role
from milburn.persistence.session_projections import (
    SessionProjectionError,
    ensure_generation_command_allowed,
    project_session_events,
)


NOW = datetime(2026, 11, 3, tzinfo=UTC)


def checkpoint(generation: int = 0) -> HandoffManifest:
    return HandoffManifest(
        role=Role.CODER,
        task_id="MB-018",
        attempt_id="a01",
        generation=generation,
        issue_ref="issue-22",
        acceptance_refs=("AC-1",),
        worktree="/repo/worktree",
        branch="branch-name",
        base_sha="base123",
        head_sha="head456",
        progress_ref="progress.md",
        completed=("slice",),
        remaining=("tests",),
        test_evidence=(),
        open_decisions=(),
        inbox_sequence=0,
        outbox_sequence=0,
        uncertain_effects=(),
        brief_digest="briefdigest",
        rules_digest="rulesdigest",
        created_at=NOW,
    )


def event(
    sequence: int,
    kind: SessionLifecycleKind,
    *,
    generation: int = 0,
    event_id: str | None = None,
    manifest: HandoffManifest | None = None,
) -> SessionLifecycleEvent:
    return SessionLifecycleEvent(
        event_id=event_id or f"event-{sequence}",
        sequence=sequence,
        task_id="MB-018",
        role=Role.CODER,
        attempt_id="a01",
        generation=generation,
        endpoint=f"pane-{generation}",
        session_id=f"session-{generation}",
        source_version=f"source-{sequence}",
        occurred_at=NOW + timedelta(seconds=sequence),
        kind=kind,
        manifest=manifest,
    )


def observation(observation_id: str = "observation-1") -> SessionObservation:
    return SessionObservation(
        observation_id=observation_id,
        task_id="MB-018",
        role=Role.CODER,
        attempt_id="a01",
        generation=0,
        endpoint="pane-0",
        session_id="session-0",
        kind=SessionObservationKind.COMPACTION,
        availability=ObservationAvailability.AVAILABLE,
        source_version="codex-v1",
        observed_at=NOW,
        finality=ObservationFinality.PARTIAL,
        compaction_count=1,
    )


def lifecycle() -> tuple[SessionLifecycleEvent | SessionObservation, ...]:
    return (
        event(0, SessionLifecycleKind.GENERATION_STARTED),
        observation(),
        event(1, SessionLifecycleKind.HANDOFF_VALIDATED, manifest=checkpoint()),
        event(2, SessionLifecycleKind.REPLACEMENT_REQUESTED),
        event(3, SessionLifecycleKind.GENERATION_FENCED),
        event(4, SessionLifecycleKind.GENERATION_STARTED, generation=1),
        event(5, SessionLifecycleKind.REPLACEMENT_COMPLETED, generation=1),
    )


def test_replay_reconstructs_logical_attempt_generations_and_latest_checkpoint() -> None:
    state = project_session_events(lifecycle())
    assert state is not None
    assert state.attempt_id == "a01"
    assert [generation.status for generation in state.generations] == [
        SessionGenerationStatus.REPLACED,
        SessionGenerationStatus.ACTIVE,
    ]
    assert state.current_generation.generation == 1
    assert state.latest_checkpoint == checkpoint()
    assert len(state.observations) == 1
    ensure_generation_command_allowed(state, generation=1)
    with pytest.raises(SessionProjectionError, match="stale"):
        ensure_generation_command_allowed(state, generation=0)


def test_duplicate_lifecycle_and_observation_delivery_are_idempotent() -> None:
    original = lifecycle()
    delivered_twice = (
        original[0], original[0], original[1], original[1], *original[2:]
    )
    assert project_session_events(delivered_twice) == project_session_events(original)


def test_same_source_version_redelivery_is_idempotent_but_conflicts_are_rejected() -> None:
    first = observation()
    redelivery = SessionObservation.from_dict(
        {
            **first.to_dict(),
            "observation_id": "redelivery",
            "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
        }
    )
    start = event(0, SessionLifecycleKind.GENERATION_STARTED)
    expected = project_session_events((start, first))
    assert project_session_events((start, first, redelivery)) == expected
    conflicting = SessionObservation.from_dict(
        {**first.to_dict(), "observation_id": "conflict", "compaction_count": 2}
    )
    with pytest.raises(SessionProjectionError, match="conflicting"):
        project_session_events((start, first, conflicting))


def test_fencing_is_required_before_next_generation_and_blocks_late_observation() -> None:
    events = (
        event(0, SessionLifecycleKind.GENERATION_STARTED),
        event(1, SessionLifecycleKind.HANDOFF_VALIDATED, manifest=checkpoint()),
        event(2, SessionLifecycleKind.REPLACEMENT_REQUESTED),
    )
    with pytest.raises(SessionProjectionError, match="fenced"):
        project_session_events(
            (*events, event(3, SessionLifecycleKind.GENERATION_STARTED, generation=1))
        )
    with pytest.raises(SessionProjectionError, match="fenced generation"):
        project_session_events(
            (*events, event(3, SessionLifecycleKind.GENERATION_FENCED), observation())
        )


def test_semantic_identity_enriches_generation_and_rejects_identity_drift() -> None:
    started_without_identity = SessionLifecycleEvent.from_dict(
        {
            **event(0, SessionLifecycleKind.GENERATION_STARTED).to_dict(),
            "endpoint": None,
            "session_id": None,
        }
    )
    identity = SessionObservation(
        observation_id="identity-1",
        task_id="MB-018",
        role=Role.CODER,
        attempt_id="a01",
        generation=0,
        endpoint="pane-observed",
        session_id="session-observed",
        kind=SessionObservationKind.IDENTITY,
        availability=ObservationAvailability.AVAILABLE,
        source_version="identity-v1",
        observed_at=NOW,
        finality=ObservationFinality.FINAL,
    )
    state = project_session_events((started_without_identity, identity))
    assert state is not None
    assert state.current_generation.endpoint == "pane-observed"
    assert state.current_generation.session_id == "session-observed"

    drift = SessionObservation.from_dict(
        {
            **observation("drift").to_dict(),
            "endpoint": "other-pane",
            "source_version": "compaction-v2",
        }
    )
    with pytest.raises(SessionProjectionError, match="identity does not match"):
        project_session_events((event(0, SessionLifecycleKind.GENERATION_STARTED), drift))
