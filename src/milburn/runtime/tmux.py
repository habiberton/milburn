"""tmux-backed process runtime with durable endpoint and generation fencing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import shlex
import time
from typing import Callable, Protocol

from .messaging import SendResult, validate_doorbell_token
from .processes import (
    CommandRunner,
    ProcessIdentity,
    ProcessInspector,
    PsProcessInspector,
    SubprocessCommandRunner,
)


_FORMAT = "#{session_id}\t#{window_id}\t#{pane_id}\t#{pane_pid}\t#{pane_dead}"


class RuntimeErrorBase(RuntimeError):
    """Base class for explicit runtime-boundary failures."""


class RuntimeCommandError(RuntimeErrorBase):
    pass


class StaleEndpointError(RuntimeErrorBase):
    pass


class EndpointUnavailableError(RuntimeErrorBase):
    pass


class ObservationStatus(str, Enum):
    RUNNING = "running"
    UNKNOWN = "unknown"
    MISSING = "missing"
    EXITED = "exited"
    STALE_GENERATION = "stale_generation"
    PROCESS_MISMATCH = "process_mismatch"


@dataclass(frozen=True, slots=True)
class WindowSpec:
    session_name: str
    window_name: str
    attempt_id: str
    role: str
    generation: int
    command: tuple[str, ...]
    worktree: Path | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        for value, field in (
            (self.session_name, "session_name"),
            (self.window_name, "window_name"),
            (self.attempt_id, "attempt_id"),
            (self.role, "role"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field} must be non-empty and trimmed")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if not self.command or any(not part for part in self.command):
            raise ValueError("command must contain non-empty arguments")
        if self.worktree is not None and not self.worktree.is_absolute():
            raise ValueError("worktree must be an absolute path")


@dataclass(frozen=True, slots=True)
class RuntimeEndpoint:
    session_name: str
    session_id: str
    window_id: str
    pane_id: str
    attempt_id: str
    role: str
    generation: int
    process: ProcessIdentity
    worktree: Path | None

    def __post_init__(self) -> None:
        for value, field, prefix in (
            (self.session_id, "session_id", "$"),
            (self.window_id, "window_id", "@"),
            (self.pane_id, "pane_id", "%"),
        ):
            if not value.startswith(prefix):
                raise ValueError(f"{field} must be a stable tmux ID")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if self.worktree is not None and not self.worktree.is_absolute():
            raise ValueError("worktree must be an absolute path")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible durable endpoint identity."""

        return {
            "session_name": self.session_name,
            "session_id": self.session_id,
            "window_id": self.window_id,
            "pane_id": self.pane_id,
            "attempt_id": self.attempt_id,
            "role": self.role,
            "generation": self.generation,
            "process": self.process.to_dict(),
            "worktree": str(self.worktree) if self.worktree is not None else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> RuntimeEndpoint:
        expected = {
            "session_name", "session_id", "window_id", "pane_id", "attempt_id",
            "role", "generation", "process", "worktree",
        }
        if set(value) != expected:
            raise ValueError("invalid runtime endpoint fields")
        strings = ("session_name", "session_id", "window_id", "pane_id", "attempt_id", "role")
        if any(not isinstance(value[field], str) for field in strings):
            raise ValueError("runtime endpoint strings are invalid")
        generation = value["generation"]
        process = value["process"]
        worktree = value["worktree"]
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValueError("generation must be an integer")
        if not isinstance(process, dict):
            raise ValueError("process must be an object")
        if worktree is not None and not isinstance(worktree, str):
            raise ValueError("worktree must be a string or null")
        return cls(
            session_name=value["session_name"],  # type: ignore[arg-type]
            session_id=value["session_id"],  # type: ignore[arg-type]
            window_id=value["window_id"],  # type: ignore[arg-type]
            pane_id=value["pane_id"],  # type: ignore[arg-type]
            attempt_id=value["attempt_id"],  # type: ignore[arg-type]
            role=value["role"],  # type: ignore[arg-type]
            generation=generation,
            process=ProcessIdentity.from_dict(process),
            worktree=Path(worktree) if worktree is not None else None,
        )


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    endpoint: RuntimeEndpoint
    status: ObservationStatus
    pane_dead: bool | None
    observed_process: ProcessIdentity | None

    @property
    def matched(self) -> bool:
        return self.status is ObservationStatus.RUNNING


@dataclass(frozen=True, slots=True)
class ObservationPolicy:
    """Bounded retries for process startup and lifecycle observation."""

    attempts: int = 20
    interval_seconds: float = 0.025

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("observation attempts must be positive")
        if self.interval_seconds < 0:
            raise ValueError("observation interval must be non-negative")


class TmuxRuntimeProtocol(Protocol):
    def create_window(self, spec: WindowSpec) -> RuntimeEndpoint: ...
    def register_endpoint(self, endpoint: RuntimeEndpoint) -> None: ...
    def send_doorbell(self, endpoint: RuntimeEndpoint, token: str) -> SendResult: ...
    def inspect(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...
    def interrupt(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...
    def terminate(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...


class TmuxRuntime:
    """Control tmux through stable IDs and validate each action by inspection."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        process_inspector: ProcessInspector | None = None,
        *,
        tmux_binary: str = "tmux",
        observation_policy: ObservationPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._runner = runner or SubprocessCommandRunner()
        self._processes = process_inspector or PsProcessInspector()
        self._tmux_binary = tmux_binary
        self._observation_policy = observation_policy or ObservationPolicy()
        self._sleep = sleeper
        self._active: dict[str, RuntimeEndpoint] = {}

    def create_window(self, spec: WindowSpec) -> RuntimeEndpoint:
        current = self._active.get(spec.attempt_id)
        if current is not None and spec.generation <= current.generation:
            raise StaleEndpointError("generation must advance for an existing attempt")

        command = shlex.join(spec.command)
        directory = str(spec.worktree) if spec.worktree is not None else None
        has_session = self._run("has-session", "-t", spec.session_name).returncode == 0
        if has_session:
            arguments = [
                "new-window", "-d", "-P", "-F", _FORMAT,
                "-t", spec.session_name, "-n", spec.window_name,
            ]
        else:
            arguments = [
                "new-session", "-d", "-P", "-F", _FORMAT,
                "-s", spec.session_name, "-n", spec.window_name,
            ]
        if directory is not None:
            arguments.extend(("-c", directory))
        arguments.append(command)
        created = self._run(*arguments)
        if created.returncode:
            raise RuntimeCommandError(created.stderr.strip() or "tmux window creation failed")
        session_id, window_id, pane_id, pid, pane_dead = _parse_row(created.stdout)
        if pane_dead:
            raise EndpointUnavailableError("new tmux pane exited before observation")
        process = self._identify_process(pid)
        if process is None:
            raise EndpointUnavailableError("new tmux pane process could not be identified")
        endpoint = RuntimeEndpoint(
            session_name=spec.session_name,
            session_id=session_id,
            window_id=window_id,
            pane_id=pane_id,
            attempt_id=spec.attempt_id,
            role=spec.role,
            generation=spec.generation,
            process=process,
            worktree=spec.worktree,
        )
        self.register_endpoint(endpoint)
        observed = self._observe_until(endpoint, {ObservationStatus.RUNNING})
        if not observed.matched:
            raise EndpointUnavailableError("new tmux endpoint failed postcondition inspection")
        if spec.title is not None:
            title = self._run("select-pane", "-t", pane_id, "-T", spec.title)
            if title.returncode:
                raise RuntimeCommandError(title.stderr.strip() or "tmux pane title failed")
        return endpoint

    def register_endpoint(self, endpoint: RuntimeEndpoint) -> None:
        """Restore an endpoint from durable state while preserving monotonicity."""

        current = self._active.get(endpoint.attempt_id)
        if current is not None and endpoint.generation < current.generation:
            raise StaleEndpointError("cannot register an older generation")
        if current is not None and endpoint.generation == current.generation and endpoint != current:
            raise StaleEndpointError("generation is already bound to another endpoint")
        self._active[endpoint.attempt_id] = endpoint

    def send_doorbell(self, endpoint: RuntimeEndpoint, token: str) -> SendResult:
        self._require_active(endpoint)
        validate_doorbell_token(token)
        before = self.inspect(endpoint)
        if not before.matched:
            return SendResult(False, False, f"endpoint is {before.status.value}")
        sent = self._run("send-keys", "-t", endpoint.pane_id, "-l", "--", token)
        if sent.returncode:
            return SendResult(False, True, sent.stderr.strip() or "send-keys failed")
        enter = self._run("send-keys", "-t", endpoint.pane_id, "Enter")
        after = self.inspect(endpoint)
        return SendResult(
            sent=enter.returncode == 0,
            endpoint_matched=after.matched,
            detail=(enter.stderr.strip() or "doorbell sent"),
        )

    def inspect(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        active = self._active.get(endpoint.attempt_id)
        if active is None or active.generation != endpoint.generation:
            return RuntimeObservation(endpoint, ObservationStatus.STALE_GENERATION, None, None)
        if active != endpoint:
            return RuntimeObservation(endpoint, ObservationStatus.PROCESS_MISMATCH, None, None)
        result = self._run("display-message", "-p", "-t", endpoint.pane_id, _FORMAT)
        if result.returncode:
            return RuntimeObservation(endpoint, ObservationStatus.MISSING, None, None)
        try:
            session_id, window_id, pane_id, pid, pane_dead = _parse_row(result.stdout)
        except (RuntimeCommandError, ValueError):
            return RuntimeObservation(endpoint, ObservationStatus.MISSING, None, None)
        if (session_id, window_id, pane_id) != (
            endpoint.session_id, endpoint.window_id, endpoint.pane_id
        ):
            return RuntimeObservation(endpoint, ObservationStatus.PROCESS_MISMATCH, pane_dead, None)
        observed_process = self._processes.identify(pid)
        if pane_dead:
            return RuntimeObservation(endpoint, ObservationStatus.EXITED, pane_dead, observed_process)
        if observed_process is None:
            return RuntimeObservation(endpoint, ObservationStatus.UNKNOWN, pane_dead, None)
        status = (
            ObservationStatus.RUNNING
            if observed_process.matches(endpoint.process)
            else ObservationStatus.PROCESS_MISMATCH
        )
        return RuntimeObservation(endpoint, status, pane_dead, observed_process)

    def interrupt(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        self._require_active(endpoint)
        before = self.inspect(endpoint)
        if not before.matched:
            return before
        result = self._run("send-keys", "-t", endpoint.pane_id, "C-c")
        if result.returncode:
            raise RuntimeCommandError(result.stderr.strip() or "tmux interrupt failed")
        after = self._observe_until(
            endpoint,
            {
                ObservationStatus.EXITED,
                ObservationStatus.MISSING,
                ObservationStatus.PROCESS_MISMATCH,
            },
        )
        if after.status not in {
            ObservationStatus.EXITED,
            ObservationStatus.MISSING,
            ObservationStatus.PROCESS_MISMATCH,
        }:
            raise EndpointUnavailableError("interrupt postcondition was not observed")
        return after

    def terminate(self, endpoint: RuntimeEndpoint) -> RuntimeObservation:
        self._require_active(endpoint)
        before = self.inspect(endpoint)
        if not before.matched:
            return before
        result = self._run("kill-pane", "-t", endpoint.pane_id)
        if result.returncode:
            raise RuntimeCommandError(result.stderr.strip() or "tmux termination failed")
        after = self._observe_until(endpoint, {ObservationStatus.MISSING})
        if after.status is not ObservationStatus.MISSING:
            raise EndpointUnavailableError("termination postcondition was not observed")
        return after

    def _require_active(self, endpoint: RuntimeEndpoint) -> None:
        active = self._active.get(endpoint.attempt_id)
        if active is None or active != endpoint:
            raise StaleEndpointError("endpoint is not the active generation")

    def _run(self, *arguments: str):
        return self._runner.run((self._tmux_binary, *arguments))

    def _identify_process(self, pid: int) -> ProcessIdentity | None:
        for attempt in range(self._observation_policy.attempts):
            process = self._processes.identify(pid)
            if process is not None:
                return process
            self._sleep_before_retry(attempt)
        return None

    def _observe_until(
        self,
        endpoint: RuntimeEndpoint,
        accepted: set[ObservationStatus],
    ) -> RuntimeObservation:
        observation: RuntimeObservation | None = None
        for attempt in range(self._observation_policy.attempts):
            observation = self.inspect(endpoint)
            if observation.status in accepted:
                return observation
            self._sleep_before_retry(attempt)
        assert observation is not None
        return observation

    def _sleep_before_retry(self, attempt: int) -> None:
        if attempt + 1 < self._observation_policy.attempts:
            self._sleep(self._observation_policy.interval_seconds)


def _parse_row(output: str) -> tuple[str, str, str, int, bool]:
    rows = [row for row in output.splitlines() if row.strip()]
    if len(rows) != 1:
        raise RuntimeCommandError("tmux returned an unexpected endpoint record")
    parts = rows[0].split("\t")
    if len(parts) != 5:
        raise RuntimeCommandError("tmux returned an invalid endpoint record")
    session_id, window_id, pane_id, raw_pid, raw_dead = parts
    if not session_id.startswith("$") or not window_id.startswith("@") or not pane_id.startswith("%"):
        raise RuntimeCommandError("tmux returned invalid stable IDs")
    return session_id, window_id, pane_id, int(raw_pid), raw_dead == "1"
