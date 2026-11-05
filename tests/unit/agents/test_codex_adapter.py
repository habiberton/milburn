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
        sandbox="workspace-write",
    )


def schema_args(launch: object) -> tuple[str, str]:
    command = launch.command  # type: ignore[attr-defined]
    index = command.index("--output-schema")
    return command[index], command[index + 1]


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
    flag, schema_path = schema_args(launch)
    assert launch.command == (
        "fake-codex", "exec", "--json", "--ignore-user-config",
        "--sandbox", "workspace-write", flag, schema_path, "-",
    )
    schema = json.loads(open(schema_path, encoding="utf-8").read())
    assert schema["properties"]["attempt_id"]["enum"] == ["attempt-1"]
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
    assert stopped.exit_code == -15
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


def test_interruption_cannot_be_collected_as_scripted_task_success() -> None:
    fake = FakeCodexAdapter(
        (ScriptedCodexRun(result_document(task_success=True), exit_code=0),)
    )
    endpoint = fake.launch(request())

    assert fake.interrupt(endpoint).observed
    collected = fake.collect(endpoint)

    assert collected.process_exit is not None
    assert collected.process_exit.exit_code == -15
    assert not collected.process_exit.succeeded
    assert collected.process_exit.stderr == "scripted process interrupted"
    assert collected.task_result is None
    assert collected.protocol_error == "Codex JSONL has no turn.completed event"


def test_running_fake_rejects_retirement_without_invalidating_endpoint() -> None:
    fake = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    endpoint = fake.launch(request())

    rejected = fake.retire(endpoint)
    still_running = fake.status(endpoint)
    steering = fake.steer(
        endpoint,
        SteeringMessage(Role.CODER, "task-6", "attempt-1", "Still active."),
    )

    assert not rejected.observed
    assert rejected.detail == "running endpoint cannot be retired"
    assert still_running.process_state is ProcessState.RUNNING
    assert steering.accepted
    assert fake.interrupt(endpoint).observed
    assert fake.retire(endpoint).observed


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
    assert "at least one completed agent_message" in (missing.protocol_error or "")
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
        sandbox="workspace-write",
    )

    with pytest.raises(ResultDecodingError, match="not allowed for role"):
        fake.launch(invalid)

    assert fake.runtime.launches == []


def test_unknown_or_full_access_sandbox_is_rejected_before_launch() -> None:
    from dataclasses import replace

    for mode in ("danger-full-access", "", "READ-ONLY"):
        with pytest.raises(ValueError, match="sandbox"):
            replace(request(), sandbox=mode)


def test_missing_sandbox_is_refused_before_any_runtime_effect() -> None:
    from dataclasses import replace

    adapter = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    with pytest.raises(ValueError, match="sandbox is required"):
        adapter.launch(replace(request(), sandbox=None))
    assert adapter.runtime.launches == []


def test_explicit_sandbox_is_passed_to_codex_exec() -> None:
    from dataclasses import replace

    adapter = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    adapter.launch(replace(request(), sandbox="read-only"))

    launch = adapter.runtime.launches[0]
    flag, schema_path = schema_args(launch)
    assert launch.command == (
        "fake-codex", "exec", "--json", "--ignore-user-config",
        "--sandbox", "read-only", flag, schema_path, "-",
    )


def test_writable_dirs_need_workspace_write_and_absolute_paths() -> None:
    from dataclasses import replace

    with pytest.raises(ValueError, match="workspace-write"):
        replace(request(), sandbox="read-only", writable_dirs=("/repo/.git",))
    with pytest.raises(ValueError, match="workspace-write"):
        replace(request(), sandbox=None, writable_dirs=("/repo/.git",))
    for bad in ("relative/.git", "/repo/../etc", "/repo\n--x", "/repo/./.git", "/repo/.git/"):
        with pytest.raises(ValueError, match="absolute"):
            replace(request(), sandbox="workspace-write", writable_dirs=(bad,))


def test_writable_dirs_are_passed_as_add_dir() -> None:
    from dataclasses import replace

    adapter = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    adapter.launch(replace(request(), sandbox="workspace-write",
                           writable_dirs=("/repo/.git",)))

    launch = adapter.runtime.launches[0]
    flag, schema_path = schema_args(launch)
    assert launch.command == (
        "fake-codex", "exec", "--json", "--ignore-user-config",
        "--sandbox", "workspace-write", "--add-dir", "/repo/.git",
        flag, schema_path, "-",
    )
