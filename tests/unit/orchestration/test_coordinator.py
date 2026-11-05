"""Decision correlation and controller authority tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain import DecisionRequest, EventType, UserDecision
from milburn.orchestration.coordinator import CoordinatorSessionManager
from milburn.persistence.sqlite_store import SQLiteEventStore
from tests.fakes.coordinator import ScriptedCoordinatorTransport


NOW = datetime(2026, 11, 4, tzinfo=UTC)


def manager(
    store: SQLiteEventStore, transport: ScriptedCoordinatorTransport
) -> CoordinatorSessionManager:
    ids = (f"event-{i}" for i in range(100))
    service = CoordinatorSessionManager(
        store, transport, clock=lambda: NOW, event_ids=lambda: next(ids)
    )
    service.register_session(
        "coordinator-1", endpoint=transport.coordinator_endpoint.pane_id
    )
    return service


def request(identifier: str = "decision-1") -> DecisionRequest:
    return DecisionRequest(
        decision_id=identifier,
        source_attempt_id="coder-1",
        feature_id="feature-1",
        issue_number=10,
        question="Choose a path",
        why_it_matters="Work cannot continue",
        options=("A", "B"),
        recommendation="A",
        blocking=True,
    )


def answer(
    *, selected: str | None = "A", decision_id: str = "decision-1"
) -> UserDecision:
    return UserDecision(
        decision_id=decision_id,
        coordinator_attempt_id="coordinator-1",
        selected_option=selected,
        answer="A",
        answered_by="operator-1",
        answered_at=NOW,
    )


def test_answer_guard_rejects_unpresented_ambiguous_and_wrong_choice(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = manager(store, ScriptedCoordinatorTransport(store))
        service.request_decision(request())
        with pytest.raises(ValueError):
            service.answer(answer())
        service.present("decision-1", coordinator_attempt_id="coordinator-1")
        with pytest.raises(ValueError):
            service.answer(answer(selected=None))
        with pytest.raises(ValueError):
            service.answer(answer(selected="C"))
        with pytest.raises(ValueError):
            service.answer(UserDecision.from_dict({
                **answer().to_dict(), "answer": "That sounds fine"
            }))
        with pytest.raises(ValueError):
            service.answer(answer(decision_id="missing"))
        assert service.open_decisions() == (request(),)


def test_duplicate_decision_id_across_features_is_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = manager(store, ScriptedCoordinatorTransport(store))
        service.request_decision(request())
        changed = DecisionRequest(
            decision_id="decision-1",
            source_attempt_id="coder-2",
            feature_id="feature-2",
            issue_number=11,
            question="Other question",
            why_it_matters="Other blocker",
            options=("Yes", "No"),
            recommendation=None,
            blocking=True,
        )
        with pytest.raises(ValueError):
            service.request_decision(changed)
        assert service.open_decisions() == (request(),)


def test_duplicate_options_and_unoffered_recommendation_are_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = manager(store, ScriptedCoordinatorTransport(store))
        base = request().to_dict()
        for options, recommendation in (
            (["A", "A"], "A"), (["A", "a"], "A"),
            (["A", " A "], "A"), (["A", "B"], "C"),
        ):
            altered = DecisionRequest.from_dict(
                {**base, "options": options, "recommendation": recommendation}
            )
            with pytest.raises(ValueError):
                service.request_decision(altered)
        assert service.open_decisions() == ()


def test_acknowledgement_requires_delivery_and_originating_worker(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        transport = ScriptedCoordinatorTransport(store)
        service = manager(store, transport)
        service.request_decision(request())
        service.present("decision-1", coordinator_attempt_id="coordinator-1")
        service.answer(answer())
        assert service.worker_inbox("coder-1") == ()
        with pytest.raises(ValueError):
            service.acknowledge("decision-1", attempt_id="coder-1")
        service.deliver_answer("decision-1")
        with pytest.raises(ValueError):
            service.acknowledge("decision-1", attempt_id="coder-2")
        service.acknowledge("decision-1", attempt_id="coder-1")
        assert service.open_decisions() == ()
        with pytest.raises(ValueError):
            service.acknowledge("decision-1", attempt_id="coder-1")


def test_worker_delivery_failure_remains_queued_across_restart(tmp_path) -> None:
    database = tmp_path / "events.db"
    with SQLiteEventStore(database) as store:
        transport = ScriptedCoordinatorTransport(store)
        service = manager(store, transport)
        service.request_decision(request())
        service.present("decision-1", coordinator_attempt_id="coordinator-1")
        service.answer(answer())
        transport.available = False
        assert not service.deliver_answer("decision-1")
        assert service.worker_inbox("coder-1") == (answer(),)
    with SQLiteEventStore(database) as store:
        transport = ScriptedCoordinatorTransport(store)
        transport.available = True
        service = manager(store, transport)
        assert service.deliver_answer("decision-1")
        assert transport.deliveries["decision-1"] == ("coder-1", answer())
        service.acknowledge("decision-1", attempt_id="coder-1")


def test_crash_before_doorbell_retries_one_durable_worker_inbox_item(tmp_path) -> None:
    class FailDeliveredStore:
        def __init__(self, delegate: SQLiteEventStore) -> None:
            self.delegate = delegate
            self.fail_once = True

        def read_stream(self, stream: str, *, after_sequence: int = -1):
            return self.delegate.read_stream(stream, after_sequence=after_sequence)

        def append(self, stream: str, expected_sequence: int, events):
            if self.fail_once and any(
                event.event_type is EventType.STEERING_DELIVERED for event in events
            ):
                self.fail_once = False
                raise OSError("crashed before doorbell")
            return self.delegate.append(stream, expected_sequence, events)

    with SQLiteEventStore(tmp_path / "events.db") as durable:
        transport = ScriptedCoordinatorTransport(durable)
        service = manager(FailDeliveredStore(durable), transport)  # type: ignore[arg-type]
        service.request_decision(request())
        service.present("decision-1", coordinator_attempt_id="coordinator-1")
        service.answer(answer())
        assert service.worker_inbox("coder-1") == ()
        with pytest.raises(OSError):
            service.deliver_answer("decision-1")
        restarted = manager(durable, transport)
        assert restarted.worker_inbox("coder-1") == ()
        assert restarted.deliver_answer("decision-1")
        assert restarted.worker_inbox("coder-1") == (answer(),)
        assert transport.deliveries == {"decision-1": ("coder-1", answer())}


def test_worker_can_acknowledge_durable_inbox_after_doorbell_failure(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        transport = ScriptedCoordinatorTransport(store)
        service = manager(store, transport)
        service.request_decision(request())
        service.present("decision-1", coordinator_attempt_id="coordinator-1")
        service.answer(answer())
        transport.available = False
        assert not service.deliver_answer("decision-1")
        assert service.worker_inbox("coder-1") == (answer(),)
        service.acknowledge("decision-1", attempt_id="coder-1")
        assert service.worker_inbox("coder-1") == ()
        with pytest.raises(ValueError):
            service.deliver_answer("decision-1")


def test_coordinator_transport_failure_keeps_decision_unread(tmp_path) -> None:
    database = tmp_path / "events.db"
    with SQLiteEventStore(database) as store:
        transport = ScriptedCoordinatorTransport(store)
        transport.available = False
        service = manager(store, transport)
        service.request_decision(request())
        assert service.wake_pending() == 0
        assert service.pending_notifications()[0].correlation_id == "decision-1"
    with SQLiteEventStore(database) as store:
        transport = ScriptedCoordinatorTransport(store)
        transport.available = True
        service = manager(store, transport)
        assert service.wake_pending() == 1
        assert transport.wakes == ["decision:decision-1"]
        assert service.open_decisions() == (request(),)


def test_only_registered_coordinator_can_present_or_replace_session(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        transport = ScriptedCoordinatorTransport(store)
        service = manager(store, transport)
        service.request_decision(request())
        with pytest.raises(ValueError):
            service.present("decision-1", coordinator_attempt_id="impostor")
        with pytest.raises(ValueError):
            service.present("decision-1", coordinator_attempt_id=42)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            service.register_session("coordinator-2", endpoint="other-window")
        assert service.active_session() == ("coordinator-1", transport.coordinator_endpoint.pane_id)
