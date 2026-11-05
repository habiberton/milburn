"""The walking skeleton end to end through the real CLI, run host, Git, and store.

Harnesses are stub executables (``fake_harness.py``) that read the rendered
brief and print each harness's real stream format. No model is called.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from milburn.app.cli import main

FAKE = Path(__file__).with_name("fake_harness.py")
pytestmark = pytest.mark.timeout(60)


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "target"
    root.mkdir()
    sh(root, "git", "init", "-q", "-b", "main")
    sh(root, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "--allow-empty", "-m", "init")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for harness in ("codex", "claude-code"):
        wrapper = bin_dir / f"fake-{harness}"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" {harness} "$@"\n')
        wrapper.chmod(0o755)
    monkeypatch.setenv("MILBURN_HOME", str(tmp_path / "milburn-home"))
    monkeypatch.setenv("MILBURN_CODEX_EXECUTABLE", str(bin_dir / "fake-codex"))
    monkeypatch.setenv("MILBURN_CLAUDE_EXECUTABLE", str(bin_dir / "fake-claude-code"))
    monkeypatch.delenv("MILBURN_ATTEMPT_ID", raising=False)
    monkeypatch.delenv("FAKE_CODER_MODE", raising=False)
    monkeypatch.delenv("FAKE_TESTER_OUTCOME", raising=False)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    sh(root, "git", "add", ".milburn/config.toml")
    sh(root, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "-m", "milburn config")
    return root


def run(*argv: str) -> int:
    return main(list(argv))


def create_task() -> None:
    assert run("task", "create", "--title", "Add feature", "--objective", "Add a feature file",
               "--accept", "feature_t1.txt exists") == 0


def build_candidate() -> None:
    create_task()
    assert run("dispatch", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0


def events(capsys: pytest.CaptureFixture[str]) -> dict:
    capsys.readouterr()
    assert run("--json", "status") == 0
    return json.loads(capsys.readouterr().out)


# --- refusals first -----------------------------------------------------------

def test_task_needs_title_objective_and_acceptance(repo: Path, capsys) -> None:
    assert run("task", "create", "--title", " ", "--objective", "x", "--accept", " ") == 1
    err = capsys.readouterr().err
    assert "title" in err and "acceptance" in err


def test_qa_gate_refuses_without_a_candidate_and_records_the_refusal(repo: Path, capsys) -> None:
    create_task()
    assert run("task", "complete", "t1") == 1
    assert "no accepted Coder candidate" in capsys.readouterr().err
    from milburn.app.project import load_project
    from milburn.persistence.sqlite_store import SQLiteEventStore

    project = load_project(repo)
    with SQLiteEventStore(project.store_path) as store:
        kinds = [event.event_type.value for event in store.read_stream("task-t1")]
    assert kinds == ["QaGateRefused"]


def test_a_wrong_reported_head_is_not_accepted_and_qa_is_refused(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAKE_CODER_MODE", "wronghead")
    build_candidate()
    assert "is not the worktree head" in capsys.readouterr().out
    assert run("qa", "t1") == 1
    assert "no accepted candidate" in capsys.readouterr().err


def test_changes_a_coder_could_not_commit_are_committed_under_its_identity(
    repo: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("FAKE_CODER_MODE", "nocommit")
    build_candidate()
    assert "result True" in capsys.readouterr().out
    log = sh(repo, "git", "log", "-1", "--format=%an <%ae>|%s", "milburn/w1/t1")
    assert log == "Milburn coder [t1/a1] <coder.t1.a1@milburn.invalid>|t1: Add feature"
    assert sh(repo, "git", "show", "milburn/w1/t1:feature_t1.txt") == "done by a1"


def test_blocked_coder_without_commits_is_recorded_not_rejected(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAKE_CODER_MODE", "blocked")
    build_candidate()
    out = capsys.readouterr().out
    assert "run completed" in out and "error" not in out
    assert run("qa", "t1") == 1


def test_failed_qa_blocks_completion(repo: Path, monkeypatch, capsys) -> None:
    build_candidate()
    monkeypatch.setenv("FAKE_TESTER_OUTCOME", "changes_requested")
    assert run("qa", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    capsys.readouterr()
    assert run("task", "complete", "t1") == 1
    assert "not passed" in capsys.readouterr().err


def test_branch_moving_after_qa_blocks_completion(repo: Path, capsys, tmp_path: Path) -> None:
    build_candidate()
    assert run("qa", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    from milburn.app.project import load_project

    worktree = load_project(repo).worktree_root / "t1"
    sh(worktree, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "--allow-empty", "-m", "late")
    capsys.readouterr()
    assert run("task", "complete", "t1") == 1
    assert "moved" in capsys.readouterr().err


def test_deliver_before_integration_is_refused(repo: Path, capsys) -> None:
    create_task()
    assert run("deliver", "w1") == 1
    assert "not integrated" in capsys.readouterr().err


def test_mutating_commands_are_refused_inside_a_role_agent(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MILBURN_ATTEMPT_ID", "t9/a1")
    assert run("task", "create", "--title", "x", "--objective", "y", "--accept", "z") == 1
    assert "inside a role agent" in capsys.readouterr().err
    assert run("status") == 0


def test_same_harness_for_coder_and_tester_is_refused_by_config(repo: Path, capsys) -> None:
    config = repo / ".milburn" / "config.toml"
    config.write_text(config.read_text().replace('harness = "claude-code"', 'harness = "codex"'))
    assert run("status") == 3
    assert "different harness" in capsys.readouterr().err


# --- the walking skeleton -------------------------------------------------------

def test_request_to_delivery_with_cross_harness_qa_and_usage(repo: Path, capsys) -> None:
    create_task()
    assert run("dispatch", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    assert "result True" in capsys.readouterr().out
    assert run("qa", "t1") == 0
    assert "claude-code" in capsys.readouterr().out
    assert run("collect", "t1", "--wait", "20") == 0
    assert run("task", "complete", "t1") == 0
    assert run("integrate", "t1") == 0
    assert run("deliver", "w1") == 0
    assert "local-only" in capsys.readouterr().out

    # The integration branch holds the Coder's commit under its own identity.
    log = sh(repo, "git", "log", "--format=%an <%ae>|%s", "milburn/w1/integration")
    assert "Milburn coder [t1/a1] <coder.t1.a1@milburn.invalid>|t1: implement" in log
    assert sh(repo, "git", "show", "milburn/w1/integration:feature_t1.txt") == "done by a1"
    # Nothing was pushed or merged into main.
    assert "feature_t1.txt" not in sh(repo, "git", "ls-tree", "--name-only", "main")

    capsys.readouterr()
    assert run("usage") == 0
    usage = capsys.readouterr().out
    assert "t1 coder codex: attempts=1, cached_input_tokens=400, input_tokens=1000, output_tokens=50" in usage
    assert "t1 tester claude-code: attempts=1, cached_input_tokens=700, input_tokens=810, output_tokens=30" in usage

    assert run("status") == 0
    status = capsys.readouterr().out
    assert "w1 [delivered]" in status and "t1 [integrated]" in status
    # Completion is final: a second complete or deliver is refused.
    assert run("task", "complete", "t1") == 1
    assert run("deliver", "w1") == 1


# --- review round 1: consistency, delivery checks, exit codes ------------------

def _project(repo: Path):
    from milburn.app.project import load_project

    return load_project(repo)


def test_a_running_attempt_blocks_collect_and_redispatch(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAKE_SLEEP", "5")
    create_task()
    assert run("dispatch", "t1") == 0
    capsys.readouterr()
    assert run("collect", "t1") == 0
    assert "still running" in capsys.readouterr().out
    assert run("dispatch", "t1") == 1
    assert "uncollected attempt" in capsys.readouterr().err
    assert run("collect", "t1", "--wait", "20") == 0
    assert "result True" in capsys.readouterr().out


def test_a_failed_launch_closes_the_attempt_and_the_task_can_retry(repo: Path, monkeypatch, capsys) -> None:
    from milburn.app import commands as commands_module

    create_task()
    original = commands_module.Commands._adapter

    def broken(self, harness, runtime):
        raise RuntimeError("harness unavailable")

    monkeypatch.setattr(commands_module.Commands, "_adapter", broken)
    assert run("dispatch", "t1") == 4
    assert "could not start" in capsys.readouterr().err
    monkeypatch.setattr(commands_module.Commands, "_adapter", original)
    assert run("dispatch", "t1") == 0
    assert "t1/a2" in capsys.readouterr().out
    assert run("collect", "t1", "--wait", "20") == 0
    assert "result True" in capsys.readouterr().out


def test_a_crash_between_intent_and_launch_is_closed_by_collect(repo: Path, monkeypatch, capsys) -> None:
    from milburn.app import commands as commands_module

    create_task()

    def crash(self, harness, runtime):
        raise KeyboardInterrupt  # not caught: simulates the process dying

    monkeypatch.setattr(commands_module.Commands, "_adapter", crash)
    with pytest.raises(KeyboardInterrupt):
        run("dispatch", "t1")
    monkeypatch.undo()
    monkeypatch.setenv("MILBURN_HOME", str(_project_home(repo)))
    _restore_env(monkeypatch, repo)
    capsys.readouterr()
    assert run("collect", "t1") == 0
    assert "never started" in capsys.readouterr().out
    assert run("dispatch", "t1") == 0


def _project_home(repo: Path) -> Path:
    return repo.parent / "milburn-home"


def _restore_env(monkeypatch, repo: Path) -> None:
    bin_dir = repo.parent / "bin"
    monkeypatch.setenv("MILBURN_CODEX_EXECUTABLE", str(bin_dir / "fake-codex"))
    monkeypatch.setenv("MILBURN_CLAUDE_EXECUTABLE", str(bin_dir / "fake-claude-code"))
    monkeypatch.chdir(repo)


def test_a_lost_collect_record_is_retried_without_rejecting_the_candidate(
    repo: Path, monkeypatch, capsys
) -> None:
    from milburn.app import state as state_module

    monkeypatch.setenv("FAKE_CODER_MODE", "nocommit")
    create_task()
    assert run("dispatch", "t1") == 0
    original = state_module.Ledger.append_many
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("store unavailable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(state_module.Ledger, "append_many", flaky)
    assert run("collect", "t1", "--wait", "20") == 4
    capsys.readouterr()
    assert run("collect", "t1") == 0
    assert "result True" in capsys.readouterr().out
    # Exactly one Milburn commit, reused by the retry.
    log = sh(repo, "git", "log", "--format=%s", "milburn/w1/t1")
    assert log.count("t1: Add feature") == 1


def test_integrate_refuses_when_the_integration_branch_moved(repo: Path, capsys) -> None:
    build_candidate()
    assert run("qa", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    assert run("task", "complete", "t1") == 0
    worktree = _project(repo).worktree_root / "w1-integration"
    sh(worktree, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "--allow-empty", "-m", "sneaky")
    capsys.readouterr()
    assert run("integrate", "t1") == 1
    assert "not at the recorded head" in capsys.readouterr().err


def test_deliver_refuses_when_the_integration_branch_moved_after_merging(repo: Path, capsys) -> None:
    build_candidate()
    assert run("qa", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    assert run("task", "complete", "t1") == 0
    assert run("integrate", "t1") == 0
    worktree = _project(repo).worktree_root / "w1-integration"
    sh(worktree, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "--allow-empty", "-m", "unreviewed")
    capsys.readouterr()
    assert run("deliver", "w1") == 1
    assert "not the last recorded merge" in capsys.readouterr().err


def _wait_for_exit(repo: Path, endpoint: str) -> None:
    import time as _time

    exit_file = _project(repo).run_dir / f"{endpoint}.exit.json"
    deadline = _time.monotonic() + 20
    while not exit_file.exists() and _time.monotonic() < deadline:
        _time.sleep(0.05)
    assert exit_file.exists()


def test_a_coder_that_switched_branches_gets_nothing_committed(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAKE_CODER_MODE", "nocommit")
    create_task()
    assert run("dispatch", "t1") == 0
    _wait_for_exit(repo, "t1-a1")
    worktree = _project(repo).worktree_root / "t1"
    sh(worktree, "git", "checkout", "-q", "-b", "elsewhere")
    capsys.readouterr()
    assert run("collect", "t1") == 0
    assert "not milburn/w1/t1" in capsys.readouterr().out
    assert sh(repo, "git", "rev-list", "--count", "elsewhere", "^main") == "0"  # nothing committed
    assert "feature_t1.txt" not in sh(repo, "git", "ls-tree", "--name-only", "-r", "elsewhere")


def test_a_tampered_git_pointer_is_refused(repo: Path, monkeypatch, capsys) -> None:
    create_task()
    assert run("dispatch", "t1") == 0
    _wait_for_exit(repo, "t1-a1")
    pointer = _project(repo).worktree_root / "t1" / ".git"
    pointer.write_text("gitdir: /tmp/elsewhere\n")
    capsys.readouterr()
    assert run("collect", "t1") == 3
    assert "does not point at" in capsys.readouterr().err


def test_unexpected_errors_exit_4_with_one_line(repo: Path, monkeypatch, capsys) -> None:
    from milburn.app import commands as commands_module

    def boom(self):
        raise ValueError("first line\nsecond line")

    monkeypatch.setattr(commands_module.Commands, "status", boom)
    assert run("status") == 4
    err = capsys.readouterr().err.strip()
    assert err.count("\n") == 0 and "first line" in err
