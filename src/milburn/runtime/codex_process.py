"""Subprocess host for one-shot ``codex exec`` launches.

This runtime implements ``CodexProcessRuntime`` for non-interactive launches.
It cannot steer a running ``exec`` process: an ``exec`` run reads its whole
prompt from stdin and then exits, so steering is refused rather than faked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import IO, Callable

from milburn.agents.codex_adapter import (
    Ack,
    ControlResult,
    ProcessCollection,
    ProcessLaunch,
    ProcessState,
    ProcessStatus,
)


@dataclass(slots=True)
class _Run:
    process: subprocess.Popen[str]
    stdout_path: Path
    stderr_path: Path
    stdout_file: IO[str]
    stderr_file: IO[str]
    collected: ProcessCollection | None = None


class SubprocessCodexRuntime:
    """Launch each agent as a child process and keep its output as log files."""

    def __init__(
        self,
        log_root: Path,
        *,
        timeout_seconds: float = 1800.0,
        endpoint_ids: Callable[[], str],
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._log_root = log_root
        self._timeout = timeout_seconds
        self._endpoint_ids = endpoint_ids
        self._runs: dict[str, _Run] = {}

    def launch(self, spec: ProcessLaunch) -> str:
        endpoint = self._endpoint_ids()
        if endpoint in self._runs:
            raise ValueError(f"endpoint {endpoint} was already launched")
        self._log_root.mkdir(parents=True, exist_ok=True)
        stdout_path = self._log_root / f"{endpoint}.jsonl"
        stderr_path = self._log_root / f"{endpoint}.stderr.log"
        stdout_file = stdout_path.open("w", encoding="utf-8")
        stderr_file = stderr_path.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                spec.command,
                cwd=spec.cwd,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except OSError:
            stdout_file.close()
            stderr_file.close()
            raise
        assert process.stdin is not None
        try:
            process.stdin.write(spec.stdin)
        finally:
            process.stdin.close()
        self._runs[endpoint] = _Run(
            process, stdout_path, stderr_path, stdout_file, stderr_file
        )
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        self._require(endpoint)
        return Ack(
            accepted=False,
            detail="codex exec runs cannot be steered; resume a session instead",
        )

    def status(self, endpoint: str) -> ProcessStatus:
        run = self._require(endpoint)
        code = run.process.poll()
        if code is None:
            return ProcessStatus(ProcessState.RUNNING)
        return ProcessStatus(ProcessState.EXITED, code)

    def interrupt(self, endpoint: str) -> ControlResult:
        run = self._require(endpoint)
        if run.process.poll() is not None:
            return ControlResult(observed=True, detail="process already exited")
        run.process.terminate()
        try:
            run.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            run.process.kill()
            run.process.wait()
        return ControlResult(observed=True, detail="process stopped")

    def collect(self, endpoint: str) -> ProcessCollection:
        """Wait for the run to exit (bounded by the timeout) and return its output."""
        run = self._require(endpoint)
        if run.collected is not None:
            return run.collected
        try:
            code = run.process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            self.interrupt(endpoint)
            code = run.process.returncode
        run.stdout_file.close()
        run.stderr_file.close()
        run.collected = ProcessCollection(
            state=ProcessState.EXITED,
            exit_code=code,
            stdout=run.stdout_path.read_text(encoding="utf-8"),
            stderr=run.stderr_path.read_text(encoding="utf-8"),
        )
        return run.collected

    def retire(self, endpoint: str) -> ControlResult:
        return self.interrupt(endpoint)

    def log_path(self, endpoint: str) -> Path:
        return self._require(endpoint).stdout_path

    def _require(self, endpoint: str) -> _Run:
        run = self._runs.get(endpoint)
        if run is None:
            raise KeyError(f"unknown endpoint {endpoint}")
        return run
