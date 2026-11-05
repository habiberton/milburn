"""Validate Architect artifacts and dependency-aware issue drafts."""

from __future__ import annotations

from pathlib import Path

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import (
    ArchitecturePackage, CommandType, EventType, PlanEnvelope, Role,
)

from .controller import Controller
from .role_results import (
    ROLE_RESULT_STREAM, RoleEventReader, artifact_digest,
    durable_feature_state, feature_events,
    parse_role_result, record_result, require_accepted_plan, require_changed_specs,
    stream_sequence, used_decision_ids, validate_decisions, validate_graph,
)
from milburn.domain import FeatureState


class ArchitectCoordinator:
    def __init__(
        self, parser: AgentResultParser, controller: Controller,
        reader: RoleEventReader, *, repository_root: Path,
    ) -> None:
        self._parser = parser
        self._controller = controller
        self._reader = reader
        self._root = repository_root

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
        events = feature_events(self._reader, plan.feature_id)
        plan_event = require_accepted_plan(events, plan)
        if durable_feature_state(events) is not FeatureState.ARCHITECTURE:
            raise ValueError("Architect result is not allowed in this feature phase")
        payload = parse_role_result(
            self._parser, document, expectation,
            role=Role.ARCHITECT, result_type="architecture_package",
        )
        if not isinstance(payload, ArchitecturePackage):
            raise ValueError("Architect result must be an ArchitecturePackage")
        if payload.feature_id != plan.feature_id or expectation.correlation.task_id != plan.feature_id:
            raise ValueError("architecture belongs to another feature")
        require_changed_specs(plan_event, self._root)
        for actual_ref, name in (
            (payload.prd_artifact, "PRD.md"),
            (payload.arch_artifact, "ARCH.md"),
        ):
            expected_ref = (
                f"{plan.feature_id}:{expectation.correlation.attempt_id}:"
                f"{name}:{artifact_digest(self._root / name)}"
            )
            if actual_ref != expected_ref:
                raise ValueError(f"{name} artifact reference does not match this attempt's bytes")
        for draft in payload.issue_drafts:
            if not any(link in {"PRD.md", "ARCH.md"} for link in draft.spec_links):
                raise ValueError("each issue draft must reference a produced spec")
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
            used_ids=used_decision_ids(self._reader),
        )
        record_result(
            self._controller, payload, expectation,
            command_type=CommandType.SUBMIT_ARCHITECTURE,
            event_type=EventType.ARCHITECTURE_PACKAGE_RECEIVED,
            feature_id=plan.feature_id,
            correlation_id=plan.feature_id,
            command_id=command_id,
            expected_sequence=expected_sequence,
            stream=ROLE_RESULT_STREAM,
            guard_sequences={
                f"feature:{plan.feature_id}": stream_sequence(
                    events, f"feature:{plan.feature_id}"
                ),
            },
        )
        return payload
