"""Known roles and deterministic lifecycle states."""

from __future__ import annotations

from enum import StrEnum

from .errors import InvalidTransitionError


class Role(StrEnum):
    COORDINATOR = "coordinator"
    PLANNER = "planner"
    CLASSIFIER_ROUTER = "classifier_router"
    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"


class FeatureState(StrEnum):
    RECEIVED = "received"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    ISSUES_READY = "issues_ready"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    COMPLETED = "completed"
    DECISION_NEEDED = "decision_needed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IssueState(StrEnum):
    DRAFT = "draft"
    BLOCKED = "blocked"
    READY = "ready"
    CODING = "coding"
    QA = "qa"
    CHANGES_REQUESTED = "changes_requested"
    PASSED = "passed"
    DONE = "done"


class AttemptState(StrEnum):
    STARTING = "starting"
    BUSY = "busy"
    IDLE = "idle"
    WAITING = "waiting"
    WAITING_USER = "waiting_user"
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    FAILED = "failed"


class GitHubEffectStatus(StrEnum):
    REQUESTED = "requested"
    RECONCILED = "reconciled"
    CALL_STARTED = "call_started"
    OBSERVED = "observed"
    UNCERTAIN = "uncertain"


class CoderOutcome(StrEnum):
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    DECISION_NEEDED = "decision_needed"
    FAILED = "failed"


class QAOutcome(StrEnum):
    PASSED = "passed"
    CHANGES_REQUESTED = "changes_requested"
    DECISION_NEEDED = "decision_needed"
    FAILED = "failed"


_TERMINAL_FEATURE_STATES = {
    FeatureState.COMPLETED,
    FeatureState.FAILED,
    FeatureState.CANCELLED,
}
_INTERRUPTION_STATES = {
    FeatureState.DECISION_NEEDED,
    FeatureState.BLOCKED,
    FeatureState.FAILED,
    FeatureState.CANCELLED,
}
_FEATURE_TRANSITIONS = {
    FeatureState.RECEIVED: {FeatureState.PLANNING},
    FeatureState.PLANNING: {FeatureState.ARCHITECTURE},
    FeatureState.ARCHITECTURE: {FeatureState.ISSUES_READY},
    FeatureState.ISSUES_READY: {FeatureState.IMPLEMENTATION},
    FeatureState.IMPLEMENTATION: {FeatureState.TESTING},
    FeatureState.TESTING: {FeatureState.IMPLEMENTATION, FeatureState.COMPLETED},
}
_ISSUE_TRANSITIONS = {
    IssueState.DRAFT: {IssueState.BLOCKED, IssueState.READY},
    IssueState.BLOCKED: {IssueState.READY},
    IssueState.READY: {IssueState.CODING},
    IssueState.CODING: {IssueState.QA, IssueState.BLOCKED},
    IssueState.QA: {
        IssueState.PASSED,
        IssueState.CHANGES_REQUESTED,
        IssueState.BLOCKED,
    },
    IssueState.CHANGES_REQUESTED: {IssueState.CODING},
    IssueState.PASSED: {IssueState.DONE},
}
_ROLE_TRANSITIONS = {
    FeatureState.RECEIVED: {Role.COORDINATOR, Role.PLANNER},
    FeatureState.PLANNING: {Role.PLANNER, Role.ARCHITECT},
    FeatureState.ARCHITECTURE: {Role.ARCHITECT},
    FeatureState.ISSUES_READY: {Role.CLASSIFIER_ROUTER, Role.CODER},
    FeatureState.IMPLEMENTATION: {Role.CLASSIFIER_ROUTER, Role.CODER, Role.TESTER},
    FeatureState.TESTING: {Role.TESTER, Role.CODER, Role.ARCHITECT},
    FeatureState.DECISION_NEEDED: {Role.COORDINATOR},
}


def ensure_feature_transition(current: FeatureState, target: FeatureState) -> None:
    """Reject a feature transition outside the approved lifecycle."""

    allowed = _FEATURE_TRANSITIONS.get(current, set()) | _INTERRUPTION_STATES
    if current in _TERMINAL_FEATURE_STATES or target not in allowed:
        raise InvalidTransitionError(f"feature transition {current} -> {target} is illegal")


def ensure_issue_transition(current: IssueState, target: IssueState) -> None:
    """Reject an issue transition outside the approved lifecycle."""

    if target not in _ISSUE_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(f"issue transition {current} -> {target} is illegal")


def ensure_role_allowed(state: FeatureState, role: Role) -> None:
    """Reject model-role recommendations that lack controller authority."""

    if role not in _ROLE_TRANSITIONS.get(state, set()):
        raise InvalidTransitionError(f"role {role} is not allowed in feature state {state}")
