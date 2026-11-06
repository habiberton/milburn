"""pr and auto-merge delivery (PRD R7, R41; ARCH §5) over a local bare remote and a fake gh."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from tests.integration.cli.test_walking_skeleton import (  # noqa: F401 - fixture
    _project, create_task, repo, run, sh,
)

pytestmark = pytest.mark.timeout(120)
FAKE_GH = Path(__file__).with_name("fake_gh.py")
GH_VARS = ("FAKE_GH_CHECKS", "FAKE_GH_FAIL", "FAKE_GH_REQUIRED", "FAKE_GH_RULES", "GH_REPO", "GH_HOST")


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
    for name in GH_VARS:
        monkeypatch.delenv(name, raising=False)
    return bare


def set_mode(repo: Path, mode: str, github_repo: str | None = "acme/toy") -> None:
    config = repo / ".milburn" / "config.toml"
    text = config.read_text().replace('delivery = "local-only"', f'delivery = "{mode}"')
    if github_repo:
        text = text.replace('remote = "origin"', f'remote = "origin"\ngithub_repo = "{github_repo}"')
    config.write_text(text)


def integrated_work_item(tasks: int = 1) -> None:
    for index in range(1, tasks + 1):
        extra = ("--work-item", "w1") if index > 1 else ()
        assert run("task", "create", "--title", f"Feature {index}", "--objective", "Add a feature file",
                   "--accept", f"feature_t{index}.txt exists", *extra) == 0
        task = f"t{index}"
        assert run("dispatch", task) == 0
        assert run("collect", task, "--wait", "20") == 0
        assert run("qa", task) == 0
        assert run("collect", task, "--wait", "20") == 0
        assert run("task", "complete", task) == 0
        assert run("integrate", task) == 0


def gh_state(tmp_path: Path) -> dict:
    path = tmp_path / "gh-state.json"
    return json.loads(path.read_text()) if path.exists() else {"prs": [], "calls": []}


def save_gh_state(tmp_path: Path, state: dict) -> None:
    (tmp_path / "gh-state.json").write_text(json.dumps(state))


def calls(tmp_path: Path, verb: str) -> list[list[str]]:
    return [call for call in gh_state(tmp_path)["calls"] if call[:2] == ["pr", verb]]


def events(repo: Path, stream: str) -> list[tuple[str, dict]]:
    from milburn.app.state import payload_of
    from milburn.persistence.sqlite_store import SQLiteEventStore

    with SQLiteEventStore(_project(repo).store_path) as store:
        return [(e.event_type.value, payload_of(e)) for e in store.read_stream(stream)]


def effects(repo: Path, kind: str, effect: str) -> int:
    return sum(1 for k, data in events(repo, "work-w1") if k == kind and data.get("effect") == effect)


def delivered(repo: Path) -> bool:
    return any(kind == "WorkItemDelivered" for kind, _ in events(repo, "work-w1"))


# --- refusals and failures first ------------------------------------------------

def test_local_only_never_calls_gh_or_pushes(repo: Path, remote: Path, tmp_path: Path) -> None:
    integrated_work_item()
    assert run("deliver", "w1") == 0
    assert gh_state(tmp_path)["calls"] == []
    assert sh(repo, "git", "ls-remote", "--heads", "origin", "milburn/w1/integration") == ""


def test_a_remote_that_is_not_github_needs_github_repo(repo: Path, remote: Path, capsys) -> None:
    set_mode(repo, "pr", github_repo=None)
    integrated_work_item()
    capsys.readouterr()
    assert run("deliver", "w1") == 3
    assert "github_repo" in capsys.readouterr().err


def test_an_unreachable_remote_fails_before_any_effect(repo: Path, remote: Path, tmp_path: Path, capsys) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    sh(repo, "git", "remote", "set-url", "origin", str(remote.parent / "missing.git"))
    capsys.readouterr()
    assert run("deliver", "w1") == 3
    assert "cannot reach remote" in capsys.readouterr().err
    assert gh_state(tmp_path)["calls"] == []


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
    assert calls(tmp_path, "create") == []


def test_a_failed_pr_create_is_retried_without_pushing_or_opening_twice(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch
) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_FAIL", "create")
    assert run("deliver", "w1") == 4
    monkeypatch.delenv("FAKE_GH_FAIL")
    assert run("deliver", "w1") == 0
    assert effects(repo, "DeliveryEffectObserved", "push") == 1
    assert effects(repo, "DeliveryEffectRequested", "open_pr") == 2  # failed once, then succeeded
    assert len(gh_state(tmp_path)["prs"]) == 1


def test_a_pr_closed_without_merging_is_refused_before_any_effect(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", "ci")
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    state = gh_state(tmp_path)
    state["prs"][0]["state"] = "CLOSED"
    save_gh_state(tmp_path, state)
    capsys.readouterr()
    assert run("deliver", "w1") == 1
    assert "closed without merging" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("required", "rules", "checks", "word"),
    [
        ("ci", "", "pending", "pending: ci"),
        ("ci", "", "fail", "failing: ci"),
        ("ci", "", "none", "not reported yet: ci"),     # CI has not started yet
        ("", "ci", "none", "not reported yet: ci"),     # required by a ruleset only
    ],
)
def test_auto_merge_waits_until_every_required_check_passed_on_the_head(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys, required, rules, checks, word
) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", required)
    monkeypatch.setenv("FAKE_GH_RULES", rules)
    monkeypatch.setenv("FAKE_GH_CHECKS", checks)
    integrated_work_item()
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    out = capsys.readouterr().out
    assert word in out and "not merged" in out
    assert calls(tmp_path, "merge") == []
    assert not delivered(repo)
    assert "feature_t1.txt" not in sh(remote, "git", "ls-tree", "--name-only", "main")


def test_unreadable_branch_protection_fails_closed(repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", "forbidden")
    integrated_work_item()
    capsys.readouterr()
    assert run("deliver", "w1") == 4
    assert "branch protection" in capsys.readouterr().err
    assert calls(tmp_path, "merge") == []


def test_fork_prs_and_retargeted_prs_are_never_adopted(repo: Path, remote: Path, tmp_path: Path, capsys) -> None:
    set_mode(repo, "pr")
    integrated_work_item()
    head = sh(repo, "git", "rev-parse", "milburn/w1/integration")
    marker = f"<!-- milburn-work-item:{_project(repo).state_dir.name}:w1 -->"
    base = {"url": "u", "headRefName": "milburn/w1/integration", "headRefOid": head,
            "body": marker, "title": "t", "mergeCommit": None, "state": "OPEN"}
    save_gh_state(tmp_path, {"calls": [], "prs": [
        {**base, "number": 1, "baseRefName": "main", "isCrossRepository": True},   # a fork
        {**base, "number": 2, "baseRefName": "dev", "isCrossRepository": False},   # retargeted
    ]})
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    assert "pull request #3" in capsys.readouterr().out


def test_every_gh_call_names_the_configured_repository(repo: Path, remote: Path, tmp_path: Path, monkeypatch) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("GH_REPO", "someone/else")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    for call in gh_state(tmp_path)["calls"]:
        if call[:1] == ["pr"]:
            assert call[call.index("--repo") + 1] == "acme/toy", call
        else:
            assert any("repos/acme/toy/" in part for part in call), call


def test_a_merged_pr_with_unreviewed_commits_is_not_recorded_as_delivered(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", "ci")
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    state = gh_state(tmp_path)
    state["prs"][0].update(state="MERGED", headRefOid="f" * 40, mergeCommit={"oid": "e" * 40})
    save_gh_state(tmp_path, state)
    capsys.readouterr()
    assert run("deliver", "w1") == 4
    assert "unreviewed commits were merged" in capsys.readouterr().err
    assert not delivered(repo)


def test_head_moved_on_github_blocks_the_merge(repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", "ci")
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    other = tmp_path / "other"
    sh(tmp_path, "git", "clone", "-q", "-b", "milburn/w1/integration", str(remote), str(other))
    sh(other, "git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "late")
    sh(other, "git", "push", "-q", "origin", "milburn/w1/integration")
    monkeypatch.setenv("FAKE_GH_CHECKS", "pass")
    capsys.readouterr()
    assert run("deliver", "w1") == 1
    assert "did not make" in capsys.readouterr().err
    assert calls(tmp_path, "merge") == []


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
    assert calls(tmp_path, "merge") == []
    assert run("deliver", "w1") == 1  # delivered once


def test_two_dependent_tasks_give_one_branch_and_one_pull_request(repo: Path, remote: Path, tmp_path: Path) -> None:
    set_mode(repo, "pr")
    integrated_work_item(tasks=2)
    assert run("deliver", "w1") == 0
    tree = sh(remote, "git", "ls-tree", "--name-only", "milburn/w1/integration")
    assert "feature_t1.txt" in tree and "feature_t2.txt" in tree
    assert len(gh_state(tmp_path)["prs"]) == 1


def test_auto_merge_merges_once_checks_pass_and_verifies_the_default_branch(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    monkeypatch.setenv("FAKE_GH_REQUIRED", "ci")
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    monkeypatch.setenv("FAKE_GH_CHECKS", "pass")
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    out = capsys.readouterr().out
    assert "merged as" in out and "origin/main" in out
    assert sh(remote, "git", "show", "main:feature_t1.txt") == "done by a1"
    merge = gh_state(tmp_path)["prs"][0]["mergeCommit"]["oid"]
    assert len(sh(remote, "git", "rev-list", "--parents", "-n", "1", merge).split()) == 3
    assert len(calls(tmp_path, "create")) == 1 and len(calls(tmp_path, "merge")) == 1


def test_auto_merge_with_nothing_required_merges(repo: Path, remote: Path, tmp_path: Path) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    assert run("deliver", "w1") == 0
    assert gh_state(tmp_path)["prs"][0]["state"] == "MERGED"


def test_a_merge_that_reports_failure_but_happened_is_reconciled_without_a_second_push(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    set_mode(repo, "auto-merge")
    integrated_work_item()
    monkeypatch.setenv("FAKE_GH_FAIL", "merge-after")
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    assert "merged as" in capsys.readouterr().out
    assert len(calls(tmp_path, "merge")) == 1


def test_after_a_crash_post_merge_a_retry_reconciles_without_pushing(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    from milburn.app import commands as commands_module

    set_mode(repo, "auto-merge")
    integrated_work_item()
    original = commands_module.Commands._finish_merged

    def crash(self, *args, **kwargs):
        raise RuntimeError("crashed after merging")

    monkeypatch.setattr(commands_module.Commands, "_finish_merged", crash)
    assert run("deliver", "w1") == 4
    monkeypatch.setattr(commands_module.Commands, "_finish_merged", original)
    # GitHub deletes the merged branch.
    sh(remote, "git", "update-ref", "-d", "refs/heads/milburn/w1/integration")
    assert run("deliver", "w1") == 0
    assert effects(repo, "DeliveryEffectRequested", "push") == 1
    assert len(calls(tmp_path, "merge")) == 1 and delivered(repo)


def test_github_repo_and_remote_url_must_agree(repo: Path, remote: Path, capsys) -> None:
    set_mode(repo, "pr", github_repo="acme/toy")
    integrated_work_item()
    sh(repo, "git", "remote", "set-url", "origin", "https://github.com/other/place.git")
    capsys.readouterr()
    assert run("deliver", "w1") == 3
    assert "must name the same repository" in capsys.readouterr().err


def test_pr_mode_accepts_a_user_squash_merge_of_the_qad_head(
    repo: Path, remote: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    from milburn.app import commands as commands_module

    set_mode(repo, "pr")
    integrated_work_item()
    original = commands_module.Commands._record_delivered
    monkeypatch.setattr(commands_module.Commands, "_record_delivered",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash before recording")))
    assert run("deliver", "w1") == 4
    monkeypatch.setattr(commands_module.Commands, "_record_delivered", original)
    # The user squash-merges on GitHub: a single-parent commit on main.
    other = tmp_path / "squash"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(other))
    sh(other, "git", "merge", "-q", "--squash", "origin/milburn/w1/integration")
    sh(other, "git", "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "-m", "squash")
    sh(other, "git", "push", "-q", "origin", "main")
    state = gh_state(tmp_path)
    state["prs"][0].update(state="MERGED", mergeCommit={"oid": sh(other, "git", "rev-parse", "HEAD")})
    save_gh_state(tmp_path, state)
    capsys.readouterr()
    assert run("deliver", "w1") == 0
    assert delivered(repo)
