"""Per-harness launch syntax and stream interpretation (ARCH §9.1).

Each ``HarnessCommands`` implementation owns one harness's command line and the
meaning of its structured output stream. It performs no process effects and
reads no terminal prose: run-end classification uses only structured fields
(event types, error codes, rate-limit status), per ARCH §8.1 step 1.

Facts validated against real runs on 2026-11-04 (Codex 0.166.0, Claude Code
2.1.316): see ``docs/harness-facts.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Protocol

from .result_parser import ResultDecodingError, codex_final_message


class Harness(StrEnum):
    CODEX = "codex"
    CLAUDE_CODE = "claude-code"


class Sandbox(StrEnum):
    """Sandboxes a launch may request. Full access is never requested."""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"


class RunEnd(StrEnum):
    """How a run ended, from structured signals only (ARCH §8.1)."""

    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HarnessUsage:
    """Milburn's usage vocabulary (ARCH §9.3); ``None`` means not reported.

    ``input_tokens`` is total input, including cached reads and cache writes.
    """

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class RunReport:
    """What one run's stream says, independent of the process exit code."""

    run_end: RunEnd
    final_message: str | None
    usage: HarnessUsage | None
    session_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class HarnessInvocation:
    """Harness-neutral launch options, already validated by ``LaunchRequest``."""

    sandbox: Sandbox
    writable_dirs: tuple[str, ...] = ()
    result_schema: dict[str, Any] | None = None
    result_schema_path: str | None = None
    model: str | None = None
    resume_session: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sandbox, Sandbox):
            raise ValueError("sandbox must be a Sandbox value")
        if not isinstance(self.writable_dirs, tuple):
            raise ValueError("writable_dirs must be a tuple")
        if self.writable_dirs and self.sandbox is not Sandbox.WORKSPACE_WRITE:
            raise ValueError("writable_dirs require the workspace-write sandbox")
        for name in ("model", "resume_session", "result_schema_path"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value.startswith("-")
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"{name} must be one token that does not start with '-'")


class HarnessCommands(Protocol):
    harness: Harness

    def command(self, invocation: HarnessInvocation) -> tuple[str, ...]: ...

    def interpret(self, stdout: str, exit_code: int | None = None) -> RunReport: ...


def _with_exit(report: RunReport, exit_code: int | None) -> RunReport:
    """A non-zero exit with no final message is a failure, not a completion."""

    if (
        exit_code not in (None, 0)
        and report.run_end is RunEnd.COMPLETED
        and report.final_message is None
    ):
        return RunReport(
            RunEnd.FAILED,
            None,
            report.usage,
            report.session_id,
            f"{report.detail}; exit code {exit_code}",
        )
    return report


def _validate_executable(executable: str) -> None:
    if not executable or any(character.isspace() for character in executable):
        raise ValueError("executable must be one command name or path")


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _json_lines(stdout: str) -> tuple[list[dict[str, Any]], str | None]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return events, f"line {line_number} is not valid JSON"
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            return events, f"line {line_number} is not a typed event"
        events.append(event)
    return events, None


class CodexCommands:
    """``codex exec --json`` syntax and event semantics."""

    harness = Harness.CODEX

    def __init__(self, executable: str = "codex") -> None:
        _validate_executable(executable)
        self._executable = executable

    def command(self, invocation: HarnessInvocation) -> tuple[str, ...]:
        options: list[str] = [
            "--json",
            "--ignore-user-config",
            "--sandbox",
            invocation.sandbox.value,
        ]
        for directory in invocation.writable_dirs:
            options += ["--add-dir", directory]
        if invocation.result_schema is not None:
            if invocation.result_schema_path is None:
                raise ValueError("Codex needs a schema file path for --output-schema")
            options += ["--output-schema", invocation.result_schema_path]
        if invocation.model is not None:
            options += ["--model", invocation.model]
        if invocation.resume_session is not None:
            return (
                self._executable,
                "exec",
                "resume",
                *options,
                invocation.resume_session,
                "-",
            )
        return (self._executable, "exec", *options, "-")

    def interpret(self, stdout: str, exit_code: int | None = None) -> RunReport:
        return _with_exit(self._interpret(stdout), exit_code)

    def _interpret(self, stdout: str) -> RunReport:
        events, malformed = _json_lines(stdout)
        session_id = next(
            (
                event["thread_id"]
                for event in events
                if event["type"] == "thread.started"
                and isinstance(event.get("thread_id"), str)
            ),
            None,
        )
        usage = None
        for event in events:
            if event["type"] == "turn.completed" and isinstance(event.get("usage"), dict):
                raw = event["usage"]
                usage = HarnessUsage(
                    input_tokens=_optional_int(raw, "input_tokens"),
                    cached_input_tokens=_optional_int(raw, "cached_input_tokens"),
                    cache_write_tokens=_optional_int(raw, "cache_write_input_tokens"),
                    output_tokens=_optional_int(raw, "output_tokens"),
                    reasoning_tokens=_optional_int(raw, "reasoning_output_tokens"),
                )
        types = {event["type"] for event in events}
        if malformed is not None:
            return RunReport(RunEnd.FAILED, None, usage, session_id, f"Codex JSONL {malformed}")
        if "turn.failed" in types or "error" in types:
            # Codex reports errors as prose messages without a stable code, so
            # an exhausted run cannot be told apart mechanically. The
            # Coordinator may record it as exhausted (ARCH §8.1 step 1).
            kind = "turn.failed" if "turn.failed" in types else "error"
            return RunReport(
                RunEnd.UNKNOWN, None, usage, session_id, f"Codex reported semantic event {kind}"
            )
        if not events:
            return RunReport(RunEnd.FAILED, None, None, None, "Codex produced no events")
        try:
            message = codex_final_message(stdout)
        except ResultDecodingError as error:
            run_end = RunEnd.COMPLETED if "turn.completed" in types else RunEnd.UNKNOWN
            return RunReport(run_end, None, usage, session_id, str(error))
        return RunReport(RunEnd.COMPLETED, message, usage, session_id, "turn.completed")


_CLAUDE_READ_ONLY_TOOLS = "Bash,Read,Glob,Grep"
_CLAUDE_WRITE_TOOLS = "Bash,Read,Edit,Write,Glob,Grep"
# Sandboxed Bash cannot write outside the working directory and temporary
# paths; unsandboxed fallback is disabled. Validated 2026-11-04.
_CLAUDE_SANDBOX_SETTINGS = json.dumps(
    {
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
        }
    },
    separators=(",", ":"),
    sort_keys=True,
)
# Committing from a worktree writes the shared Git directory, which needs an
# explicit allowance; the command still runs inside the sandbox.
_CLAUDE_GIT_ALLOWANCES = ("Bash(git add:*)", "Bash(git commit:*)")
# Values of rate_limit_info.status that mean the run was refused for quota.
# Only "allowed" has been observed so far; ARCH §13 item 10 tracks capture of
# a real refusal.
_CLAUDE_REFUSED_STATUSES = frozenset({"rejected"})
# Error subtypes that are failures of the run itself, never quota exhaustion.
_CLAUDE_FAILURE_SUBTYPES = frozenset({"error_max_turns"})


class ClaudeCodeCommands:
    """``claude -p --output-format stream-json`` syntax and event semantics."""

    harness = Harness.CLAUDE_CODE

    def __init__(self, executable: str = "claude") -> None:
        _validate_executable(executable)
        self._executable = executable

    def command(self, invocation: HarnessInvocation) -> tuple[str, ...]:
        writable = invocation.sandbox is Sandbox.WORKSPACE_WRITE
        command: list[str] = [
            self._executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # Isolation (PRD R37): no user, project, or local settings, and no
            # MCP servers or connectors. Cut a trivial launch from ~59k to ~3.5k
            # input tokens in the 2026-11-04 measurement.
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--settings",
            _CLAUDE_SANDBOX_SETTINGS,
            "--permission-mode",
            "acceptEdits" if writable else "dontAsk",
            "--tools",
            _CLAUDE_WRITE_TOOLS if writable else _CLAUDE_READ_ONLY_TOOLS,
        ]
        if writable:
            command += ["--allowedTools", *_CLAUDE_GIT_ALLOWANCES]
        for directory in invocation.writable_dirs:
            command += ["--add-dir", directory]
        if invocation.result_schema is not None:
            command += [
                "--json-schema",
                json.dumps(invocation.result_schema, separators=(",", ":"), sort_keys=True),
            ]
        if invocation.model is not None:
            command += ["--model", invocation.model]
        if invocation.resume_session is not None:
            command += ["--resume", invocation.resume_session]
        return tuple(command)

    def interpret(self, stdout: str, exit_code: int | None = None) -> RunReport:
        return _with_exit(self._interpret(stdout), exit_code)

    def _interpret(self, stdout: str) -> RunReport:
        events, malformed = _json_lines(stdout)
        session_id: str | None = None
        refused = False
        result: dict[str, Any] | None = None
        for event in events:
            if isinstance(event.get("session_id"), str):
                if session_id is not None and event["session_id"] != session_id:
                    return RunReport(
                        RunEnd.FAILED, None, None, session_id,
                        "Claude Code stream mixes session IDs",
                    )
                session_id = event["session_id"]
            if event["type"] == "rate_limit_event":
                info = event.get("rate_limit_info")
                if isinstance(info, dict) and info.get("status") in _CLAUDE_REFUSED_STATUSES:
                    refused = True
            elif event["type"] == "result":
                result = event
        usage = _claude_usage(result.get("usage")) if result else None
        if malformed is not None:
            run_end = RunEnd.EXHAUSTED if refused else RunEnd.FAILED
            return RunReport(run_end, None, usage, session_id, f"Claude Code stream {malformed}")
        if result is None:
            if refused:
                return RunReport(
                    RunEnd.EXHAUSTED, None, None, session_id, "rate limit refused before a result"
                )
            return RunReport(RunEnd.UNKNOWN, None, None, session_id, "no result event")
        if result.get("api_error_status") == 429 or refused:
            return RunReport(
                RunEnd.EXHAUSTED,
                None,
                usage,
                session_id,
                f"rate limited (api_error_status={result.get('api_error_status')!r})",
            )
        if result.get("is_error") is not False or result.get("subtype") != "success":
            # Only subtypes known not to mean exhaustion are failures. Anything
            # else stays unknown so the Coordinator can judge it, and hand off
            # if it was a usage limit (ARCH §8.1 step 1, §13 item 10).
            known_failure = result.get("subtype") in _CLAUDE_FAILURE_SUBTYPES
            return RunReport(
                RunEnd.FAILED if known_failure else RunEnd.UNKNOWN,
                None,
                usage,
                session_id,
                f"result subtype {result.get('subtype')!r}, is_error={result.get('is_error')!r}",
            )
        structured = result.get("structured_output")
        if not isinstance(structured, dict):
            # Every launch requests --json-schema, so prose in ``result`` is
            # never accepted as the result: enforcement must not be skipped.
            return RunReport(
                RunEnd.COMPLETED, None, usage, session_id,
                "result has no structured_output; schema enforcement was not applied",
            )
        message = json.dumps(structured, separators=(",", ":"), sort_keys=True)
        return RunReport(RunEnd.COMPLETED, message, usage, session_id, "result success")


def _claude_usage(raw: object) -> HarnessUsage | None:
    if not isinstance(raw, dict):
        return None
    uncached = _optional_int(raw, "input_tokens")
    cache_read = _optional_int(raw, "cache_read_input_tokens")
    cache_write = _optional_int(raw, "cache_creation_input_tokens")
    parts = (uncached, cache_read, cache_write)
    total = sum(part for part in parts if part is not None) if any(
        part is not None for part in parts
    ) else None
    details = raw.get("output_tokens_details")
    reasoning = _optional_int(details, "thinking_tokens") if isinstance(details, dict) else None
    return HarnessUsage(
        input_tokens=total,
        cached_input_tokens=cache_read,
        cache_write_tokens=cache_write,
        output_tokens=_optional_int(raw, "output_tokens"),
        reasoning_tokens=reasoning,
    )
