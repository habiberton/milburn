"""GhClient against a stub gh that replays canned output (no network)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from milburn.integrations.github.gh import GhClient, GhError, GitHubRepo, repo_from_url

REPO = GitHubRepo("github.com", "acme/toy")


def client(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> GhClient:
    script = tmp_path / "gh"
    script.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"sys.stdout.write({stdout!r})\nsys.stderr.write({stderr!r})\nsys.exit({code})\n"
    )
    script.chmod(0o755)
    return GhClient(tmp_path, REPO, executable=str(script))


def pr(number: int, body: str, **extra) -> dict:
    data = {"number": number, "url": f"u/{number}", "state": "OPEN", "headRefName": "b",
            "headRefOid": "a" * 40, "baseRefName": "main", "body": body, "mergeCommit": None,
            "isCrossRepository": False}
    data.update(extra)
    return data


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/toy.git", ("github.com", "acme/toy")),
        ("https://x-token@github.com/acme/toy", ("github.com", "acme/toy")),
        ("git@github.com:acme/toy.git", ("github.com", "acme/toy")),
        ("ssh://git@ghe.example.com:2222/acme/toy.git", ("ghe.example.com", "acme/toy")),
        ("/srv/git/toy.git", None),
        ("https://github.com/acme", None),
    ],
)
def test_repo_from_url(url: str, expected) -> None:
    parsed = repo_from_url(url)
    assert (parsed.host, parsed.name) == expected if expected else parsed is None


def test_two_of_our_prs_with_one_marker_are_refused(tmp_path: Path) -> None:
    gh = client(tmp_path, stdout=json.dumps([pr(1, "<!-- m -->"), pr(2, "<!-- m -->")]))
    with pytest.raises(GhError, match="#1, #2"):
        gh.find_pr("b", "main", "<!-- m -->")


def test_fork_wrong_base_and_unmarked_prs_are_not_ours(tmp_path: Path) -> None:
    gh = client(tmp_path, stdout=json.dumps([
        pr(1, "<!-- m -->", isCrossRepository=True),
        pr(2, "<!-- m -->", baseRefName="dev"),
        pr(3, "someone else's PR"),
    ]))
    assert gh.find_pr("b", "main", "<!-- m -->") is None


@pytest.mark.parametrize("stdout", ["not json", json.dumps({"a": 1}), json.dumps([{"number": 1}]),
                                    json.dumps([pr(1, "m", state="DRAFT")])])
def test_malformed_gh_output_is_an_error(tmp_path: Path, stdout: str) -> None:
    with pytest.raises(GhError):
        client(tmp_path, stdout=stdout).find_pr("b", "main", "m")


def test_every_required_check_must_have_reported_and_passed(tmp_path: Path) -> None:
    checks = [{"name": "ci", "bucket": "pass"}, {"name": "docs", "bucket": "skipping"},
              {"name": "e2e", "bucket": "cancel"}, {"name": "lint", "bucket": "pending"}]
    report = client(tmp_path, stdout=json.dumps(checks), code=1).checks(
        1, ["ci", "docs", "e2e", "lint", "deploy"])
    assert not report.passing
    assert report.failing == ("e2e",) and report.pending == ("lint",) and report.missing == ("deploy",)


def test_nothing_reported_with_nothing_required_passes(tmp_path: Path) -> None:
    gh = client(tmp_path, stderr="no checks reported on the 'b' branch", code=1)
    assert gh.checks(1, []).passing
    assert not gh.checks(1, ["ci"]).passing
    with pytest.raises(GhError):
        client(tmp_path, stderr="HTTP 502", code=1).checks(1, ["ci"])


def test_required_contexts_fail_closed_on_an_unreadable_protection(tmp_path: Path) -> None:
    with pytest.raises(GhError, match="branch protection"):
        client(tmp_path, stderr="Resource not accessible (HTTP 403)", code=1).required_contexts("main")


def test_a_failing_call_raises_with_its_last_message_line(tmp_path: Path) -> None:
    with pytest.raises(GhError, match="Head branch was modified"):
        client(tmp_path, stderr="x\nHead branch was modified", code=1).merge_pr(1, head_sha="a" * 40, subject="s")


@pytest.mark.parametrize("bad", ["", "g h"])
def test_executable_must_be_one_token(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        GhClient(tmp_path, REPO, executable=bad)
