"""Production tmux bridge against the public runtime fake."""

from datetime import UTC, datetime

import pytest

from milburn.domain import DecisionRequest, UserDecision
from milburn.orchestration.coordinator import (
    CoordinatorSessionManager,
    TmuxCoordinatorTransport,
)
from milburn.persistence.sqlite_store import SQLiteEventStore
from milburn.runtime.tmux import ObservationStatus, WindowSpec
from tests.fakes.tmux import FakeTmuxRuntime
from tests.fakes.coordinator import ScriptedCoordinatorTransport


NOW = datetime(2026, 11, 4, tzinfo=UTC)


def test_tmux_bridge_wakes_only_recorded_endpoint_and_worker_inbox(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        runtime = FakeTmuxRuntime()
        coordinator_endpoint = runtime.create_window(WindowSpec(
            session_name="milburn", window_name="coordinator",
            attempt_id="coordinator-1", role="coordinator", generation=0,
            command=("codex",),
        ))
        worker_endpoint = runtime.create_window(WindowSpec(
            session_name="milburn", window_name="worker",
            attempt_id="coder-1", role="coder", generation=0,
            command=("codex",),
        ))
        transport = TmuxCoordinatorTransport(
            store, runtime, coordinator_endpoint,
            worker_endpoints={"coder-1": worker_endpoint},
        )
        ids = (f"event-{i}" for i in range(100))
        manager = CoordinatorSessionManager(
            store, transport, clock=lambda: NOW, event_ids=lambda: next(ids)
        )
        manager.register_session("coordinator-1", endpoint=coordinator_endpoint.pane_id)
        request = DecisionRequest(
            decision_id="decision-1", source_attempt_id="coder-1",
            feature_id="feature-1", issue_number=10,
            question="Choose", why_it_matters="Blocked", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        manager.request_decision(request)
        runtime.set_status(coordinator_endpoint, ObservationStatus.MISSING)
        assert manager.wake_pending() == 0
        assert manager.pending_notifications()[0].unread
        runtime.set_status(coordinator_endpoint, ObservationStatus.RUNNING)
        assert manager.wake_pending() == 1
        assert runtime.actions[-1].value == "inbox:decision:decision-1"
        manager.present("decision-1", coordinator_attempt_id="coordinator-1")
        decision = UserDecision(
            decision_id="decision-1", coordinator_attempt_id="coordinator-1",
            selected_option="A", answer="A", answered_by="operator-1",
            answered_at=NOW,
        )
        manager.answer(decision)
        assert manager.worker_inbox("coder-1") == ()
        assert manager.deliver_answer("decision-1")
        assert manager.worker_inbox("coder-1") == (decision,)
        assert runtime.actions[-1].value == "inbox:decision-1"
        manager.acknowledge("decision-1", attempt_id="coder-1")
        assert manager.worker_inbox("coder-1") == ()


def test_scripted_transport_matches_bridge_preconditions_and_terminal_states(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        scripted = ScriptedCoordinatorTransport(store)
        live = TmuxCoordinatorTransport(
            store, scripted.runtime, scripted.coordinator_endpoint,
            worker_endpoints={"coder-1": scripted.worker_endpoint},
        )
        ids = (f"event-{i}" for i in range(100))
        manager = CoordinatorSessionManager(
            store, live, clock=lambda: NOW, event_ids=lambda: next(ids)
        )
        manager.register_session(
            "coordinator-1", endpoint=scripted.coordinator_endpoint.pane_id
        )
        answer = UserDecision(
            decision_id="decision-1", coordinator_attempt_id="coordinator-1",
            selected_option="A", answer="A", answered_by="operator-1",
            answered_at=NOW,
        )
        for transport in (live, scripted):
            with pytest.raises(ValueError):
                transport.wake_coordinator("coordinator-1", "%wrong", "missing")
            with pytest.raises(ValueError):
                transport.deliver_answer("coder-1", "decision-1", answer)

        manager.request_decision(DecisionRequest(
            decision_id="decision-1", source_attempt_id="coder-1",
            feature_id="feature-1", issue_number=10, question="Choose",
            why_it_matters="Blocked", options=("A", "B"),
            recommendation="A", blocking=True,
        ))
        for transport in (live, scripted):
            assert transport.wake_coordinator(
                "coordinator-1", scripted.coordinator_endpoint.pane_id,
                "decision:decision-1"
            )
            with pytest.raises(ValueError):
                transport.deliver_answer("coder-1", "decision-1", answer)
        manager.present("decision-1", coordinator_attempt_id="coordinator-1")
        manager.answer(answer)
        with pytest.raises(ValueError):
            scripted.deliver_answer("coder-1", "decision-1", answer)
        assert manager.deliver_answer("decision-1")
        for transport in (live, scripted):
            assert transport.deliver_answer("coder-1", "decision-1", answer)
        manager.acknowledge("decision-1", attempt_id="coder-1")
        for transport in (live, scripted):
            with pytest.raises(ValueError):
                transport.deliver_answer("coder-1", "decision-1", answer)
            with pytest.raises(ValueError):
                transport.wake_coordinator(
                    "coordinator-1", scripted.coordinator_endpoint.pane_id,
                    "decision:decision-1"
                )
