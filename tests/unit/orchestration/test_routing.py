"""Classifier/Router proposals remain recommendations under controller policy."""

from datetime import UTC, datetime
import json

import pytest

from milburn.agents.result_parser import AgentResultParser
from milburn.domain import EventType, FeatureState, Role, RoleRouteProposal
from milburn.orchestration.controller import Controller
from milburn.orchestration.routing import RouteEscalation, RouterCoordinator
from milburn.orchestration.workflow import TransitionGuard
from milburn.persistence.sqlite_store import SQLiteEventStore
from milburn.persistence.errors import ConcurrencyError
from tests.fakes.role_results import document, expectation, seed_event


NOW = datetime(2026, 11, 4, tzinfo=UTC)
EXPECTED = expectation(Role.CLASSIFIER_ROUTER, "role_route_proposal")


def proposal(role: Role = Role.PLANNER) -> RoleRouteProposal:
    return RoleRouteProposal(
        request_id="request-1", current_state=FeatureState.RECEIVED,
        proposed_role=role, reason="Planning is next", confidence=0.9,
        decision_needed=False,
    )


def coordinator(store: SQLiteEventStore) -> RouterCoordinator:
    seed_event(store, EventType.REQUEST_ACCEPTED, facts={"request_id": "request-1"})
    ids = (f"event-{number}" for number in range(100))
    return RouterCoordinator(
        AgentResultParser(), TransitionGuard(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
        store,
    )


def accept(service: RouterCoordinator, raw: str):
    return service.accept(
        raw, EXPECTED, feature_id="feature-1", request_id="request-1",
        current_state=FeatureState.RECEIVED,
        command_id="command-1", expected_sequence=0,
    )


def test_unknown_role_version_and_arbitrary_command_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        unknown_role = json.loads(document(proposal(), EXPECTED))
        unknown_role["payload"]["proposed_role"] = "shell"
        for raw in (
            json.dumps(unknown_role),
            document(proposal(), EXPECTED, schema_version=2),
            document(proposal(), EXPECTED, payload_extra={"credentials": "secret"}),
            document(proposal(), EXPECTED, payload_extra={"command": "launch"}),
        ):
            with pytest.raises(ValueError):
                accept(service, raw)
        assert len(store.read_all()) == 1


def test_illegal_transition_and_stale_state_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        with pytest.raises(ValueError):
            accept(service, document(proposal(Role.TESTER), EXPECTED))
        with pytest.raises(ValueError):
            service.accept(
                document(proposal(), EXPECTED), EXPECTED,
                feature_id="feature-1", request_id="request-1",
                current_state=FeatureState.IMPLEMENTATION,
                command_id="command-1", expected_sequence=0,
            )
        assert len(store.read_all()) == 1


def test_valid_route_records_proposal_after_approval(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        approved = accept(coordinator(store), document(proposal(), EXPECTED))
        assert approved.role is Role.PLANNER
        events = store.read_all()
        assert len(events) == 2
        assert events[-1].event_type is EventType.ROLE_ROUTE_PROPOSED
        assert events[-1].correlation_id == "request-1"


def test_decision_needed_escalates_without_granting_route(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        model = RoleRouteProposal.from_dict({
            **proposal().to_dict(), "decision_needed": True, "confidence": 0.2
        })
        outcome = accept(coordinator(store), document(model, EXPECTED))
        assert isinstance(outcome, RouteEscalation)
        assert outcome.request_id == "request-1"
        assert len(store.read_all()) == 2


def test_route_uses_durable_state_and_ambiguous_illegal_role_escalates(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        seed_event(store, EventType.DECISION_REQUIRED)
        model = RoleRouteProposal.from_dict({
            **proposal(Role.TESTER).to_dict(),
            "current_state": "decision_needed",
            "decision_needed": True,
        })
        outcome = service.accept(
            document(model, EXPECTED), EXPECTED,
            feature_id="feature-1", request_id="request-1",
            current_state=FeatureState.DECISION_NEEDED,
            command_id="command-1", expected_sequence=1,
        )
        assert isinstance(outcome, RouteEscalation)
        assert store.read_all()[-1].event_type is EventType.ROLE_ROUTE_PROPOSED


def test_false_caller_state_cannot_approve_route(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        seed_event(store, EventType.FEATURE_COMPLETED)
        with pytest.raises(ValueError):
            service.accept(
                document(proposal(), EXPECTED), EXPECTED,
                feature_id="feature-1", request_id="request-1",
                current_state=FeatureState.RECEIVED,
                command_id="command-1", expected_sequence=1,
            )
        assert len(store.read_all()) == 2


def test_plan_between_route_validation_and_append_rejects_stale_route(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        seed_event(store, EventType.REQUEST_ACCEPTED, facts={"request_id": "request-1"})

        class RacingController(Controller):
            def handle(self, *args, **kwargs):
                seed_event(
                    store, EventType.PLAN_RECEIVED,
                    stream_override="role-results",
                    facts={"feature_id": "feature-1"},
                )
                return super().handle(*args, **kwargs)

        ids = (f"event-{number}" for number in range(100))
        service = RouterCoordinator(
            AgentResultParser(), TransitionGuard(),
            RacingController(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
            store,
        )
        with pytest.raises(ConcurrencyError):
            accept(service, document(proposal(), EXPECTED))
        assert all(event.event_type is not EventType.ROLE_ROUTE_PROPOSED
                   for event in store.read_all())
