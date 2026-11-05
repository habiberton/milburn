import json
from pathlib import Path

import pytest

from milburn.agents.harness import (
    ClaudeCodeCommands,
    CodexCommands,
    Harness,
    HarnessInvocation,
    HarnessUsage,
    RunEnd,
    Sandbox,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "harness"
SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
FORBIDDEN = ("danger-full-access", "bypassPermissions", "--dangerously-skip-permissions")


def jsonl(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def claude_result(**overrides: object) -> dict:
    event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "s-1",
        "structured_output": {"ok": True},
        "result": '{"ok":true}',
        "usage": {"input_tokens": 2, "cache_read_input_tokens": 10,
                  "cache_creation_input_tokens": 5, "output_tokens": 7},
    }
    event.update(overrides)
    return event


# --- Claude Code: run-end classification, negative cases first -------------

def test_claude_rate_limit_refusal_without_result_is_exhausted() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}})
    )
    assert report.run_end is RunEnd.EXHAUSTED
    assert report.final_message is None


def test_claude_http_429_result_is_exhausted_even_with_structured_output() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(claude_result(is_error=True, subtype="error_during_execution", api_error_status=429))
    )
    assert report.run_end is RunEnd.EXHAUSTED
    assert report.final_message is None


def test_claude_refusal_after_a_success_result_is_still_exhausted() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(
            {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}},
            claude_result(),
        )
    )
    assert report.run_end is RunEnd.EXHAUSTED


def test_claude_allowed_rate_limit_status_is_not_exhaustion() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}, claude_result())
    )
    assert report.run_end is RunEnd.COMPLETED


def test_claude_known_failure_subtype_fails() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(claude_result(is_error=True, subtype="error_max_turns"))
    )
    assert report.run_end is RunEnd.FAILED
    assert report.final_message is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_error": True},
        {"is_error": True, "subtype": "error_during_execution"},
        {"is_error": None},
        {"subtype": "error_max_budget_usd"},
    ],
)
def test_claude_unrecognised_errors_stay_unknown_for_the_coordinator(overrides: dict) -> None:
    report = ClaudeCodeCommands().interpret(jsonl(claude_result(**overrides)))
    assert report.run_end is RunEnd.UNKNOWN
    assert report.final_message is None


def test_claude_prose_result_is_never_accepted_without_structured_output() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(claude_result(structured_output=None, result='{"ok":true}'))
    )
    assert report.final_message is None
    assert "schema enforcement" in report.detail


def test_claude_mixed_session_ids_are_malformed() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl({"type": "system", "subtype": "init", "session_id": "a"}, claude_result(session_id="b"))
    )
    assert report.run_end is RunEnd.FAILED
    assert "session" in report.detail


@pytest.mark.parametrize("commands", [CodexCommands(), ClaudeCodeCommands()])
def test_nonzero_exit_without_a_message_fails(commands: object) -> None:
    stream = (
        jsonl({"type": "turn.completed", "usage": {}})
        if isinstance(commands, CodexCommands)
        else jsonl(claude_result(structured_output=None))
    )
    report = commands.interpret(stream, 3)  # type: ignore[attr-defined]
    assert report.run_end is RunEnd.FAILED


def test_nonzero_exit_does_not_discard_a_completed_result() -> None:
    report = ClaudeCodeCommands().interpret(jsonl(claude_result()), 17)
    assert report.run_end is RunEnd.COMPLETED
    assert report.final_message is not None


def test_claude_stream_without_result_is_unknown() -> None:
    report = ClaudeCodeCommands().interpret(jsonl({"type": "system", "subtype": "init"}))
    assert report.run_end is RunEnd.UNKNOWN


def test_claude_malformed_stream_fails() -> None:
    report = ClaudeCodeCommands().interpret('{"type":"system"}\nnot json\n')
    assert report.run_end is RunEnd.FAILED
    assert "line 2" in report.detail


def test_claude_success_without_any_message_has_no_final_message() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(claude_result(structured_output=None, result="  ")), 0
    )
    assert report.run_end is RunEnd.COMPLETED
    assert report.final_message is None


def test_claude_structured_output_wins_over_result_text() -> None:
    report = ClaudeCodeCommands().interpret(
        jsonl(claude_result(structured_output={"b": 1, "a": 2}, result="prose"))
    )
    assert json.loads(report.final_message or "") == {"a": 2, "b": 1}


def test_claude_usage_totals_include_cache_reads_and_writes() -> None:
    report = ClaudeCodeCommands().interpret(jsonl(claude_result()))
    assert report.usage == HarnessUsage(
        input_tokens=17, cached_input_tokens=10, cache_write_tokens=5,
        output_tokens=7, reasoning_tokens=None,
    )


def test_claude_missing_usage_fields_stay_unavailable_not_zero() -> None:
    report = ClaudeCodeCommands().interpret(jsonl(claude_result(usage={"output_tokens": 3})))
    assert report.usage == HarnessUsage(output_tokens=3)


def test_recorded_claude_run_with_tool_use_and_schema() -> None:
    report = ClaudeCodeCommands().interpret(
        (FIXTURES / "claude_code_tool_and_schema.jsonl").read_text()
    )
    assert report.run_end is RunEnd.COMPLETED
    assert json.loads(report.final_message or "") == {"files": 1, "outcome": "passed"}
    assert report.session_id == "343a8c83-cd00-4af7-9a05-91586b899eb6"
    assert report.usage == HarnessUsage(
        input_tokens=4 + 58810 + 58719, cached_input_tokens=58719,
        cache_write_tokens=58810, output_tokens=159, reasoning_tokens=0,
    )


def test_recorded_isolated_claude_launch_is_small() -> None:
    report = ClaudeCodeCommands().interpret(
        (FIXTURES / "claude_code_isolated_minimal.jsonl").read_text()
    )
    assert report.run_end is RunEnd.COMPLETED
    assert report.usage is not None and report.usage.input_tokens is not None
    assert report.usage.input_tokens < 10_000


# --- Codex: run-end classification ------------------------------------------

@pytest.mark.parametrize("kind", ["error", "turn.failed"])
def test_codex_error_events_are_unknown_for_the_coordinator_to_judge(kind: str) -> None:
    report = CodexCommands().interpret(jsonl({"type": "thread.started", "thread_id": "t"}, {"type": kind}))
    assert report.run_end is RunEnd.UNKNOWN
    assert report.final_message is None
    assert kind in report.detail


def test_codex_empty_and_malformed_streams_fail() -> None:
    assert CodexCommands().interpret("").run_end is RunEnd.FAILED
    assert CodexCommands().interpret("nope\n").run_end is RunEnd.FAILED


def test_codex_stream_without_turn_completed_is_unknown() -> None:
    report = CodexCommands().interpret(jsonl({"type": "thread.started", "thread_id": "t"}))
    assert report.run_end is RunEnd.UNKNOWN
    assert "no turn.completed" in report.detail


def test_codex_event_after_turn_completed_has_no_final_message() -> None:
    report = CodexCommands().interpret(
        jsonl(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
            {"type": "turn.completed", "usage": {}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
        )
    )
    assert report.final_message is None
    assert "after turn.completed" in report.detail


def test_recorded_codex_run() -> None:
    report = CodexCommands().interpret((FIXTURES / "codex_schema_minimal.jsonl").read_text())
    assert report.run_end is RunEnd.COMPLETED
    assert json.loads(report.final_message or "") == {"ok": True}
    assert report.session_id == "01a1aa6b-6898-7e92-ac9b-a97513948111"
    assert report.usage == HarnessUsage(
        input_tokens=18765, cached_input_tokens=0, cache_write_tokens=0,
        output_tokens=15, reasoning_tokens=0,
    )


# --- Commands ----------------------------------------------------------------

@pytest.mark.parametrize("commands", [CodexCommands(), ClaudeCodeCommands()])
@pytest.mark.parametrize("sandbox", list(Sandbox))
def test_no_command_ever_requests_full_access(commands: object, sandbox: Sandbox) -> None:
    command = commands.command(  # type: ignore[attr-defined]
        HarnessInvocation(sandbox=sandbox, result_schema=SCHEMA, result_schema_path="/s.json")
    )
    assert not any(marker in part for part in command for marker in FORBIDDEN)


def test_codex_schema_needs_a_file_path() -> None:
    with pytest.raises(ValueError, match="schema file"):
        CodexCommands().command(HarnessInvocation(sandbox=Sandbox.READ_ONLY, result_schema=SCHEMA))


def test_codex_resume_puts_options_before_the_session_and_stdin_marker() -> None:
    command = CodexCommands("codex").command(
        HarnessInvocation(sandbox=Sandbox.WORKSPACE_WRITE, model="m1", resume_session="sess-1")
    )
    assert command == (
        "codex", "exec", "resume", "--json", "--ignore-user-config",
        "--sandbox", "workspace-write", "--model", "m1", "sess-1", "-",
    )


def test_claude_read_only_has_no_edit_tools_and_denies_unapproved_actions() -> None:
    command = ClaudeCodeCommands().command(HarnessInvocation(sandbox=Sandbox.READ_ONLY))
    tools = command[command.index("--tools") + 1].split(",")
    assert "Edit" not in tools and "Write" not in tools
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--allowedTools" not in command


def test_claude_commands_are_isolated_and_sandboxed() -> None:
    command = ClaudeCodeCommands().command(HarnessInvocation(sandbox=Sandbox.READ_ONLY))
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    settings = json.loads(command[command.index("--settings") + 1])
    assert settings["sandbox"] == {
        "enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False,
    }


def test_claude_workspace_write_allows_only_git_add_and_commit() -> None:
    command = ClaudeCodeCommands("claude").command(
        HarnessInvocation(
            sandbox=Sandbox.WORKSPACE_WRITE,
            writable_dirs=("/repo/.git",),
            result_schema=SCHEMA,
            model="opus",
            resume_session="s-9",
        )
    )
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"
    start = command.index("--allowedTools") + 1
    assert command[start:start + 2] == ("Bash(git add:*)", "Bash(git commit:*)")
    assert command[command.index("--add-dir") + 1] == "/repo/.git"
    assert json.loads(command[command.index("--json-schema") + 1]) == SCHEMA
    assert command[command.index("--model") + 1] == "opus"
    assert command[command.index("--resume") + 1] == "s-9"


@pytest.mark.parametrize("bad", ["", "co dex", "a\tb"])
def test_executables_must_be_one_token(bad: str) -> None:
    with pytest.raises(ValueError):
        CodexCommands(bad)
    with pytest.raises(ValueError):
        ClaudeCodeCommands(bad)


def test_usage_rejects_negative_and_boolean_counts() -> None:
    with pytest.raises(ValueError):
        HarnessUsage(input_tokens=-1)
    with pytest.raises(ValueError):
        HarnessUsage(output_tokens=True)


def test_harness_names() -> None:
    assert CodexCommands.harness is Harness.CODEX
    assert ClaudeCodeCommands.harness is Harness.CLAUDE_CODE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sandbox": "workspace-write"},
        {"sandbox": Sandbox.READ_ONLY, "writable_dirs": ("/repo/.git",)},
        {"sandbox": Sandbox.READ_ONLY, "writable_dirs": ["/repo/.git"]},
        {"sandbox": Sandbox.READ_ONLY, "model": "--dangerously-skip-permissions"},
        {"sandbox": Sandbox.READ_ONLY, "resume_session": "-x"},
        {"sandbox": Sandbox.READ_ONLY, "model": "a b"},
        {"sandbox": Sandbox.READ_ONLY, "result_schema_path": ""},
    ],
)
def test_invocation_rejects_unsafe_values(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        HarnessInvocation(**kwargs)
