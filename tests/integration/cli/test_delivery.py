"""pr and auto-merge delivery (PRD R7, R41; ARCH §5) over a local bare remote and a fake gh."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from tests.integration.cli.test_walking_skeleton import (  # noqa: F401 - fixture
    _project, create_task, repo, run, sh,
)

pytestmark = pytest.mark.timeout(90)
FAKE_GH = Path(__file__).with_name("fake_gh.py")


@pytest.fixture()
def remote(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bare = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh(repo, "git", "remote", "add", "origin", str(bare))
    sh(repo, "git", "push", "-q", "origin", "main")
    wrapper = tmp_path / "bin" / "fake-gh"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_GH}" "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv("MILBURN_GH_EXECUTABLE", str(wrapper))
    monkeypatch.setenv("FAKE_GH_STATE", str(tmp_path / "gh-state.json"))
    monkeypatch.setenv("FAKE_GH_REMOTE", str(bare))
    for name in ("FAKE_GH_CHECKS", "FAKE_GH_FAIL"):
        monkeypatch.delenv(name, raising=False)
    return bare


def set_mode(repo: Path, mode: str) -> None:
    config = repo / ".milburn" / "config.toml"
    config.write_text(config.read_text().replace('delivery = "local-only"', f'delivery = "{mode}"'))


def integrated_work_item() -> None:
    create_task()
    assert run("dispatch", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    assert run("qa", "t1") == 0
    assert run("collect", "t1", "--wait", "20") == 0
    assert run("task", "complete", "t1") == 0
    assert run("integrate", "t1") == 0


def gh_state(tmp_path: Path) -> dict:
    path = tmp_path / "gh-state.json"
    return json.loads(path.read_text()) if path.exists() else {"prs": [], "calls": []}


def calls(tmp_path: Path, verb: str) -> int:
    return sum(1 for call in gh_state(tmp_path)["calls"] if call[:2] == ["pr", verb])


def events(repo: Path, stream: str) -> list[tuple[str, dict]]:
    from milburn.app.state import payload_of
    from milburn.persistence.sqlite_store import SQLiteEventStore

    with SQLiteEventStore(_project(repo).store_path) as store:
        return [(e.event_type.value, payload_of(e)) for e in store.read_stream(stream)]


# --- refusals and failures first ------------------------------------------------

def test_local_only_never_calls_gh_or_pushes(repo: Path, remote: Path, tmp_path: Path) -> None:
    integrated_work_item()
    assert run("deliver", "w1") == 0
    assert gh_state(tmp_path)["calls"] == []
    assert sh(repo, "git", "ls-remote", "origin", "refs/heads/milburn/w1/integration") == ""


def test_a_remote_branch_with_foreign_commits_is_not_overwritten(
    repo: Path, remote: Path, tmp_path: Path, capsys
) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    sh(repo, "git", "push", "-q", "origin", "main:refs/heads/milburn/w1/integration")
    other = tmp_path / "other"
    sh(tmp_path, "git", "clone", "-q", "-b", "milburn/w1/integration", str(remote), str(other))
    sh(other, "git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "foreign")
    sh(other, "git", "push", "-q", "origin", "milburn/w1/integration")
    capsys.readouterr()
    assert run("deliver", "w1") == 1
    assert "did not make" in capsys.readouterr().err
    assert calls(tmp_path, "create") == 0


def test_an_unreachable_remote_fails_with_exit_4(repo: Path, remote: Path, capsys) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    sh(repo, "git", "remote", "set-url", "origin", str(remote.parent / "missing.git"))
    capsys.readouterr()
    assert run("deliver", "w1") == 4
    assert "cannot reach remote" in capsys.readouterr().err


def test_a_failed_pr_create_is_retried_without_pushing_or_opening_twice(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch
) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_FAIL", "create")
    assert run("deliver", "w1") == 4
    monkeypatch.delenv("FAKE_GH_FAIL")
    assert run("deliver", "w1") == 0
    kinds = [(kind, data["effect"]) for kind, data in events(repo, "work-w1") if "effect" in data]
    assert kinds.count(("DeliveryEffectObserved", "push")) == 1
    assert len(gh_state(tmp_path)["prs"]) == 1


def test_a_pr_closed_without_merging_is_refused(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    assert run("deliver", "w1") == 0
    state = gh_state(tmp_path)
    state["prs"][0]["state"] = "CLOSED"
    (tmp_path / "gh-state.json").write_text(json.dumps(state))
    capsys.readouterr()
    assert run("deliver", "w1") == 1
    assert "closed without merging" in capsys.readouterr().err


@pytest.mark.parametrize(("checks", "word"), [("pending", "pending"), ("fail", "failing")])
def test_auto_merge_waits_for_required_checks(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys, checks: str, word: str
) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_CHECKS", checks)
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    out = capsys.readouterr().out
    assert f"required checks {word}: ci" in out and "not merged" in out
    assert calls(tmp_path, "merge") == 0
    assert not [kind for kind, _ in events(repo, "work-w1") if kind == "WorkItemDelivered"]
    assert "feature_t1.txt" not in sh(remote, "git", "ls-tree", "--name-only", "main")


# --- delivery -----------------------------------------------------------------------

def test_pr_mode_pushes_and_opens_one_pull_request_and_never_merges(
    repo: Path, remote: Path, tmp_path: Path, capsys
) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    assert "pull request #1" in capsys.readouterr().out
    head = sh(repo, "git", "rev-parse", "milburn/w1/integration")
    assert sh(remote, "git", "rev-parse", "refs/heads/milburn/w1/integration") == head
    pr = gh_state(tmp_path)["prs"][0]
    assert pr["state"] == "OPEN" and pr["baseRefName"] == "main"
    assert "<!-- milburn-work-item:" in pr["body"] and "passed on claude-code" in pr["body"]
    assert calls(tmp_path, "merge") == 0
    assert run("deliver", "w1") == 1  # delivered once


def test_auto_merge_merges_once_checks_pass_and_verifies_the_default_branch(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    assert run("deliver", "w1") == 0
    monkeypatch.setenv("FAKE_GH_CHECKS", "pass")
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    out = capsys.readouterr().out
    assert "merged as" in out and "origin/main" in out
    assert sh(remote, "git", "show", "main:feature_t1.txt") == "done by a1"
    merge = gh_state(tmp_path)["prs"][0]["mergeCommit"]["oid"]
    assert len(sh(remote, "git", "rev-list", "--parents", "-n", "1", merge).split()) == 3  # a merge commit
    assert calls(tmp_path, "create") == 1 and calls(tmp_path, "merge") == 1


def test_auto_merge_with_no_required_checks_merges(repo: Path, remote: Path, tmp_path: Path) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    assert gh_state(tmp_path)["prs"][0]["state"] == "MERGED"


def test_a_merge_that_reports_failure_but_happened_is_reconciled(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_FAIL", "merge-after")
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    assert "merged as" in capsys.readouterr().out
    assert calls(tmp_path, "merge") == 1
