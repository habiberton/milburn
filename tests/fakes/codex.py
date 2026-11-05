"""Deterministic Codex adapter fixtures with no process or network effects."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable
from pathlib import Path
import tempfile

from milburn.agents.codex_adapter import (
    Ack,
    AgentEndpoint,
    AgentResult,
    AgentStatus,
    CodexAdapter,
    ControlResult,
    LaunchRequest,
    ProcessCollection,
    ProcessLaunch,
    ProcessState,
    ProcessStatus,
    SteeringMessage,
)


TERMINALS = ("completed", "exhausted", "error", "truncated")


@dataclass(frozen=True, slots=True)
class ScriptedCodexRun:
    """One scripted run.

    ``terminal`` picks how the stream ends: ``completed`` (a normal end, with
    the result document if any), ``exhausted`` (the harness's quota refusal,
    where it has one), ``error`` (a reported error), or ``truncated`` (the
    stream stops early, as when a run is killed).
    """

    result_document: str | None
    exit_code: int = 0
    stderr: str = ""
    terminal: str = "completed"

    def __post_init__(self) -> None:
        if self.terminal not in TERMINALS:
            raise ValueError(f"terminal must be one of {TERMINALS}")


@dataclass(slots=True)
class _ActiveRun:
    script: ScriptedCodexRun
    state: ProcessState = ProcessState.RUNNING
    interrupted: bool = False


class FakeCodexRuntime:
    """A process boundary that consumes one scripted run per launch."""

    def __init__(
        self,
        scripts: tuple[ScriptedCodexRun, ...],
        *,
        render: Callable[[ScriptedCodexRun], str] | None = None,
        prefix: str = "fake-codex",
    ) -> None:
        self._render = render or _codex_jsonl
        self._prefix = prefix
        self._remaining = list(scripts)
        self._runs: dict[str, _ActiveRun] = {}
        self.launches: list[ProcessLaunch] = []
        self.steering: list[tuple[str, str]] = []
        self.interrupted: list[str] = []
        self.retired: list[str] = []

    def launch(self, spec: ProcessLaunch) -> str:
        if not self._remaining:
            raise AssertionError("no scripted Codex run remains")
        endpoint = f"{self._prefix}-{len(self.launches) + 1}"
        self.launches.append(spec)
        self._runs[endpoint] = _ActiveRun(self._remaining.pop(0))
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        run = self._require(endpoint)
        if run.state is not ProcessState.RUNNING:
            return Ack(accepted=False, detail="endpoint is not running")
        self.steering.append((endpoint, message))
        return Ack(accepted=True, detail="scripted acknowledgement")

    def status(self, endpoint: str) -> ProcessStatus:
        run = self._require(endpoint)
        if run.state is not ProcessState.EXITED:
            exit_code = None
        elif run.interrupted:
            exit_code = -15
        else:
            exit_code = run.script.exit_code
        return ProcessStatus(run.state, exit_code)

    def interrupt(self, endpoint: str) -> ControlResult:
        run = self._require(endpoint)
        if run.state is not ProcessState.RUNNING:
            return ControlResult(observed=False, detail="endpoint already exited")
        run.state = ProcessState.EXITED
        run.interrupted = True
        self.interrupted.append(endpoint)
        return ControlResult(observed=True, detail="scripted interrupt")

    def collect(self, endpoint: str) -> ProcessCollection:
        run = self._require(endpoint)
        run.state = ProcessState.EXITED
        if run.interrupted:
            # Like the real runtime, a killed run leaves the partial stream it
            # wrote before the signal.
            return ProcessCollection(
                state=ProcessState.EXITED,
                exit_code=-15,
                stdout=self._render(ScriptedCodexRun(None, terminal="truncated")),
                stderr="scripted process interrupted",
            )
        return ProcessCollection(
            state=ProcessState.EXITED,
            exit_code=run.script.exit_code,
            stdout=self._render(run.script),
            stderr=run.script.stderr,
        )

    def retire(self, endpoint: str) -> ControlResult:
        run = self._require(endpoint)
        if run.state is ProcessState.RUNNING:
            return ControlResult(
                observed=False, detail="running endpoint cannot be retired"
            )
        self.retired.append(endpoint)
        del self._runs[endpoint]
        return ControlResult(observed=True, detail="scripted retirement")

    def _require(self, endpoint: str) -> _ActiveRun:
        try:
            return self._runs[endpoint]
        except KeyError as error:
            raise AssertionError(f"unknown fake endpoint {endpoint}") from error


class FakeCodexAdapter:
    """Public fake with the same lifecycle as ``CodexAdapter``."""

    def __init__(
        self, scripts: tuple[ScriptedCodexRun, ...], *, schema_dir: Path | None = None
    ) -> None:
        self.runtime = FakeCodexRuntime(scripts)
        self._adapter = CodexAdapter(
            self.runtime,
            executable="fake-codex",
            schema_dir=schema_dir or Path(tempfile.mkdtemp(prefix="milburn-schemas-")),
        )

    def launch(self, request: LaunchRequest) -> AgentEndpoint:
        return self._adapter.launch(request)

    def steer(self, endpoint: AgentEndpoint, message: SteeringMessage) -> Ack:
        return self._adapter.steer(endpoint, message)

    def status(self, endpoint: AgentEndpoint) -> AgentStatus:
        return self._adapter.status(endpoint)

    def interrupt(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._adapter.interrupt(endpoint)

    def collect(self, endpoint: AgentEndpoint) -> AgentResult:
        return self._adapter.collect(endpoint)

    def retire(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._adapter.retire(endpoint)


def _codex_jsonl(script: ScriptedCodexRun) -> str:
    """Render the event shape emitted by ``codex exec --json``.

    Codex has no structured quota signal, so ``exhausted`` renders as the prose
    ``error`` event a real usage-limit failure produces.
    """

    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "fake-thread"},
        {"type": "turn.started"},
    ]
    if script.terminal == "truncated":
        pass
    elif script.terminal == "exhausted":
        events.append({"type": "error", "message": "usage limit reached"})
    elif script.terminal == "error":
        events.append({"type": "turn.failed", "error": {"message": "failed"}})
    else:
        if script.result_document is not None:
            events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "fake-item",
                        "type": "agent_message",
                        "text": script.result_document,
                    },
                }
            )
        events.append({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
    return "\n".join(json.dumps(event) for event in events) + "\n"
