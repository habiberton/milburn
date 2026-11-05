from dataclasses import replace

import pytest

from milburn.agents.briefs import BriefRenderer
from milburn.orchestration.coder import CoderCoordinator, CoderStartupError
from milburn.runtime.worktrees import PriorProcessState, WorktreeRequest
from tests.fakes.worktrees import FakeWorktreeManager
from tests.unit.orchestration.test_coder import assignment
from tests.unit.validation.test_handoff_manifest import expectation, manifest
from milburn.domain.sessions import TestEvidence as HandoffTestEvidence


def checkpoint(item):
    lease = item.lease
    values = dict(task_id=lease.task_id, attempt_id=lease.attempt_id,
                  generation=0, issue_ref=f"issue-{lease.issue_number}",
                  acceptance_refs=("AC-1",), worktree=str(lease.worktree),
                  branch=lease.branch, base_sha=lease.base_sha, head_sha=lease.base_sha,
                  progress_ref=f".milburn/issues/{lease.issue_number}/progress.txt",
                  brief_digest="briefdigest", rules_digest="rulesdigest")
    return manifest(**values, test_evidence=(HandoffTestEvidence(
        command="pytest tests/unit", result="12 passed", passed=True,
        revision=lease.base_sha,
    ),)), expectation(**values)


def prepared(tmp_path):
    item = assignment(tmp_path)
    manager = FakeWorktreeManager()
    lease = item.lease
    manager.prepare(WorktreeRequest(lease.repository, lease.worktree_root,
                                    lease.task_id, lease.issue_number,
                                    lease.attempt_id, lease.base_sha))
    return item, manager


def test_replacement_uses_validated_durable_handoff_without_private_transcript(tmp_path):
    item, manager = prepared(tmp_path)
    handoff, expected = checkpoint(item)
    brief = CoderCoordinator(manager, BriefRenderer()).resume(
        item, PriorProcessState.STOPPED, handoff, expected)
    assert "Issue #13" in brief.content
    assert "progress.txt" in brief.content
    assert "previous transcript" not in brief.content
    assert ("resume", item.lease.attempt_id) in manager.actions


@pytest.mark.parametrize("change", [
    {"task_id": "wrong"}, {"head_sha": "0" * 40},
    {"progress_ref": "other.txt"},
])
def test_replacement_rejects_stale_or_mismatched_handoff_before_worktree_resume(tmp_path, change):
    item, manager = prepared(tmp_path)
    handoff, expected = checkpoint(item)
    with pytest.raises(ValueError):
        CoderCoordinator(manager, BriefRenderer()).resume(
            item, PriorProcessState.STOPPED, replace(handoff, **change), expected)
    assert ("resume", item.lease.attempt_id) not in manager.actions


def test_replacement_cannot_derive_its_own_expectation_from_handoff(tmp_path):
    item, manager = prepared(tmp_path)
    handoff, expected = checkpoint(item)
    with pytest.raises(CoderStartupError):
        CoderCoordinator(manager, BriefRenderer()).resume(
            item, PriorProcessState.STOPPED, handoff,
            replace(expected, issue_ref="issue-99"))
    assert ("resume", item.lease.attempt_id) not in manager.actions


def test_replacement_rejects_expected_head_different_from_worktree(tmp_path):
    item, manager = prepared(tmp_path)
    handoff, expected = checkpoint(item)
    with pytest.raises(CoderStartupError):
        CoderCoordinator(manager, BriefRenderer()).resume(
            item, PriorProcessState.STOPPED,
            replace(handoff, head_sha="0" * 40,
                    test_evidence=()),
            replace(expected, head_sha="0" * 40))
    assert ("resume", item.lease.attempt_id) not in manager.actions
