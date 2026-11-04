"""Deterministic replay for logical attempts and session generations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from milburn.domain.sessions import (
    HandoffManifest,
    ObservationAvailability,
    SessionGeneration,
    SessionGenerationStatus,
    SessionLifecycleEvent,
    SessionLifecycleKind,
    SessionObservation,
    SessionObservationKind,
)
from milburn.domain.states import Role


class SessionProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionProjection:
    task_id: str
    role: Role
    attempt_id: str
    generations: tuple[SessionGeneration, ...]
    observations: tuple[SessionObservation, ...]
    latest_checkpoint: HandoffManifest | None
    replacement_requested: bool
    replacement_completed: bool
    version: int

    @property
    def current_generation(self) -> SessionGeneration:
        if not self.generations:
            raise SessionProjectionError("attempt has no session generation")
        return self.generations[-1]


def project_session_events(
    events: Iterable[SessionLifecycleEvent | SessionObservation],
) -> SessionProjection | None:
    state: SessionProjection | None = None
    lifecycle_ids: dict[str, SessionLifecycleEvent] = {}
    observation_ids: dict[str, SessionObservation] = {}
    observation_versions: dict[
        tuple[str, str, str, int, SessionObservationKind, str],
        SessionObservation,
    ] = {}

    for event in events:
        if isinstance(event, SessionObservation):
            if state is None:
                raise SessionProjectionError("a generation must start before observations")
            _require_correlation(state, event.task_id, event.role, event.attempt_id)
            if event.generation >= len(state.generations):
                raise SessionProjectionError("observation targets an unknown generation")
            generation = state.generations[event.generation]
            _require_observation_identity(generation, event)
            previous = observation_ids.get(event.observation_id)
            if previous is not None:
                if previous != event:
                    raise SessionProjectionError(
                        f"observation ID {event.observation_id} has conflicting content"
                    )
                continue
            semantic = observation_versions.get(event.semantic_key)
            if semantic is not None:
                if _observation_signature(semantic) != _observation_signature(event):
                    raise SessionProjectionError(
                        f"source version {event.source_version} has conflicting content"
                    )
                observation_ids[event.observation_id] = event
                continue
            if generation.status is not SessionGenerationStatus.ACTIVE:
                raise SessionProjectionError("a fenced generation cannot accept observations")
            observation_ids[event.observation_id] = event
            observation_versions[event.semantic_key] = event
            generations = state.generations
            if (
                event.kind is SessionObservationKind.IDENTITY
                and event.availability is ObservationAvailability.AVAILABLE
                and (generation.endpoint is None or generation.session_id is None)
            ):
                enriched = replace(
                    generation,
                    endpoint=generation.endpoint or event.endpoint,
                    session_id=generation.session_id or event.session_id,
                )
                generations = (
                    *state.generations[: event.generation],
                    enriched,
                    *state.generations[event.generation + 1 :],
                )
            state = replace(
                state,
                generations=generations,
                observations=(*state.observations, event),
            )
            continue

        if not isinstance(event, SessionLifecycleEvent):
            raise SessionProjectionError("session replay accepts only session events")
        previous = lifecycle_ids.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise SessionProjectionError(
                    f"event ID {event.event_id} has conflicting content"
                )
            continue
        lifecycle_ids[event.event_id] = event
        expected_sequence = 0 if state is None else state.version + 1
        if event.sequence != expected_sequence:
            raise SessionProjectionError(
                f"event sequence {event.sequence} does not follow {expected_sequence - 1}"
            )
        state = _apply_lifecycle(state, event)
    return state


def ensure_generation_command_allowed(
    state: SessionProjection, *, generation: int
) -> None:
    """Fence delayed steering and lifecycle commands from old generations."""

    if generation != state.current_generation.generation:
        raise SessionProjectionError("command targets a stale session generation")
    if state.current_generation.status is not SessionGenerationStatus.ACTIVE:
        raise SessionProjectionError("command targets a fenced session generation")


def _apply_lifecycle(
    state: SessionProjection | None, event: SessionLifecycleEvent
) -> SessionProjection:
    if event.kind is SessionLifecycleKind.GENERATION_STARTED:
        if state is None:
            if event.generation != 0:
                raise SessionProjectionError("the first generation must be zero")
            generation = SessionGeneration(
                attempt_id=event.attempt_id,
                generation=0,
                endpoint=event.endpoint,
                session_id=event.session_id,
                source_version=event.source_version,
                started_at=event.occurred_at,
                status=SessionGenerationStatus.ACTIVE,
            )
            return SessionProjection(
                event.task_id,
                event.role,
                event.attempt_id,
                (generation,),
                (),
                None,
                False,
                False,
                event.sequence,
            )
        _require_correlation(state, event.task_id, event.role, event.attempt_id)
        if not state.replacement_requested:
            raise SessionProjectionError("a new generation needs a replacement request")
        if state.current_generation.status is not SessionGenerationStatus.FENCED:
            raise SessionProjectionError("the old generation must be fenced before launch")
        if event.generation != state.current_generation.generation + 1:
            raise SessionProjectionError("generation numbers must be monotonic")
        generation = SessionGeneration(
            attempt_id=event.attempt_id,
            generation=event.generation,
            endpoint=event.endpoint,
            session_id=event.session_id,
            source_version=event.source_version,
            started_at=event.occurred_at,
            status=SessionGenerationStatus.ACTIVE,
        )
        return replace(
            state,
            generations=(*state.generations, generation),
            replacement_completed=False,
            version=event.sequence,
        )
    if state is None:
        raise SessionProjectionError("session stream must begin with generation start")
    _require_correlation(state, event.task_id, event.role, event.attempt_id)
    _require_lifecycle_identity(state, event)

    if event.kind is SessionLifecycleKind.HANDOFF_VALIDATED:
        if event.generation != state.current_generation.generation:
            raise SessionProjectionError("handoff targets a stale generation")
        if state.current_generation.status is not SessionGenerationStatus.ACTIVE:
            raise SessionProjectionError("handoff cannot validate after fencing")
        return replace(state, latest_checkpoint=event.manifest, version=event.sequence)
    if event.kind is SessionLifecycleKind.REPLACEMENT_REQUESTED:
        if state.latest_checkpoint is None:
            raise SessionProjectionError("replacement needs a validated checkpoint")
        checkpoint = state.latest_checkpoint
        if (
            checkpoint.task_id != state.task_id
            or checkpoint.role is not state.role
            or checkpoint.attempt_id != state.attempt_id
            or checkpoint.generation != state.current_generation.generation
        ):
            raise SessionProjectionError(
                "replacement needs a checkpoint for the current session generation"
            )
        if event.generation != state.current_generation.generation:
            raise SessionProjectionError("replacement targets a stale generation")
        if state.current_generation.status is not SessionGenerationStatus.ACTIVE:
            raise SessionProjectionError("generation is already fenced")
        return replace(state, replacement_requested=True, version=event.sequence)
    if event.kind is SessionLifecycleKind.GENERATION_FENCED:
        if not state.replacement_requested:
            raise SessionProjectionError("generation cannot fence before replacement request")
        if event.generation != state.current_generation.generation:
            raise SessionProjectionError("fence targets a stale generation")
        generations = (
            *state.generations[:-1],
            replace(
                state.current_generation,
                status=SessionGenerationStatus.FENCED,
                fenced_at=event.occurred_at,
            ),
        )
        return replace(state, generations=generations, version=event.sequence)
    if event.kind is SessionLifecycleKind.REPLACEMENT_COMPLETED:
        if len(state.generations) < 2:
            raise SessionProjectionError("replacement cannot complete before new launch")
        if event.generation != state.current_generation.generation:
            raise SessionProjectionError("completion targets a stale generation")
        previous = state.generations[-2]
        if previous.status is not SessionGenerationStatus.FENCED:
            raise SessionProjectionError("previous generation is not fenced")
        generations = (
            *state.generations[:-2],
            replace(previous, status=SessionGenerationStatus.REPLACED),
            state.current_generation,
        )
        return replace(
            state,
            generations=generations,
            replacement_requested=False,
            replacement_completed=True,
            version=event.sequence,
        )
    raise SessionProjectionError(f"unsupported lifecycle event {event.kind!r}")


def _require_correlation(
    state: SessionProjection, task_id: str, role: Role, attempt_id: str
) -> None:
    if (task_id, role, attempt_id) != (state.task_id, state.role, state.attempt_id):
        raise SessionProjectionError("session event changed logical attempt correlation")


def _require_observation_identity(
    generation: SessionGeneration, observation: SessionObservation
) -> None:
    if (
        generation.endpoint is not None
        and observation.endpoint is not None
        and generation.endpoint != observation.endpoint
    ) or (
        generation.session_id is not None
        and observation.session_id is not None
        and generation.session_id != observation.session_id
    ):
        raise SessionProjectionError(
            "observation identity does not match its session generation"
        )


def _require_lifecycle_identity(
    state: SessionProjection, event: SessionLifecycleEvent
) -> None:
    generation = state.current_generation
    if event.generation != generation.generation:
        raise SessionProjectionError("lifecycle event targets a stale generation")
    if (event.endpoint, event.session_id) != (
        generation.endpoint,
        generation.session_id,
    ):
        raise SessionProjectionError(
            "lifecycle event identity does not match the live session generation"
        )


def _observation_signature(observation: SessionObservation) -> tuple[object, ...]:
    return (
        observation.kind,
        observation.availability,
        observation.finality,
        observation.endpoint,
        observation.session_id,
        observation.compaction_count,
        observation.context_used_tokens,
        observation.context_window_tokens,
    )
