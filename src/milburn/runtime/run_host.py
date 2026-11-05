"""Detached run host for role-agent runs (ARCH A1).

The ``milburn`` CLI is not a daemon: ``dispatch`` starts a run and exits, and a
later ``collect`` reads the result. Each run is hosted by a small detached
Python process (``python -m milburn.runtime.run_host <run_dir> <endpoint>``)
that feeds the brief on stdin, writes stdout and stderr to files, waits for the
harness, and records the exit code atomically. Everything about a run is in
files under ``run_dir``, so any later CLI process can observe it:

- ``<endpoint>.launch.json``: command, working directory, and added environment
  (mode 0600; the directory lives outside every worktree).
- ``<endpoint>.brief``: the stdin brief.
- ``<endpoint>.host.json``: the host process identity (PID plus start time).
- ``<endpoint>.jsonl`` / ``<endpoint>.stderr.log``: the harness output.
- ``<endpoint>.exit.json``: ``{"exit_code": n}``, written only after the child
  exits. Its presence is the only proof that a run finished.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Callable

import milburn

from milburn.agents.codex_adapter import (
    Ack,
    ControlResult,
    ProcessCollection,
    ProcessLaunch,
    ProcessState,
    ProcessStatus,
)
from .processes import ProcessIdentity, ProcessInspector, PsProcessInspector

_ENDPOINT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class RunHostError(RuntimeError):
    """A run could not be started or observed as requested."""


def _paths(run_dir: Path, endpoint: str) -> dict[str, Path]:
    return {
        "launch": run_dir / f"{endpoint}.launch.json",
        "brief": run_dir / f"{endpoint}.brief",
        "host": run_dir / f"{endpoint}.host.json",
        "stdout": run_dir / f"{endpoint}.jsonl",
        "stderr": run_dir / f"{endpoint}.stderr.log",
        "exit": run_dir / f"{endpoint}.exit.json",
        "retired": run_dir / f"{endpoint}.retired",
    }


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _write_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class DetachedRunRuntime:
    """``CodexProcessRuntime`` whose runs outlive the launching process."""

    def __init__(
        self,
        run_dir: Path,
        *,
        endpoint_ids: Callable[[], str],
        inspector: ProcessInspector | None = None,
        python: str = sys.executable,
        stop_grace_seconds: float = 10.0,
    ) -> None:
        if not run_dir.is_absolute():
            raise ValueError("run_dir must be absolute")
        self._run_dir = run_dir
        self._endpoint_ids = endpoint_ids
        self._inspector = inspector or PsProcessInspector()
        self._python = python
        self._grace = stop_grace_seconds

    def launch(self, spec: ProcessLaunch) -> str:
        endpoint = self._endpoint_ids()
        if not isinstance(endpoint, str) or not _ENDPOINT.fullmatch(endpoint):
            raise RunHostError(f"invalid endpoint id {endpoint!r}")
        self._run_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._run_dir, 0o700)
        paths = _paths(self._run_dir, endpoint)
        if paths["launch"].exists():
            raise RunHostError(f"endpoint {endpoint} was already launched")
        _write_private(
            paths["launch"],
            json.dumps(
                {"command": list(spec.command), "cwd": spec.cwd, "env": dict(spec.env)},
                sort_keys=True,
            ),
        )
        _write_private(paths["brief"], spec.stdin)
        package_root = str(Path(milburn.__file__).resolve().parents[1])
        host_env = dict(os.environ)
        # The host needs Milburn importable; the harness child gets the
        # caller's original PYTHONPATH back (see _host_main).
        host_env["MILBURN_RUN_HOST_PYTHONPATH"] = os.environ.get("PYTHONPATH", "")
        host_env["PYTHONPATH"] = os.pathsep.join(
            part for part in (package_root, os.environ.get("PYTHONPATH", "")) if part
        )
        with open(self._run_dir / f"{endpoint}.host.log", "w", encoding="utf-8") as log:
            host = subprocess.Popen(
                (self._python, "-m", "milburn.runtime.run_host", str(self._run_dir), endpoint),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=host_env,
            )
        identity = None
        for _ in range(20):
            identity = self._inspector.identify(host.pid)
            if identity is not None:
                break
            time.sleep(0.05)
        if identity is None:
            # The host may already have finished a very short run; its exit
            # file is then the evidence. Record the PID without a start time.
            identity_record = {"pid": host.pid, "started_at": "", "executable": ""}
        else:
            identity_record = identity.to_dict()
        _write_atomic(paths["host"], json.dumps(identity_record, sort_keys=True))
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        self._require(endpoint)
        return Ack(
            accepted=False,
            detail="headless runs cannot be steered; resume the session instead",
        )

    def status(self, endpoint: str) -> ProcessStatus:
        paths = self._require(endpoint)
        code = self._exit_code(paths)
        if code is not None:
            return ProcessStatus(ProcessState.EXITED, code)
        if self._host_alive(paths):
            return ProcessStatus(ProcessState.RUNNING)
        if paths["exit"].exists():
            return ProcessStatus(ProcessState.EXITED, self._exit_code(paths))
        return ProcessStatus(ProcessState.UNKNOWN)

    def interrupt(self, endpoint: str) -> ControlResult:
        paths = self._require(endpoint)
        if paths["exit"].exists():
            return ControlResult(observed=True, detail="process already exited")
        if not self._host_alive(paths):
            return ControlResult(observed=False, detail="host is not running; outcome unknown")
        pid = int(json.loads(paths["host"].read_text(encoding="utf-8"))["pid"])
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + self._grace
        while time.monotonic() < deadline:
            if paths["exit"].exists() or not self._host_alive(paths):
                break
            time.sleep(0.05)
        if not paths["exit"].exists() and self._host_alive(paths):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return ControlResult(observed=True, detail="process stopped")

    def collect(self, endpoint: str) -> ProcessCollection:
        """Return the run's output once finished; never blocks."""

        paths = self._require(endpoint)
        status = self.status(endpoint)
        if status.state is ProcessState.RUNNING:
            return ProcessCollection(ProcessState.RUNNING, None, "", "")
        stdout = paths["stdout"].read_text(encoding="utf-8") if paths["stdout"].exists() else ""
        stderr = paths["stderr"].read_text(encoding="utf-8") if paths["stderr"].exists() else ""
        # A host that died without an exit file is reported as exited without
        # an exit code, which the adapter records as a protocol error.
        return ProcessCollection(ProcessState.EXITED, status.exit_code, stdout, stderr)

    def wait(self, endpoint: str, timeout_seconds: float) -> ProcessStatus:
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.status(endpoint)
            if status.state is not ProcessState.RUNNING or time.monotonic() >= deadline:
                return status
            time.sleep(0.1)

    def retire(self, endpoint: str) -> ControlResult:
        paths = self._require(endpoint)
        if self.status(endpoint).state is ProcessState.RUNNING:
            return ControlResult(observed=False, detail="running endpoint cannot be retired")
        paths["retired"].touch()
        return ControlResult(observed=True, detail="endpoint retired")

    def log_path(self, endpoint: str) -> Path:
        return self._require(endpoint)["stdout"]

    def _require(self, endpoint: str) -> dict[str, Path]:
        if not isinstance(endpoint, str) or not _ENDPOINT.fullmatch(endpoint):
            raise KeyError(f"unknown endpoint {endpoint!r}")
        paths = _paths(self._run_dir, endpoint)
        if not paths["launch"].exists():
            raise KeyError(f"unknown endpoint {endpoint}")
        return paths

    @staticmethod
    def _exit_code(paths: dict[str, Path]) -> int | None:
        try:
            record = json.loads(paths["exit"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        code = record.get("exit_code") if isinstance(record, dict) else None
        return code if isinstance(code, int) and not isinstance(code, bool) else None

    @staticmethod
    def _host_identity(paths: dict[str, Path]) -> ProcessIdentity | None:
        try:
            record = json.loads(paths["host"].read_text(encoding="utf-8"))
            if not record.get("started_at"):
                return None
            return ProcessIdentity.from_dict(record)
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            return None

    def _group_has_younger_members(self, host: ProcessIdentity) -> bool:
        listed = subprocess.run(
            ("pgrep", "-g", str(host.pid)), capture_output=True, text=True, timeout=10
        )
        host_started = _parse_start(host.started_at)
        for token in listed.stdout.split():
            member = self._inspector.identify(int(token))
            if member is None or host_started is None:
                continue
            started = _parse_start(member.started_at)
            if started is not None and started >= host_started:
                return True
        return False

    def _host_alive(self, paths: dict[str, Path]) -> bool:
        """True while the host or anything in its process group still runs.

        The host leads its own session, so the harness child shares its
        process group; a child that outlives a killed host keeps the run
        alive. A host whose identity was never recorded is treated as alive
        until its group is gone, so a live run is never collected as dead.
        """

        identity = self._host_identity(paths)
        if identity is not None:
            observed = self._inspector.identify(identity.pid)
            if observed is not None and observed.matches(identity):
                return True
            # Identified host is gone. Its child may still run in its group,
            # but only if the group still has members started no earlier than
            # the host; otherwise the PID may have been reused.
            return self._group_has_younger_members(identity)
        try:
            record = json.loads(paths["host"].read_text(encoding="utf-8"))
            pid = int(record["pid"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True


def _parse_start(value: str) -> float | None:
    """Parse ``ps -o lstart`` output (``Wed Nov  4 23:13:55 2026``)."""

    try:
        return time.mktime(time.strptime(" ".join(value.split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError):
        return None


def _host_main(run_dir: Path, endpoint: str) -> int:
    """Run inside the detached host: execute the child and record its exit."""

    paths = _paths(run_dir, endpoint)
    launch = json.loads(paths["launch"].read_text(encoding="utf-8"))
    env = dict(os.environ)
    original = env.pop("MILBURN_RUN_HOST_PYTHONPATH", "")
    if original:
        env["PYTHONPATH"] = original
    else:
        env.pop("PYTHONPATH", None)
    env.update(launch["env"])
    child: subprocess.Popen[bytes] | None = None

    def forward(signum: int, _frame: object) -> None:
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, forward)
    with (
        paths["brief"].open("rb") as brief,
        paths["stdout"].open("wb") as stdout,
        paths["stderr"].open("wb") as stderr,
    ):
        try:
            child = subprocess.Popen(
                launch["command"], cwd=launch["cwd"], stdin=brief,
                stdout=stdout, stderr=stderr, env=env,
            )
            code = child.wait()
        except OSError as error:
            stderr.write(f"run host could not start the command: {error}\n".encode())
            code = 127
    _write_atomic(paths["exit"], json.dumps({"exit_code": code}))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    sys.exit(_host_main(Path(sys.argv[1]), sys.argv[2]))
