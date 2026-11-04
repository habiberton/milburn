"""Deterministic state and role validation."""

import pytest

from milburn.domain import (
    FeatureState,
    InvalidTransitionError,
    IssueState,
    Role,
    ensure_feature_transition,
    ensure_issue_transition,
    ensure_role_allowed,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (FeatureState.RECEIVED, FeatureState.PLANNING),
        (FeatureState.PLANNING, FeatureState.ARCHITECTURE),
        (FeatureState.ARCHITECTURE, FeatureState.ISSUES_READY),
        (FeatureState.ISSUES_READY, FeatureState.IMPLEMENTATION),
        (FeatureState.IMPLEMENTATION, FeatureState.TESTING),
        (FeatureState.TESTING, FeatureState.COMPLETED),
        (FeatureState.RECEIVED, FeatureState.DECISION_NEEDED),
        (FeatureState.IMPLEMENTATION, FeatureState.BLOCKED),
    ],
)
def test_approved_feature_transitions(current: FeatureState, target: FeatureState) -> None:
    ensure_feature_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (FeatureState.RECEIVED, FeatureState.COMPLETED),
        (FeatureState.PLANNING, FeatureState.TESTING),
        (FeatureState.TESTING, FeatureState.IMPLEMENTATION),
        (FeatureState.COMPLETED, FeatureState.IMPLEMENTATION),
        (FeatureState.CANCELLED, FeatureState.PLANNING),
    ],
)
def test_illegal_feature_transitions_fail(current: FeatureState, target: FeatureState) -> None:
    with pytest.raises(InvalidTransitionError, match="feature transition"):
        ensure_feature_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IssueState.DRAFT, IssueState.BLOCKED),
        (IssueState.DRAFT, IssueState.READY),
        (IssueState.READY, IssueState.CODING),
        (IssueState.CODING, IssueState.QA),
        (IssueState.QA, IssueState.CHANGES_REQUESTED),
        (IssueState.CHANGES_REQUESTED, IssueState.CODING),
        (IssueState.QA, IssueState.PASSED),
        (IssueState.PASSED, IssueState.DONE),
    ],
)
def test_approved_issue_transitions(current: IssueState, target: IssueState) -> None:
    ensure_issue_transition(current, target)


def test_issue_cannot_skip_independent_qa() -> None:
    with pytest.raises(InvalidTransitionError, match="issue transition"):
        ensure_issue_transition(IssueState.CODING, IssueState.DONE)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IssueState.CODING, IssueState.BLOCKED),
        (IssueState.QA, IssueState.BLOCKED),
    ],
)
def test_issue_cannot_take_unapproved_blocked_edges(
    current: IssueState, target: IssueState
) -> None:
    with pytest.raises(InvalidTransitionError, match="issue transition"):
        ensure_issue_transition(current, target)


@pytest.mark.parametrize(
    ("state", "role"),
    [
        (FeatureState.RECEIVED, Role.COORDINATOR),
        (FeatureState.RECEIVED, Role.PLANNER),
        (FeatureState.PLANNING, Role.ARCHITECT),
        (FeatureState.ISSUES_READY, Role.CODER),
        (FeatureState.IMPLEMENTATION, Role.TESTER),
        (FeatureState.TESTING, Role.ARCHITECT),
        (FeatureState.DECISION_NEEDED, Role.COORDINATOR),
    ],
)
def test_roles_allowed_by_approved_workflow(state: FeatureState, role: Role) -> None:
    ensure_role_allowed(state, role)


def test_model_recommendation_cannot_bypass_role_guard() -> None:
    with pytest.raises(InvalidTransitionError, match="not allowed"):
        ensure_role_allowed(FeatureState.ARCHITECTURE, Role.CODER)


@pytest.mark.parametrize(
    "operation",
    [
        lambda: ensure_feature_transition("received", FeatureState.PLANNING),
        lambda: ensure_feature_transition(FeatureState.RECEIVED, "planning"),
        lambda: ensure_issue_transition("ready", IssueState.CODING),
        lambda: ensure_issue_transition(IssueState.READY, "coding"),
        lambda: ensure_role_allowed("received", Role.PLANNER),
        lambda: ensure_role_allowed(FeatureState.RECEIVED, "planner"),
    ],
)
def test_guards_reject_raw_strings(operation: object) -> None:
    with pytest.raises(InvalidTransitionError, match="known"):
        operation()  # type: ignore[operator]
