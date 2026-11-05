"""Keep Classifier/Router output behind the deterministic transition guard."""

from __future__ import annotations

from dataclasses import dataclass

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import (
    CommandType, EventType, FeatureState, Role, RoleRouteProposal,
)

from .controller import Controller
from .role_results import parse_role_result, record_result
from .workflow import ApprovedRoute, TransitionGuard


@dataclass(frozen=True, slots=True)
class RouteEscalation:
    request_id: str
    reason: str


class RouterCoordinator:
    def __init__(
        self, parser: AgentResultParser, guard: TransitionGuard,
        controller: Controller,
    ) -> None:
        self._parser = parser
        self._guard = guard
        self._controller = controller

    def accept(
        self,
        document: str | bytes | bytearray,
        expectation: ResultExpectation,
        *,
        feature_id: str,
        request_id: str,
        current_state: FeatureState,
        command_id: str,
        expected_sequence: int,
    ) -> ApprovedRoute | RouteEscalation:
        """Validate the route before recording the bounded proposal."""
        payload = parse_role_result(
            self._parser, document, expectation,
            role=Role.CLASSIFIER_ROUTER, result_type="role_route_proposal",
        )
        if not isinstance(payload, RoleRouteProposal):
            raise ValueError("Router result must be a RoleRouteProposal")
        if (
            payload.request_id != request_id
            or payload.current_state is not current_state
            or expectation.correlation.task_id != feature_id
        ):
            raise ValueError("route does not match current request and feature state")
        approved = self._guard.approve_route(payload)
        record_result(
            self._controller, payload, expectation,
            command_type=CommandType.PROPOSE_ROLE_ROUTE,
            event_type=EventType.ROLE_ROUTE_PROPOSED,
            feature_id=feature_id,
            correlation_id=request_id,
            command_id=command_id,
            expected_sequence=expected_sequence,
        )
        if payload.decision_needed:
            return RouteEscalation(request_id, payload.reason)
        return approved
