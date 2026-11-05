"""Shared validation and controller recording for bounded role results."""

from __future__ import annotations

import json
from typing import Iterable, Mapping

from milburn.agents.result_parser import AgentResultParser, ResultExpectation
from milburn.domain import (
    CommandEnvelope, CommandType, DecisionRequest, EventFact, EventType,
    Role, VersionedModel,
)

from .controller import Controller


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
        facts=(
            EventFact(name="attempt_id", value=expectation.correlation.attempt_id),
            EventFact(name="result_type", value=expectation.result_type),
            EventFact(name="result", value=json.dumps(payload.to_dict(), sort_keys=True)),
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
) -> None:
    ids = [item.decision_id for item in decisions]
    if len(set(ids)) != len(ids):
        raise ValueError("decision IDs must be unique")
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
