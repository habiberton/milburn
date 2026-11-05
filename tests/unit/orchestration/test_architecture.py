"""Architect package validation and controller-owned acceptance."""

from datetime import UTC, datetime

import pytest

from milburn.agents.result_parser import AgentResultParser
from milburn.domain import (
    ArchitecturePackage, DecisionRequest, EventType, IssueDraft, PlanEnvelope, PlanStage, Role,
)
from milburn.orchestration.architecture import ArchitectCoordinator
from milburn.orchestration.controller import Controller
from milburn.persistence.sqlite_store import SQLiteEventStore
from tests.fakes.role_results import document, expectation


NOW = datetime(2026, 11, 4, tzinfo=UTC)
EXPECTED = expectation(Role.ARCHITECT, "architecture_package")


def plan() -> PlanEnvelope:
    return PlanEnvelope(
        feature_id="feature-1", summary="Build it",
        stages=(PlanStage(stage_id="stage-1", title="Build", description="Build it"),),
        dependencies=(), risks=(), decisions_needed=(),
    )


def draft(key: str, dependencies: tuple[str, ...] = ()) -> IssueDraft:
    return IssueDraft(
        task_key=key, title=f"Build {key}", objective=f"Implement {key}",
        spec_links=("PRD.md", "ARCH.md"), acceptance_criteria=("It works",),
        dependencies=dependencies, test_instructions=("Run tests",),
        expected_artifacts=(f"src/{key}.py",), risks=(), non_goals=(),
    )


def package(
    *, drafts: tuple[IssueDraft, ...] | None = None,
    prd: str = "PRD.md", arch: str = "ARCH.md",
) -> ArchitecturePackage:
    return ArchitecturePackage(
        feature_id="feature-1", prd_artifact=prd, arch_artifact=arch,
        issue_drafts=drafts or (draft("task-1"), draft("task-2", ("task-1",))),
        open_decisions=(),
    )


def coordinator(store: SQLiteEventStore) -> ArchitectCoordinator:
    ids = (f"event-{number}" for number in range(100))
    return ArchitectCoordinator(
        AgentResultParser(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
    )


def accept(service: ArchitectCoordinator, item: ArchitecturePackage):
    return service.accept(
        document(item, EXPECTED), EXPECTED, plan(), known_task_keys=(),
        command_id="command-1", expected_sequence=-1,
    )


def test_unknown_version_role_and_extra_payload_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        for raw in (
            document(package(), EXPECTED, schema_version=2),
            document(package(), EXPECTED, role="planner"),
            document(package(), EXPECTED, payload_extra={"github_token": "secret"}),
        ):
            with pytest.raises(ValueError):
                service.accept(
                    raw, EXPECTED, plan(), known_task_keys=(),
                    command_id="command-1", expected_sequence=-1,
                )
        assert store.read_all() == ()


def test_rejects_missing_specs_duplicate_unknown_and_cyclic_drafts(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        invalid = (
            package(prd="other.md"),
            package(arch="../ARCH.md"),
            package(drafts=(draft("task-1"), draft("task-1"))),
            package(drafts=(draft("task-1", ("missing",)),)),
            package(drafts=(draft("task-1", ("task-2",)), draft("task-2", ("task-1",)))),
        )
        for item in invalid:
            with pytest.raises(ValueError):
                accept(service, item)
        assert store.read_all() == ()


def test_valid_architecture_records_one_event_with_dependency_aware_drafts(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        approved = accept(service, package())
        assert tuple(draft.task_key for draft in approved.issue_drafts) == ("task-1", "task-2")
        events = store.read_all()
        assert len(events) == 1
        assert events[0].event_type is EventType.ARCHITECTURE_PACKAGE_RECEIVED


def test_existing_task_dependency_allowed_but_key_collision_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store)
        package_with_existing = package(drafts=(draft("task-1", ("existing-1",)),))
        accepted = service.accept(
            document(package_with_existing, EXPECTED), EXPECTED, plan(),
            known_task_keys=("existing-1",), command_id="command-1",
            expected_sequence=-1,
        )
        assert accepted.issue_drafts[0].dependencies == ("existing-1",)

    with SQLiteEventStore(tmp_path / "other.db") as store:
        service = coordinator(store)
        with pytest.raises(ValueError):
            service.accept(
                document(package(drafts=(draft("existing-1"),)), EXPECTED),
                EXPECTED, plan(), known_task_keys=("existing-1",),
                command_id="command-1", expected_sequence=-1,
            )
        assert store.read_all() == ()


def test_open_decision_from_another_attempt_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        decision = DecisionRequest(
            decision_id="decision-1", source_attempt_id="planner-1",
            feature_id="feature-1", issue_number=None,
            question="Choose", why_it_matters="Needed", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        item = ArchitecturePackage.from_dict({
            **package().to_dict(), "open_decisions": [decision.to_dict()]
        })
        with pytest.raises(ValueError):
            accept(coordinator(store), item)
        assert store.read_all() == ()
