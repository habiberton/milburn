from __future__ import annotations

from pathlib import Path
import importlib.util
import sys

import pytest

from milburn.runtime.messaging import validate_doorbell_token
from milburn.runtime.processes import CommandResult, ProcessIdentity
from milburn.runtime.tmux import (
    EndpointUnavailableError,
    ObservationStatus,
    ObservationPolicy,
    RuntimeEndpoint,
    StaleEndpointError,
    TmuxRuntime,
    WindowSpec,
)


_FAKE_SPEC = importlib.util.spec_from_file_location(
    "milburn_test_fake_tmux",
    Path(__file__).parents[2] / "fakes" / "tmux.py",
)
assert _FAKE_SPEC is not None and _FAKE_SPEC.loader is not None
_fake_module = importlib.util.module_from_spec(_FAKE_SPEC)
sys.modules[_FAKE_SPEC.name] = _fake_module
_FAKE_SPEC.loader.exec_module(_fake_module)
FakeTmuxRuntime = _fake_module.FakeTmuxRuntime


class TmuxSimulator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.exists = False
        self.dead = False
        self.process = ProcessIdentity(4321, "Mon Nov  2 10:00:00 2026", "python3")
        self.identity_failures = 0

    def run(self, arguments: tuple[str, ...]) -> CommandResult:
        self.calls.append(tuple(arguments))
        operation = arguments[1]
        if operation == "has-session":
            return CommandResult(0 if self.exists else 1)
        if operation in {"new-session", "new-window"}:
            self.exists = True
            self.dead = False
            return CommandResult(0, "$7\t@12\t%19\t4321\t0\n")
        if operation == "display-message":
            if not self.exists:
                return CommandResult(1, stderr="missing")
            return CommandResult(0, f"$7\t@12\t%19\t4321\t{int(self.dead)}\n")
        if operation == "kill-pane":
            self.exists = False
            return CommandResult(0)
        if operation == "send-keys" and arguments[-1] == "C-c":
            self.dead = True
            return CommandResult(0)
        return CommandResult(0)

    def identify(self, pid: int) -> ProcessIdentity | None:
        if not self.exists or self.dead:
            return None
        if self.identity_failures:
            self.identity_failures -= 1
            return None
        assert pid == self.process.pid
        return self.process


def spec(*, generation: int = 0, attempt_id: str = "attempt-1") -> WindowSpec:
    return WindowSpec(
        session_name="milburn",
        window_name="coder-5",
        attempt_id=attempt_id,
        role="coder",
        generation=generation,
        command=("python3", "-m", "worker"),
        worktree=Path("/tmp/worktree"),
        title="Coder issue 5",
    )


def test_create_window_records_stable_ids_and_process_identity() -> None:
    simulator = TmuxSimulator()
    runtime = TmuxRuntime(simulator, simulator)

    endpoint = runtime.create_window(spec())

    assert endpoint.session_id == "$7"
    assert endpoint.window_id == "@12"
    assert endpoint.pane_id == "%19"
    assert endpoint.process == simulator.process
    assert endpoint.worktree == Path("/tmp/worktree")
    create = simulator.calls[1]
    assert create[1] == "new-session"
    assert ("-n", "coder-5") == (create[create.index("-n")], create[create.index("-n") + 1])
    assert create[-1] == "python3 -m worker"
    assert runtime.inspect(endpoint).matched


def test_create_window_uses_named_window_in_existing_session() -> None:
    simulator = TmuxSimulator()
    simulator.exists = True
    runtime = TmuxRuntime(simulator, simulator)

    runtime.create_window(spec())

    assert simulator.calls[1][1] == "new-window"
    assert simulator.calls[1][simulator.calls[1].index("-t") + 1] == "milburn"


def test_doorbell_is_literal_and_success_requires_post_send_inspection() -> None:
    simulator = TmuxSimulator()
    runtime = TmuxRuntime(simulator, simulator)
    endpoint = runtime.create_window(spec())

    result = runtime.send_doorbell(endpoint, "inbox:0042")

    assert result.accepted
    literal_call = next(call for call in simulator.calls if "-l" in call)
    assert literal_call[-2:] == ("--", "inbox:0042")
    assert simulator.calls[-1][1] == "display-message"


@pytest.mark.parametrize("token", ["", " padded", "line\nbreak", "x" * 257])
def test_invalid_doorbells_are_rejected(token: str) -> None:
    with pytest.raises(ValueError):
        validate_doorbell_token(token)


def test_replacement_generation_fences_old_endpoint() -> None:
    runtime = FakeTmuxRuntime()
    old = runtime.create_window(spec(generation=2))
    replacement = runtime.create_window(spec(generation=3))

    assert runtime.inspect(old).status is ObservationStatus.STALE_GENERATION
    assert runtime.inspect(replacement).matched
    with pytest.raises(StaleEndpointError):
        runtime.send_doorbell(old, "inbox:1")


def test_same_or_older_generation_cannot_replace_endpoint() -> None:
    runtime = FakeTmuxRuntime()
    runtime.create_window(spec(generation=2))

    with pytest.raises(StaleEndpointError):
        runtime.create_window(spec(generation=2))
    with pytest.raises(StaleEndpointError):
        runtime.create_window(spec(generation=1))


def test_process_start_identity_detects_pid_reuse() -> None:
    simulator = TmuxSimulator()
    runtime = TmuxRuntime(simulator, simulator)
    endpoint = runtime.create_window(spec())
    simulator.process = ProcessIdentity(4321, "Mon Nov  2 10:01:00 2026", "python3")

    observation = runtime.inspect(endpoint)

    assert observation.status is ObservationStatus.PROCESS_MISMATCH


def test_exec_executable_change_preserves_same_process_identity() -> None:
    simulator = TmuxSimulator()
    runtime = TmuxRuntime(simulator, simulator)
    endpoint = runtime.create_window(spec())
    simulator.process = ProcessIdentity(
        endpoint.process.pid,
        endpoint.process.started_at,
        "codex-after-exec",
    )

    observation = runtime.inspect(endpoint)

    assert observation.status is ObservationStatus.RUNNING
    assert observation.observed_process is not None
    assert observation.observed_process.executable == "codex-after-exec"


def test_startup_process_observation_retries_are_bounded_and_injected() -> None:
    simulator = TmuxSimulator()
    simulator.identity_failures = 2
    sleeps: list[float] = []
    runtime = TmuxRuntime(
        simulator,
        simulator,
        observation_policy=ObservationPolicy(attempts=3, interval_seconds=0.5),
        sleeper=sleeps.append,
    )

    endpoint = runtime.create_window(spec())

    assert endpoint.process == simulator.process
    assert sleeps == [0.5, 0.5]


def test_lifecycle_operations_return_observed_postconditions() -> None:
    simulator = TmuxSimulator()
    runtime = TmuxRuntime(simulator, simulator)
    endpoint = runtime.create_window(spec())

    interrupted = runtime.interrupt(endpoint)

    assert interrupted.status is ObservationStatus.EXITED
    assert simulator.calls[-1][1] == "display-message"

    second_simulator = TmuxSimulator()
    second_runtime = TmuxRuntime(second_simulator, second_simulator)
    second = second_runtime.create_window(spec(attempt_id="attempt-2"))
    terminated = second_runtime.terminate(second)
    assert terminated.status is ObservationStatus.MISSING
    assert second_simulator.calls[-1][1] == "display-message"


def test_interrupt_rejects_unobserved_success() -> None:
    simulator = TmuxSimulator()
    sleeps: list[float] = []
    runtime = TmuxRuntime(
        simulator,
        simulator,
        observation_policy=ObservationPolicy(attempts=3, interval_seconds=0.5),
        sleeper=sleeps.append,
    )
    endpoint = runtime.create_window(spec())
    simulator.dead = False

    original_run = simulator.run

    def ignore_interrupt(arguments: tuple[str, ...]) -> CommandResult:
        if len(arguments) > 2 and arguments[1] == "send-keys" and arguments[-1] == "C-c":
            simulator.calls.append(tuple(arguments))
            return CommandResult(0)
        return original_run(arguments)

    simulator.run = ignore_interrupt  # type: ignore[method-assign]
    with pytest.raises(EndpointUnavailableError, match="postcondition"):
        runtime.interrupt(endpoint)
    assert sleeps == [0.5, 0.5]


def test_fake_runtime_is_deterministic_and_records_actions() -> None:
    runtime = FakeTmuxRuntime()
    endpoint = runtime.create_window(spec())
    sent = runtime.send_doorbell(endpoint, "inbox:9")
    observation = runtime.terminate(endpoint)

    assert sent.accepted
    assert observation.status is ObservationStatus.MISSING
    assert [action.kind for action in runtime.actions] == [
        "create_window", "send_doorbell", "terminate"
    ]


@pytest.mark.parametrize("operation", ["interrupt", "terminate"])
@pytest.mark.parametrize(
    "status",
    [
        ObservationStatus.UNKNOWN,
        ObservationStatus.MISSING,
        ObservationStatus.EXITED,
        ObservationStatus.PROCESS_MISMATCH,
    ],
)
def test_fake_lifecycle_does_not_act_on_non_running_endpoint(
    operation: str,
    status: ObservationStatus,
) -> None:
    runtime = FakeTmuxRuntime()
    endpoint = runtime.create_window(spec())
    runtime.set_status(endpoint, status)

    observation = getattr(runtime, operation)(endpoint)

    assert observation.status is status
    assert runtime.inspect(endpoint).status is status
    assert [action.kind for action in runtime.actions] == ["create_window"]


def test_durable_endpoint_can_be_registered_after_restart() -> None:
    endpoint = RuntimeEndpoint(
        session_name="milburn",
        session_id="$7",
        window_id="@12",
        pane_id="%19",
        attempt_id="attempt-1",
        role="coder",
        generation=4,
        process=ProcessIdentity(4321, "start", "python3"),
        worktree=Path("/tmp/worktree"),
    )
    simulator = TmuxSimulator()
    simulator.exists = True
    simulator.process = endpoint.process
    runtime = TmuxRuntime(simulator, simulator)

    runtime.register_endpoint(endpoint)

    assert runtime.inspect(endpoint).matched


def test_endpoint_identity_round_trips_through_durable_data() -> None:
    runtime = FakeTmuxRuntime()
    endpoint = runtime.create_window(spec(generation=4))

    restored = RuntimeEndpoint.from_dict(endpoint.to_dict())

    assert restored == endpoint


def test_same_generation_cannot_be_rebound_to_different_process() -> None:
    runtime = FakeTmuxRuntime()
    endpoint = runtime.create_window(spec(generation=4))
    conflicting = RuntimeEndpoint.from_dict(endpoint.to_dict())
    conflicting = RuntimeEndpoint(
        session_name=conflicting.session_name,
        session_id=conflicting.session_id,
        window_id=conflicting.window_id,
        pane_id=conflicting.pane_id,
        attempt_id=conflicting.attempt_id,
        role=conflicting.role,
        generation=conflicting.generation,
        process=ProcessIdentity(9999, "other-start", "python3"),
        worktree=conflicting.worktree,
    )

    with pytest.raises(StaleEndpointError, match="already bound"):
        runtime.register_endpoint(conflicting)
