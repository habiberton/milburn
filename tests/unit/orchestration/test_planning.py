"""Planner result validation before controller state changes."""

from datetime import UTC, datetime
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from milburn.agents.result_parser import (
    AgentResultParser, ResultCorrelation, ResultExpectation,
)
from milburn.domain import (
    DecisionRequest, EventType, PlanEnvelope, PlanStage, RequestEnvelope, Role,
)
from milburn.orchestration.controller import Controller
from milburn.orchestration.planning import PlannerCoordinator
from milburn.persistence.sqlite_store import SQLiteEventStore
from milburn.persistence.errors import ConcurrencyError
from tests.fakes.role_results import document, expectation, seed_event


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


def coordinator(store: SQLiteEventStore, root: Path) -> PlannerCoordinator:
    seed_event(store, EventType.REQUEST_ACCEPTED, facts={
        "request": json.dumps(request().to_dict(), sort_keys=True),
        "request_id": request().request_id,
    })
    ids = (f"event-{number}" for number in range(100))
    return PlannerCoordinator(
        AgentResultParser(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
        store,
        repository_root=root,
    )


def test_rejects_unknown_version_wrong_role_and_extra_payload_without_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        for result in (
            document(plan(), EXPECTED, schema_version=2),
            document(plan(), EXPECTED, role="architect"),
            document(plan(), EXPECTED, payload_extra={"shell_command": "rm -rf ."}),
        ):
            with pytest.raises(ValueError):
                service.accept(result, EXPECTED, request(), command_id="command-1", expected_sequence=-1)
        assert len(store.read_all()) == 1


def test_rejects_duplicate_unknown_and_cyclic_stage_dependencies(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
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
        assert len(store.read_all()) == 1


def test_decision_must_correlate_with_feature_and_planner_attempt(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
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
        assert len(store.read_all()) == 1


def test_duplicate_decisions_and_failed_agent_result_do_not_change_state(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
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
        assert len(store.read_all()) == 1


def test_plan_feature_mismatch_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        mismatched = PlanEnvelope.from_dict({
            **plan().to_dict(), "feature_id": "other-feature"
        })
        with pytest.raises(ValueError):
            service.accept(
                document(mismatched, EXPECTED), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert len(store.read_all()) == 1


def test_valid_plan_records_one_controller_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        accepted = service.accept(
            document(plan(), EXPECTED), EXPECTED, request(),
            command_id="command-1", expected_sequence=-1,
        )
        assert accepted == plan()
        events = store.read_all()
        assert len(events) == 2
        assert events[-1].event_type is EventType.PLAN_RECEIVED
        assert events[-1].correlation_id == "request-1"
        facts = {fact.name: fact.value for fact in events[-1].facts}
        assert facts["prd_base_digest"] == "absent"
        assert facts["arch_base_digest"] == "absent"


def test_request_must_be_durably_accepted_before_plan(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        ids = (f"event-{number}" for number in range(100))
        service = PlannerCoordinator(
            AgentResultParser(),
            Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
            store,
            repository_root=tmp_path,
        )
        with pytest.raises(ValueError):
            service.accept(
                document(plan(), EXPECTED), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_completed_feature_rejects_late_plan_even_with_current_sequence(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        seed_event(store, EventType.FEATURE_COMPLETED)
        with pytest.raises(ValueError):
            service.accept(
                document(plan(), EXPECTED), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert len(store.read_all()) == 2


def test_planner_decision_id_collision_with_other_feature_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        seed_event(store, EventType.DECISION_REQUESTED,
                   feature_id="other-feature", facts={"decision_id": "decision-1",
                                                      "source_attempt_id": "other-attempt"})
        decision = DecisionRequest(
            decision_id="decision-1", source_attempt_id="planner-1",
            feature_id="feature-1", issue_number=None, question="Choose",
            why_it_matters="Needed", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        with pytest.raises(ValueError):
            service.accept(
                document(plan(decisions=(decision,)), EXPECTED), EXPECTED,
                request(), command_id="command-1", expected_sequence=-1,
            )
        assert len(store.read_stream("feature:feature-1")) == 1


def test_concurrent_features_cannot_record_same_decision_id(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        seed_event(store, EventType.REQUEST_ACCEPTED, feature_id="feature-1", facts={
            "request": json.dumps(request().to_dict(), sort_keys=True),
            "request_id": "request-1",
        })
        second_request = RequestEnvelope.from_dict({
            **request().to_dict(), "request_id": "request-2",
            "feature_id": "feature-2",
        })
        seed_event(store, EventType.REQUEST_ACCEPTED, feature_id="feature-2", facts={
            "request": json.dumps(second_request.to_dict(), sort_keys=True),
            "request_id": "request-2",
        })
        barrier = Barrier(2)

        class BarrierController(Controller):
            def handle(self, *args, **kwargs):
                barrier.wait(timeout=3)
                return super().handle(*args, **kwargs)

        def submit(feature: str, attempt: str, req: RequestEnvelope) -> bool:
            expected = ResultExpectation(
                correlation=ResultCorrelation(
                    role=Role.PLANNER, task_id=feature, attempt_id=attempt,
                ),
                result_type="plan_envelope",
            )
            decision = DecisionRequest(
                decision_id="shared-decision", source_attempt_id=attempt,
                feature_id=feature, issue_number=None, question="Choose",
                why_it_matters="Needed", options=("A", "B"),
                recommendation="A", blocking=True,
            )
            result = PlanEnvelope.from_dict({
                **plan(decisions=(decision,)).to_dict(), "feature_id": feature,
            })
            ids = (f"{feature}-event-{i}" for i in range(10))
            service = PlannerCoordinator(
                AgentResultParser(),
                BarrierController(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
                store, repository_root=tmp_path,
            )
            try:
                service.accept(
                    document(result, expected), expected, req,
                    command_id=f"command-{feature}", expected_sequence=-1,
                )
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(
                lambda args: submit(*args),
                (("feature-1", "planner-1", request()),
                 ("feature-2", "planner-2", second_request)),
            ))
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1
        assert sum(event.event_type is EventType.PLAN_RECEIVED
                   for event in store.read_all()) == 1


def test_feature_completion_between_validation_and_plan_append_is_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        seed_event(store, EventType.REQUEST_ACCEPTED, facts={
            "request": json.dumps(request().to_dict(), sort_keys=True),
            "request_id": "request-1",
        })

        class RacingController(Controller):
            def handle(self, *args, **kwargs):
                seed_event(store, EventType.FEATURE_COMPLETED)
                return super().handle(*args, **kwargs)

        ids = (f"event-{number}" for number in range(100))
        service = PlannerCoordinator(
            AgentResultParser(),
            RacingController(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
            store, repository_root=tmp_path,
        )
        with pytest.raises(ConcurrencyError):
            service.accept(
                document(plan(), EXPECTED), EXPECTED, request(),
                command_id="command-1", expected_sequence=-1,
            )
        assert all(event.event_type is not EventType.PLAN_RECEIVED
                   for event in store.read_all())
