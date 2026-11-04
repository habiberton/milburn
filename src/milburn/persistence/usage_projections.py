"""Deterministic replay of append-only token usage observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from milburn.domain.usage import (
    TOKEN_FIELDS,
    TokenCounts,
    TokenUsageObservation,
    UsageObservationKind,
)


class UsageProjectionError(ValueError):
    """Raised when usage facts cannot form one deterministic projection."""


class UsageAvailability(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class UsageFinality(StrEnum):
    FINAL = "final"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class UsageAggregate:
    """Reported token subtotal plus explicit completeness/finality evidence."""

    reported_tokens: TokenCounts
    availability: UsageAvailability
    finality: UsageFinality


@dataclass(frozen=True, slots=True)
class TokenUsageSummary:
    attempt_totals: Mapping[str, UsageAggregate] = field(default_factory=dict)
    task_totals: Mapping[str, UsageAggregate] = field(default_factory=dict)
    role_totals: Mapping[str, UsageAggregate] = field(default_factory=dict)
    workflow_totals: UsageAggregate = field(
        default_factory=lambda: UsageAggregate(
            TokenCounts(), UsageAvailability.UNAVAILABLE, UsageFinality.UNAVAILABLE
        )
    )

    def __post_init__(self) -> None:
        for name in ("attempt_totals", "task_totals", "role_totals"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(slots=True)
class _SourceState:
    task_id: str
    role: str
    attempt_id: str
    session_id: str | None
    endpoint: str | None
    counts: dict[str, int | None] = field(
        default_factory=lambda: {field_name: None for field_name in TOKEN_FIELDS}
    )
    versions: dict[str, tuple[object, ...]] = field(default_factory=dict)
    available: bool = False
    unavailable_seen: bool = False
    final: bool = False


def project_usage_events(
    observations: Iterable[TokenUsageObservation],
) -> TokenUsageSummary:
    """Replay usage facts; exact duplicate delivery never changes totals."""

    seen_ids: dict[str, TokenUsageObservation] = {}
    sources: list[_SourceState] = []
    attempt_correlations: dict[str, tuple[str, str]] = {}

    for observation in observations:
        if not isinstance(observation, TokenUsageObservation):
            raise UsageProjectionError("usage replay accepts only usage observations")
        duplicate = seen_ids.get(observation.observation_id)
        if duplicate is not None:
            if duplicate != observation:
                raise UsageProjectionError(
                    f"observation ID {observation.observation_id} has "
                    "conflicting content"
                )
            continue
        seen_ids[observation.observation_id] = observation

        correlation = (observation.task_id, observation.role.value)
        previous_correlation = attempt_correlations.setdefault(
            observation.attempt_id, correlation
        )
        if previous_correlation != correlation:
            raise UsageProjectionError(
                f"attempt {observation.attempt_id} changed task or role correlation"
            )

        state = _resolve_source(sources, observation)
        signature = _semantic_signature(observation)
        previous_version = state.versions.get(observation.source_version)
        if previous_version is not None:
            if previous_version != signature:
                raise UsageProjectionError(
                    f"source version {observation.source_version} has "
                    "conflicting content"
                )
            continue
        state.versions[observation.source_version] = signature

        if state.final:
            raise UsageProjectionError(
                "usage observation arrived after the source's final total"
            )
        if observation.kind is UsageObservationKind.UNAVAILABLE:
            state.unavailable_seen = True
            continue

        assert observation.counts is not None
        state.available = True
        for field_name in TOKEN_FIELDS:
            reported = getattr(observation.counts, field_name)
            if reported is None:
                continue
            current = state.counts[field_name]
            if observation.cumulative:
                if current is not None and reported < current:
                    raise UsageProjectionError(
                        f"cumulative {field_name} regressed from {current} "
                        f"to {reported}"
                    )
                state.counts[field_name] = reported
            else:
                state.counts[field_name] = (current or 0) + reported
        if observation.kind is UsageObservationKind.FINAL:
            state.final = True

    attempt_sources: dict[str, list[_SourceState]] = {}
    task_sources: dict[str, list[_SourceState]] = {}
    role_sources: dict[str, list[_SourceState]] = {}
    all_sources: list[_SourceState] = []
    for state in sources:
        attempt_sources.setdefault(state.attempt_id, []).append(state)
        task_sources.setdefault(state.task_id, []).append(state)
        role_sources.setdefault(state.role, []).append(state)
        all_sources.append(state)

    return TokenUsageSummary(
        attempt_totals={
            key: _aggregate(value) for key, value in attempt_sources.items()
        },
        task_totals={key: _aggregate(value) for key, value in task_sources.items()},
        role_totals={key: _aggregate(value) for key, value in role_sources.items()},
        workflow_totals=_aggregate(all_sources),
    )


def _semantic_signature(observation: TokenUsageObservation) -> tuple[object, ...]:
    """Exclude delivery identity/time and late optional correlation metadata."""

    return (
        observation.task_id,
        observation.role,
        observation.attempt_id,
        observation.kind,
        observation.counts,
        observation.cumulative,
    )


def _resolve_source(
    sources: list[_SourceState], observation: TokenUsageObservation
) -> _SourceState:
    candidates = [source for source in sources if _compatible(source, observation)]
    if not candidates:
        source = _SourceState(
            task_id=observation.task_id,
            role=observation.role.value,
            attempt_id=observation.attempt_id,
            session_id=observation.session_id,
            endpoint=observation.endpoint,
        )
        sources.append(source)
        return source
    if len(candidates) > 1:
        scores = [(_match_score(source, observation), source) for source in candidates]
        best_score = max(score for score, _source in scores)
        best = [source for score, source in scores if score == best_score]
        if best_score == 0 or len(best) != 1:
            raise UsageProjectionError(
                "usage source is ambiguous without stable session or endpoint evidence"
            )
        source = best[0]
    else:
        source = candidates[0]
    if source.session_id is None:
        source.session_id = observation.session_id
    if source.endpoint is None:
        source.endpoint = observation.endpoint
    return source


def _compatible(source: _SourceState, observation: TokenUsageObservation) -> bool:
    if (
        source.task_id,
        source.role,
        source.attempt_id,
    ) != (
        observation.task_id,
        observation.role.value,
        observation.attempt_id,
    ):
        return False
    return not (
        source.session_id is not None
        and observation.session_id is not None
        and source.session_id != observation.session_id
    ) and not (
        source.endpoint is not None
        and observation.endpoint is not None
        and source.endpoint != observation.endpoint
    )


def _match_score(source: _SourceState, observation: TokenUsageObservation) -> int:
    return sum(
        (
            observation.session_id is not None
            and source.session_id == observation.session_id,
            observation.endpoint is not None
            and source.endpoint == observation.endpoint,
        )
    )


def _aggregate(sources: list[_SourceState]) -> UsageAggregate:
    totals: dict[str, int | None] = {}
    for field_name in TOKEN_FIELDS:
        values = [source.counts[field_name] for source in sources]
        reported = [value for value in values if value is not None]
        totals[field_name] = sum(reported) if reported else None

    available_sources = [source for source in sources if source.available]
    unavailable_seen = any(source.unavailable_seen for source in sources)
    counts_complete = all(value is not None for value in totals.values())
    if not available_sources:
        availability = UsageAvailability.UNAVAILABLE
        finality = UsageFinality.UNAVAILABLE
    else:
        availability = (
            UsageAvailability.COMPLETE
            if counts_complete and not unavailable_seen
            else UsageAvailability.PARTIAL
        )
        finality = (
            UsageFinality.FINAL
            if len(available_sources) == len(sources)
            and all(source.final for source in available_sources)
            else UsageFinality.PARTIAL
        )
    return UsageAggregate(TokenCounts(**totals), availability, finality)
