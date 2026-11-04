import json

import pytest

from milburn.agents.codex_adapter import (
    CodexAdapter,
    EndpointCorrelationError,
    LaunchRequest,
    ProcessState,
    SteeringMessage,
)
from milburn.agents.result_parser import ResultCorrelation, result_contract
from milburn.domain import Role
from tests.fakes.codex import FakeCodexAdapter, ScriptedCodexRun


CORRELATION = ResultCorrelation(Role.CODER, "task-6", "attempt-1")


def request() -> LaunchRequest:
    return LaunchRequest(
        role=Role.CODER,
        task_id="task-6",
        attempt_id="attempt-1",
        worktree="/tmp/milburn-task-6",
        objective="Implement one bounded issue.",
        role_rules="Do not approve your own work.",
        task_context="Issue #6 is ready and dependencies are complete.",
        repository_instructions="Read AGENTS.md and preserve unrelated work.",
        result_contract=result_contract(CORRELATION, "coder_result"),
        required_skills=("milburn-long-running-coder",),
    )


def result_document(*, task_success: bool = True) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "role": "coder",
            "task_id": "task-6",
            "attempt_id": "attempt-1",
            "task_success": task_success,
            "result_type": "coder_result",
            "payload": {"head_sha": "abc123"},
        }
    )


def test_launch_uses_injected_runtime_with_bounded_rendered_brief() -> None:
    fake = FakeCodexAdapter((ScriptedCodexRun(result_document()),))

    endpoint = fake.launch(request())

    launch = fake.runtime.launches[0]
    assert launch.command == ("fake-codex", "exec", "--json", "-")
    assert launch.cwd == "/tmp/milburn-task-6"
    assert "- role: coder" in launch.stdin
    assert "- task_id: task-6" in launch.stdin
    assert endpoint.runtime_endpoint == "fake-codex-1"
    assert len(endpoint.brief_digest) == 64
    assert len(endpoint.rules_digest) == 64


def test_lifecycle_delegates_through_runtime_and_correlates_steering() -> None:
    fake = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    endpoint = fake.launch(request())

    status = fake.status(endpoint)
    ack = fake.steer(
        endpoint,
        SteeringMessage(Role.CODER, "task-6", "attempt-1", "Continue."),
    )
    interrupted = fake.interrupt(endpoint)
    retired = fake.retire(endpoint)

    assert status.process_state is ProcessState.EXITED
    assert ack.accepted
    assert interrupted.observed
    assert retired.observed
    assert fake.runtime.steering == [("fake-codex-1", "Continue.")]

    with pytest.raises(EndpointCorrelationError):
        fake.steer(
            endpoint,
            SteeringMessage(Role.CODER, "task-6", "attempt-2", "Wrong target."),
        )


@pytest.mark.parametrize(
    ("exit_code", "task_success"),
    [(0, False), (17, True)],
)
def test_process_exit_and_task_success_are_independent(
    exit_code: int, task_success: bool
) -> None:
    fake = FakeCodexAdapter(
        (ScriptedCodexRun(result_document(task_success=task_success), exit_code),)
    )
    endpoint = fake.launch(request())

    collected = fake.collect(endpoint)

    assert collected.process_exit is not None
    assert collected.process_exit.exit_code == exit_code
    assert collected.process_exit.succeeded is (exit_code == 0)
    assert collected.task_result is not None
    assert collected.task_result.task_success is task_success
    assert collected.protocol_error is None


def test_deterministic_fake_scripts_missing_and_malformed_results() -> None:
    fake = FakeCodexAdapter(
        (
            ScriptedCodexRun(None, exit_code=9, stderr="crashed"),
            ScriptedCodexRun("not-json", exit_code=0),
        )
    )

    missing = fake.collect(fake.launch(request()))
    malformed = fake.collect(fake.launch(request()))

    assert missing.process_exit is not None
    assert missing.process_exit.stderr == "crashed"
    assert missing.task_result is None
    assert missing.protocol_error == "Codex exited without a semantic task result"
    assert malformed.process_exit is not None
    assert malformed.task_result is None
    assert "not valid JSON" in (malformed.protocol_error or "")


def test_invalid_runtime_endpoint_is_rejected() -> None:
    class InvalidRuntime:
        def launch(self, spec: object) -> str:
            return ""

    with pytest.raises(ValueError, match="invalid endpoint"):
        CodexAdapter(InvalidRuntime()).launch(request())  # type: ignore[arg-type]
