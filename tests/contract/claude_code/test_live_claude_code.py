"""Protected contract against the installed Claude Code CLI.

Skipped unless ``MILBURN_RUN_LIVE_CLAUDE=1`` is set. It launches one real,
isolated, sandboxed ``claude -p`` run through the product subprocess runtime
and checks the schema-enforced result, run-end classification, and usage.
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from milburn.agents.codex_adapter import ClaudeCodeAdapter, LaunchRequest
from milburn.agents.harness import Harness, RunEnd
from milburn.domain import Role, RoleRouteProposal
from milburn.runtime.codex_process import SubprocessCodexRuntime


def _require_live_claude() -> str:
    if os.environ.get("MILBURN_RUN_LIVE_CLAUDE") != "1":
        pytest.skip("set MILBURN_RUN_LIVE_CLAUDE=1 for the protected live contract")
    executable = shutil.which("claude")
    if executable is None:
        pytest.fail("MILBURN_RUN_LIVE_CLAUDE=1 but claude is not installed")
    return executable


@pytest.mark.timeout(300)
def test_live_claude_code_schema_enforced_result(tmp_path: Path) -> None:
    executable = _require_live_claude()
    worktree = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(worktree)], check=True, timeout=10)
    counter = itertools.count(1)
    runtime = SubprocessCodexRuntime(
        tmp_path / "logs", timeout_seconds=240, endpoint_ids=lambda: f"live-{next(counter)}"
    )
    adapter = ClaudeCodeAdapter(runtime, executable=executable, schema_dir=tmp_path / "schemas")
    request = LaunchRequest(
        role=Role.CLASSIFIER_ROUTER,
        task_id="request-1",
        attempt_id="live-claude-1",
        worktree=str(worktree),
        objective="Return the one required role_route_proposal result and do nothing else.",
        role_rules="Do not use tools. Return only the required structured result.",
        task_context=(
            "Use this typed payload: {\"schema_version\":1,\"request_id\":"
            "\"request-1\",\"current_state\":\"received\",\"proposed_role\":"
            "\"planner\",\"reason\":\"Planning is required.\",\"confidence\":"
            "1.0,\"decision_needed\":false}. Set task_success to true."
        ),
        repository_instructions="Do not inspect or modify the temporary repository.",
        expected_result_type="role_route_proposal",
        sandbox="read-only",
    )

    endpoint = adapter.launch(request)
    result = adapter.collect(endpoint)

    assert endpoint.harness is Harness.CLAUDE_CODE
    assert result.process_exit is not None and result.process_exit.exit_code == 0
    assert result.run_end is RunEnd.COMPLETED, result.protocol_error
    assert result.protocol_error is None
    assert isinstance(result.task_result.payload, RoleRouteProposal)
    assert result.session_id
    assert result.usage is not None and result.usage.input_tokens
