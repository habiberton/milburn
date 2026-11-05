"""Validate Architect artifacts and dependency-aware issue drafts."""

from __future__ import annotations

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import (
    ArchitecturePackage, CommandType, EventType, PlanEnvelope, Role,
)

from .controller import Controller
from .role_results import parse_role_result, record_result, validate_decisions, validate_graph


class ArchitectCoordinator:
    def __init__(self, parser: AgentResultParser, controller: Controller) -> None:
        self._parser = parser
        self._controller = controller

    def accept(
        self,
        document: str | bytes | bytearray,
        expectation: ResultExpectation,
        plan: PlanEnvelope,
        *,
        known_task_keys: tuple[str, ...],
        command_id: str,
        expected_sequence: int,
    ) -> ArchitecturePackage:
        """Require specs and a valid issue DAG before recording the package."""
        if not isinstance(plan, PlanEnvelope):
            raise ValueError("accepted plan is required")
        payload = parse_role_result(
            self._parser, document, expectation,
            role=Role.ARCHITECT, result_type="architecture_package",
        )
        if not isinstance(payload, ArchitecturePackage):
            raise ValueError("Architect result must be an ArchitecturePackage")
        if payload.feature_id != plan.feature_id or expectation.correlation.task_id != plan.feature_id:
            raise ValueError("architecture belongs to another feature")
        if payload.prd_artifact != "PRD.md" or payload.arch_artifact != "ARCH.md":
            raise ValueError("architecture must name root PRD.md and ARCH.md artifacts")
        keys = tuple(draft.task_key for draft in payload.issue_drafts)
        if any(key in known_task_keys for key in keys):
            raise ValueError("issue draft key collides with an existing task")
        validate_graph(
            keys,
            {draft.task_key: draft.dependencies for draft in payload.issue_drafts},
            external=known_task_keys,
        )
        validate_decisions(
            payload.open_decisions,
            feature_id=plan.feature_id,
            attempt_id=expectation.correlation.attempt_id,
        )
        record_result(
            self._controller, payload, expectation,
            command_type=CommandType.SUBMIT_ARCHITECTURE,
            event_type=EventType.ARCHITECTURE_PACKAGE_RECEIVED,
            feature_id=plan.feature_id,
            correlation_id=plan.feature_id,
            command_id=command_id,
            expected_sequence=expected_sequence,
        )
        return payload
