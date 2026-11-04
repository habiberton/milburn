"""Protected lifecycle contract against the installed Codex CLI.

This module is skipped unless ``MILBURN_RUN_LIVE_CODEX=1`` is explicitly set.
Ordinary tests use ``tests.fakes.codex`` and never launch a process or network
connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from milburn.agents.codex_adapter import (
    Ack,
    CodexAdapter,
    ControlResult,
    LaunchRequest,
    ProcessCollection,
    ProcessLaunch,
    ProcessState,
    ProcessStatus,
    SteeringMessage,
)
from milburn.domain import Role, RoleRouteProposal


@dataclass(frozen=True, slots=True)
class _CompletedRun:
    stdout: str
    stderr: str
    returncode: int


class _LiveExecRuntime:
    """Bounded subprocess boundary used only by the protected contract."""

    def __init__(self) -> None:
        self._runs: dict[str, _CompletedRun] = {}

    def launch(self, spec: ProcessLaunch) -> str:
        completed = subprocess.run(
            spec.command,
            cwd=spec.cwd,
            input=spec.stdin,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        endpoint = "live-codex-1"
        self._runs[endpoint] = _CompletedRun(
            completed.stdout, completed.stderr, completed.returncode
        )
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        self._runs[endpoint]
        return Ack(False, "one-shot exec process has already completed")

    def status(self, endpoint: str) -> ProcessStatus:
        run = self._runs[endpoint]
        return ProcessStatus(ProcessState.EXITED, run.returncode)

    def interrupt(self, endpoint: str) -> ControlResult:
        self._runs[endpoint]
        return ControlResult(False, "completed process cannot be interrupted")

    def collect(self, endpoint: str) -> ProcessCollection:
        run = self._runs[endpoint]
        return ProcessCollection(
            ProcessState.EXITED, run.returncode, run.stdout, run.stderr
        )

    def retire(self, endpoint: str) -> ControlResult:
        self._runs.pop(endpoint)
        return ControlResult(True, "live contract result retired")


class _LiveInterruptRuntime:
    """Asynchronous live boundary used to observe an interrupt postcondition."""

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def launch(self, spec: ProcessLaunch) -> str:
        process = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write(spec.stdin)
        process.stdin.close()
        process.stdin = None
        endpoint = "live-codex-interrupt-1"
        self._processes[endpoint] = process
        return endpoint

    def steer(self, endpoint: str, message: str) -> Ack:
        process = self._processes[endpoint]
        if process.poll() is not None:
            return Ack(False, "process has already exited")
        return Ack(False, "one-shot exec stdin is closed after launch")

    def status(self, endpoint: str) -> ProcessStatus:
        returncode = self._processes[endpoint].poll()
        if returncode is None:
            return ProcessStatus(ProcessState.RUNNING)
        return ProcessStatus(ProcessState.EXITED, returncode)

    def interrupt(self, endpoint: str) -> ControlResult:
        process = self._processes[endpoint]
        if process.poll() is not None:
            return ControlResult(False, "process has already exited")
        process.terminate()
        process.wait(timeout=10)
        return ControlResult(True, "process termination observed")

    def collect(self, endpoint: str) -> ProcessCollection:
        process = self._processes[endpoint]
        stdout, stderr = process.communicate(timeout=10)
        return ProcessCollection(
            ProcessState.EXITED, process.returncode, stdout, stderr
        )

    def retire(self, endpoint: str) -> ControlResult:
        process = self._processes[endpoint]
        if process.poll() is None:
            return ControlResult(False, "running process cannot be retired")
        del self._processes[endpoint]
        return ControlResult(True, "interrupted endpoint retired")


def _require_live_codex() -> str:
    if os.environ.get("MILBURN_RUN_LIVE_CODEX") != "1":
        pytest.skip("set MILBURN_RUN_LIVE_CODEX=1 for the protected live contract")
    executable = shutil.which("codex")
    if executable is None:
        pytest.fail("MILBURN_RUN_LIVE_CODEX=1 but codex is not installed")
    return executable


def test_live_codex_adapter_launch_jsonl_collect_and_retire(tmp_path: Path) -> None:
    executable = _require_live_codex()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=10)
    runtime = _LiveExecRuntime()
    adapter = CodexAdapter(runtime, executable=executable)
    request = LaunchRequest(
        role=Role.CLASSIFIER_ROUTER,
        task_id="request-1",
        attempt_id="live-contract-1",
        worktree=str(tmp_path),
        objective="Return the one required role_route_proposal result and do nothing else.",
        role_rules="Do not use tools. Return only the exact required JSON object.",
        task_context=(
            "Use this typed payload: {\"schema_version\":1,\"request_id\":"
            "\"request-1\",\"current_state\":\"received\",\"proposed_role\":"
            "\"planner\",\"reason\":\"Planning is required.\",\"confidence\":"
            "1.0,\"decision_needed\":false}. Set task_success to true."
        ),
        repository_instructions="Do not inspect or modify the temporary repository.",
        expected_result_type="role_route_proposal",
    )

    endpoint = adapter.launch(request)
    status = adapter.status(endpoint)
    steering = adapter.steer(
        endpoint,
        SteeringMessage(
            Role.CLASSIFIER_ROUTER,
            "request-1",
            "live-contract-1",
            "This completed one-shot endpoint must reject steering.",
        ),
    )
    interrupt = adapter.interrupt(endpoint)
    result = adapter.collect(endpoint)

    assert status.process_state is ProcessState.EXITED
    assert not steering.accepted
    assert "already completed" in steering.detail
    assert not interrupt.observed
    assert "cannot be interrupted" in interrupt.detail
    assert result.process_exit is not None
    assert result.process_exit.exit_code == 0
    assert result.protocol_error is None
    assert result.task_result is not None
    assert isinstance(result.task_result.payload, RoleRouteProposal)
    assert result.task_result.task_success
    assert adapter.retire(endpoint).observed
    with pytest.raises(KeyError):
        adapter.status(endpoint)


def test_live_codex_adapter_interrupts_running_process(tmp_path: Path) -> None:
    executable = _require_live_codex()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=10)
    runtime = _LiveInterruptRuntime()
    adapter = CodexAdapter(runtime, executable=executable)
    request = LaunchRequest(
        role=Role.CLASSIFIER_ROUTER,
        task_id="request-interrupt",
        attempt_id="live-interrupt-1",
        worktree=str(tmp_path),
        objective="Return the required result.",
        role_rules="Do not modify the repository.",
        task_context="This turn will be interrupted by the lifecycle contract.",
        repository_instructions="Do not inspect or modify the temporary repository.",
        expected_result_type="role_route_proposal",
    )

    endpoint = adapter.launch(request)
    running = adapter.status(endpoint)
    steering = adapter.steer(
        endpoint,
        SteeringMessage(
            Role.CLASSIFIER_ROUTER,
            "request-interrupt",
            "live-interrupt-1",
            "This one-shot boundary must reject unsafe mid-process steering.",
        ),
    )
    interrupted = adapter.interrupt(endpoint)
    stopped = adapter.status(endpoint)
    result = adapter.collect(endpoint)

    assert running.process_state is ProcessState.RUNNING
    assert not steering.accepted
    assert "stdin is closed" in steering.detail
    assert interrupted.observed
    assert stopped.process_state is ProcessState.EXITED
    assert result.process_exit is not None
    assert not result.process_exit.succeeded
    assert result.task_result is None
    assert adapter.retire(endpoint).observed
