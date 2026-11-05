"""Architect package validation and controller-owned acceptance."""

from datetime import UTC, datetime
import json
from hashlib import sha256
from pathlib import Path

import pytest

from milburn.agents.result_parser import AgentResultParser
from milburn.domain import (
    ArchitecturePackage, DecisionRequest, EventType, IssueDraft, PlanEnvelope, PlanStage, Role,
)
from milburn.orchestration.architecture import ArchitectCoordinator
from milburn.orchestration.controller import Controller
from milburn.persistence.sqlite_store import SQLiteEventStore
from tests.fakes.role_results import document, expectation, seed_event


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


def coordinator(store: SQLiteEventStore, root: Path) -> ArchitectCoordinator:
    seed_event(store, EventType.REQUEST_ACCEPTED, facts={"request_id": "request-1"})
    (root / "PRD.md").write_text("# Old product\n")
    (root / "ARCH.md").write_text("# Old architecture\n")
    seed_event(store, EventType.PLAN_RECEIVED, facts={
        "result": json.dumps(plan().to_dict(), sort_keys=True),
        "prd_base_digest": sha256((root / "PRD.md").read_bytes()).hexdigest(),
        "arch_base_digest": sha256((root / "ARCH.md").read_bytes()).hexdigest(),
    })
    (root / "PRD.md").write_text("# Product\n")
    (root / "ARCH.md").write_text("# Architecture\n")
    ids = (f"event-{number}" for number in range(100))
    return ArchitectCoordinator(
        AgentResultParser(),
        Controller(store, clock=lambda: NOW, event_ids=lambda: next(ids)),
        store,
        repository_root=root,
    )


def accept(service: ArchitectCoordinator, item: ArchitecturePackage):
    return service.accept(
        document(item, EXPECTED), EXPECTED, plan(), known_task_keys=(),
        command_id="command-1", expected_sequence=-1,
    )


def test_unknown_version_role_and_extra_payload_rejected_before_event(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
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
        assert len(store.read_all()) == 2


def test_rejects_missing_specs_duplicate_unknown_and_cyclic_drafts(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
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
        assert len(store.read_all()) == 2


def test_valid_architecture_records_one_event_with_dependency_aware_drafts(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        approved = accept(service, package())
        assert tuple(draft.task_key for draft in approved.issue_drafts) == ("task-1", "task-2")
        events = store.read_all()
        assert len(events) == 3
        assert events[-1].event_type is EventType.ARCHITECTURE_PACKAGE_RECEIVED


def test_existing_task_dependency_allowed_but_key_collision_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        package_with_existing = package(drafts=(draft("task-1", ("existing-1",)),))
        accepted = service.accept(
            document(package_with_existing, EXPECTED), EXPECTED, plan(),
            known_task_keys=("existing-1",), command_id="command-1",
            expected_sequence=-1,
        )
        assert accepted.issue_drafts[0].dependencies == ("existing-1",)

    with SQLiteEventStore(tmp_path / "other.db") as store:
        service = coordinator(store, tmp_path)
        with pytest.raises(ValueError):
            service.accept(
                document(package(drafts=(draft("existing-1"),)), EXPECTED),
                EXPECTED, plan(), known_task_keys=("existing-1",),
                command_id="command-1", expected_sequence=-1,
            )
        assert len(store.read_all()) == 2


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
            accept(coordinator(store, tmp_path), item)
        assert len(store.read_all()) == 2


def test_artifacts_must_exist_and_drafts_link_to_them(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        (tmp_path / "PRD.md").unlink()
        with pytest.raises(ValueError):
            accept(service, package())
        (tmp_path / "PRD.md").write_text("# Product\n")
        unrelated = IssueDraft.from_dict({
            **draft("task-1").to_dict(), "spec_links": ["README.md"]
        })
        with pytest.raises(ValueError):
            accept(service, package(drafts=(unrelated,)))
        assert len(store.read_all()) == 2


def test_preexisting_specs_unrelated_to_current_plan_are_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        (tmp_path / "PRD.md").write_text("# Old product\n")
        (tmp_path / "ARCH.md").write_text("# Old architecture\n")
        with pytest.raises(ValueError):
            accept(service, package())
        (tmp_path / "PRD.md").write_text("# Product\n")
        with pytest.raises(ValueError):
            accept(service, package())
        assert len(store.read_all()) == 2


def test_symlinked_spec_cannot_masquerade_as_root_artifact(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "PRD.md").write_text("# Other product\n")
        (tmp_path / "PRD.md").unlink()
        (tmp_path / "PRD.md").symlink_to(nested / "PRD.md")
        with pytest.raises(ValueError):
            accept(service, package())
        assert len(store.read_all()) == 2


def test_architecture_requires_durable_matching_plan(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        changed = PlanEnvelope.from_dict({
            **plan().to_dict(), "summary": "Unapproved plan"
        })
        with pytest.raises(ValueError):
            service.accept(
                document(package(), EXPECTED), EXPECTED, changed,
                known_task_keys=(), command_id="command-1", expected_sequence=-1,
            )
        assert len(store.read_all()) == 2


def test_decision_id_collision_with_prior_event_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = coordinator(store, tmp_path)
        seed_event(store, EventType.DECISION_REQUESTED,
                   feature_id="other-feature", facts={"decision_id": "decision-1",
                                                      "source_attempt_id": "other-attempt"})
        decision = DecisionRequest(
            decision_id="decision-1", source_attempt_id="architect-1",
            feature_id="feature-1", issue_number=None, question="Choose",
            why_it_matters="Needed", options=("A", "B"),
            recommendation="A", blocking=True,
        )
        item = ArchitecturePackage.from_dict({
            **package().to_dict(), "open_decisions": [decision.to_dict()]
        })
        with pytest.raises(ValueError):
            accept(service, item)
        assert len(store.read_stream("feature:feature-1")) == 2
