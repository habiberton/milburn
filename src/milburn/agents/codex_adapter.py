"""Codex-specific launch and result semantics over an injected runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from milburn.domain import Role

from .briefs import BriefRenderer, LaunchBrief, RenderedBrief
from .result_parser import (
    AgentResultError,
    AgentResultParser,
    ParsedAgentResult,
    ResultCorrelation,
)


class ProcessState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProcessLaunch:
    command: tuple[str, ...]
    cwd: str
    stdin: str


@dataclass(frozen=True, slots=True)
class ProcessStatus:
    state: ProcessState
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessCollection:
    state: ProcessState
    exit_code: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class Ack:
    accepted: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ControlResult:
    observed: bool
    detail: str


class CodexProcessRuntime(Protocol):
    """Injected process boundary; it contains no Milburn task semantics."""

    def launch(self, spec: ProcessLaunch) -> str: ...

    def steer(self, endpoint: str, message: str) -> Ack: ...

    def status(self, endpoint: str) -> ProcessStatus: ...

    def interrupt(self, endpoint: str) -> ControlResult: ...

    def collect(self, endpoint: str) -> ProcessCollection: ...

    def retire(self, endpoint: str) -> ControlResult: ...


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    role: Role
    task_id: str
    attempt_id: str
    worktree: str
    objective: str
    role_rules: str
    task_context: str
    repository_instructions: str
    result_contract: str
    required_skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentEndpoint:
    runtime_endpoint: str
    role: Role
    task_id: str
    attempt_id: str
    brief_digest: str
    rules_digest: str


@dataclass(frozen=True, slots=True)
class SteeringMessage:
    role: Role
    task_id: str
    attempt_id: str
    content: str


@dataclass(frozen=True, slots=True)
class AgentStatus:
    endpoint: AgentEndpoint
    process_state: ProcessState
    exit_code: int | None


@dataclass(frozen=True, slots=True)
class ProcessExit:
    exit_code: int
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Collection evidence with independent process and task outcomes."""

    endpoint: AgentEndpoint
    process_exit: ProcessExit | None
    task_result: ParsedAgentResult | None
    protocol_error: str | None

    @property
    def collection_complete(self) -> bool:
        return self.process_exit is not None


class EndpointCorrelationError(ValueError):
    """Raised when steering is addressed to another logical attempt."""


class CodexAdapter:
    """Own Codex CLI syntax while delegating process effects to a runtime."""

    def __init__(
        self,
        runtime: CodexProcessRuntime,
        *,
        executable: str = "codex",
        renderer: BriefRenderer | None = None,
        parser: AgentResultParser | None = None,
    ) -> None:
        if not executable or any(character.isspace() for character in executable):
            raise ValueError("executable must be one command name or path")
        self._runtime = runtime
        self._executable = executable
        self._renderer = renderer or BriefRenderer()
        self._parser = parser or AgentResultParser()

    def launch(self, request: LaunchRequest) -> AgentEndpoint:
        rendered = self._render(request)
        runtime_endpoint = self._runtime.launch(
            ProcessLaunch(
                command=(self._executable, "exec", "--json", "-"),
                cwd=request.worktree,
                stdin=rendered.content,
            )
        )
        if not isinstance(runtime_endpoint, str) or not runtime_endpoint.strip():
            raise ValueError("runtime returned an invalid endpoint")
        return AgentEndpoint(
            runtime_endpoint=runtime_endpoint,
            role=request.role,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            brief_digest=rendered.digest,
            rules_digest=rendered.rules_digest,
        )

    def steer(self, endpoint: AgentEndpoint, message: SteeringMessage) -> Ack:
        expected = (endpoint.role, endpoint.task_id, endpoint.attempt_id)
        actual = (message.role, message.task_id, message.attempt_id)
        if actual != expected:
            raise EndpointCorrelationError(
                "steering correlation does not match the target endpoint"
            )
        if not message.content.strip():
            raise ValueError("steering content must be non-empty")
        return self._runtime.steer(endpoint.runtime_endpoint, message.content)

    def status(self, endpoint: AgentEndpoint) -> AgentStatus:
        observed = self._runtime.status(endpoint.runtime_endpoint)
        return AgentStatus(
            endpoint=endpoint,
            process_state=observed.state,
            exit_code=observed.exit_code,
        )

    def interrupt(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._runtime.interrupt(endpoint.runtime_endpoint)

    def collect(self, endpoint: AgentEndpoint) -> AgentResult:
        collected = self._runtime.collect(endpoint.runtime_endpoint)
        if collected.state is not ProcessState.EXITED:
            return AgentResult(
                endpoint=endpoint,
                process_exit=None,
                task_result=None,
                protocol_error=None,
            )
        if collected.exit_code is None:
            return AgentResult(
                endpoint=endpoint,
                process_exit=None,
                task_result=None,
                protocol_error="runtime reported exited without an exit code",
            )

        process_exit = ProcessExit(collected.exit_code, collected.stderr)
        if not collected.stdout.strip():
            return AgentResult(
                endpoint=endpoint,
                process_exit=process_exit,
                task_result=None,
                protocol_error="Codex exited without a semantic task result",
            )
        try:
            task_result = self._parser.parse(
                collected.stdout,
                ResultCorrelation(
                    role=endpoint.role,
                    task_id=endpoint.task_id,
                    attempt_id=endpoint.attempt_id,
                ),
            )
        except AgentResultError as error:
            return AgentResult(
                endpoint=endpoint,
                process_exit=process_exit,
                task_result=None,
                protocol_error=str(error),
            )
        return AgentResult(
            endpoint=endpoint,
            process_exit=process_exit,
            task_result=task_result,
            protocol_error=None,
        )

    def retire(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._runtime.retire(endpoint.runtime_endpoint)

    def _render(self, request: LaunchRequest) -> RenderedBrief:
        return self._renderer.render(
            LaunchBrief(
                role=request.role,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                objective=request.objective,
                role_rules=request.role_rules,
                task_context=request.task_context,
                repository_instructions=request.repository_instructions,
                result_contract=request.result_contract,
                required_skills=request.required_skills,
            )
        )
