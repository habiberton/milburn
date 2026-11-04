"""Strict parsing and correlation of semantic Codex task results."""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping

from milburn.domain import Role


RESULT_SCHEMA_VERSION = 1
KNOWN_RESULT_TYPES = frozenset(
    {
        "architecture_package",
        "coder_result",
        "coordinator_result",
        "decision_request",
        "plan_envelope",
        "qa_report",
        "role_route_proposal",
    }
)


class AgentResultError(ValueError):
    """Base class for an invalid semantic agent result."""


class ResultDecodingError(AgentResultError):
    """Raised when the result is not a supported strict JSON envelope."""


class ResultCorrelationError(AgentResultError):
    """Raised when a result does not belong to the expected attempt."""


@dataclass(frozen=True, slots=True)
class ResultCorrelation:
    role: Role
    task_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise ResultCorrelationError("role must be a known Milburn role")
        for field_name in ("task_id", "attempt_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ResultCorrelationError(
                    f"{field_name} must be a non-empty identifier"
                )
            if any(character.isspace() for character in value):
                raise ResultCorrelationError(
                    f"{field_name} must not contain whitespace"
                )


@dataclass(frozen=True, slots=True)
class ParsedAgentResult:
    """A task outcome kept separate from the Codex process exit."""

    schema_version: int
    correlation: ResultCorrelation
    task_success: bool
    result_type: str
    payload: Mapping[str, Any]


class AgentResultParser:
    """Accept only known result versions, types, fields, and correlation."""

    _FIELDS = frozenset(
        {
            "schema_version",
            "role",
            "task_id",
            "attempt_id",
            "task_success",
            "result_type",
            "payload",
        }
    )

    def __init__(
        self,
        *,
        supported_versions: frozenset[int] = frozenset({RESULT_SCHEMA_VERSION}),
        known_result_types: frozenset[str] = KNOWN_RESULT_TYPES,
    ) -> None:
        if not supported_versions:
            raise ValueError("supported_versions must not be empty")
        if not known_result_types:
            raise ValueError("known_result_types must not be empty")
        self._supported_versions = supported_versions
        self._known_result_types = known_result_types

    def parse(
        self, document: str | bytes | bytearray, expected: ResultCorrelation
    ) -> ParsedAgentResult:
        if not isinstance(expected, ResultCorrelation):
            raise ResultCorrelationError("expected correlation is required")
        try:
            payload = json.loads(document)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as error:
            raise ResultDecodingError(f"result is not valid JSON: {error}") from error
        if not isinstance(payload, dict):
            raise ResultDecodingError("result must be a JSON object")

        fields = frozenset(payload)
        if fields != self._FIELDS:
            missing = sorted(self._FIELDS - fields)
            unknown = sorted(fields - self._FIELDS)
            details = []
            if missing:
                details.append(f"missing {missing}")
            if unknown:
                details.append(f"unknown {unknown}")
            raise ResultDecodingError("invalid result fields: " + ", ".join(details))

        version = payload["schema_version"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise ResultDecodingError("schema_version must be an integer")
        if version not in self._supported_versions:
            raise ResultDecodingError(f"unsupported result schema version {version}")

        try:
            role = Role(payload["role"])
        except (TypeError, ValueError) as error:
            raise ResultDecodingError(f"unknown result role {payload['role']!r}") from error
        try:
            actual = ResultCorrelation(
                role=role,
                task_id=payload["task_id"],
                attempt_id=payload["attempt_id"],
            )
        except ResultCorrelationError as error:
            raise ResultDecodingError(f"invalid result correlation: {error}") from error
        if actual != expected:
            raise ResultCorrelationError(
                "result correlation mismatch: "
                f"expected {expected.role.value}/{expected.task_id}/{expected.attempt_id}, "
                f"received {actual.role.value}/{actual.task_id}/{actual.attempt_id}"
            )

        task_success = payload["task_success"]
        if not isinstance(task_success, bool):
            raise ResultDecodingError("task_success must be a boolean")
        result_type = payload["result_type"]
        if not isinstance(result_type, str) or result_type not in self._known_result_types:
            raise ResultDecodingError(f"unknown result_type {result_type!r}")
        result_payload = payload["payload"]
        if not isinstance(result_payload, dict):
            raise ResultDecodingError("payload must be a JSON object")
        _validate_json(result_payload)

        return ParsedAgentResult(
            schema_version=version,
            correlation=actual,
            task_success=task_success,
            result_type=result_type,
            payload=_freeze(result_payload),
        )


def result_contract(correlation: ResultCorrelation, result_type: str) -> str:
    """Return the exact single-object contract included in a launch brief."""

    if result_type not in KNOWN_RESULT_TYPES:
        raise ResultDecodingError(f"unknown result_type {result_type!r}")
    example = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "role": correlation.role.value,
        "task_id": correlation.task_id,
        "attempt_id": correlation.attempt_id,
        "task_success": False,
        "result_type": result_type,
        "payload": {},
    }
    return (
        "Return exactly one JSON object matching this envelope; replace payload and "
        "task_success with the observed task result, and do not change correlation: "
        + json.dumps(example, sort_keys=True, separators=(",", ":"))
    )


def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ResultDecodingError("payload object keys must be strings")
        for item in value.values():
            _validate_json(item)
        return
    raise ResultDecodingError("payload contains a non-JSON value")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
