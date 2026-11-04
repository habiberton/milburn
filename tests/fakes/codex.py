"""Deterministic Codex adapter fixtures with no process or network effects."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class ScriptedCodexRun:
    result_document: str | None
    exit_code: int = 0
    stderr: str = ""


class FakeCodexRuntime:
    """A process boundary that consumes one scripted run per launch."""

    def __init__(self, scripts: tuple[ScriptedCodexRun, ...]) -> None:
        self._remaining = list(scripts)
        self._runs: dict[str, ScriptedCodexRun] = {}
        self.launches: list[ProcessLaunch] = []
        self.steering: list[tuple[str, str]] = []
        self.interrupted: list[str] = []
        self.retired: list[str] = []

    def launch(self, spec: ProcessLaunch) -> str:
        if not self._remaining:
            raise AssertionError("no scripted Codex run remains")
        endpoint = f"fake-codex-{len(self.launches) + 1}"
        self.launches.append(spec)
        self._runs[endpoint] = self._remaining.pop(0)
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        self._require(endpoint)
        self.steering.append((endpoint, message))
        return Ack(accepted=True, detail="scripted acknowledgement")

    def status(self, endpoint: str) -> ProcessStatus:
        run = self._require(endpoint)
        return ProcessStatus(ProcessState.EXITED, run.exit_code)

    def interrupt(self, endpoint: str) -> ControlResult:
        self._require(endpoint)
        self.interrupted.append(endpoint)
        return ControlResult(observed=True, detail="scripted interrupt")

    def collect(self, endpoint: str) -> ProcessCollection:
        run = self._require(endpoint)
        return ProcessCollection(
            state=ProcessState.EXITED,
            exit_code=run.exit_code,
            stdout=run.result_document or "",
            stderr=run.stderr,
        )

    def retire(self, endpoint: str) -> ControlResult:
        self._require(endpoint)
        self.retired.append(endpoint)
        return ControlResult(observed=True, detail="scripted retirement")

    def _require(self, endpoint: str) -> ScriptedCodexRun:
        try:
            return self._runs[endpoint]
        except KeyError as error:
            raise AssertionError(f"unknown fake endpoint {endpoint}") from error


class FakeCodexAdapter:
    """Public fake with the same lifecycle as ``CodexAdapter``."""

    def __init__(self, scripts: tuple[ScriptedCodexRun, ...]) -> None:
        self.runtime = FakeCodexRuntime(scripts)
        self._adapter = CodexAdapter(self.runtime, executable="fake-codex")

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
