"""Shared validation and controller recording for bounded role results."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable, Mapping, Protocol

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import (
    CommandEnvelope, CommandType, DecisionRequest, DomainEvent, EventFact, EventType,
    FeatureState, PlanEnvelope, RequestEnvelope, Role, VersionedModel,
)

from .controller import Controller


class RoleEventReader(Protocol):
    def read_stream(
        self, stream: str, *, after_sequence: int = -1
    ) -> tuple[DomainEvent, ...]: ...

    def read_all(self, *, after_position: int = 0) -> tuple[DomainEvent, ...]: ...


ROLE_RESULT_STREAM = "role-results"


def feature_events(reader: RoleEventReader, feature_id: str) -> tuple[DomainEvent, ...]:
    """Read feature events and serialized role results in durable append order."""
    return tuple(
        event for event in reader.read_all()
        if event.stream == f"feature:{feature_id}"
        or (
            event.stream == ROLE_RESULT_STREAM
            and any(fact.name == "feature_id" and fact.value == feature_id
                    for fact in event.facts)
        )
    )


def stream_sequence(events: tuple[DomainEvent, ...], stream: str) -> int:
    """Sequence observed with the validation snapshot, or -1 when absent."""
    return max(
        (event.sequence for event in events if event.stream == stream),
        default=-1,
    )


def artifact_digest(path: Path) -> str:
    """Return an exact baseline marker for a root spec file."""
    if not path.is_file():
        return "absent"
    return sha256(path.read_bytes()).hexdigest()


def durable_feature_state(events: tuple[DomainEvent, ...]) -> FeatureState | None:
    """Rebuild the feature phase from authoritative lifecycle events."""
    state: FeatureState | None = None
    phases = {
        EventType.REQUEST_ACCEPTED: FeatureState.RECEIVED,
        EventType.PLAN_RECEIVED: FeatureState.ARCHITECTURE,
        EventType.ARCHITECTURE_PACKAGE_RECEIVED: FeatureState.ISSUES_READY,
        EventType.GITHUB_ISSUE_READY: FeatureState.ISSUES_READY,
        EventType.CODER_ATTEMPT_STARTED: FeatureState.IMPLEMENTATION,
        EventType.TESTING_REQUESTED: FeatureState.TESTING,
        EventType.DECISION_REQUIRED: FeatureState.DECISION_NEEDED,
        EventType.FEATURE_COMPLETED: FeatureState.COMPLETED,
    }
    for recorded in events:
        state = phases.get(recorded.event_type, state)
        facts = {fact.name: fact.value for fact in recorded.facts}
        if "feature_state" in facts:
            state = FeatureState(facts["feature_state"])
    return state


def require_accepted_request(
    events: tuple[DomainEvent, ...], request: RequestEnvelope
) -> None:
    accepted = [event for event in events if event.event_type is EventType.REQUEST_ACCEPTED]
    if len(accepted) != 1:
        raise ValueError("feature must have exactly one accepted request")
    facts = {fact.name: fact.value for fact in accepted[0].facts}
    try:
        durable = RequestEnvelope.from_dict(json.loads(facts["request"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("accepted request lacks a valid durable envelope") from error
    if durable != request or facts.get("request_id") != request.request_id:
        raise ValueError("Planner input does not match the accepted request")


def require_accepted_plan(
    events: tuple[DomainEvent, ...], plan: PlanEnvelope
) -> DomainEvent:
    accepted = [event for event in events if event.event_type is EventType.PLAN_RECEIVED]
    if len(accepted) != 1:
        raise ValueError("feature must have exactly one accepted plan")
    facts = {fact.name: fact.value for fact in accepted[0].facts}
    try:
        durable = PlanEnvelope.from_dict(json.loads(facts["result"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("accepted plan lacks a valid durable envelope") from error
    if durable != plan:
        raise ValueError("Architect input does not match the accepted plan")
    return accepted[0]


def require_changed_specs(
    plan_event: DomainEvent, root: Path,
) -> None:
    facts = {fact.name: fact.value for fact in plan_event.facts}
    for name, field in (("PRD.md", "prd_base_digest"),
                        ("ARCH.md", "arch_base_digest")):
        baseline = facts.get(field)
        if baseline is None or not (
            baseline == "absent" or re.fullmatch(r"[0-9a-f]{64}", baseline)
        ):
            raise ValueError("accepted plan lacks valid spec baselines")
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"{name} must exist with content before acceptance")
        if artifact_digest(path) == baseline:
            raise ValueError(f"{name} has not changed since the accepted plan")


def used_decision_ids(reader: RoleEventReader) -> frozenset[str]:
    """Collect IDs from all feature results and explicit decision events."""
    ids: set[str] = set()
    for recorded in reader.read_all():
        facts = {fact.name: fact.value for fact in recorded.facts}
        if "decision_id" in facts:
            ids.add(facts["decision_id"])
        if recorded.event_type not in {
            EventType.PLAN_RECEIVED, EventType.ARCHITECTURE_PACKAGE_RECEIVED
        }:
            continue
        if "result" not in facts:
            continue
        try:
            payload = json.loads(facts["result"])
            rows = payload.get("decisions_needed", payload.get("open_decisions", ()))
            ids.update(row["decision_id"] for row in rows)
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError("durable role result has malformed decision IDs") from error
    return frozenset(ids)


def parse_role_result(
    parser: AgentResultParser,
    document: str | bytes | bytearray,
    expectation: ResultExpectation,
    *,
    role: Role,
    result_type: str,
) -> VersionedModel:
    """Reject a forged or failed role result before policy or event effects."""
    if not isinstance(expectation, ResultExpectation):
        raise ValueError("a fixed result expectation is required")
    if expectation.correlation.role is not role or expectation.result_type != result_type:
        raise ValueError("result expectation has the wrong role or type")
    parsed = parser.parse(document, expectation)
    if not parsed.task_success:
        raise ValueError("agent reported task failure")
    return parsed.payload


def record_result(
    controller: Controller,
    payload: VersionedModel,
    expectation: ResultExpectation,
    *,
    command_type: CommandType,
    event_type: EventType,
    feature_id: str,
    correlation_id: str,
    command_id: str,
    expected_sequence: int,
    stream: str | None = None,
    extra_facts: tuple[EventFact, ...] = (),
    guard_sequences: Mapping[str, int] | None = None,
) -> None:
    """Use the controller's role and intent policy after all result checks."""
    command = CommandEnvelope(
        command_id=command_id,
        command_type=command_type,
        actor_role=expectation.correlation.role,
        feature_id=feature_id,
        issue_number=None,
        attempt_id=expectation.correlation.attempt_id,
        correlation_id=correlation_id,
    )
    controller.handle(
        command,
        intent_type=event_type,
        expected_sequence=expected_sequence,
        stream=stream,
        guard_sequences=guard_sequences,
        facts=(
            EventFact(name="feature_id", value=feature_id),
            EventFact(name="attempt_id", value=expectation.correlation.attempt_id),
            EventFact(name="result_type", value=expectation.result_type),
            EventFact(name="result", value=json.dumps(payload.to_dict(), sort_keys=True)),
            *extra_facts,
        ),
    )


def validate_graph(
    keys: Iterable[str],
    dependencies: Mapping[str, tuple[str, ...]],
    *,
    external: Iterable[str] = (),
) -> None:
    """Reject duplicate, unknown, self, and cyclic local dependencies."""
    ordered = tuple(keys)
    local = set(ordered)
    if len(local) != len(ordered):
        raise ValueError("graph keys must be unique")
    known = local | set(external)
    if set(dependencies) != local:
        raise ValueError("every graph key must have one dependency entry")
    for key, refs in dependencies.items():
        if len(set(refs)) != len(refs):
            raise ValueError(f"{key} has duplicate dependencies")
        if key in refs or any(ref not in known for ref in refs):
            raise ValueError(f"{key} has a self or unknown dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("dependency graph contains a cycle")
        if key in visited:
            return
        visiting.add(key)
        for ref in dependencies[key]:
            if ref in local:
                visit(ref)
        visiting.remove(key)
        visited.add(key)

    for key in ordered:
        visit(key)


def validate_decisions(
    decisions: tuple[DecisionRequest, ...],
    *,
    feature_id: str,
    attempt_id: str,
    used_ids: frozenset[str] = frozenset(),
) -> None:
    ids = [item.decision_id for item in decisions]
    if len(set(ids)) != len(ids):
        raise ValueError("decision IDs must be unique")
    if any(identifier in used_ids for identifier in ids):
        raise ValueError("decision ID was already used in this workflow")
    for item in decisions:
        if (
            item.feature_id != feature_id
            or item.source_attempt_id != attempt_id
            or item.issue_number is not None
        ):
            raise ValueError("decision must correlate with this feature and role attempt")
        normalized = [option.strip().casefold() for option in item.options]
        if len(set(normalized)) != len(normalized):
            raise ValueError("decision options must be unambiguous")
        if item.recommendation is not None and item.recommendation.strip().casefold() not in normalized:
            raise ValueError("decision recommendation must be an offered option")
