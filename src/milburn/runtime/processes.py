"""Process inspection used to fence tmux endpoints against PID reuse."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    """Run argument-vector commands without invoking a shell."""

    def run(self, arguments: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            tuple(arguments),
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """A process fingerprint; start time distinguishes a reused PID."""

    pid: int
    started_at: str
    executable: str

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("pid must be positive")
        if not self.started_at.strip():
            raise ValueError("started_at must not be empty")
        if not self.executable.strip():
            raise ValueError("executable must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "started_at": self.started_at,
            "executable": self.executable,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ProcessIdentity:
        if set(value) != {"pid", "started_at", "executable"}:
            raise ValueError("invalid process identity fields")
        pid = value["pid"]
        started_at = value["started_at"]
        executable = value["executable"]
        if not isinstance(pid, int) or isinstance(pid, bool):
            raise ValueError("pid must be an integer")
        if not isinstance(started_at, str) or not isinstance(executable, str):
            raise ValueError("process identity strings are invalid")
        return cls(pid, started_at, executable)


class ProcessInspector(Protocol):
    def identify(self, pid: int) -> ProcessIdentity | None: ...


class PsProcessInspector:
    """Portable process identity based on the OS process start timestamp."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def identify(self, pid: int) -> ProcessIdentity | None:
        if pid <= 0:
            return None
        started = self._runner.run(("ps", "-o", "lstart=", "-p", str(pid)))
        executable = self._runner.run(("ps", "-o", "comm=", "-p", str(pid)))
        if started.returncode or executable.returncode:
            return None
        start_value = started.stdout.strip()
        executable_value = executable.stdout.strip()
        if not start_value or not executable_value:
            return None
        return ProcessIdentity(pid, start_value, executable_value)
