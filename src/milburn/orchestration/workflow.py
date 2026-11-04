"""Deterministic workflow transition and route approval guard."""

from __future__ import annotations

from dataclasses import dataclass

from milburn.domain import (
    FeatureState,
    IssueState,
    Role,
    RoleRouteProposal,
    ensure_feature_transition,
    ensure_issue_transition,
    ensure_role_allowed,
)


@dataclass(frozen=True, slots=True)
class ApprovedRoute:
    """A route recommendation that controller policy has approved."""

    request_id: str
    feature_state: FeatureState
    role: Role


class TransitionGuard:
    """Single pure entry point for approved lifecycle and role transitions."""

    def feature(self, current: FeatureState, target: FeatureState) -> None:
        ensure_feature_transition(current, target)

    def issue(self, current: IssueState, target: IssueState) -> None:
        ensure_issue_transition(current, target)

    def approve_route(self, proposal: RoleRouteProposal) -> ApprovedRoute:
        """Validate a model recommendation without granting it direct authority."""

        ensure_role_allowed(proposal.current_state, proposal.proposed_role)
        return ApprovedRoute(
            request_id=proposal.request_id,
            feature_state=proposal.current_state,
            role=proposal.proposed_role,
        )
