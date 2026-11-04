"""Workflow guard tests exercise the approved transition table."""

from __future__ import annotations

import pytest

from milburn.domain import (
    FeatureState,
    InvalidTransitionError,
    IssueState,
    Role,
    RoleRouteProposal,
)
from milburn.orchestration.workflow import TransitionGuard


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
        (FeatureState.PLANNING, FeatureState.BLOCKED),
        (FeatureState.ARCHITECTURE, FeatureState.FAILED),
        (FeatureState.TESTING, FeatureState.CANCELLED),
    ],
)
def test_guard_accepts_legal_feature_transitions(
    current: FeatureState, target: FeatureState
) -> None:
    TransitionGuard().feature(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (FeatureState.RECEIVED, FeatureState.ARCHITECTURE),
        (FeatureState.IMPLEMENTATION, FeatureState.COMPLETED),
        (FeatureState.TESTING, FeatureState.IMPLEMENTATION),
        (FeatureState.COMPLETED, FeatureState.BLOCKED),
    ],
)
def test_guard_rejects_illegal_feature_transitions(
    current: FeatureState, target: FeatureState
) -> None:
    with pytest.raises(InvalidTransitionError):
        TransitionGuard().feature(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IssueState.DRAFT, IssueState.BLOCKED),
        (IssueState.DRAFT, IssueState.READY),
        (IssueState.BLOCKED, IssueState.READY),
        (IssueState.READY, IssueState.CODING),
        (IssueState.CODING, IssueState.QA),
        (IssueState.QA, IssueState.PASSED),
        (IssueState.QA, IssueState.CHANGES_REQUESTED),
        (IssueState.CHANGES_REQUESTED, IssueState.CODING),
        (IssueState.PASSED, IssueState.DONE),
    ],
)
def test_guard_accepts_every_legal_issue_transition(
    current: IssueState, target: IssueState
) -> None:
    TransitionGuard().issue(current, target)


def test_guard_rejects_issue_transition_that_bypasses_qa() -> None:
    with pytest.raises(InvalidTransitionError):
        TransitionGuard().issue(IssueState.CODING, IssueState.DONE)


def proposal(state: FeatureState, role: Role) -> RoleRouteProposal:
    return RoleRouteProposal(
        request_id="request-1",
        current_state=state,
        proposed_role=role,
        reason="recommended by the router",
        confidence=0.9,
        decision_needed=False,
    )


@pytest.mark.parametrize(
    ("state", "role"),
    [
        (FeatureState.RECEIVED, Role.COORDINATOR),
        (FeatureState.RECEIVED, Role.PLANNER),
        (FeatureState.PLANNING, Role.PLANNER),
        (FeatureState.PLANNING, Role.ARCHITECT),
        (FeatureState.ARCHITECTURE, Role.ARCHITECT),
        (FeatureState.ISSUES_READY, Role.CLASSIFIER_ROUTER),
        (FeatureState.ISSUES_READY, Role.CODER),
        (FeatureState.IMPLEMENTATION, Role.CLASSIFIER_ROUTER),
        (FeatureState.IMPLEMENTATION, Role.CODER),
        (FeatureState.IMPLEMENTATION, Role.TESTER),
        (FeatureState.TESTING, Role.TESTER),
        (FeatureState.TESTING, Role.CODER),
        (FeatureState.TESTING, Role.ARCHITECT),
        (FeatureState.DECISION_NEEDED, Role.COORDINATOR),
    ],
)
def test_legal_model_recommendation_requires_controller_approval(
    state: FeatureState, role: Role
) -> None:
    recommendation = proposal(state, role)

    approved = TransitionGuard().approve_route(recommendation)

    assert approved.role is role
    assert approved.feature_state is state
    assert approved is not recommendation


def test_model_recommendation_cannot_bypass_controller_authority() -> None:
    with pytest.raises(InvalidTransitionError, match="not allowed"):
        TransitionGuard().approve_route(
            proposal(FeatureState.ARCHITECTURE, Role.CODER)
        )
