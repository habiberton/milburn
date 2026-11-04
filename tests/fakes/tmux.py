"""Deterministic in-memory implementation of the public tmux runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass

from milburn.runtime.messaging import SendResult, validate_doorbell_token
from milburn.runtime.processes import ProcessIdentity
from milburn.runtime.tmux import (
    ObservationStatus,
    RuntimeEndpoint,
    RuntimeObservation,
    StaleEndpointError,
    WindowSpec,
)


@dataclass(frozen=True, slots=True)
class FakeRuntimeAction:
    kind: str
    attempt_id: str
    generation: int
    value: str | None = None


class FakeTmuxRuntime:
    """A controllable runtime that never invokes tmux or OS processes."""

    def __init__(self) -> None:
        self._next_id = 1
        self._active: dict[str, RuntimeEndpoint] = {}
        self._statuses: dict[tuple[str, int], ObservationStatus] = {}
        self.actions: list[FakeRuntimeAction] = []

    def create_window(self, spec: WindowSpec) -> RuntimeEndpoint:
        current = self._active.get(spec.attempt_id)
        if current is not None and spec.generation <= current.generation:
            raise StaleEndpointError("generation must advance for an existing attempt")
        number = self._next_id
        self._next_id += 1
        endpoint = RuntimeEndpoint(
            session_name=spec.session_name,
            session_id=f"${number}",
            window_id=f"@{number}",
            pane_id=f"%{number}",
            attempt_id=spec.attempt_id,
            role=spec.role,
            generation=spec.generation,
            process=ProcessIdentity(number + 1000, f"start-{number}", spec.command[0]),
            worktree=spec.worktree,
        )
        self.register_endpoint(endpoint)
        self.actions.append(
            FakeRuntimeAction("create_window", spec.attempt_id, spec.generation, spec.window_name)
        )
        return endpoint

    def register_endpoint(self, endpoint: RuntimeEndpoint) -> None:
        current = self._active.get(endpoint.attempt_id)
        if current is not None and endpoint.generation < current.generation:
            raise StaleEndpointError("cannot register an older generation")
        if current is not None and endpoint.generation == current.generation and endpoint != current:
            raise StaleEndpointError("generation is already bound to another endpoint")
        self._active[endpoint.attempt_id] = endpoint
        self._statuses[(endpoint.attempt_id, endpoint.generation)] = ObservationStatus.RUNNING

    def send_doorbell(self, endpoint: RuntimeEndpoint, token: str) -> SendResult:
        self._require_active(endpoint)
        validate_doorbell_token(token)
        observation = self.inspect(endpoint)
        sent = observation.matched
        if sent:
            self.actions.append(
                FakeRuntimeAction("send_doorbell", endpoint.attempt_id, endpoint.generation, token)
            )
        return SendResult(sent, observation.matched, "doorbell sent" if sent else "endpoint unavailable")

    def inspect(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        active = self._active.get(endpoint.attempt_id)
        if active is None or active.generation != endpoint.generation:
            status = ObservationStatus.STALE_GENERATION
        elif active != endpoint:
            status = ObservationStatus.PROCESS_MISMATCH
        else:
            status = self._statuses.get(
                (endpoint.attempt_id, endpoint.generation), ObservationStatus.MISSING
            )
        process = endpoint.process if status is ObservationStatus.RUNNING else None
        pane_dead = status in {ObservationStatus.EXITED, ObservationStatus.MISSING}
        return RuntimeObservation(endpoint, status, pane_dead, process)

    def interrupt(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        self._require_active(endpoint)
        before = self.inspect(endpoint)
        if not before.matched:
            return before
        self.actions.append(FakeRuntimeAction("interrupt", endpoint.attempt_id, endpoint.generation))
        self._statuses[(endpoint.attempt_id, endpoint.generation)] = ObservationStatus.EXITED
        return self.inspect(endpoint)

    def terminate(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        self._require_active(endpoint)
        before = self.inspect(endpoint)
        if not before.matched:
            return before
        self.actions.append(FakeRuntimeAction("terminate", endpoint.attempt_id, endpoint.generation))
        self._statuses[(endpoint.attempt_id, endpoint.generation)] = ObservationStatus.MISSING
        return self.inspect(endpoint)

    def set_status(self, endpoint: RuntimeEndpoint, status: ObservationStatus) -> None:
        self._statuses[(endpoint.attempt_id, endpoint.generation)] = status

    def _require_active(self, endpoint: RuntimeEndpoint) -> None:
        if self._active.get(endpoint.attempt_id) != endpoint:
            raise StaleEndpointError("endpoint is not the active generation")
