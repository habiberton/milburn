"""Both harness adapters give the same outcomes for the same scripted runs (Q6)."""

from dataclasses import replace

import pytest

from milburn.agents.codex_adapter import EndpointCorrelationError
from milburn.agents.harness import Harness, RunEnd
from milburn.domain import CoderResult
from tests.fakes.claude_code import FakeClaudeCodeAdapter
from tests.fakes.codex import FakeCodexAdapter, ScriptedCodexRun
from tests.unit.agents.test_codex_adapter import request, result_document

FAKES = [FakeCodexAdapter, FakeClaudeCodeAdapter]


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
def test_missing_result_is_a_protocol_error_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(None, exit_code=9),))
    collected = fake.collect(fake.launch(request()))
    assert collected.task_result is None
    assert collected.protocol_error
    assert collected.run_end is not RunEnd.COMPLETED or collected.protocol_error


@pytest.mark.parametrize("fake_type", FAKES)
def test_interrupted_run_has_no_task_result_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(result_document()),))
    endpoint = fake.launch(request())
    fake.interrupt(endpoint)
    collected = fake.collect(endpoint)
    assert collected.task_result is None
    assert collected.run_end is RunEnd.FAILED


@pytest.mark.parametrize("fake_type", FAKES)
def test_valid_result_parses_identically_on_every_harness(fake_type: type) -> None:
    fake = fake_type((ScriptedCodexRun(result_document(), exit_code=0),))
    endpoint = fake.launch(request())
    collected = fake.collect(endpoint)
    assert collected.protocol_error is None
    assert collected.run_end is RunEnd.COMPLETED
    assert isinstance(collected.task_result.payload, CoderResult)
    assert collected.session_id is not None
    assert fake.runtime.launches[0].env == ()


def test_endpoints_cannot_cross_harnesses() -> None:
    codex = FakeCodexAdapter((ScriptedCodexRun(result_document()),))
    claude = FakeClaudeCodeAdapter((ScriptedCodexRun(result_document()),))
    endpoint = codex.launch(request())
    assert endpoint.harness is Harness.CODEX
    with pytest.raises(EndpointCorrelationError, match="codex"):
        claude.collect(endpoint)


def test_env_and_model_reach_the_launch() -> None:
    fake = FakeClaudeCodeAdapter((ScriptedCodexRun(result_document()),))
    fake.launch(replace(request(), env=(("GIT_AUTHOR_NAME", "Coder"),), model="opus"))
    launch = fake.runtime.launches[0]
    assert launch.env == (("GIT_AUTHOR_NAME", "Coder"),)
    assert launch.command[launch.command.index("--model") + 1] == "opus"


@pytest.mark.parametrize(
    "env",
    [
        (("1BAD", "x"),),
        (("A", "x"), ("A", "y")),
        (("A", "x\0y"),),
        (("A",),),
        ["A", "x"],
    ],
)
def test_invalid_env_is_rejected(env: object) -> None:
    with pytest.raises(ValueError):
        replace(request(), env=env)


@pytest.mark.parametrize("model", ["", "a b"])
def test_invalid_model_is_rejected(model: str) -> None:
    with pytest.raises(ValueError):
        replace(request(), model=model)
