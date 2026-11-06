"""GhClient against a stub gh that replays canned output (no network)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from milburn.integrations.github.gh import GhClient, GhError


def client(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> GhClient:
    script = tmp_path / "gh"
    script.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"sys.stdout.write({stdout!r})\nsys.stderr.write({stderr!r})\nsys.exit({code})\n"
    )
    script.chmod(0o755)
    return GhClient(tmp_path, executable=str(script))


def pr(number: int, body: str) -> dict:
    return {"number": number, "url": f"u/{number}", "state": "OPEN", "headRefName": "b",
            "headRefOid": "a" * 40, "baseRefName": "main", "body": body, "mergeCommit": None}


def test_two_prs_with_one_marker_are_refused(tmp_path: Path) -> None:
    gh = client(tmp_path, stdout=json.dumps([pr(1, "<!-- m -->"), pr(2, "<!-- m -->")]))
    with pytest.raises(GhError, match="2 pull requests"):
        gh.find_pr("b", "<!-- m -->")


def test_a_pr_without_the_marker_is_not_ours(tmp_path: Path) -> None:
    gh = client(tmp_path, stdout=json.dumps([pr(1, "someone else's PR on this branch")]))
    assert gh.find_pr("b", "<!-- m -->") is None


def test_invalid_json_is_an_error_not_an_empty_result(tmp_path: Path) -> None:
    with pytest.raises(GhError, match="invalid JSON"):
        client(tmp_path, stdout="not json").find_pr("b", "m")


def test_checks_need_every_required_check_to_pass_or_be_skipped(tmp_path: Path) -> None:
    checks = [{"name": "ci", "bucket": "pass"}, {"name": "docs", "bucket": "skipping"},
              {"name": "e2e", "bucket": "cancel"}, {"name": "lint", "bucket": "pending"}]
    report = client(tmp_path, stdout=json.dumps(checks), code=8).required_checks(1)
    assert not report.passing
    assert report.failing == ("e2e",) and report.pending == ("lint",) and report.required == 4


def test_no_required_checks_passes_but_an_unexplained_failure_is_an_error(tmp_path: Path) -> None:
    none = client(tmp_path, stderr="no required checks reported on the 'b' branch", code=1)
    assert none.required_checks(1).passing
    with pytest.raises(GhError):
        client(tmp_path, stderr="HTTP 502", code=1).required_checks(1)


def test_a_failing_call_raises_with_its_last_message_line(tmp_path: Path) -> None:
    with pytest.raises(GhError, match="Head branch was modified"):
        client(tmp_path, stderr="x\nHead branch was modified", code=1).merge_pr(1, head_sha="a" * 40, subject="s")


@pytest.mark.parametrize("bad", ["", "g h"])
def test_executable_must_be_one_token(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        GhClient(tmp_path, executable=bad)
