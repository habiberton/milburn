"""Deterministic semantic result documents for role coordinator tests."""

from __future__ import annotations

import json

from milburn.agents.result_parser import ResultCorrelation, ResultExpectation
from milburn.domain import Role, VersionedModel


def expectation(role: Role, result_type: str) -> ResultExpectation:
    return ResultExpectation(
        correlation=ResultCorrelation(
            role=role, task_id="feature-1", attempt_id=f"{role.value}-1"
        ),
        result_type=result_type,
    )


def document(
    model: VersionedModel, expected: ResultExpectation, *,
    schema_version: int = 1, role: str | None = None,
    payload_extra: dict[str, object] | None = None,
) -> str:
    payload = model.to_dict()
    payload.update(payload_extra or {})
    return json.dumps({
        "schema_version": schema_version,
        "role": role or expected.correlation.role.value,
        "task_id": expected.correlation.task_id,
        "attempt_id": expected.correlation.attempt_id,
        "task_success": True,
        "result_type": expected.result_type,
        "payload": payload,
    })
