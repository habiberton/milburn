import json
from datetime import datetime, timezone

import pytest

from milburn.agents.codex_adapter import (
    CodexAdapter,
    EndpointCorrelationError,
    LaunchRequest,
    ProcessState,
    SteeringMessage,
)
from milburn.agents.result_parser import ResultDecodingError
from milburn.domain import CoderOutcome, CoderResult, EvidenceItem, Role, SkillBinding
from tests.fakes.codex import FakeCodexAdapter, ScriptedCodexRun


SKILL = SkillBinding(
    skill_name="milburn-long-running-coder",
    version="1",
    root_digest="rootabc",
    resource_digests=("resource123",),
    workspace_path=".agents/skills/milburn-long-running-coder",
    validated_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
)


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
        expected_result_type="coder_result",
        skill_bindings=(SKILL,),
    )


def result_document(*, task_success: bool = True) -> str:
    payload = CoderResult(
        attempt_id="attempt-1",
        issue_number=6,
        outcome=CoderOutcome.CANDIDATE,
        head_sha="abc123",
        progress_path=".milburn/issues/6/progress.txt",
        commits=("abc123",),
        files_changed=("src/example.py",),
        test_claims=(EvidenceItem(name="pytest", outcome="passed", evidence="19"),),
        risks=(),
    )
    return json.dumps(
        {
            "schema_version": 1,
            "role": "coder",
            "task_id": "task-6",
            "attempt_id": "attempt-1",
            "task_success": task_success,
            "result_type": "coder_result",
            "payload": payload.to_dict(),
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
    assert endpoint.expected_result_type == "coder_result"
    assert endpoint.expected_result_schema_version == 1
    assert endpoint.skill_bindings == (SKILL,)
    assert "root_digest=rootabc" in launch.stdin
    assert "resource_digests=resource123" in launch.stdin
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
    stopped = fake.status(endpoint)
    late_ack = fake.steer(
        endpoint,
        SteeringMessage(Role.CODER, "task-6", "attempt-1", "Too late."),
    )
    repeated_interrupt = fake.interrupt(endpoint)
    retired = fake.retire(endpoint)

    assert status.process_state is ProcessState.RUNNING
    assert status.exit_code is None
    assert ack.accepted
    assert interrupted.observed
    assert stopped.process_state is ProcessState.EXITED
    assert not late_ack.accepted
    assert not repeated_interrupt.observed
    assert retired.observed
    assert fake.runtime.steering == [("fake-codex-1", "Continue.")]

    with pytest.raises(AssertionError, match="unknown fake endpoint"):
        fake.status(endpoint)
    with pytest.raises(AssertionError, match="unknown fake endpoint"):
        fake.collect(endpoint)
    with pytest.raises(AssertionError, match="unknown fake endpoint"):
        fake.steer(
            endpoint,
            SteeringMessage(Role.CODER, "task-6", "attempt-1", "Retired."),
        )
    with pytest.raises(AssertionError, match="unknown fake endpoint"):
        fake.interrupt(endpoint)
    with pytest.raises(AssertionError, match="unknown fake endpoint"):
        fake.retire(endpoint)

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
    assert isinstance(collected.task_result.payload, CoderResult)
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
    assert "exactly one completed agent_message" in (missing.protocol_error or "")
    assert malformed.process_exit is not None
    assert malformed.task_result is None
    assert "not valid JSON" in (malformed.protocol_error or "")


def test_invalid_runtime_endpoint_is_rejected() -> None:
    class InvalidRuntime:
        def launch(self, spec: object) -> str:
            return ""

    with pytest.raises(ValueError, match="invalid endpoint"):
        CodexAdapter(InvalidRuntime()).launch(request())  # type: ignore[arg-type]


def test_launch_rejects_result_type_not_allowed_for_role_before_runtime_effect() -> None:
    fake = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    invalid = request()
    invalid = LaunchRequest(
        role=invalid.role,
        task_id=invalid.task_id,
        attempt_id=invalid.attempt_id,
        worktree=invalid.worktree,
        objective=invalid.objective,
        role_rules=invalid.role_rules,
        task_context=invalid.task_context,
        repository_instructions=invalid.repository_instructions,
        expected_result_type="qa_report",
        skill_bindings=invalid.skill_bindings,
    )

    with pytest.raises(ResultDecodingError, match="not allowed for role"):
        fake.launch(invalid)

    assert fake.runtime.launches == []
