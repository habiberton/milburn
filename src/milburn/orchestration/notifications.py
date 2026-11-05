"""Coordinator notifications persisted in the shared append-only event stream."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Callable, Protocol

from milburn.domain import CoordinatorNotification, DomainEvent, EventFact, EventType


COORDINATOR_STREAM = "coordinator:primary"


class NotificationStore(Protocol):
    def read_stream(self, stream: str, *, after_sequence: int = -1) -> tuple[DomainEvent, ...]: ...

    def append(
        self, stream: str, expected_sequence: int, events: tuple[DomainEvent, ...]
    ) -> tuple[DomainEvent, ...]: ...


def event(
    event_type: EventType,
    *,
    sequence: int,
    correlation_id: str,
    clock: Callable[[], datetime],
    event_ids: Callable[[], str],
    facts: tuple[EventFact, ...],
) -> DomainEvent:
    return DomainEvent(
        event_id=f"{event_ids()}-{sequence}",
        stream=COORDINATOR_STREAM,
        sequence=sequence,
        event_type=event_type,
        occurred_at=clock(),
        correlation_id=correlation_id,
        causation_id=None,
        facts=facts,
    )


def notification_facts(item: CoordinatorNotification) -> tuple[EventFact, ...]:
    return (
        EventFact(name="notification_id", value=item.notification_id),
        EventFact(name="notification", value=json.dumps(item.to_dict(), sort_keys=True)),
    )


class NotificationQueue:
    """Replay unread items; never discard a notification merely because waking failed."""

    def __init__(
        self,
        store: NotificationStore,
        *,
        clock: Callable[[], datetime],
        event_ids: Callable[[], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._event_ids = event_ids

    def queue(self, item: CoordinatorNotification) -> None:
        if not isinstance(item, CoordinatorNotification) or not item.unread:
            raise ValueError("new notification must be a validated unread item")
        if item.kind not in {"decision", "result", "failure"}:
            raise ValueError("notification kind is not actionable")
        history = self._store.read_stream(COORDINATOR_STREAM)
        if item.notification_id in self._items(history):
            raise ValueError("notification ID already exists")
        sequence = history[-1].sequence if history else -1
        self._store.append(
            COORDINATOR_STREAM,
            sequence,
            (
                event(
                    EventType.COORDINATOR_NOTIFICATION_QUEUED,
                    sequence=sequence + 1,
                    correlation_id=item.correlation_id,
                    clock=self._clock,
                    event_ids=self._event_ids,
                    facts=notification_facts(item),
                ),
            ),
        )

    def unread(self) -> tuple[CoordinatorNotification, ...]:
        items = self._items(self._store.read_stream(COORDINATOR_STREAM))
        return tuple(
            sorted(
                (item for item in items.values() if item.unread),
                key=lambda item: (-item.priority, item.created_at, item.notification_id),
            )
        )

    @staticmethod
    def _items(history: tuple[DomainEvent, ...]) -> dict[str, CoordinatorNotification]:
        items: dict[str, CoordinatorNotification] = {}
        for recorded in history:
            facts = {fact.name: fact.value for fact in recorded.facts}
            if recorded.event_type is EventType.COORDINATOR_NOTIFICATION_QUEUED:
                item = CoordinatorNotification.from_dict(json.loads(facts["notification"]))
                if item.notification_id in items:
                    raise ValueError("duplicate durable notification ID")
                items[item.notification_id] = item
            elif recorded.event_type in (
                EventType.COORDINATOR_NOTIFICATION_READ,
                EventType.DECISION_PRESENTED,
            ) and "notification_id" in facts:
                identifier = facts["notification_id"]
                prior = items.get(identifier)
                if prior is None or not prior.unread:
                    raise ValueError("invalid durable notification read")
                items[identifier] = CoordinatorNotification.from_dict(
                    {**prior.to_dict(), "unread": False}
                )
        return items
