"""Fakes match the real harness streams and each other (boundary question 6)."""

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from milburn.agents.codex_adapter import EndpointCorrelationError, IDENTITY_ENV
from milburn.agents.harness import ClaudeCodeCommands, CodexCommands, Harness, RunEnd
from milburn.domain import CoderResult
from tests.fakes.claude_code import FakeClaudeCodeAdapter, claude_stream
from tests.fakes.codex import FakeCodexAdapter, ScriptedCodexRun, _codex_jsonl
from tests.unit.agents.test_codex_adapter import request, result_document

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "harness"
FAKES = [FakeCodexAdapter, FakeClaudeCodeAdapter]

# Exact run end for each scripted terminal. Codex has no structured quota
# signal (docs/harness-facts.md), so its exhausted run is unknown.
EXPECTED = {
    (FakeCodexAdapter, "completed"): RunEnd.COMPLETED,
    (FakeCodexAdapter, "exhausted"): RunEnd.UNKNOWN,
    (FakeCodexAdapter, "error"): RunEnd.UNKNOWN,
    (FakeCodexAdapter, "truncated"): RunEnd.UNKNOWN,
    (FakeClaudeCodeAdapter, "completed"): RunEnd.COMPLETED,
    (FakeClaudeCodeAdapter, "exhausted"): RunEnd.EXHAUSTED,
    (FakeClaudeCodeAdapter, "error"): RunEnd.UNKNOWN,
    (FakeClaudeCodeAdapter, "truncated"): RunEnd.UNKNOWN,
}


def event_types(stream: str) -> set[str]:
    return {json.loads(line)["type"] for line in stream.splitlines() if line.strip()}


# --- fakes against recorded real runs --------------------------------------

@pytest.mark.parametrize(
    ("render", "fixture", "commands"),
    [
        (_codex_jsonl, "codex_schema_minimal.jsonl", CodexCommands()),
        (claude_stream, "claude_code_tool_and_schema.jsonl", ClaudeCodeCommands()),
    ],
)
def test_fake_completed_stream_matches_the_recorded_run(render, fixture, commands) -> None:
    recorded = (FIXTURES / fixture).read_text()
    fake = render(ScriptedCodexRun('{"ok":true}'))
    assert event_types(fake) <= event_types(recorded)
    for stream in (recorded, fake):
        report = commands.interpret(stream, 0)
        assert report.run_end is RunEnd.COMPLETED
        assert report.final_message is not None
        assert report.session_id
        assert report.usage is not None and report.usage.output_tokens is not None


# --- terminal states ----------------------------------------------------------

@pytest.mark.parametrize("fake_type", FAKES)
@pytest.mark.parametrize("terminal", ["completed", "exhausted", "error", "truncated"])
def test_exact_run_end_for_every_terminal(fake_type: type, terminal: str) -> None:
    fake = fake_type((ScriptedCodexRun(result_document(), terminal=terminal),))
    collected = fake.collect(fake.launch(request()))
    assert collected.run_end is EXPECTED[(fake_type, terminal)]
    if terminal == "completed":
        assert collected.protocol_error is None
        assert isinstance(collected.task_result.payload, CoderResult)
    else:
        assert collected.task_result is None
        assert collected.protocol_error


@pytest.mark.parametrize("fake_type", FAKES)
def test_interrupted_run_is_unknown_like_the_real_runtime(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(result_document()),))
    endpoint = fake.launch(request())
    fake.interrupt(endpoint)
    collected = fake.collect(endpoint)
    assert collected.task_result is None
    assert collected.run_end is RunEnd.UNKNOWN


@pytest.mark.parametrize("fake_type", FAKES)
def test_completed_without_result_and_nonzero_exit_fails_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(None, exit_code=9),))
    collected = fake.collect(fake.launch(request()))
    assert collected.run_end is RunEnd.FAILED
    assert collected.task_result is None
    assert "exit code 9" in (collected.protocol_error or "")


@pytest.mark.parametrize("fake_type", FAKES)
def test_completed_without_result_and_zero_exit_is_a_protocol_error(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(None),))
    collected = fake.collect(fake.launch(request()))
    assert collected.run_end is RunEnd.COMPLETED
    assert collected.task_result is None
    assert collected.protocol_error


# --- shared guards --------------------------------------------------------------

@pytest.mark.parametrize("fake_type", FAKES)
def test_missing_sandbox_is_refused_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(result_document()),))
    with pytest.raises(ValueError, match="sandbox is required"):
        fake.launch(replace(request(), sandbox=None))
    assert fake.runtime.launches == []


@pytest.mark.parametrize("fake_type", FAKES)
def test_wrong_attempt_result_is_rejected_on_every_harness(fake_type: type) -> None:
    document = result_document().replace('"attempt-1"', '"attempt-2"')
    fake = fake_type((ScriptedCodexRun(document),))
    collected = fake.collect(fake.launch(request()))
    assert collected.task_result is None
    assert "attempt" in (collected.protocol_error or "")


@pytest.mark.parametrize("fake_type", FAKES)
def test_non_json_result_is_rejected_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun("prose, not a result"),))
    collected = fake.collect(fake.launch(request()))
    assert collected.task_result is None
    assert collected.protocol_error


@pytest.mark.parametrize("fake_type", FAKES)
def test_every_launch_carries_the_per_attempt_identity(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(result_document()),))
    fake.launch(request())
    env = dict(fake.runtime.launches[0].env)
    assert set(IDENTITY_ENV) <= set(env)
    assert env["MILBURN_ATTEMPT_ID"] == "attempt-1"
    assert env["GIT_AUTHOR_NAME"] == env["GIT_COMMITTER_NAME"] == "Milburn coder [task-6/attempt-1]"
    assert env["GIT_AUTHOR_EMAIL"] == "coder.task-6.attempt-1@milburn.invalid"


@pytest.mark.parametrize("name", sorted(IDENTITY_ENV))
def test_callers_cannot_override_the_identity(name: str) -> None:
    with pytest.raises(ValueError, match="cannot be overridden"):
        replace(request(), env=((name, "someone else"),))


def test_endpoints_cannot_cross_harnesses() -> None:
    codex = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    claude = FakeClaudeCodeAdapter((ScriptedCodexRun(result_document()),))
    endpoint = codex.launch(request())
    assert endpoint.harness is Harness.CODEX
    with pytest.raises(EndpointCorrelationError, match="codex"):
        claude.collect(endpoint)


def test_extra_env_and_model_reach_the_launch() -> None:
    fake = FakeClaudeCodeAdapter((ScriptedCodexRun(result_document()),))
    fake.launch(replace(request(), env=(("TERM", "dumb"),), model="opus"))
    launch = fake.runtime.launches[0]
    assert ("TERM", "dumb") in launch.env
    assert launch.command[launch.command.index("--model") + 1] == "opus"


@pytest.mark.parametrize(
    "env",
    [(("1BAD", "x"),), (("A", "x"), ("A", "y")), (("A", "x\0y"),), (("A",),), ["A", "x"]],
)
def test_invalid_env_is_rejected(env: object) -> None:
    with pytest.raises(ValueError):
        replace(request(), env=env)


@pytest.mark.parametrize("model", ["", "a b"])
def test_invalid_model_is_rejected(model: str) -> None:
    with pytest.raises(ValueError):
        replace(request(), model=model)


@pytest.mark.parametrize("directory", ["/", str(Path.home()), os.path.dirname(str(Path.home()))])
def test_writable_dirs_cannot_cover_the_home_directory(directory: str) -> None:
    with pytest.raises(ValueError, match="home directory"):
        replace(request(), writable_dirs=(directory,))


def test_tampered_schema_file_is_rewritten_before_use(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    fake = FakeCodexAdapter((ScriptedCodexRun(result_document()),) * 2, schema_dir=schema_dir)
    fake.launch(request())
    command = fake.runtime.launches[0].command
    path = Path(command[command.index("--output-schema") + 1])
    original = path.read_text()
    path.write_text('{"type":"object"}')
    fake.launch(request())
    assert path.read_text() == original
    assert (schema_dir.stat().st_mode & 0o777) == 0o700
