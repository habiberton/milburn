"""Typed immutable envelopes shared across Milburn components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .base import (
    VersionedModel,
    require_bool,
    require_enum,
    require_identifier,
    require_non_negative,
    require_text,
)
from .errors import InvalidEnvelopeError
from .states import (
    AttemptState,
    CoderOutcome,
    FeatureState,
    GitHubEffectStatus,
    QAOutcome,
    Role,
)


def _timestamp(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEnvelopeError(f"{field_name} must be a timezone-aware datetime")


def _identifiers(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        require_identifier(value, field_name)


def _texts(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        require_text(value, field_name)


@dataclass(frozen=True, slots=True)
class RequestEnvelope(VersionedModel):
    request_id: str
    feature_id: str
    objective: str
    repository_id: str
    base_branch: str
    delivery_posture: str
    submitted_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.request_id, "request_id")
        require_identifier(self.feature_id, "feature_id")
        require_identifier(self.repository_id, "repository_id")
        require_identifier(self.base_branch, "base_branch")
        require_text(self.objective, "objective")
        require_text(self.delivery_posture, "delivery_posture")
        _timestamp(self.submitted_at, "submitted_at")


@dataclass(frozen=True, slots=True)
class RoleRouteProposal(VersionedModel):
    request_id: str
    current_state: FeatureState
    proposed_role: Role
    reason: str
    confidence: float
    decision_needed: bool

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.request_id, "request_id")
        require_enum(self.current_state, FeatureState, "current_state")
        require_enum(self.proposed_role, Role, "proposed_role")
        require_text(self.reason, "reason")
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise InvalidEnvelopeError("confidence must be a number")
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidEnvelopeError("confidence must be between 0 and 1")
        require_bool(self.decision_needed, "decision_needed")


@dataclass(frozen=True, slots=True)
class DecisionRequest(VersionedModel):
    decision_id: str
    source_attempt_id: str
    feature_id: str
    issue_number: int | None
    question: str
    why_it_matters: str
    options: tuple[str, ...]
    recommendation: str | None
    blocking: bool

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.decision_id, "decision_id")
        require_identifier(self.source_attempt_id, "source_attempt_id")
        require_identifier(self.feature_id, "feature_id")
        if self.issue_number is not None:
            require_non_negative(self.issue_number, "issue_number")
        require_text(self.question, "question")
        require_text(self.why_it_matters, "why_it_matters")
        if len(self.options) < 2:
            raise InvalidEnvelopeError("options must contain at least two choices")
        _texts(self.options, "options")
        if self.recommendation is not None:
            require_text(self.recommendation, "recommendation")
        require_bool(self.blocking, "blocking")


@dataclass(frozen=True, slots=True)
class UserDecision(VersionedModel):
    decision_id: str
    coordinator_attempt_id: str
    selected_option: str | None
    answer: str
    answered_by: str
    answered_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.decision_id, "decision_id")
        require_identifier(self.coordinator_attempt_id, "coordinator_attempt_id")
        if self.selected_option is not None:
            require_text(self.selected_option, "selected_option")
        require_text(self.answer, "answer")
        require_identifier(self.answered_by, "answered_by")
        _timestamp(self.answered_at, "answered_at")


@dataclass(frozen=True, slots=True)
class CoordinatorNotification(VersionedModel):
    notification_id: str
    kind: str
    correlation_id: str
    priority: int
    summary: str
    unread: bool
    created_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.notification_id, "notification_id")
        require_identifier(self.kind, "kind")
        require_identifier(self.correlation_id, "correlation_id")
        require_non_negative(self.priority, "priority")
        require_text(self.summary, "summary")
        require_bool(self.unread, "unread")
        _timestamp(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class PlanStage(VersionedModel):
    stage_id: str
    title: str
    description: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.stage_id, "stage_id")
        require_text(self.title, "title")
        require_text(self.description, "description")
        _identifiers(self.dependencies, "dependencies")


@dataclass(frozen=True, slots=True)
class PlanEnvelope(VersionedModel):
    feature_id: str
    summary: str
    stages: tuple[PlanStage, ...]
    dependencies: tuple[str, ...]
    risks: tuple[str, ...]
    decisions_needed: tuple[DecisionRequest, ...]

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.feature_id, "feature_id")
        require_text(self.summary, "summary")
        if not self.stages:
            raise InvalidEnvelopeError("stages must not be empty")
        _identifiers(self.dependencies, "dependencies")
        _texts(self.risks, "risks")


@dataclass(frozen=True, slots=True)
class IssueDraft(VersionedModel):
    task_key: str
    title: str
    objective: str
    spec_links: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...]
    test_instructions: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    risks: tuple[str, ...]
    non_goals: tuple[str, ...]

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.task_key, "task_key")
        require_text(self.title, "title")
        require_text(self.objective, "objective")
        if not self.spec_links:
            raise InvalidEnvelopeError("spec_links must not be empty")
        if not self.acceptance_criteria:
            raise InvalidEnvelopeError("acceptance_criteria must not be empty")
        if not self.test_instructions:
            raise InvalidEnvelopeError("test_instructions must not be empty")
        if not self.expected_artifacts:
            raise InvalidEnvelopeError("expected_artifacts must not be empty")
        _texts(self.spec_links, "spec_links")
        _texts(self.acceptance_criteria, "acceptance_criteria")
        _identifiers(self.dependencies, "dependencies")
        _texts(self.test_instructions, "test_instructions")
        _texts(self.expected_artifacts, "expected_artifacts")
        _texts(self.risks, "risks")
        _texts(self.non_goals, "non_goals")


@dataclass(frozen=True, slots=True)
class ArchitecturePackage(VersionedModel):
    feature_id: str
    prd_artifact: str
    arch_artifact: str
    issue_drafts: tuple[IssueDraft, ...]
    open_decisions: tuple[DecisionRequest, ...]

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.feature_id, "feature_id")
        require_text(self.prd_artifact, "prd_artifact")
        require_text(self.arch_artifact, "arch_artifact")
        if not self.issue_drafts:
            raise InvalidEnvelopeError("issue_drafts must not be empty")


@dataclass(frozen=True, slots=True)
class GitHubEffect(VersionedModel):
    effect_id: str
    repository_id: str
    operation: str
    idempotency_marker: str
    requested_arguments_digest: str
    status: GitHubEffectStatus
    remote_identity: str | None
    last_observation: datetime | None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.effect_id, "effect_id")
        require_identifier(self.repository_id, "repository_id")
        require_identifier(self.operation, "operation")
        require_text(self.idempotency_marker, "idempotency_marker")
        require_identifier(self.requested_arguments_digest, "requested_arguments_digest")
        require_enum(self.status, GitHubEffectStatus, "status")
        if self.remote_identity is not None:
            require_identifier(self.remote_identity, "remote_identity")
        if self.last_observation is not None:
            _timestamp(self.last_observation, "last_observation")


@dataclass(frozen=True, slots=True)
class SkillBinding(VersionedModel):
    skill_name: str
    version: str
    root_digest: str
    resource_digests: tuple[str, ...]
    workspace_path: str
    validated_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.skill_name, "skill_name")
        require_identifier(self.version, "version")
        require_identifier(self.root_digest, "root_digest")
        _identifiers(self.resource_digests, "resource_digests")
        require_text(self.workspace_path, "workspace_path")
        _timestamp(self.validated_at, "validated_at")


@dataclass(frozen=True, slots=True)
class AgentAttempt(VersionedModel):
    attempt_id: str
    generation: int
    role: Role
    feature_id: str
    issue_number: int | None
    endpoint: str
    worktree: str | None
    branch: str | None
    base_sha: str | None
    rules_digest: str
    skill_bindings: tuple[SkillBinding, ...]
    status: AttemptState

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.attempt_id, "attempt_id")
        require_non_negative(self.generation, "generation")
        require_enum(self.role, Role, "role")
        require_identifier(self.feature_id, "feature_id")
        if self.issue_number is not None:
            require_non_negative(self.issue_number, "issue_number")
        require_identifier(self.endpoint, "endpoint")
        if self.worktree is not None:
            require_text(self.worktree, "worktree")
        if self.branch is not None:
            require_identifier(self.branch, "branch")
        if self.base_sha is not None:
            require_identifier(self.base_sha, "base_sha")
        require_identifier(self.rules_digest, "rules_digest")
        require_enum(self.status, AttemptState, "status")


@dataclass(frozen=True, slots=True)
class EvidenceItem(VersionedModel):
    name: str
    outcome: str
    evidence: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_text(self.name, "name")
        require_identifier(self.outcome, "outcome")
        require_text(self.evidence, "evidence")


@dataclass(frozen=True, slots=True)
class CoderResult(VersionedModel):
    attempt_id: str
    issue_number: int
    outcome: CoderOutcome
    head_sha: str
    progress_path: str
    commits: tuple[str, ...]
    files_changed: tuple[str, ...]
    test_claims: tuple[EvidenceItem, ...]
    risks: tuple[str, ...]

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.attempt_id, "attempt_id")
        require_non_negative(self.issue_number, "issue_number")
        require_enum(self.outcome, CoderOutcome, "outcome")
        require_identifier(self.head_sha, "head_sha")
        require_text(self.progress_path, "progress_path")
        if not self.commits:
            raise InvalidEnvelopeError("commits must not be empty")
        _identifiers(self.commits, "commits")
        _texts(self.files_changed, "files_changed")
        _texts(self.risks, "risks")


@dataclass(frozen=True, slots=True)
class QAReport(VersionedModel):
    attempt_id: str
    issue_number: int
    candidate_sha: str
    outcome: QAOutcome
    acceptance_results: tuple[EvidenceItem, ...]
    commands: tuple[str, ...]
    evidence_artifacts: tuple[str, ...]
    defects: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.attempt_id, "attempt_id")
        require_non_negative(self.issue_number, "issue_number")
        require_enum(self.outcome, QAOutcome, "outcome")
        require_identifier(self.candidate_sha, "candidate_sha")
        if not self.acceptance_results:
            raise InvalidEnvelopeError("acceptance_results must not be empty")
        if not self.commands:
            raise InvalidEnvelopeError("commands must not be empty")
        _texts(self.commands, "commands")
        _texts(self.evidence_artifacts, "evidence_artifacts")
        _texts(self.defects, "defects")
        require_text(self.summary, "summary")
