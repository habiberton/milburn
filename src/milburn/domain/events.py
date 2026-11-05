"""Append-only event contracts for Milburn's durable streams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .base import VersionedModel, require_enum, require_identifier, require_non_negative
from .errors import InvalidEnvelopeError


class EventType(StrEnum):
    REQUEST_ACCEPTED = "RequestAccepted"
    ROLE_ROUTE_PROPOSED = "RoleRouteProposed"
    ROLE_ROUTE_APPROVED = "RoleRouteApproved"
    COORDINATOR_SESSION_STARTED = "CoordinatorSessionStarted"
    USER_MESSAGE_RECEIVED = "UserMessageReceived"
    DECISION_REQUESTED = "DecisionRequested"
    COORDINATOR_NOTIFICATION_QUEUED = "CoordinatorNotificationQueued"
    COORDINATOR_NOTIFICATION_READ = "CoordinatorNotificationRead"
    DECISION_PRESENTED = "DecisionPresented"
    USER_DECISION_RECEIVED = "UserDecisionReceived"
    DECISION_ANSWER_VALIDATED = "DecisionAnswerValidated"
    STEERING_QUEUED = "SteeringQueued"
    STEERING_DELIVERED = "SteeringDelivered"
    STEERING_ACKNOWLEDGED = "SteeringAcknowledged"
    DECISION_RESOLVED = "DecisionResolved"
    AGENT_LAUNCH_REQUESTED = "AgentLaunchRequested"
    AGENT_STARTED = "AgentStarted"
    PLAN_RECEIVED = "PlanReceived"
    ARCHITECTURE_PACKAGE_RECEIVED = "ArchitecturePackageReceived"
    GITHUB_ISSUE_CREATED = "GitHubIssueCreated"
    GITHUB_ISSUE_READY = "GitHubIssueReady"
    GITHUB_EFFECT_REQUESTED = "GitHubEffectRequested"
    GITHUB_EFFECT_OBSERVED = "GitHubEffectObserved"
    GITHUB_EFFECT_RECONCILED = "GitHubEffectReconciled"
    GITHUB_MCP_CALL_STARTED = "GitHubMcpCallStarted"
    GITHUB_EFFECT_UNCERTAIN = "GitHubEffectUncertain"
    CODER_ATTEMPT_REQUESTED = "CoderAttemptRequested"
    WORKTREE_CREATED = "WorktreeCreated"
    CODER_ATTEMPT_STARTED = "CoderAttemptStarted"
    CODER_CHECKPOINT_OBSERVED = "CoderCheckpointObserved"
    CODER_RESULT_RECEIVED = "CoderResultReceived"
    TESTING_REQUESTED = "TestingRequested"
    TESTER_STARTED = "TesterStarted"
    TEST_RESULT_RECEIVED = "TestResultReceived"
    CHANGES_REQUESTED = "ChangesRequested"
    ISSUE_APPROVED = "IssueApproved"
    DECISION_REQUIRED = "DecisionRequired"
    AGENT_STOPPED = "AgentStopped"
    RECOVERY_STARTED = "RecoveryStarted"
    RECOVERY_COMPLETED = "RecoveryCompleted"
    AGENT_RESUMED = "AgentResumed"
    FEATURE_COMPLETED = "FeatureCompleted"
    # Enforcement CLI (ARCH §4, §5, §8).
    PROJECT_INITIALIZED = "ProjectInitialized"
    WORK_ITEM_OPENED = "WorkItemOpened"
    TASK_CREATED = "TaskCreated"
    ATTEMPT_DISPATCHED = "AttemptDispatched"
    ATTEMPT_COLLECTED = "AttemptCollected"
    AGENT_USAGE_OBSERVED = "AgentUsageObserved"
    QA_GATE_REFUSED = "QaGateRefused"
    TASK_COMPLETED = "TaskCompleted"
    TASK_INTEGRATED = "TaskIntegrated"
    WORK_ITEM_DELIVERED = "WorkItemDelivered"
    SESSION_GENERATION_EXHAUSTED = "SessionGenerationExhausted"
    ATTEMPT_HANDED_OFF = "AttemptHandedOff"


@dataclass(frozen=True, slots=True)
class EventFact(VersionedModel):
    name: str
    value: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.name, "name")
        if not isinstance(self.value, str):
            raise InvalidEnvelopeError("value must be a string")


@dataclass(frozen=True, slots=True)
class DomainEvent(VersionedModel):
    event_id: str
    stream: str
    sequence: int
    event_type: EventType
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None
    facts: tuple[EventFact, ...] = ()

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.event_id, "event_id")
        require_identifier(self.stream, "stream")
        require_non_negative(self.sequence, "sequence")
        require_enum(self.event_type, EventType, "event_type")
        require_identifier(self.correlation_id, "correlation_id")
        if self.causation_id is not None:
            require_identifier(self.causation_id, "causation_id")
        names = [fact.name for fact in self.facts]
        if len(names) != len(set(names)):
            raise InvalidEnvelopeError("event fact names must be unique")
