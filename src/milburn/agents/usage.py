"""Convert supported Codex semantic usage payloads into domain observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from milburn.domain.states import Role
from milburn.domain.usage import (
    TOKEN_FIELDS,
    TokenCounts,
    TokenUsageObservation,
    UsageObservationKind,
)


class SemanticUsageError(ValueError):
    """Raised when a supported semantic API returns an invalid usage payload."""


@dataclass(frozen=True, slots=True)
class UsageCorrelation:
    task_id: str
    role: Role
    attempt_id: str
    endpoint: str | None = None
    session_id: str | None = None
    model: str | None = None


class CodexUsageConverter:
    """Strict semantic boundary; it never accepts terminal text or prose."""

    _FIELDS = frozenset({"source_version", "kind", "cumulative", *TOKEN_FIELDS})

    def observe(
        self,
        *,
        observation_id: str,
        correlation: UsageCorrelation,
        observed_at: datetime,
        semantic_payload: Mapping[str, object] | None,
        unavailable_source_version: str = "unavailable",
    ) -> TokenUsageObservation:
        if not isinstance(correlation, UsageCorrelation):
            raise SemanticUsageError("usage correlation is required")
        if semantic_payload is None:
            return TokenUsageObservation(
                observation_id=observation_id,
                source_version=unavailable_source_version,
                task_id=correlation.task_id,
                role=correlation.role,
                attempt_id=correlation.attempt_id,
                endpoint=correlation.endpoint,
                session_id=correlation.session_id,
                model=correlation.model,
                kind=UsageObservationKind.UNAVAILABLE,
                counts=None,
                cumulative=False,
                observed_at=observed_at,
            )
        if not isinstance(semantic_payload, Mapping):
            raise SemanticUsageError(
                "usage must come from a structured Codex semantic payload"
            )
        fields = frozenset(semantic_payload)
        unknown = fields - self._FIELDS
        required = {"source_version", "kind", "cumulative"}
        missing = required - fields
        if unknown or missing:
            details = []
            if missing:
                details.append(f"missing {sorted(missing)}")
            if unknown:
                details.append(f"unknown {sorted(unknown)}")
            raise SemanticUsageError(
                "invalid semantic usage fields: " + ", ".join(details)
            )

        try:
            kind = UsageObservationKind(semantic_payload["kind"])
        except (TypeError, ValueError) as error:
            raise SemanticUsageError(
                f"unknown usage kind {semantic_payload['kind']!r}"
            ) from error
        cumulative = semantic_payload["cumulative"]
        if not isinstance(cumulative, bool):
            raise SemanticUsageError("cumulative must be a boolean")
        source_version = semantic_payload["source_version"]
        if not isinstance(source_version, str):
            raise SemanticUsageError("source_version must be an identifier")

        reported: dict[str, int | None] = {}
        for field_name in TOKEN_FIELDS:
            value = semantic_payload.get(field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise SemanticUsageError(
                    f"{field_name} must be a non-negative integer when reported"
                )
            reported[field_name] = value
        if kind is UsageObservationKind.UNAVAILABLE and any(
            value is not None for value in reported.values()
        ):
            raise SemanticUsageError(
                "unavailable usage must not contain fabricated token counts"
            )
        counts = (
            None
            if kind is UsageObservationKind.UNAVAILABLE
            else TokenCounts(**reported)
        )
        try:
            return TokenUsageObservation(
                observation_id=observation_id,
                source_version=source_version,
                task_id=correlation.task_id,
                role=correlation.role,
                attempt_id=correlation.attempt_id,
                endpoint=correlation.endpoint,
                session_id=correlation.session_id,
                model=correlation.model,
                kind=kind,
                counts=counts,
                cumulative=cumulative,
                observed_at=observed_at,
            )
        except ValueError as error:
            raise SemanticUsageError(str(error)) from error
