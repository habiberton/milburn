"""Strict versioned contracts for observability-only token usage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .base import (
    VersionedModel,
    require_bool,
    require_enum,
    require_identifier,
    require_non_negative,
    require_timezone_aware,
)
from .errors import InvalidEnvelopeError
from .states import Role


class UsageObservationKind(StrEnum):
    """Whether an observation is provisional, authoritative, or unavailable."""

    PARTIAL = "partial"
    FINAL = "final"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TokenCounts(VersionedModel):
    """Only token dimensions actually reported by Codex."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        for field_name in TOKEN_FIELDS:
            value = getattr(self, field_name)
            if value is not None:
                require_non_negative(value, field_name)

    @property
    def has_reported_value(self) -> bool:
        return any(getattr(self, field_name) is not None for field_name in TOKEN_FIELDS)


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
)


@dataclass(frozen=True, slots=True)
class TokenUsageObservation(VersionedModel):
    """One append-only usage fact emitted at the Codex semantic boundary."""

    observation_id: str
    source_version: str
    task_id: str
    role: Role
    attempt_id: str
    endpoint: str | None
    session_id: str | None
    model: str | None
    kind: UsageObservationKind
    counts: TokenCounts | None
    cumulative: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.observation_id, "observation_id")
        require_identifier(self.source_version, "source_version")
        require_identifier(self.task_id, "task_id")
        require_enum(self.role, Role, "role")
        require_identifier(self.attempt_id, "attempt_id")
        for field_name in ("endpoint", "session_id", "model"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name)
        require_enum(self.kind, UsageObservationKind, "kind")
        require_bool(self.cumulative, "cumulative")
        require_timezone_aware(self.observed_at, "observed_at")

        if self.kind is UsageObservationKind.UNAVAILABLE:
            if self.counts is not None:
                raise InvalidEnvelopeError(
                    "unavailable usage must not contain fabricated token counts"
                )
            if self.cumulative:
                raise InvalidEnvelopeError(
                    "unavailable usage cannot claim cumulative counter semantics"
                )
            return
        if self.counts is None or not self.counts.has_reported_value:
            raise InvalidEnvelopeError(
                "partial and final usage require at least one reported token count"
            )
        if self.kind is UsageObservationKind.FINAL and not self.cumulative:
            raise InvalidEnvelopeError(
                "final usage is an authoritative cumulative total"
            )

    @property
    def source_key(self) -> tuple[str, str, str, str, str]:
        """Stable source identity used to reconcile cumulative snapshots."""

        return (
            self.task_id,
            self.role.value,
            self.attempt_id,
            self.session_id or "",
            self.endpoint or "",
        )
