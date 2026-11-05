"""Scriptable Coordinator transport using the production bridge and fake tmux."""

from __future__ import annotations

from milburn.domain import UserDecision
from milburn.orchestration.coordinator import TmuxCoordinatorTransport
from milburn.persistence.sqlite_store import SQLiteEventStore
from milburn.runtime.tmux import ObservationStatus, WindowSpec

from tests.fakes.tmux import FakeTmuxRuntime


class ScriptedCoordinatorTransport:
    """Observe production bridge effects without weakening its preconditions."""

    def __init__(
        self, store: SQLiteEventStore, *, worker_attempt_id: str = "coder-1"
    ) -> None:
        self.runtime = FakeTmuxRuntime()
        self.coordinator_endpoint = self.runtime.create_window(WindowSpec(
            session_name="milburn", window_name="coordinator",
            attempt_id="coordinator-1", role="coordinator", generation=0,
            command=("codex",),
        ))
        self.worker_endpoint = self.runtime.create_window(WindowSpec(
            session_name="milburn", window_name="worker",
            attempt_id=worker_attempt_id, role="coder", generation=0,
            command=("codex",),
        ))
        self._bridge = TmuxCoordinatorTransport(
            store, self.runtime, self.coordinator_endpoint,
            worker_endpoints={worker_attempt_id: self.worker_endpoint},
        )
        self._available = True
        self.wakes: list[str] = []
        self.deliveries: dict[str, tuple[str, UserDecision]] = {}

    @property
    def available(self) -> bool:
        return self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = value
        status = ObservationStatus.RUNNING if value else ObservationStatus.MISSING
        self.runtime.set_status(self.coordinator_endpoint, status)
        self.runtime.set_status(self.worker_endpoint, status)

    def wake_coordinator(
        self, attempt_id: str, endpoint: str, notification_id: str
    ) -> bool:
        sent = self._bridge.wake_coordinator(attempt_id, endpoint, notification_id)
        if sent:
            self.wakes.append(notification_id)
        return sent

    def deliver_answer(
        self, attempt_id: str, decision_id: str, answer: UserDecision
    ) -> bool:
        sent = self._bridge.deliver_answer(attempt_id, decision_id, answer)
        if sent:
            previous = self.deliveries.get(decision_id)
            if previous is not None and previous != (attempt_id, answer):
                raise ValueError("conflicting delivery")
            self.deliveries[decision_id] = (attempt_id, answer)
        return sent
