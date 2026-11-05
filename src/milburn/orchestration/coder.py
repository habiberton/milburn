"""Bound one Coder launch to one ready issue, lease, and durable startup brief."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from milburn.agents.briefs import BriefRenderer, RenderedBrief, LaunchBrief, CODER_BOUNDARY_QUESTIONS
from milburn.domain import AgentAttempt, AttemptState, IssueState, Role
from milburn.integrations.github.contracts import Issue, RepositoryId
from milburn.runtime.worktrees import (
    PriorProcessState, WorktreeLease, WorktreeManagerProtocol,
)
from milburn.domain.sessions import HandoffManifest
from milburn.validation.handoff_manifest import HandoffExpectation, HandoffManifestValidator


class CoderStartupError(ValueError):
    """The Coder launch would not have a complete, approved assignment."""


_STATUS_LABELS = frozenset({
    "milburn:ready", "milburn:blocked", "milburn:in-progress", "milburn:qa",
    "milburn:changes-requested", "milburn:done", "milburn:decision-needed",
})
CODER_ROLE_RULES = "\n".join((
    "Work only on this issue in the assigned worktree. Maintain progress.txt and issue-linked commits.",
    "Submit progress or candidate only; controller and independent Tester own approval and closure.",
    "Write negative tests before validators and adapters; require fake/live parity tests.",
    "Boundary questions:", *CODER_BOUNDARY_QUESTIONS,
))


@dataclass(frozen=True, slots=True)
class CoderAssignment:
    issue: Issue
    state: IssueState
    attempt: AgentAttempt
    lease: WorktreeLease
    dependencies: tuple[tuple[int, IssueState], ...]
    comments: tuple[str, ...]
    acceptance: tuple[str, ...]
    spec_refs: tuple[str, ...]
    repository_instructions: str

    def validate(self, *, replacement: bool = False) -> None:
        if not isinstance(self.issue, Issue) or not isinstance(self.attempt, AgentAttempt) or not isinstance(self.lease, WorktreeLease):
            raise CoderStartupError("issue, attempt, and worktree lease must use known contracts")
        states = (
            {IssueState.CODING: "milburn:in-progress",
             IssueState.CHANGES_REQUESTED: "milburn:changes-requested"}
            if replacement else {IssueState.READY: "milburn:ready"}
        )
        if (not isinstance(self.state, IssueState) or self.state not in states
            or self.issue.state != "open"
            or "milburn:task" not in self.issue.labels
            or set(self.issue.labels) & _STATUS_LABELS != {states.get(self.state)}):
            raise CoderStartupError("Coder assignment requires one open issue in its expected state")
        if (self.attempt.role is not Role.CODER or self.attempt.status is not AttemptState.STARTING
            or self.attempt.issue_number != self.issue.number
            or self.lease.issue_number != self.issue.number
            or self.attempt.attempt_id != self.lease.attempt_id
            or self.attempt.worktree != str(self.lease.worktree)
            or self.attempt.branch != self.lease.branch
            or self.attempt.base_sha != self.lease.base_sha):
            raise CoderStartupError("Coder attempt and lease do not match the assigned issue")
        if (not isinstance(self.dependencies, tuple)
            or any(not isinstance(entry, tuple) or len(entry) != 2
                   or not isinstance(entry[0], int) or isinstance(entry[0], bool)
                   or not isinstance(entry[1], IssueState) for entry in self.dependencies)
            or len({number for number, _ in self.dependencies}) != len(self.dependencies)):
            raise CoderStartupError("dependencies must be a unique tuple")
        if any(not isinstance(number, int) or isinstance(number, bool) or number <= 0 or number == self.issue.number
               or state is not IssueState.DONE for number, state in self.dependencies):
            raise CoderStartupError("dependencies must all be distinct completed issues")
        for name in ("comments", "acceptance", "spec_refs"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise CoderStartupError(f"{name} must contain only meaningful text")
        if (not self.acceptance or not self.spec_refs
            or not isinstance(self.repository_instructions, str)
            or not self.repository_instructions.strip()):
            raise CoderStartupError("Coder launch requires acceptance, specs, and repository instructions")
        if not any(binding.skill_name == "milburn-long-running-coder" for binding in self.attempt.skill_bindings):
            raise CoderStartupError("Coder skill binding is missing")


class CoderCoordinator:
    def __init__(self, worktrees: WorktreeManagerProtocol, renderer: BriefRenderer,
                 *, repository_id: RepositoryId, repository_path: Path,
                 handoffs: HandoffManifestValidator | None = None) -> None:
        if not isinstance(repository_id, RepositoryId) or not isinstance(repository_path, Path) or not repository_path.is_absolute():
            raise CoderStartupError("configured repository identity and path are required")
        self._worktrees = worktrees
        self._renderer = renderer
        self._handoffs = handoffs or HandoffManifestValidator()
        self._repository_id = repository_id
        self._repository_path = repository_path

    def prepare(self, assignment: CoderAssignment) -> RenderedBrief:
        return self._prepare(assignment, allow_dirty=False)

    def _prepare(self, assignment: CoderAssignment, *, allow_dirty: bool,
                 manifest: HandoffManifest | None = None) -> RenderedBrief:
        if not isinstance(assignment, CoderAssignment):
            raise CoderStartupError("Coder assignment must use the known contract")
        assignment.validate(replacement=allow_dirty)
        if (assignment.issue.repository_id != self._repository_id
            or assignment.lease.repository != self._repository_path):
            raise CoderStartupError("issue and worktree do not belong to the configured repository")
        inspection = self._worktrees.inspect(assignment.lease)
        if not inspection.matched or (not allow_dirty and inspection.clean is not True):
            raise CoderStartupError("Coder worktree is not a registered lease in the required state")
        lease = assignment.lease
        issue = assignment.issue
        context = "\n".join((
            f"Issue #{issue.number}: {issue.title}",
            f"Repository: {issue.repository_id.value}",
            f"Issue body:\n{issue.body}",
            "Acceptance criteria:\n" + "\n".join(f"- {item}" for item in assignment.acceptance),
            "Dependencies:\n" + ("\n".join(f"- #{number}: {state.value}" for number, state in assignment.dependencies) or "- none"),
            "Recent comments:\n" + ("\n".join(f"- {item}" for item in assignment.comments) or "- none"),
            "Spec references:\n" + "\n".join(f"- {item}" for item in assignment.spec_refs),
            f"Branch: {lease.branch}\nWorktree: {lease.worktree}\nBase SHA: {lease.base_sha}",
            f"Git status: {'clean' if inspection.clean is True else 'dirty or unknown'}; inspect every uncommitted change before editing.",
        ))
        if manifest is not None:
            context += "\n" + "\n".join((
                "Validated durable handoff:",
                f"progress_ref: {manifest.progress_ref}",
                f"head_sha: {manifest.head_sha}",
                f"inbox_sequence: {manifest.inbox_sequence}",
                f"outbox_sequence: {manifest.outbox_sequence}",
                "completed: " + "; ".join(manifest.completed),
                "remaining: " + "; ".join(manifest.remaining),
                "test_evidence: " + "; ".join(
                    f"{item.command} -> {item.result} at {item.revision}"
                    for item in manifest.test_evidence),
                "uncertain_effects: " + "; ".join(
                    f"{effect.effect_id} reconciled={effect.reconciled}"
                    for effect in manifest.uncertain_effects),
                "open_decisions: " + "; ".join(manifest.open_decisions),
            ))
        startup = "\n".join((
            "Before editing, confirm the repository, issue, attempt, branch, worktree, and base SHA.",
            "Read AGENTS.md and repository guidance; read this issue, its dependencies, and recent comments.",
            f"Read .milburn/issues/{issue.number}/progress.txt if present and verify each claim.",
            "Inspect Git status and every uncommitted change.",
            f"Search issue-specific Git history for [#{issue.number}] and inspect branch history.",
            "Inspect the diff from base SHA to current HEAD.",
            "Run the configured smoke check and tests through scripts/run-tests.sh and record each bounded summary and log reference.",
            "Compare code, progress, commits, and tests with every acceptance criterion; choose one incomplete step.",
            "For a replacement, use this durable context and validated handoff; perform the full startup sequence.",
        ))
        rendered = self._renderer.render(LaunchBrief(
            role=Role.CODER, task_id=lease.task_id, attempt_id=lease.attempt_id,
            objective=issue.title, role_rules=CODER_ROLE_RULES,
            task_context=context + "\n\nStartup sequence:\n" + startup,
            repository_instructions=assignment.repository_instructions,
            result_contract="Return a versioned CoderResult with candidate SHA, issue-linked commits, progress path, test claims, and risks. A candidate is a claim for Tester validation.",
            skill_bindings=assignment.attempt.skill_bindings,
        ))
        if rendered.rules_digest != assignment.attempt.rules_digest:
            raise CoderStartupError("rendered Coder rules digest does not match attempt")
        return rendered

    def resume(self, assignment: CoderAssignment, prior_process: PriorProcessState,
               manifest: HandoffManifest | None = None,
               expectation: HandoffExpectation | None = None) -> RenderedBrief:
        if not isinstance(assignment, CoderAssignment):
            raise CoderStartupError("Coder assignment must use the known contract")
        assignment.validate(replacement=True)
        if prior_process is not PriorProcessState.STOPPED:
            raise CoderStartupError("replacement requires proof that prior process stopped")
        if not isinstance(manifest, HandoffManifest) or not isinstance(expectation, HandoffExpectation):
            raise CoderStartupError("replacement requires a durable validated handoff")
        lease = assignment.lease
        if (expectation.task_id != lease.task_id or expectation.role is not Role.CODER
            or expectation.attempt_id != lease.attempt_id
            or expectation.issue_ref != f"issue-{lease.issue_number}"
            or expectation.worktree != str(lease.worktree)
            or expectation.branch != lease.branch or expectation.base_sha != lease.base_sha
            or expectation.progress_ref != f".milburn/issues/{lease.issue_number}/progress.txt"
            or expectation.rules_digest != assignment.attempt.rules_digest):
            raise CoderStartupError("handoff expectation does not match assignment")
        inspection = self._worktrees.inspect(lease)
        if not inspection.matched or inspection.head_sha != expectation.head_sha:
            raise CoderStartupError("handoff head does not match observed worktree")
        self._handoffs.validate(manifest, expectation)
        brief = self._prepare(assignment, allow_dirty=True, manifest=manifest)
        resumed = self._worktrees.resume(assignment.lease, prior_process)
        if resumed.head_sha != expectation.head_sha:
            raise CoderStartupError("worktree changed during replacement validation")
        return brief
