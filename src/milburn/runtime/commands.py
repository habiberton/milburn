"""Bounded command output with a durable log outside Coder worktrees."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
from time import monotonic

from .worktrees import WorktreeLease, WorktreeManagerProtocol, WorktreeError


class CommandExecutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BoundedCommandResult:
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    log_ref: Path
    excerpt: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    @property
    def summary(self) -> str:
        status = "passed" if self.passed else f"failed ({self.exit_code})"
        display = shlex.join(self.command)
        if len(display) > 512:
            display = display[:509] + "..."
        return f"{display}: {status}; {self.duration_seconds:.2f}s; log: {self.log_ref}"


class BoundedCommandRunner:
    def __init__(self, log_dir: Path, *, worktrees: WorktreeManagerProtocol,
                 max_excerpt_chars: int = 2_000) -> None:
        if not isinstance(log_dir, Path) or not log_dir.is_absolute():
            raise CommandExecutionError("log directory must be absolute")
        if not isinstance(max_excerpt_chars, int) or isinstance(max_excerpt_chars, bool) or max_excerpt_chars < 0:
            raise CommandExecutionError("excerpt limit must be non-negative")
        self._log_dir = log_dir
        self._max_excerpt_chars = max_excerpt_chars
        self._worktrees = worktrees

    def run(self, lease: WorktreeLease, command: tuple[str, ...], *, timeout: float = 300) -> BoundedCommandResult:
        if not isinstance(lease, WorktreeLease) or not lease.worktree.is_dir():
            raise CommandExecutionError("command requires an existing assigned worktree")
        try:
            inspection = self._worktrees.inspect(lease)
        except WorktreeError as error:
            raise CommandExecutionError("command requires a registered owned worktree") from error
        if not inspection.matched or inspection.branch != lease.branch:
            raise CommandExecutionError("command requires a registered owned worktree")
        if not isinstance(command, tuple) or not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise CommandExecutionError("command must be a non-empty argument tuple")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise CommandExecutionError("timeout must be positive")
        if self._log_dir == lease.worktree or lease.worktree in self._log_dir.parents:
            raise CommandExecutionError("command logs must be outside the worktree")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        start = monotonic()
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", dir=self._log_dir,
                                         prefix="coder-command-", suffix=".log", delete=False) as log:
            log_path = Path(log.name)
            try:
                completed = subprocess.run(command, cwd=lease.worktree, text=True,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           timeout=timeout, check=False)
                exit_code = completed.returncode
            except subprocess.TimeoutExpired:
                exit_code = 124
                log.write("\nCommand timed out.\n")
            except OSError as error:
                exit_code = 127
                log.write(f"\nCommand could not start: {type(error).__name__}.\n")
        elapsed = monotonic() - start
        excerpt = ""
        if exit_code and self._max_excerpt_chars:
            with log_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - self._max_excerpt_chars))
                excerpt = stream.read().decode("utf-8", errors="replace")[-self._max_excerpt_chars:]
        return BoundedCommandResult(command, exit_code, elapsed, log_path, excerpt)

    def run_tests(self, lease: WorktreeLease, pytest_args: tuple[str, ...], *, timeout: float = 300) -> BoundedCommandResult:
        if not isinstance(pytest_args, tuple) or any(not isinstance(arg, str) or not arg for arg in pytest_args):
            raise CommandExecutionError("test arguments must be a string tuple")
        script = lease.worktree / "scripts/run-tests.sh"
        if not script.is_file() or not os.access(script, os.X_OK):
            raise CommandExecutionError("assigned worktree lacks scripts/run-tests.sh")
        return self.run(lease, (str(script), *pytest_args), timeout=timeout)
