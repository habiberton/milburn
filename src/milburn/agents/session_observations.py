"""Strict conversion of supported Codex session semantic observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from milburn.domain.sessions import (
    ObservationAvailability,
    ObservationFinality,
    SessionObservation,
    SessionObservationKind,
)
from milburn.domain.states import Role


class SemanticSessionObservationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionCorrelation:
    task_id: str
    role: Role
    attempt_id: str
    generation: int
    endpoint: str | None = None
    session_id: str | None = None


class CodexSessionObservationConverter:
    """Accept structured API data only; never inspect terminal prose."""

    _FIELDS = frozenset(
        {
            "kind",
            "availability",
            "source_version",
            "finality",
            "endpoint",
            "session_id",
            "compaction_count",
            "context_used_tokens",
            "context_window_tokens",
        }
    )

    def observe(
        self,
        *,
        observation_id: str,
        correlation: SessionCorrelation,
        observed_at: datetime,
        semantic_payload: Mapping[str, object] | None,
        unavailable_kind: SessionObservationKind | None = None,
        unavailable_source_version: str | None = None,
    ) -> SessionObservation:
        if not isinstance(correlation, SessionCorrelation):
            raise SemanticSessionObservationError("session correlation is required")
        if semantic_payload is None:
            if unavailable_kind is None:
                raise SemanticSessionObservationError(
                    "unavailable observations require the unsupported observation kind"
                )
            return SessionObservation(
                observation_id=observation_id,
                task_id=correlation.task_id,
                role=correlation.role,
                attempt_id=correlation.attempt_id,
                generation=correlation.generation,
                endpoint=correlation.endpoint,
                session_id=correlation.session_id,
                kind=unavailable_kind,
                availability=ObservationAvailability.UNAVAILABLE,
                source_version=(
                    unavailable_source_version
                    or f"unavailable-{unavailable_kind.value}"
                ),
                observed_at=observed_at,
                finality=ObservationFinality.FINAL,
            )
        if not isinstance(semantic_payload, Mapping):
            raise SemanticSessionObservationError(
                "session observation must come from a structured semantic payload"
            )
        fields = frozenset(semantic_payload)
        unknown = fields - self._FIELDS
        required = {"kind", "availability", "source_version", "finality"}
        missing = required - fields
        if unknown or missing:
            details = []
            if missing:
                details.append(f"missing {sorted(missing)}")
            if unknown:
                details.append(f"unknown {sorted(unknown)}")
            raise SemanticSessionObservationError(
                "invalid semantic session fields: " + ", ".join(details)
            )
        try:
            kind = SessionObservationKind(semantic_payload["kind"])
            availability = ObservationAvailability(semantic_payload["availability"])
            finality = ObservationFinality(semantic_payload["finality"])
            source_version = semantic_payload["source_version"]
            if not isinstance(source_version, str):
                raise TypeError("source_version must be an identifier")
            endpoint = self._optional_identifier(semantic_payload.get("endpoint"), "endpoint")
            session_id = self._optional_identifier(
                semantic_payload.get("session_id"), "session_id"
            )
            numbers = {
                name: self._optional_count(semantic_payload.get(name), name)
                for name in (
                    "compaction_count",
                    "context_used_tokens",
                    "context_window_tokens",
                )
            }
            return SessionObservation(
                observation_id=observation_id,
                task_id=correlation.task_id,
                role=correlation.role,
                attempt_id=correlation.attempt_id,
                generation=correlation.generation,
                endpoint=endpoint if endpoint is not None else correlation.endpoint,
                session_id=(
                    session_id if session_id is not None else correlation.session_id
                ),
                kind=kind,
                availability=availability,
                source_version=source_version,
                observed_at=observed_at,
                finality=finality,
                **numbers,
            )
        except (TypeError, ValueError) as error:
            raise SemanticSessionObservationError(str(error)) from error

    @staticmethod
    def _optional_identifier(value: object, name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be an identifier")
        return value

    @staticmethod
    def _optional_count(value: object, name: str) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError(f"{name} must be a non-negative integer")
        return value
