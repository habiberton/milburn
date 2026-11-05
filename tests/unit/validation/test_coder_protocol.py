from pathlib import Path
import json
import subprocess

import pytest

from milburn.domain import CoderOutcome, CoderResult, EvidenceItem, IssueState
from milburn.runtime.worktrees import WorktreeLease, WorktreeRequest
from milburn.validation.coder_protocol import CoderProtocolError, CoderProtocolGuard, GitCoderProbe, parse_progress


def git(path: Path, *args: str) -> str:
    return subprocess.run(("git", *args), cwd=path, check=True, text=True,
                          capture_output=True).stdout.strip()


def workspace(tmp_path: Path):
    repo = tmp_path / "repo"; repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    root = tmp_path / "worktrees"; root.mkdir()
    request = WorktreeRequest(repo, root, "task-13", 13, "attempt-1", base)
    git(repo, "worktree", "add", "-qb", request.branch, str(request.worktree), base)
    lease = WorktreeLease.from_request(request)
    return lease


COMMANDS = ("scripts/run-tests.sh tests/unit", "scripts/smoke-test.sh")


def log_path(lease, candidate, command):
    kind = "smoke" if "smoke" in command else "tests"
    return lease.repository.parent / "logs" / f"{candidate}-{kind}.log"


def claim(lease, candidate, command):
    return EvidenceItem(name=command, outcome="passed", evidence=json.dumps({
        "command": command, "result": "1 passed", "revision": candidate,
        "log_ref": str(log_path(lease, candidate, command)),
    }))


def guard(lease):
    return CoderProtocolGuard(GitCoderProbe(), log_root=lease.repository.parent / "logs",
                              required_commands=COMMANDS)


def result(lease, **changes):
    candidate = changes.get("head_sha", git(lease.worktree, "rev-parse", "HEAD^"))
    values = dict(attempt_id=lease.attempt_id, issue_number=lease.issue_number,
                  outcome=CoderOutcome.CANDIDATE, head_sha=candidate,
                  progress_path=f".milburn/issues/{lease.issue_number}/progress.txt",
                  commits=(candidate,), files_changed=("src.py",),
                  test_claims=tuple(claim(lease, candidate, command) for command in COMMANDS), risks=())
    values.update(changes)
    return CoderResult(**values)


def progress(lease, head=None, attempt=None, validation=None):
    current = head or git(lease.worktree, "rev-parse", "HEAD")
    if validation is None:
        validation = "\n".join(
            f"- {command}: passed; revision:{current}; log:{log_path(lease, current, command)}"
            for command in COMMANDS
        )
    return f'''Issue: #{lease.issue_number}
Branch: {lease.branch}
Base revision: {lease.base_sha}
Current head: {current}
Last updated: 2026-11-04T12:00:00Z
Agent attempt: {attempt or lease.attempt_id}

Goal
Build feature

Completed
- Work committed

In progress
- Clean

Next
1. Hand off

Decisions and assumptions
- none

Files changed
- src.py: feature

Validation
{validation}

Blockers
- none

Handoff note
Fresh Coder should inspect current diff.
'''


def commit_code(lease, message="Build feature [#13]"):
    (lease.worktree / "src.py").write_text("feature\n")
    git(lease.worktree, "add", "src.py")
    git(lease.worktree, "commit", "-qm", message)
    candidate = git(lease.worktree, "rev-parse", "HEAD")
    for command in COMMANDS:
        path = log_path(lease, candidate, command)
        path.parent.mkdir(exist_ok=True)
        path.write_text("1 passed\n")
    path = lease.worktree / f".milburn/issues/{lease.issue_number}/progress.txt"
    path.parent.mkdir(parents=True)
    path.write_text(progress(lease, head=candidate))
    git(lease.worktree, "add", str(path.relative_to(lease.worktree)))
    git(lease.worktree, "commit", "-qm", "Record progress [#13]")


@pytest.mark.parametrize("change", [
    {"attempt_id": "other"}, {"issue_number": 14}, {"progress_path": "../escape"},
    {"head_sha": "0" * 40}, {"test_claims": ()},
])
def test_candidate_rejects_mismatched_identity_and_missing_evidence(tmp_path, change):
    lease = workspace(tmp_path); commit_code(lease)
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease, **change), lease,
                                                     IssueState.CODING)


def test_rejects_unmarked_code_commit_and_false_progress(tmp_path):
    lease = workspace(tmp_path); commit_code(lease, "Unmarked")
    with pytest.raises(CoderProtocolError, match="marker"):
        guard(lease).accept(result(lease), lease,
                                                     IssueState.CODING)
    path = lease.worktree / ".milburn/issues/13/progress.txt"
    path.write_text(path.read_text().replace("Current head: " + result(lease).head_sha, "Current head: " + "0" * 40))
    with pytest.raises(CoderProtocolError, match="head"):
        guard(lease).accept(result(lease), lease,
                                                     IssueState.CODING)


def test_rejects_self_approval_and_wrong_issue_state(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease), lease,
                                                     IssueState.DONE)
    path = lease.worktree / ".milburn/issues/13/progress.txt"
    path.write_text(path.read_text().replace("- none\n\nHandoff", "- self-approved\n\nHandoff"))
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease), lease,
                                                     IssueState.CODING)


def test_progress_parser_rejects_missing_duplicate_and_unknown_sections(tmp_path):
    lease = workspace(tmp_path)
    text = progress(lease)
    for bad in (text.replace("Validation\n", ""), text + "\nUnknown\nX\n",
                text.replace("Issue: #13", "Issue: #13\nIssue: #13")):
        with pytest.raises(CoderProtocolError):
            parse_progress(bad)


def test_accepts_marked_reachable_candidate_with_test_evidence(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    accepted = guard(lease).accept(result(lease), lease,
                                                            IssueState.CODING)
    assert accepted.head_sha == git(lease.worktree, "rev-parse", "HEAD^")


def test_rejects_intermediate_code_changes_after_candidate_even_if_reverted(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    candidate = git(lease.worktree, "rev-parse", "HEAD^")
    (lease.worktree / "src.py").write_text("temporary change\n")
    git(lease.worktree, "add", "src.py"); git(lease.worktree, "commit", "-qm", "Later code")
    (lease.worktree / "src.py").write_text("feature\n")
    git(lease.worktree, "add", "src.py"); git(lease.worktree, "commit", "-qm", "Revert code")
    with pytest.raises(CoderProtocolError, match="after candidate"):
        guard(lease).accept(result(lease, head_sha=candidate,
                                                      commits=(candidate,)), lease,
                                                 IssueState.CODING)


def test_rejects_not_passed_validation_claim(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    path = lease.worktree / ".milburn/issues/13/progress.txt"
    path.write_text(path.read_text().replace("scripts/run-tests.sh tests/unit: passed", "scripts/run-tests.sh tests/unit: not passed"))
    git(lease.worktree, "add", str(path.relative_to(lease.worktree)))
    git(lease.worktree, "commit", "-qm", "Record failed validation")
    with pytest.raises(CoderProtocolError, match="validation"):
        guard(lease).accept(result(lease, head_sha=git(lease.worktree, "rev-parse", "HEAD~2"),
                                                     commits=(git(lease.worktree, "rev-parse", "HEAD~2"),)),
                                               lease, IssueState.CODING)


def test_rejects_string_issue_state_and_duplicate_file_claims(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease), lease, "coding")
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease, files_changed=("src.py", "src.py")),
                                               lease, IssueState.CODING)


def test_rejects_invented_passing_test_log(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    candidate = git(lease.worktree, "rev-parse", "HEAD^")
    invented = EvidenceItem(name=COMMANDS[0], outcome="passed", evidence=json.dumps({
        "command": COMMANDS[0], "result": "1 passed", "revision": candidate,
        "log_ref": "/missing/result.log",
    }))
    with pytest.raises(CoderProtocolError, match="log reference"):
        guard(lease).accept(result(lease, test_claims=(invented, claim(lease, candidate, COMMANDS[1]))),
                                               lease, IssueState.CODING)


@pytest.mark.parametrize("change", [
    {"command": "scripts/run-tests.sh other"},
    {"revision": "0" * 40},
    {"result": "failed"},
    {"log_ref": "/missing/result.log"},
])
def test_rejects_mismatched_test_evidence_fields(tmp_path, change):
    lease = workspace(tmp_path); commit_code(lease)
    original = result(lease)
    values = json.loads(original.test_claims[0].evidence)
    values.update(change)
    changed = EvidenceItem(name=original.test_claims[0].name, outcome="passed",
                           evidence=json.dumps(values))
    with pytest.raises(CoderProtocolError):
        guard(lease).accept(result(lease, test_claims=(changed, original.test_claims[1])),
                            lease, IssueState.CODING)


def test_rejects_log_with_larger_pass_count_substring(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    candidate = git(lease.worktree, "rev-parse", "HEAD^")
    log_path(lease, candidate, COMMANDS[0]).write_text("11 passed\n")
    with pytest.raises(CoderProtocolError, match="result"):
        guard(lease).accept(result(lease), lease, IssueState.CODING)


def test_rejects_committed_progress_symlink_to_external_file(tmp_path):
    lease = workspace(tmp_path); commit_code(lease)
    candidate = git(lease.worktree, "rev-parse", "HEAD^")
    path = lease.worktree / ".milburn/issues/13/progress.txt"
    outside = tmp_path / "external-progress.txt"
    outside.write_text(path.read_text())
    path.unlink(); path.symlink_to(outside)
    git(lease.worktree, "add", str(path.relative_to(lease.worktree)))
    git(lease.worktree, "commit", "-qm", "Link progress")
    with pytest.raises(CoderProtocolError, match="progress"):
        guard(lease).accept(result(lease, head_sha=candidate,
                                                      commits=(candidate,)), lease,
                                               IssueState.CODING)
