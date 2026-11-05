"""Validate Planner results and record approved plan intent."""

from __future__ import annotations

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import CommandType, EventType, PlanEnvelope, RequestEnvelope, Role

from .controller import Controller
from .role_results import parse_role_result, record_result, validate_decisions, validate_graph


class PlannerCoordinator:
    def __init__(self, parser: AgentResultParser, controller: Controller) -> None:
        self._parser = parser
        self._controller = controller

    def accept(
        self,
        document: str | bytes | bytearray,
        expectation: ResultExpectation,
        request: RequestEnvelope,
        *,
        command_id: str,
        expected_sequence: int,
    ) -> PlanEnvelope:
        """Require a correlated, acyclic plan before appending PlanReceived."""
        if not isinstance(request, RequestEnvelope):
            raise ValueError("request must be a RequestEnvelope")
        payload = parse_role_result(
            self._parser, document, expectation,
            role=Role.PLANNER, result_type="plan_envelope",
        )
        if not isinstance(payload, PlanEnvelope):
            raise ValueError("Planner result must be a PlanEnvelope")
        if payload.feature_id != request.feature_id:
            raise ValueError("plan belongs to another feature")
        if expectation.correlation.task_id != request.feature_id:
            raise ValueError("Planner result task does not match feature")
        validate_graph(
            (stage.stage_id for stage in payload.stages),
            {stage.stage_id: stage.dependencies for stage in payload.stages},
        )
        if len(set(payload.dependencies)) != len(payload.dependencies):
            raise ValueError("plan dependencies must be unique")
        validate_decisions(
            payload.decisions_needed,
            feature_id=request.feature_id,
            attempt_id=expectation.correlation.attempt_id,
        )
        record_result(
            self._controller, payload, expectation,
            command_type=CommandType.SUBMIT_PLAN,
            event_type=EventType.PLAN_RECEIVED,
            feature_id=request.feature_id,
            correlation_id=request.request_id,
            command_id=command_id,
            expected_sequence=expected_sequence,
        )
        return payload
