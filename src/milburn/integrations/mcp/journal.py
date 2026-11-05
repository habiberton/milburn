"""Effect journal and generation fence for uncertain external mutations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re
from typing import Protocol


def _require_identifier(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value) is None
    ):
        raise ValueError(f"{name} must be a compact identifier")


@dataclass(frozen=True, slots=True)
class EffectFence:
    """Controller-owned correlation used to reject stale session generations."""

    task_id: str
    attempt_id: str
    generation: int

    def __post_init__(self) -> None:
        _require_identifier(self.task_id, "task_id")
        _require_identifier(self.attempt_id, "attempt_id")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise ValueError("generation must be an integer")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")


class EffectStatus(StrEnum):
    REQUESTED = "requested"
    RECONCILED = "reconciled"
    CALL_STARTED = "call_started"
    OBSERVED = "observed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EffectRequest:
    effect_id: str
    repository_id: str
    operation: str
    idempotency_marker: str
    arguments_digest: str
    fence: EffectFence


@dataclass(frozen=True, slots=True)
class EffectRecord:
    request: EffectRequest
    status: EffectStatus
    remote_identity: str | None = None


class EffectConflictError(ValueError):
    """An effect ID was reused for a different mutation."""


class StaleGenerationError(ValueError):
    """A mutation came from a fenced session generation."""


class EffectJournal(Protocol):
    def request(self, request: EffectRequest) -> EffectRecord: ...

    def transition(
        self,
        effect_id: str,
        status: EffectStatus,
        *,
        remote_identity: str | None = None,
    ) -> EffectRecord: ...

    def get(self, effect_id: str) -> EffectRecord | None: ...


class GenerationFence(Protocol):
    def assert_current(self, fence: EffectFence) -> None: ...


class InMemoryGenerationFence:
    """Deterministic controller-side fence suitable for local composition/tests."""

    def __init__(self) -> None:
        self._current: dict[tuple[str, str], int] = {}

    def activate(self, task_id: str, attempt_id: str, generation: int) -> None:
        key = (task_id, attempt_id)
        current = self._current.get(key)
        if current is not None and generation < current:
            raise StaleGenerationError("cannot reactivate an older generation")
        self._current[key] = generation

    def assert_current(self, fence: EffectFence) -> None:
        current = self._current.get((fence.task_id, fence.attempt_id))
        if current is None or current != fence.generation:
            raise StaleGenerationError(
                f"generation {fence.generation} is not active for "
                f"{fence.task_id}/{fence.attempt_id}"
            )


class InMemoryEffectJournal:
    """Append-observable local journal; production persistence implements the protocol."""

    def __init__(self) -> None:
        self._records: dict[str, EffectRecord] = {}
        self._markers: dict[tuple[str, str], str] = {}
        self.history: list[EffectRecord] = []

    def request(self, request: EffectRequest) -> EffectRecord:
        current = self._records.get(request.effect_id)
        if current is not None:
            if (
                current.request.fence.task_id != request.fence.task_id
                or replace(current.request, fence=request.fence) != request
            ):
                raise EffectConflictError(
                    f"effect ID {request.effect_id!r} is already bound to another request"
                )
            if current.request.fence != request.fence:
                current = replace(current, request=request)
                self._store(current)
            return current
        marker_key = (request.repository_id, request.idempotency_marker)
        marker_effect = self._markers.get(marker_key)
        if marker_effect is not None:
            raise EffectConflictError(
                f"idempotency marker {request.idempotency_marker!r} is already "
                f"bound to effect {marker_effect!r}"
            )
        record = EffectRecord(request=request, status=EffectStatus.REQUESTED)
        self._markers[marker_key] = request.effect_id
        self._store(record)
        return record

    def transition(
        self,
        effect_id: str,
        status: EffectStatus,
        *,
        remote_identity: str | None = None,
    ) -> EffectRecord:
        try:
            current = self._records[effect_id]
        except KeyError as error:
            raise EffectConflictError(f"unknown effect ID {effect_id!r}") from error
        allowed = {
            EffectStatus.REQUESTED: {EffectStatus.RECONCILED},
            EffectStatus.RECONCILED: {
                EffectStatus.CALL_STARTED,
                EffectStatus.OBSERVED,
            },
            EffectStatus.CALL_STARTED: {
                EffectStatus.RECONCILED,
                EffectStatus.OBSERVED,
                EffectStatus.UNCERTAIN,
            },
            EffectStatus.UNCERTAIN: {
                EffectStatus.RECONCILED,
                EffectStatus.OBSERVED,
            },
            EffectStatus.OBSERVED: {EffectStatus.OBSERVED},
        }
        if status not in allowed[current.status]:
            raise EffectConflictError(
                f"invalid effect transition {current.status.value} -> {status.value}"
            )
        if status is EffectStatus.OBSERVED and not remote_identity:
            raise EffectConflictError("observed effects require a remote identity")
        if status is not EffectStatus.OBSERVED and remote_identity is not None:
            raise EffectConflictError("only observed effects have a remote identity")
        record = replace(current, status=status, remote_identity=remote_identity)
        self._store(record)
        return record

    def get(self, effect_id: str) -> EffectRecord | None:
        return self._records.get(effect_id)

    def _store(self, record: EffectRecord) -> None:
        self._records[record.request.effect_id] = record
        self.history.append(record)
