"""Event recording and replay for the ``milburn`` CLI (PRD R26, ARCH §3).

Every CLI event carries two facts: ``actor`` (``controller`` or
``coordinator``) and ``payload`` (canonical JSON). State is never stored
elsewhere: ``replay`` folds the event store into ``ProjectState``.

Streams: ``project`` allocates work item and task IDs; ``task-<id>`` holds one
task's attempts, gate decisions, and integration; ``work-<id>`` holds delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
import uuid

from milburn.domain.events import DomainEvent, EventFact, EventType
from milburn.persistence.sqlite_store import SQLiteEventStore

ACTORS = ("controller", "coordinator")
NO_STREAM = -1


@dataclass(slots=True)
class Attempt:
    attempt_id: str
    role: str
    harness: str
    endpoint: str
    worktree: str
    base_sha: str
    sandbox: str
    candidate_sha: str | None = None
    started: dict[str, Any] | None = None
    collected: dict[str, Any] | None = None


@dataclass(slots=True)
class Task:
    task_id: str
    work_item: str
    task_type: str
    title: str
    objective: str
    acceptance: list[str]
    branch: str
    attempts: list[Attempt] = field(default_factory=list)
    completed: dict[str, Any] | None = None
    integrated: dict[str, Any] | None = None
    refusals: int = 0

    def latest(self, role: str) -> Attempt | None:
        matching = [attempt for attempt in self.attempts if attempt.role == role]
        return matching[-1] if matching else None


@dataclass(slots=True)
class WorkItem:
    work_item: str
    title: str
    base_sha: str
    branch: str
    integration_worktree: str
    tasks: list[str] = field(default_factory=list)
    last_merge: str | None = None
    delivered: dict[str, Any] | None = None

    @property
    def expected_head(self) -> str:
        """The integration head the record says is current."""

        return self.last_merge or self.base_sha


@dataclass(slots=True)
class ProjectState:
    work_items: dict[str, WorkItem] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    usage: list[dict[str, Any]] = field(default_factory=list)
    sequences: dict[str, int] = field(default_factory=dict)


def payload_of(event: DomainEvent) -> dict[str, Any]:
    facts = {fact.name: fact.value for fact in event.facts}
    return json.loads(facts["payload"])


def actor_of(event: DomainEvent) -> str:
    return {fact.name: fact.value for fact in event.facts}["actor"]


class Ledger:
    """Append CLI events with optimistic concurrency and replay them."""

    def __init__(self, store: SQLiteEventStore) -> None:
        self._store = store

    def append(
        self,
        stream: str,
        expected_sequence: int,
        event_type: EventType,
        payload: dict[str, Any],
        *,
        actor: str,
        correlation_id: str,
    ) -> DomainEvent:
        if actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}")
        event = DomainEvent(
            event_id=f"evt-{uuid.uuid4().hex}",
            stream=stream,
            sequence=expected_sequence + 1,
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            causation_id=None,
            facts=(
                EventFact(name="actor", value=actor),
                EventFact(
                    name="payload",
                    value=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            ),
        )
        return self._store.append(stream, expected_sequence, (event,))[0]

    def append_many(
        self,
        stream: str,
        expected_sequence: int,
        items: list[tuple[EventType, dict[str, Any]]],
        *,
        actor: str,
        correlation_id: str,
    ) -> tuple[DomainEvent, ...]:
        """Append several events atomically: all of them or none."""

        if actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}")
        now = datetime.now(timezone.utc)
        events = tuple(
            DomainEvent(
                event_id=f"evt-{uuid.uuid4().hex}",
                stream=stream,
                sequence=expected_sequence + offset,
                event_type=event_type,
                occurred_at=now,
                correlation_id=correlation_id,
                causation_id=None,
                facts=(
                    EventFact(name="actor", value=actor),
                    EventFact(
                        name="payload",
                        value=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    ),
                ),
            )
            for offset, (event_type, payload) in enumerate(items, start=1)
        )
        return self._store.append(stream, expected_sequence, events)

    def replay(self) -> ProjectState:
        state = ProjectState()
        for event in self._store.read_all():
            state.sequences[event.stream] = event.sequence
            data = payload_of(event)
            kind = event.event_type
            if kind is EventType.WORK_ITEM_OPENED:
                state.work_items[data["work_item"]] = WorkItem(
                    data["work_item"], data["title"], data["base_sha"],
                    data["branch"], data["integration_worktree"],
                )
            elif kind is EventType.TASK_CREATED:
                state.tasks[data["task"]] = Task(
                    data["task"], data["work_item"], data["task_type"], data["title"],
                    data["objective"], list(data["acceptance"]), data["branch"],
                )
                state.work_items[data["work_item"]].tasks.append(data["task"])
            elif kind is EventType.ATTEMPT_DISPATCHED:
                state.tasks[data["task"]].attempts.append(
                    Attempt(
                        data["attempt"], data["role"], data["harness"], data["endpoint"],
                        data["worktree"], data["base_sha"], data["sandbox"],
                        data.get("candidate_sha"),
                    )
                )
            elif kind is EventType.AGENT_STARTED:
                for attempt in state.tasks[data["task"]].attempts:
                    if attempt.attempt_id == data["attempt"]:
                        attempt.started = data
            elif kind is EventType.ATTEMPT_COLLECTED:
                task = state.tasks[data["task"]]
                for attempt in task.attempts:
                    if attempt.attempt_id == data["attempt"]:
                        attempt.collected = data
            elif kind is EventType.AGENT_USAGE_OBSERVED:
                state.usage.append(data)
            elif kind in (EventType.ATTEMPT_HANDED_OFF, EventType.SESSION_GENERATION_EXHAUSTED):
                pass  # recorded for audit and reports; dispatch carries the state
            elif kind is EventType.QA_GATE_REFUSED:
                state.tasks[data["task"]].refusals += 1
            elif kind is EventType.TASK_COMPLETED:
                state.tasks[data["task"]].completed = data
            elif kind is EventType.TASK_INTEGRATED:
                state.tasks[data["task"]].integrated = data
                state.work_items[data["work_item"]].last_merge = data["merge_sha"]
            elif kind is EventType.WORK_ITEM_DELIVERED:
                state.work_items[data["work_item"]].delivered = data
        return state

    def sequence(self, stream: str) -> int:
        return self._store.stream_sequence(stream)
