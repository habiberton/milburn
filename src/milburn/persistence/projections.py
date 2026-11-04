"""Pure deterministic projections rebuilt from append-only domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol, TypeVar

from milburn.domain import (
    AttemptState,
    DomainEvent,
    EventType,
    GitHubEffectStatus,
    IssueState,
)

from .errors import ProjectionError


class DecisionState(StrEnum):
    REQUESTED = "requested"
    PRESENTED = "presented"
    ANSWERED = "answered"
    VALIDATED = "validated"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class TaskProjection:
    task_id: str
    state: IssueState
    last_event_id: str


@dataclass(frozen=True, slots=True)
class AttemptProjection:
    attempt_id: str
    state: AttemptState
    last_event_id: str


@dataclass(frozen=True, slots=True)
class DecisionProjection:
    decision_id: str
    state: DecisionState
    last_event_id: str


@dataclass(frozen=True, slots=True)
class NotificationProjection:
    notification_id: str
    unread: bool
    last_event_id: str


@dataclass(frozen=True, slots=True)
class EffectProjection:
    effect_id: str
    state: GitHubEffectStatus
    remote_identity: str | None
    last_event_id: str


@dataclass(frozen=True, slots=True)
class WorkflowProjection:
    """Immutable current state reconstructed without external reads."""

    tasks: Mapping[str, TaskProjection] = field(default_factory=dict)
    attempts: Mapping[str, AttemptProjection] = field(default_factory=dict)
    decisions: Mapping[str, DecisionProjection] = field(default_factory=dict)
    notifications: Mapping[str, NotificationProjection] = field(default_factory=dict)
    effects: Mapping[str, EffectProjection] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tasks", "attempts", "decisions", "notifications", "effects"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


class EventReader(Protocol):
    def read_all(self, *, after_position: int = 0) -> tuple[DomainEvent, ...]: ...


_TASK_STATES = {
    EventType.GITHUB_ISSUE_CREATED: IssueState.DRAFT,
    EventType.GITHUB_ISSUE_READY: IssueState.READY,
    EventType.CODER_ATTEMPT_STARTED: IssueState.CODING,
    EventType.TESTING_REQUESTED: IssueState.QA,
    EventType.CHANGES_REQUESTED: IssueState.CHANGES_REQUESTED,
    EventType.ISSUE_APPROVED: IssueState.DONE,
}
_ATTEMPT_STATES = {
    EventType.AGENT_LAUNCH_REQUESTED: AttemptState.STARTING,
    EventType.AGENT_STARTED: AttemptState.BUSY,
    EventType.CODER_ATTEMPT_STARTED: AttemptState.BUSY,
    EventType.TESTER_STARTED: AttemptState.BUSY,
    EventType.DECISION_REQUESTED: AttemptState.WAITING_USER,
    EventType.AGENT_STOPPED: AttemptState.STOPPED,
    EventType.AGENT_RESUMED: AttemptState.BUSY,
    EventType.RECOVERY_STARTED: AttemptState.UNKNOWN,
    EventType.RECOVERY_COMPLETED: AttemptState.IDLE,
}
_DECISION_STATES = {
    EventType.DECISION_REQUESTED: DecisionState.REQUESTED,
    EventType.DECISION_PRESENTED: DecisionState.PRESENTED,
    EventType.USER_DECISION_RECEIVED: DecisionState.ANSWERED,
    EventType.DECISION_ANSWER_VALIDATED: DecisionState.VALIDATED,
    EventType.STEERING_DELIVERED: DecisionState.DELIVERED,
    EventType.STEERING_ACKNOWLEDGED: DecisionState.ACKNOWLEDGED,
    EventType.DECISION_RESOLVED: DecisionState.RESOLVED,
}
_EFFECT_STATES = {
    EventType.GITHUB_EFFECT_REQUESTED: GitHubEffectStatus.REQUESTED,
    EventType.GITHUB_EFFECT_RECONCILED: GitHubEffectStatus.RECONCILED,
    EventType.GITHUB_MCP_CALL_STARTED: GitHubEffectStatus.CALL_STARTED,
    EventType.GITHUB_EFFECT_OBSERVED: GitHubEffectStatus.OBSERVED,
    EventType.GITHUB_EFFECT_UNCERTAIN: GitHubEffectStatus.UNCERTAIN,
}


def project_events(events: Iterable[DomainEvent]) -> WorkflowProjection:
    """Fold events into a new deterministic projection."""

    state = WorkflowProjection()
    for event in events:
        state = project_event(state, event)
    return state


def replay(reader: EventReader) -> WorkflowProjection:
    """Rebuild current state from the reader's complete durable history."""

    return project_events(reader.read_all())


def project_event(state: WorkflowProjection, event: DomainEvent) -> WorkflowProjection:
    """Apply one event without mutating the previous projection."""

    facts = {fact.name: fact.value for fact in event.facts}
    tasks = dict(state.tasks)
    attempts = dict(state.attempts)
    decisions = dict(state.decisions)
    notifications = dict(state.notifications)
    effects = dict(state.effects)

    task_id = facts.get("task_id") or facts.get("issue_number")
    task_state = _fact_enum(facts, "task_state", IssueState) or _TASK_STATES.get(
        event.event_type
    )
    if task_state is not None and task_id is None:
        raise ProjectionError(f"{event.event_type.value} requires task_id or issue_number")
    if task_id is not None and task_state is not None:
        tasks[task_id] = TaskProjection(task_id, task_state, event.event_id)

    attempt_id = facts.get("attempt_id") or facts.get("source_attempt_id")
    attempt_state = _fact_enum(
        facts, "attempt_state", AttemptState
    ) or _ATTEMPT_STATES.get(event.event_type)
    if attempt_state is not None and attempt_id is None:
        raise ProjectionError(f"{event.event_type.value} requires attempt_id")
    if attempt_id is not None and attempt_state is not None:
        attempts[attempt_id] = AttemptProjection(
            attempt_id, attempt_state, event.event_id
        )

    decision_id = facts.get("decision_id")
    decision_state = _fact_enum(
        facts, "decision_state", DecisionState
    ) or _DECISION_STATES.get(event.event_type)
    if decision_state is not None and decision_id is None:
        raise ProjectionError(f"{event.event_type.value} requires decision_id")
    if decision_id is not None and decision_state is not None:
        decisions[decision_id] = DecisionProjection(
            decision_id, decision_state, event.event_id
        )

    notification_id = facts.get("notification_id")
    if (
        event.event_type is EventType.COORDINATOR_NOTIFICATION_QUEUED
        and notification_id is None
    ):
        raise ProjectionError("CoordinatorNotificationQueued requires notification_id")
    if notification_id is not None:
        unread = event.event_type is EventType.COORDINATOR_NOTIFICATION_QUEUED
        if "notification_unread" in facts:
            unread = _parse_bool(facts["notification_unread"])
        notifications[notification_id] = NotificationProjection(
            notification_id, unread, event.event_id
        )

    effect_id = facts.get("effect_id")
    effect_state = _fact_enum(
        facts, "effect_state", GitHubEffectStatus
    ) or _EFFECT_STATES.get(event.event_type)
    if effect_state is not None and effect_id is None:
        raise ProjectionError(f"{event.event_type.value} requires effect_id")
    if effect_id is not None and effect_state is not None:
        previous = effects.get(effect_id)
        remote_identity = facts.get("remote_identity")
        if remote_identity is None and previous is not None:
            remote_identity = previous.remote_identity
        effects[effect_id] = EffectProjection(
            effect_id, effect_state, remote_identity, event.event_id
        )

    return WorkflowProjection(tasks, attempts, decisions, notifications, effects)


def _parse_bool(value: str) -> bool:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ProjectionError(f"boolean fact must be true or false, got {value!r}")


EnumValue = TypeVar("EnumValue", bound=StrEnum)


def _fact_enum(
    facts: Mapping[str, str], name: str, enum_type: type[EnumValue]
) -> EnumValue | None:
    value = facts.get(name)
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError as error:
        raise ProjectionError(
            f"{name} has unknown {enum_type.__name__} value {value!r}"
        ) from error
