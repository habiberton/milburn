"""Planner result validation before controller state changes."""

from datetime import UTC, datetime
import json

import pytest

from milburn.agents.result_parser import AgentResultParser
from milburn.domain import (
    DecisionRequest, EventType, PlanEnvelope, PlanStage, RequestEnvelope, Role,
)
from milburn.orchestration.controller import Controller
from milburn.orchestration.planning import PlannerCoordinator
from milburn.persistence.sqlite_store import SQLiteEventStore
from tests.fakes.role_results import document, expectation


NOW = datetime(2026, 11, 4, tzinfo=UTC)
EXPECTED = expectation(Role.PLANNER, "plan_envelope")


def request() -> RequestEnvelope:
    return RequestEnvelope(
        request_id="request-1", feature_id="feature-1", objective="Build it",
        repository_id="repo-1", base_branch="main", delivery_posture="review",
        submitted_at=NOW,
    )


def plan(
    *, stages: tuple[PlanStage, ...] | None = None,
    decisions: tuple[DecisionRequest, ...] = (),
) -> PlanEnvelope:
    return PlanEnvelope(
        feature_id="feature-1", summary="Build in stages",
        stages=stages or (
            PlanStage(stage_id="stage-1", title="Design", description="Design it"),
            PlanStage(stage_id="stage-2", title="Build", description="Build it",
                      dependencies=("stage-1",)),
        ),
        dependencies=(), risks=("Unknown integration",),
        decisions_needed=decisions,
    )


def coordinator(store: SQLiteEventStore) -> PlannerCoordinator:
    ids = (f"event-{number}" for number in range(100))
    return PlannerCoordinator(
        AgentResultParser(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
    )


def test_rejects_unknown_version_wrong_role_and_extra_payload_without_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        for result in (
            document(plan(), EXPECTED, schema_version=2),
            document(plan(), EXPECTED, role="architect"),
            document(plan(), EXPECTED, payload_extra={"shell_command": "rm -rf ."}),
        ):
            with pytest.raises(ValueError):
                service.accept(result, EXPECTED, request(), command_id="command-1", expected_sequence=-1)
        assert store.read_all() == ()


def test_rejects_duplicate_unknown_and_cyclic_stage_dependencies(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        bad_stages = (
            (
                PlanStage(stage_id="stage-1", title="One", description="One"),
                PlanStage(stage_id="stage-1", title="Two", description="Two"),
            ),
            (PlanStage(stage_id="stage-1", title="One", description="One",
                       dependencies=("missing",)),),
            (
                PlanStage(stage_id="stage-1", title="One", description="One",
                          dependencies=("stage-2",)),
                PlanStage(stage_id="stage-2", title="Two", description="Two",
                          dependencies=("stage-1",)),
            ),
        )
        for stages in bad_stages:
            with pytest.raises(ValueError):
                service.accept(
                    document(plan(stages=stages), EXPECTED), EXPECTED, request(),
                    command_id="command-1", expected_sequence=-1,
                )
        assert store.read_all() == ()


def test_decision_must_correlate_with_feature_and_planner_attempt(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        decision = DecisionRequest(
            decision_id="decision-1", source_attempt_id="other-attempt",
            feature_id="feature-1", issue_number=None, question="Choose",
            why_it_matters="Needed", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        with pytest.raises(ValueError):
            service.accept(
                document(plan(decisions=(decision,)), EXPECTED), EXPECTED,
                request(), command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_duplicate_decisions_and_failed_agent_result_do_not_change_state(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        decision = DecisionRequest(
            decision_id="decision-1", source_attempt_id="planner-1",
            feature_id="feature-1", issue_number=None, question="Choose",
            why_it_matters="Needed", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        with pytest.raises(ValueError):
            service.accept(
                document(plan(decisions=(decision, decision)), EXPECTED),
                EXPECTED, request(), command_id="command-1", expected_sequence=-1,
            )
        failed = json.loads(document(plan(), EXPECTED))
        failed["task_success"] = False
        with pytest.raises(ValueError):
            service.accept(
                json.dumps(failed), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_plan_feature_mismatch_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        mismatched = PlanEnvelope.from_dict({
            **plan().to_dict(), "feature_id": "other-feature"
        })
        with pytest.raises(ValueError):
            service.accept(
                document(mismatched, EXPECTED), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_valid_plan_records_one_controller_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        accepted = service.accept(
            document(plan(), EXPECTED), EXPECTED, request(),
            command_id="command-1", expected_sequence=-1,
        )
        assert accepted == plan()
        events = store.read_all()
        assert len(events) == 1
        assert events[0].event_type is EventType.PLAN_RECEIVED
        assert events[0].correlation_id == "request-1"
