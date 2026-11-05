"""Harness launch and result semantics over an injected process runtime.

``AgentAdapter`` owns the harness-neutral lifecycle (brief rendering, result
correlation, schema enforcement). A ``HarnessCommands`` implementation owns one
harness's command line and stream (``agents/harness.py``). ``CodexAdapter`` and
``ClaudeCodeAdapter`` bind the two (ARCH §9.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Protocol

from milburn.domain import Role, SkillBinding

from .briefs import BriefRenderer, LaunchBrief, RenderedBrief
from .harness import (
    ClaudeCodeCommands,
    CodexCommands,
    Harness,
    HarnessCommands,
    HarnessInvocation,
    HarnessUsage,
    RunEnd,
    Sandbox,
)
from .result_parser import (
    AgentResultError,
    AgentResultParser,
    ParsedAgentResult,
    ResultCorrelation,
    ResultExpectation,
    result_contract,
    result_schema,
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
    env: tuple[tuple[str, str], ...] = ()
    """Variables added to the inherited environment (per-attempt Git identity, G22)."""


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
    expected_result_type: str
    expected_result_schema_version: int = 1
    skill_bindings: tuple[SkillBinding, ...] = ()
    sandbox: str | None = None
    writable_dirs: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    model: str | None = None

    def __post_init__(self) -> None:
        if self.sandbox is not None and self.sandbox not in SANDBOX_MODES:
            raise ValueError(
                f"sandbox must be one of {sorted(SANDBOX_MODES)} or None"
            )
        if not isinstance(self.env, tuple):
            raise ValueError("env must be a tuple of (name, value) pairs")
        names: set[str] = set()
        for pair in self.env:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise ValueError("env must be a tuple of (name, value) pairs")
            name, value = pair
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise ValueError(f"invalid environment variable name {name!r}")
            if name in IDENTITY_ENV:
                raise ValueError(f"{name} is set by the adapter and cannot be overridden")
            if name in names:
                raise ValueError(f"duplicate environment variable {name}")
            names.add(name)
            if not isinstance(value, str) or "\0" in value:
                raise ValueError(f"environment value for {name} must be text without NUL")
        if self.model is not None and (
            not isinstance(self.model, str)
            or not self.model
            or any(character.isspace() for character in self.model)
        ):
            raise ValueError("model must be a non-empty name without whitespace")
        if not isinstance(self.writable_dirs, tuple):
            raise ValueError("writable_dirs must be a tuple")
        if self.writable_dirs and self.sandbox != "workspace-write":
            raise ValueError("writable_dirs require the workspace-write sandbox")
        for directory in self.writable_dirs:
            if (
                not isinstance(directory, str)
                or not directory.startswith("/")
                or "\n" in directory
                or os.path.normpath(directory) != directory
            ):
                raise ValueError("writable_dirs must be absolute normalized paths")
            # Resolve symlinks so an alias cannot slip past the checks below.
            home = Path.home().resolve()
            resolved = Path(directory).resolve()
            if resolved == Path("/") or home == resolved or home.is_relative_to(resolved):
                raise ValueError(
                    "writable_dirs must not contain the home directory (that is full access)"
                )
            milburn_home = home / ".milburn"
            if resolved == milburn_home or resolved.is_relative_to(milburn_home):
                raise ValueError(
                    "writable_dirs must not include ~/.milburn (event store and schemas)"
                )


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

IDENTITY_ENV = frozenset(
    {
        "MILBURN_ATTEMPT_ID",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    }
)
"""Variables the adapter always sets from the request (G22, PRD R40)."""

SANDBOX_MODES = frozenset(mode.value for mode in Sandbox)
"""Sandbox modes the controller may request. Full access is never requested."""


@dataclass(frozen=True, slots=True)
class AgentEndpoint:
    runtime_endpoint: str
    role: Role
    task_id: str
    attempt_id: str
    expected_result_type: str
    expected_result_schema_version: int
    brief_digest: str
    rules_digest: str
    skill_bindings: tuple[SkillBinding, ...]
    harness: Harness = Harness.CODEX


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
    run_end: RunEnd = RunEnd.UNKNOWN
    usage: HarnessUsage | None = None
    session_id: str | None = None

    @property
    def collection_complete(self) -> bool:
        return self.process_exit is not None


class EndpointCorrelationError(ValueError):
    """Raised when steering is addressed to another logical attempt."""


_HARNESS_NAMES = {Harness.CODEX: "Codex", Harness.CLAUDE_CODE: "Claude Code"}


class AgentAdapter:
    """Run one role attempt on one harness through an injected process runtime."""

    def __init__(
        self,
        runtime: CodexProcessRuntime,
        commands: HarnessCommands,
        *,
        renderer: BriefRenderer | None = None,
        parser: AgentResultParser | None = None,
        schema_dir: Path | None = None,
        identity_email: str | None = None,
    ) -> None:
        if identity_email is not None and (
            not identity_email or any(c.isspace() for c in identity_email) or "@" not in identity_email
        ):
            raise ValueError("identity_email must be one email address")
        self._runtime = runtime
        self._commands = commands
        self._renderer = renderer or BriefRenderer()
        self._parser = parser or AgentResultParser()
        # Private, per-user directory: a shared /tmp location would let another
        # user plant a weaker schema under the predictable digest name.
        self._schema_dir = schema_dir or Path.home() / ".milburn" / "schemas"
        self._identity_email = identity_email

    @property
    def harness(self) -> Harness:
        return self._commands.harness

    def launch(self, request: LaunchRequest) -> AgentEndpoint:
        if request.sandbox is None:
            # ARCH §9.1: never fall back to the harness's own default, which
            # may be full access (gap G12).
            raise ValueError("sandbox is required; choose read-only or workspace-write")
        expectation = self._expectation(request)
        rendered = self._render(request, expectation)
        schema = result_schema(expectation)
        command = self._commands.command(
            HarnessInvocation(
                sandbox=Sandbox(request.sandbox),
                writable_dirs=request.writable_dirs,
                result_schema=schema,
                result_schema_path=self._schema_file(schema),
                model=request.model,
            )
        )
        runtime_endpoint = self._runtime.launch(
            ProcessLaunch(
                command=command,
                cwd=request.worktree,
                stdin=rendered.content,
                env=self._identity_env(request) + request.env,
            )
        )
        if not isinstance(runtime_endpoint, str) or not runtime_endpoint.strip():
            raise ValueError("runtime returned an invalid endpoint")
        return AgentEndpoint(
            runtime_endpoint=runtime_endpoint,
            role=request.role,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            expected_result_type=expectation.result_type,
            expected_result_schema_version=expectation.schema_version,
            brief_digest=rendered.digest,
            rules_digest=rendered.rules_digest,
            skill_bindings=rendered.skill_bindings,
            harness=self.harness,
        )

    def steer(self, endpoint: AgentEndpoint, message: SteeringMessage) -> Ack:
        self._require_harness(endpoint)
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
        self._require_harness(endpoint)
        observed = self._runtime.status(endpoint.runtime_endpoint)
        return AgentStatus(
            endpoint=endpoint,
            process_state=observed.state,
            exit_code=observed.exit_code,
        )

    def interrupt(self, endpoint: AgentEndpoint) -> ControlResult:
        self._require_harness(endpoint)
        return self._runtime.interrupt(endpoint.runtime_endpoint)

    def collect(self, endpoint: AgentEndpoint) -> AgentResult:
        self._require_harness(endpoint)
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
        name = _HARNESS_NAMES[self.harness]
        if not collected.stdout.strip():
            return AgentResult(
                endpoint=endpoint,
                process_exit=process_exit,
                task_result=None,
                protocol_error=f"{name} exited without a semantic task result",
                run_end=RunEnd.FAILED,
            )
        report = self._commands.interpret(collected.stdout, collected.exit_code)
        common = {
            "endpoint": endpoint,
            "process_exit": process_exit,
            "run_end": report.run_end,
            "usage": report.usage,
            "session_id": report.session_id,
        }
        if report.final_message is None:
            return AgentResult(task_result=None, protocol_error=report.detail, **common)
        try:
            task_result = self._parser.parse(
                report.final_message, self._expectation_for(endpoint)
            )
        except AgentResultError as error:
            return AgentResult(task_result=None, protocol_error=str(error), **common)
        return AgentResult(task_result=task_result, protocol_error=None, **common)

    def retire(self, endpoint: AgentEndpoint) -> ControlResult:
        self._require_harness(endpoint)
        return self._runtime.retire(endpoint.runtime_endpoint)

    def _require_harness(self, endpoint: AgentEndpoint) -> None:
        if endpoint.harness is not self.harness:
            raise EndpointCorrelationError(
                f"endpoint belongs to {endpoint.harness.value}, not {self.harness.value}"
            )

    def _identity_env(self, request: LaunchRequest) -> tuple[tuple[str, str], ...]:
        """Per-attempt Git identity and attempt marker, never the user's (G22)."""

        name = f"Milburn {request.role.value} [{request.task_id}/{request.attempt_id}]"
        email = self._identity_email or (
            f"{request.role.value}.{request.task_id}.{request.attempt_id}@milburn.invalid"
        )
        return (
            # Attempt IDs repeat across tasks, so the marker is task-qualified.
            ("MILBURN_ATTEMPT_ID", f"{request.task_id}/{request.attempt_id}"),
            ("GIT_AUTHOR_NAME", name),
            ("GIT_AUTHOR_EMAIL", email),
            ("GIT_COMMITTER_NAME", name),
            ("GIT_COMMITTER_EMAIL", email),
        )

    def _schema_file(self, schema: dict[str, object]) -> str:
        """Write the schema content-addressed in a private directory; verify reuse."""

        content = json.dumps(schema, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._schema_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._schema_dir, 0o700)
        path = self._schema_dir / f"{digest}.json"
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != content:
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        return str(path)

    def _expectation_for(self, endpoint: AgentEndpoint) -> ResultExpectation:
        return ResultExpectation(
            correlation=ResultCorrelation(
                role=endpoint.role,
                task_id=endpoint.task_id,
                attempt_id=endpoint.attempt_id,
            ),
            result_type=endpoint.expected_result_type,
            schema_version=endpoint.expected_result_schema_version,
        )

    def _expectation(self, request: LaunchRequest) -> ResultExpectation:
        return ResultExpectation(
            correlation=ResultCorrelation(
                role=request.role,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
            ),
            result_type=request.expected_result_type,
            schema_version=request.expected_result_schema_version,
        )

    def _render(
        self, request: LaunchRequest, expectation: ResultExpectation
    ) -> RenderedBrief:
        return self._renderer.render(
            LaunchBrief(
                role=request.role,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                objective=request.objective,
                role_rules=request.role_rules,
                task_context=request.task_context,
                repository_instructions=request.repository_instructions,
                result_contract=result_contract(expectation),
                skill_bindings=request.skill_bindings,
            )
        )


class CodexAdapter(AgentAdapter):
    """``codex exec`` role runs."""

    def __init__(
        self,
        runtime: CodexProcessRuntime,
        *,
        executable: str = "codex",
        renderer: BriefRenderer | None = None,
        parser: AgentResultParser | None = None,
        schema_dir: Path | None = None,
    ) -> None:
        super().__init__(
            runtime,
            CodexCommands(executable),
            renderer=renderer,
            parser=parser,
            schema_dir=schema_dir,
        )


class ClaudeCodeAdapter(AgentAdapter):
    """``claude -p`` role runs."""

    def __init__(
        self,
        runtime: CodexProcessRuntime,
        *,
        executable: str = "claude",
        renderer: BriefRenderer | None = None,
        parser: AgentResultParser | None = None,
        schema_dir: Path | None = None,
    ) -> None:
        super().__init__(
            runtime,
            ClaudeCodeCommands(executable),
            renderer=renderer,
            parser=parser,
            schema_dir=schema_dir,
        )
