"""Durable Coordinator decision round trip with controller-owned authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Callable, Protocol

from milburn.domain import (
    CoordinatorNotification,
    DecisionRequest,
    DomainEvent,
    EventFact,
    EventType,
    UserDecision,
)

from .notifications import (
    COORDINATOR_STREAM,
    NotificationQueue,
    NotificationStore,
    event,
    notification_facts,
)


class CoordinatorTransport(Protocol):
    """Injected delivery boundary; it has no launch, GitHub, or approval method."""

    def wake_coordinator(self, notification_id: str) -> bool: ...

    def deliver_answer(
        self, attempt_id: str, decision_id: str, answer: UserDecision
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Decision:
    request: DecisionRequest
    state: str
    presenter: str | None = None
    answer: UserDecision | None = None


class CoordinatorSessionManager:
    """Keep one durable Coordinator inbox and correlate worker decisions."""

    def __init__(
        self,
        store: NotificationStore,
        transport: CoordinatorTransport,
        *,
        clock: Callable[[], datetime],
        event_ids: Callable[[], str],
    ) -> None:
        self._store = store
        self._transport = transport
        self._clock = clock
        self._event_ids = event_ids
        self._notifications = NotificationQueue(store, clock=clock, event_ids=event_ids)

    def register_session(self, attempt_id: str, *, endpoint: str) -> None:
        """Record the controller-provisioned primary endpoint once."""
        if (
            not isinstance(attempt_id, str) or not attempt_id
            or attempt_id != attempt_id.strip() or any(c.isspace() for c in attempt_id)
            or not isinstance(endpoint, str) or not endpoint
            or endpoint != endpoint.strip() or any(c.isspace() for c in endpoint)
        ):
            raise ValueError("attempt ID and endpoint must be identifiers")
        history = self._history()
        active = self._session(history)
        if active is not None:
            if active == (attempt_id, endpoint):
                return
            raise ValueError("a primary Coordinator session is already registered")
        self._append(history, ((EventType.COORDINATOR_SESSION_STARTED, attempt_id, (
            EventFact(name="coordinator_attempt_id", value=attempt_id),
            EventFact(name="endpoint", value=endpoint),
        )),))

    def active_session(self) -> tuple[str, str] | None:
        return self._session(self._history())

    def request_decision(self, request: DecisionRequest) -> None:
        if not isinstance(request, DecisionRequest):
            raise ValueError("request must be a DecisionRequest")
        if len(set(request.options)) != len(request.options):
            raise ValueError("decision options must be unique")
        if request.recommendation is not None and request.recommendation not in request.options:
            raise ValueError("recommendation must be an offered option")
        history = self._history()
        if request.decision_id in self._decisions(history):
            raise ValueError("decision ID already exists")
        notice = CoordinatorNotification(
            notification_id=f"decision:{request.decision_id}",
            kind="decision",
            correlation_id=request.decision_id,
            priority=2 if request.blocking else 1,
            summary=request.question,
            unread=True,
            created_at=self._clock(),
        )
        if notice.notification_id in NotificationQueue._items(history):
            raise ValueError("notification ID already exists")
        self._append(
            history,
            (
                (EventType.DECISION_REQUESTED, request.decision_id, (
                    EventFact(name="decision_id", value=request.decision_id),
                    EventFact(name="source_attempt_id", value=request.source_attempt_id),
                    EventFact(name="request", value=json.dumps(request.to_dict(), sort_keys=True)),
                )),
                (EventType.COORDINATOR_NOTIFICATION_QUEUED, request.decision_id,
                 notification_facts(notice)),
            ),
        )

    def pending_notifications(self) -> tuple[CoordinatorNotification, ...]:
        return self._notifications.unread()

    def open_decisions(self) -> tuple[DecisionRequest, ...]:
        return tuple(
            record.request for record in self._decisions(self._history()).values()
            if record.state != "resolved"
        )

    def wake_pending(self) -> int:
        """Ring the existing endpoint only; unread items stay durable until presented."""
        if self.active_session() is None:
            return 0
        count = 0
        for item in self.pending_notifications():
            if self._transport.wake_coordinator(item.notification_id):
                count += 1
        return count

    def accept_new_work(self, message: str) -> bool:
        """Refuse unrelated intake until unread results and open decisions drain."""
        if not isinstance(message, str) or not message.strip():
            raise ValueError("user message must be non-empty")
        if self.pending_notifications() or self.open_decisions():
            raise ValueError("drain Coordinator notifications and decisions first")
        history = self._history()
        self._append(history, ((EventType.USER_MESSAGE_RECEIVED, "coordinator:primary", (
            EventFact(name="message", value=message),
        )),))
        return True

    def present(self, decision_id: str, *, coordinator_attempt_id: str) -> None:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("decision ID is required")
        if not isinstance(coordinator_attempt_id, str):
            raise ValueError("coordinator attempt ID is required")
        history = self._history()
        self._required(history, decision_id, "requested")
        if not coordinator_attempt_id or coordinator_attempt_id != coordinator_attempt_id.strip():
            raise ValueError("coordinator attempt ID is required")
        active = self._session(history)
        if active is None or coordinator_attempt_id != active[0]:
            raise ValueError("only the registered Coordinator may present a decision")
        notice_id = f"decision:{decision_id}"
        notice = NotificationQueue._items(history).get(notice_id)
        if notice is None or not notice.unread:
            raise ValueError("decision notification is not unread")
        self._append(history, ((EventType.DECISION_PRESENTED, decision_id, (
            EventFact(name="decision_id", value=decision_id),
            EventFact(name="notification_id", value=notice_id),
            EventFact(name="coordinator_attempt_id", value=coordinator_attempt_id),
        )),))

    def answer(self, answer: UserDecision) -> None:
        if not isinstance(answer, UserDecision):
            raise ValueError("answer must be a UserDecision")
        history = self._history()
        record = self._required(history, answer.decision_id, "presented")
        if answer.coordinator_attempt_id != record.presenter:
            raise ValueError("answer came from a different Coordinator attempt")
        if answer.selected_option is None or answer.selected_option not in record.request.options:
            raise ValueError("answer must select exactly one offered option")
        self._append(history, (
            (EventType.USER_DECISION_RECEIVED, answer.decision_id, (
                EventFact(name="decision_id", value=answer.decision_id),
                EventFact(name="answer", value=json.dumps(answer.to_dict(), sort_keys=True)),
            )),
            (EventType.DECISION_ANSWER_VALIDATED, answer.decision_id, (
                EventFact(name="decision_id", value=answer.decision_id),
            )),
            (EventType.STEERING_QUEUED, answer.decision_id, (
                EventFact(name="decision_id", value=answer.decision_id),
                EventFact(name="source_attempt_id", value=record.request.source_attempt_id),
            )),
        ))

    def deliver_answer(self, decision_id: str) -> bool:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("decision ID is required")
        history = self._history()
        record = self._required(history, decision_id, "queued")
        if record.answer is None:
            raise ValueError("queued decision has no validated answer")
        if not self._transport.deliver_answer(
            record.request.source_attempt_id, decision_id, record.answer
        ):
            return False
        self._append(history, ((EventType.STEERING_DELIVERED, decision_id, (
            EventFact(name="decision_id", value=decision_id),
            EventFact(name="source_attempt_id", value=record.request.source_attempt_id),
        )),))
        return True

    def acknowledge(self, decision_id: str, *, attempt_id: str) -> None:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("decision ID is required")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("worker attempt ID is required")
        history = self._history()
        record = self._required(history, decision_id, "delivered")
        if attempt_id != record.request.source_attempt_id:
            raise ValueError("acknowledgement came from a different worker")
        self._append(history, (
            (EventType.STEERING_ACKNOWLEDGED, decision_id, (
                EventFact(name="decision_id", value=decision_id),
                EventFact(name="source_attempt_id", value=attempt_id),
            )),
            (EventType.DECISION_RESOLVED, decision_id, (
                EventFact(name="decision_id", value=decision_id),
            )),
        ))

    def _history(self) -> tuple[DomainEvent, ...]:
        return self._store.read_stream(COORDINATOR_STREAM)

    @staticmethod
    def _session(history: tuple[DomainEvent, ...]) -> tuple[str, str] | None:
        session: tuple[str, str] | None = None
        for recorded in history:
            if recorded.event_type is EventType.COORDINATOR_SESSION_STARTED:
                facts = {fact.name: fact.value for fact in recorded.facts}
                if session is not None:
                    raise ValueError("multiple durable primary Coordinator sessions")
                session = (facts["coordinator_attempt_id"], facts["endpoint"])
        return session

    def _append(
        self,
        history: tuple[DomainEvent, ...],
        rows: tuple[tuple[EventType, str, tuple[EventFact, ...]], ...],
    ) -> None:
        sequence = history[-1].sequence if history else -1
        events = tuple(
            event(
                kind,
                sequence=sequence + index,
                correlation_id=correlation_id,
                clock=self._clock,
                event_ids=self._event_ids,
                facts=facts,
            )
            for index, (kind, correlation_id, facts) in enumerate(rows, start=1)
        )
        self._store.append(COORDINATOR_STREAM, sequence, events)

    @staticmethod
    def _decisions(history: tuple[DomainEvent, ...]) -> dict[str, _Decision]:
        decisions: dict[str, _Decision] = {}
        transitions = {
            EventType.DECISION_PRESENTED: ("requested", "presented"),
            EventType.USER_DECISION_RECEIVED: ("presented", "answered"),
            EventType.DECISION_ANSWER_VALIDATED: ("answered", "validated"),
            EventType.STEERING_QUEUED: ("validated", "queued"),
            EventType.STEERING_DELIVERED: ("queued", "delivered"),
            EventType.STEERING_ACKNOWLEDGED: ("delivered", "acknowledged"),
            EventType.DECISION_RESOLVED: ("acknowledged", "resolved"),
        }
        for recorded in history:
            facts = {fact.name: fact.value for fact in recorded.facts}
            if recorded.event_type is EventType.DECISION_REQUESTED:
                request = DecisionRequest.from_dict(json.loads(facts["request"]))
                if request.decision_id in decisions:
                    raise ValueError("duplicate durable decision ID")
                decisions[request.decision_id] = _Decision(request, "requested")
            elif recorded.event_type in transitions:
                identifier = facts["decision_id"]
                prior = decisions.get(identifier)
                before, after = transitions[recorded.event_type]
                if prior is None or prior.state != before:
                    raise ValueError("invalid durable decision transition")
                presenter = facts.get("coordinator_attempt_id", prior.presenter)
                answer = (
                    UserDecision.from_dict(json.loads(facts["answer"]))
                    if recorded.event_type is EventType.USER_DECISION_RECEIVED
                    else prior.answer
                )
                decisions[identifier] = _Decision(prior.request, after, presenter, answer)
        return decisions

    @classmethod
    def _required(
        cls, history: tuple[DomainEvent, ...], decision_id: str, state: str
    ) -> _Decision:
        record = cls._decisions(history).get(decision_id)
        if record is None or record.state != state:
            raise ValueError(f"decision is unknown or not {state}")
        return record
