"""Scripted decision path through durable state and unavailable transports."""

from datetime import UTC, datetime

import pytest

from milburn.domain import DecisionRequest, UserDecision
from milburn.orchestration.coordinator import CoordinatorSessionManager
from milburn.persistence.sqlite_store import SQLiteEventStore


NOW = datetime(2026, 11, 4, tzinfo=UTC)


class ScriptedTransport:
    def __init__(self) -> None:
        self.available = False
        self.wakes: list[str] = []
        self.deliveries: list[tuple[str, str]] = []

    def wake_coordinator(self, notification_id: str) -> bool:
        if not self.available:
            return False
        self.wakes.append(notification_id)
        return True

    def deliver_answer(
        self, attempt_id: str, decision_id: str, answer: UserDecision
    ) -> bool:
        if not self.available:
            return False
        self.deliveries.append((attempt_id, decision_id))
        return True


def service(store: SQLiteEventStore, transport: ScriptedTransport) -> CoordinatorSessionManager:
    ids = (f"event-{i}" for i in range(100))
    return CoordinatorSessionManager(
        store, transport, clock=lambda: NOW, event_ids=lambda: next(ids)
    )


def test_unavailable_coordinator_ambiguous_answer_and_restart(tmp_path) -> None:
    database = tmp_path / "events.db"
    transport = ScriptedTransport()
    request = DecisionRequest(
        decision_id="decision-77",
        source_attempt_id="coder-77",
        feature_id="feature-3",
        issue_number=77,
        question="Which implementation?",
        why_it_matters="The worker is blocked",
        options=("minimal", "complete"),
        recommendation="minimal",
        blocking=True,
    )
    with SQLiteEventStore(database) as store:
        coordinator = service(store, transport)
        coordinator.register_session("coordinator-1", endpoint="tmux:coordinator")
        coordinator.request_decision(request)
        assert coordinator.wake_pending() == 0
        with pytest.raises(ValueError):
            coordinator.accept_new_work("Start another task")

    with SQLiteEventStore(database) as store:
        transport.available = True
        coordinator = service(store, transport)
        assert coordinator.active_session() == ("coordinator-1", "tmux:coordinator")
        assert coordinator.wake_pending() == 1
        coordinator.present("decision-77", coordinator_attempt_id="coordinator-1")
        ambiguous = UserDecision(
            decision_id="decision-77",
            coordinator_attempt_id="coordinator-1",
            selected_option=None,
            answer="That sounds fine",
            answered_by="operator-1",
            answered_at=NOW,
        )
        with pytest.raises(ValueError):
            coordinator.answer(ambiguous)
        assert transport.deliveries == []
        assert coordinator.open_decisions() == (request,)
        coordinator.answer(
            UserDecision(
                decision_id="decision-77",
                coordinator_attempt_id="coordinator-1",
                selected_option="minimal",
                answer="Use the minimal implementation",
                answered_by="operator-1",
                answered_at=NOW,
            )
        )
        assert coordinator.deliver_answer("decision-77")
        assert transport.deliveries == [("coder-77", "decision-77")]
        coordinator.acknowledge("decision-77", attempt_id="coder-77")
        assert coordinator.accept_new_work("Start another task")

    with SQLiteEventStore(database) as store:
        coordinator = service(store, transport)
        assert coordinator.open_decisions() == ()
        assert coordinator.pending_notifications() == ()
