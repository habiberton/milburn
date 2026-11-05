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
from tests.fakes.role_results import document, expectation


NOW = datetime(2026, 11, 4, tzinfo=UTC)
EXPECTED = expectation(Role.CLASSIFIER_ROUTER, "role_route_proposal")


def proposal(role: Role = Role.PLANNER) -> RoleRouteProposal:
    return RoleRouteProposal(
        request_id="request-1", current_state=FeatureState.RECEIVED,
        proposed_role=role, reason="Planning is next", confidence=0.9,
        decision_needed=False,
    )


def coordinator(store: SQLiteEventStore) -> RouterCoordinator:
    ids = (f"event-{number}" for number in range(100))
    return RouterCoordinator(
        AgentResultParser(), TransitionGuard(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
    )


def accept(service: RouterCoordinator, raw: str):
    return service.accept(
        raw, EXPECTED, feature_id="feature-1", request_id="request-1",
        current_state=FeatureState.RECEIVED,
        command_id="command-1", expected_sequence=-1,
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
        assert store.read_all() == ()


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
                command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_valid_route_records_proposal_after_approval(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        approved = accept(coordinator(store), document(proposal(), EXPECTED))
        assert approved.role is Role.PLANNER
        events = store.read_all()
        assert len(events) == 1
        assert events[0].event_type is EventType.ROLE_ROUTE_PROPOSED
        assert events[0].correlation_id == "request-1"


def test_decision_needed_escalates_without_granting_route(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        model = RoleRouteProposal.from_dict({
            **proposal().to_dict(), "decision_needed": True, "confidence": 0.2
        })
        outcome = accept(coordinator(store), document(model, EXPECTED))
        assert isinstance(outcome, RouteEscalation)
        assert outcome.request_id == "request-1"
        assert len(store.read_all()) == 1
