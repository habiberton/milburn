from datetime import UTC, datetime

from milburn.agents.briefs import BriefRenderer
from milburn.domain import AgentAttempt, AttemptState, IssueState, Role, SkillBinding
from milburn.integrations.github.contracts import Issue, RepositoryId
from milburn.orchestration.coder import CoderAssignment, CoderCoordinator
from milburn.runtime.worktrees import GitWorktreeManager
from milburn.validation.coder_protocol import CoderProtocolGuard, GitCoderProbe
from tests.unit.validation.test_coder_protocol import workspace, commit_code, result


def test_ready_issue_through_worktree_launch_and_candidate_guard(tmp_path):
    lease = workspace(tmp_path)
    manager = GitWorktreeManager()
    manager.register(lease)
    binding = SkillBinding(skill_name="milburn-long-running-coder", version="1",
                           root_digest="abc", resource_digests=(),
                           workspace_path=".agents/skills/milburn-long-running-coder",
                           validated_at=datetime(2026, 11, 4, tzinfo=UTC))
    attempt = AgentAttempt(attempt_id=lease.attempt_id, generation=0,
                           role=Role.CODER, feature_id="feature-1", issue_number=13,
                           endpoint="window-1", worktree=str(lease.worktree),
                           branch=lease.branch, base_sha=lease.base_sha,
                           rules_digest="rules", skill_bindings=(binding,),
                           status=AttemptState.STARTING)
    issue = Issue(RepositoryId("acme", "milburn"), 13, "Build feature", "Objective",
                  "open", ("milburn:task", "milburn:ready"))
    assignment = CoderAssignment(issue, IssueState.READY, attempt, lease,
                                 ((12, IssueState.DONE),), ("Latest decision",),
                                 ("Feature works",), ("PRD.md:204-294",), "Read AGENTS.md")
    brief = CoderCoordinator(manager, BriefRenderer()).prepare(assignment)
    assert "Issue #13" in brief.content
    assert "[#13]" in brief.content
    commit_code(lease)
    candidate = CoderProtocolGuard(GitCoderProbe()).accept(result(lease), lease,
                                                            IssueState.CODING)
    assert candidate.issue_number == 13
    assert candidate.head_sha != manager.inspect(lease).head_sha
