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
        return Ack(False, "one-shot exec process has already completed")

    def status(self, endpoint: str) -> ProcessStatus:
        run = self._runs[endpoint]
        return ProcessStatus(ProcessState.EXITED, run.returncode)

    def interrupt(self, endpoint: str) -> ControlResult:
        return ControlResult(True, "completed process needs no interrupt")

    def collect(self, endpoint: str) -> ProcessCollection:
        run = self._runs[endpoint]
        return ProcessCollection(
            ProcessState.EXITED, run.returncode, run.stdout, run.stderr
        )

    def retire(self, endpoint: str) -> ControlResult:
        self._runs.pop(endpoint)
        return ControlResult(True, "live contract result retired")


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
    result = adapter.collect(endpoint)

    assert status.process_state is ProcessState.EXITED
    assert result.process_exit is not None
    assert result.process_exit.exit_code == 0
    assert result.protocol_error is None
    assert result.task_result is not None
    assert isinstance(result.task_result.payload, RoleRouteProposal)
    assert result.task_result.task_success
    assert adapter.retire(endpoint).observed
