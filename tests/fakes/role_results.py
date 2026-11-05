"""Deterministic semantic result documents for role coordinator tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from milburn.agents.result_parser import ResultCorrelation, ResultExpectation
from milburn.domain import DomainEvent, EventFact, EventType, Role, VersionedModel
from milburn.persistence.sqlite_store import SQLiteEventStore


def expectation(role: Role, result_type: str) -> ResultExpectation:
    return ResultExpectation(
        correlation=ResultCorrelation(
            role=role, task_id="feature-1", attempt_id=f"{role.value}-1"
        ),
        result_type=result_type,
    )


def document(
    model: VersionedModel, expected: ResultExpectation, *,
    schema_version: int = 1, role: str | None = None,
    payload_extra: dict[str, object] | None = None,
) -> str:
    payload = model.to_dict()
    payload.update(payload_extra or {})
    return json.dumps({
        "schema_version": schema_version,
        "role": role or expected.correlation.role.value,
        "task_id": expected.correlation.task_id,
        "attempt_id": expected.correlation.attempt_id,
        "task_success": True,
        "result_type": expected.result_type,
        "payload": payload,
    })


def seed_event(
    store: SQLiteEventStore, kind: EventType, *,
    feature_id: str = "feature-1", facts: dict[str, str] | None = None,
    stream_override: str | None = None,
) -> None:
    stream = stream_override or f"feature:{feature_id}"
    sequence = store.stream_sequence(stream)
    store.append(stream, sequence, (DomainEvent(
        event_id=f"seed-{stream.replace(':', '-')}-{sequence + 1}",
        stream=stream, sequence=sequence + 1, event_type=kind,
        occurred_at=datetime(2026, 11, 4, tzinfo=UTC),
        correlation_id=feature_id, causation_id=None,
        facts=tuple(
            EventFact(name=name, value=value)
            for name, value in (facts or {}).items()
        ),
    ),))
