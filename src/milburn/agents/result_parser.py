"""Strict parsing of semantic Codex JSONL events and typed task results."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import ClassVar

from milburn.domain import (
    ArchitecturePackage,
    CoderResult,
    DecisionRequest,
    PlanEnvelope,
    QAReport,
    RequestEnvelope,
    Role,
    RoleRouteProposal,
    UserDecision,
    VersionedModel,
)
from milburn.domain.errors import DomainError


RESULT_SCHEMA_VERSION = 1
RESULT_MODELS: dict[str, type[VersionedModel]] = {
    "architecture_package": ArchitecturePackage,
    "coder_result": CoderResult,
    "decision_request": DecisionRequest,
    "plan_envelope": PlanEnvelope,
    "qa_report": QAReport,
    "request_envelope": RequestEnvelope,
    "role_route_proposal": RoleRouteProposal,
    "user_decision": UserDecision,
}
KNOWN_RESULT_TYPES = frozenset(RESULT_MODELS)
ROLE_RESULT_TYPES: dict[Role, frozenset[str]] = {
    Role.COORDINATOR: frozenset({"request_envelope", "user_decision"}),
    Role.PLANNER: frozenset({"plan_envelope", "decision_request"}),
    Role.CLASSIFIER_ROUTER: frozenset({"role_route_proposal"}),
    Role.ARCHITECT: frozenset({"architecture_package", "decision_request"}),
    Role.CODER: frozenset({"coder_result", "decision_request"}),
    Role.TESTER: frozenset({"qa_report", "decision_request"}),
}


class AgentResultError(ValueError):
    """Base class for an invalid semantic agent result."""


class ResultDecodingError(AgentResultError):
    """Raised when JSONL or its final result is not a supported envelope."""


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
class ResultExpectation:
    """The immutable result contract fixed before an agent is launched."""

    correlation: ResultCorrelation
    result_type: str
    schema_version: int = RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != RESULT_SCHEMA_VERSION
        ):
            raise ResultDecodingError(
                f"unsupported result schema version {self.schema_version}"
            )
        if self.result_type not in KNOWN_RESULT_TYPES:
            raise ResultDecodingError(f"unknown result_type {self.result_type!r}")
        allowed = ROLE_RESULT_TYPES[self.correlation.role]
        if self.result_type not in allowed:
            raise ResultDecodingError(
                f"result_type {self.result_type!r} is not allowed for role "
                f"{self.correlation.role.value!r}"
            )


@dataclass(frozen=True, slots=True)
class ParsedAgentResult:
    """A typed task outcome kept separate from the Codex process exit."""

    schema_version: int
    correlation: ResultCorrelation
    task_success: bool
    result_type: str
    payload: VersionedModel


class AgentResultParser:
    """Extract the final semantic agent message and validate its typed payload."""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def parse_jsonl(
        self, document: str | bytes | bytearray, expected: ResultExpectation
    ) -> ParsedAgentResult:
        """Parse Codex ``exec --json`` events without inspecting terminal prose."""

        if isinstance(document, (bytes, bytearray)):
            try:
                text = bytes(document).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ResultDecodingError("Codex JSONL is not UTF-8") from error
        elif isinstance(document, str):
            text = document
        else:
            raise ResultDecodingError("Codex JSONL must be text or bytes")

        final_messages: list[str] = []
        turn_completed = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if turn_completed:
                raise ResultDecodingError(
                    "Codex JSONL contains an event after turn.completed"
                )
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ResultDecodingError(
                    f"Codex JSONL line {line_number} is not valid JSON: {error}"
                ) from error
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ResultDecodingError(
                    f"Codex JSONL line {line_number} is not a typed event"
                )
            event_type = event["type"]
            if event_type == "item.completed":
                item = event.get("item")
                if not isinstance(item, dict):
                    raise ResultDecodingError("item.completed is missing its item object")
                if item.get("type") == "agent_message":
                    message = item.get("text")
                    if not isinstance(message, str) or not message.strip():
                        raise ResultDecodingError(
                            "completed agent_message is missing semantic text"
                        )
                    final_messages.append(message)
            elif event_type == "turn.completed":
                turn_completed = True
            elif event_type in {"turn.failed", "error"}:
                raise ResultDecodingError(f"Codex reported semantic event {event_type}")

        if not turn_completed:
            raise ResultDecodingError("Codex JSONL has no turn.completed event")
        if len(final_messages) != 1:
            raise ResultDecodingError(
                "Codex JSONL must contain exactly one completed agent_message; "
                f"received {len(final_messages)}"
            )
        return self.parse(final_messages[0], expected)

    def parse(
        self, document: str | bytes | bytearray, expected: ResultExpectation
    ) -> ParsedAgentResult:
        """Parse the semantic agent-message text as one strict result object."""

        if not isinstance(expected, ResultExpectation):
            raise ResultCorrelationError("expected launch result contract is required")
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
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != expected.schema_version
        ):
            raise ResultDecodingError(
                f"result schema version mismatch: expected {expected.schema_version}, "
                f"received {version!r}"
            )

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
        if actual != expected.correlation:
            wanted = expected.correlation
            raise ResultCorrelationError(
                "result correlation mismatch: "
                f"expected {wanted.role.value}/{wanted.task_id}/{wanted.attempt_id}, "
                f"received {actual.role.value}/{actual.task_id}/{actual.attempt_id}"
            )

        task_success = payload["task_success"]
        if not isinstance(task_success, bool):
            raise ResultDecodingError("task_success must be a boolean")
        result_type = payload["result_type"]
        if result_type != expected.result_type:
            raise ResultDecodingError(
                f"result_type mismatch: expected {expected.result_type!r}, "
                f"received {result_type!r}"
            )
        result_payload = payload["payload"]
        if not isinstance(result_payload, dict):
            raise ResultDecodingError("payload must be a JSON object")
        try:
            typed_payload = RESULT_MODELS[result_type].from_dict(result_payload)
        except (DomainError, TypeError, ValueError) as error:
            raise ResultDecodingError(
                f"invalid {result_type} payload: {error}"
            ) from error
        payload_attempt_id = getattr(typed_payload, "attempt_id", None)
        if payload_attempt_id is not None and payload_attempt_id != actual.attempt_id:
            raise ResultCorrelationError(
                "typed payload attempt_id does not match result correlation"
            )

        return ParsedAgentResult(
            schema_version=version,
            correlation=actual,
            task_success=task_success,
            result_type=result_type,
            payload=typed_payload,
        )


def result_contract(expectation: ResultExpectation) -> str:
    """Return the exact wrapper contract included in a launch brief."""

    example = {
        "schema_version": expectation.schema_version,
        "role": expectation.correlation.role.value,
        "task_id": expectation.correlation.task_id,
        "attempt_id": expectation.correlation.attempt_id,
        "task_success": False,
        "result_type": expectation.result_type,
        "payload": {
            "schema_version": RESULT_MODELS[
                expectation.result_type
            ].CURRENT_SCHEMA_VERSION
        },
    }
    return (
        "Return exactly one JSON object matching this envelope. The payload must "
        f"match the typed {RESULT_MODELS[expectation.result_type].__name__} domain "
        "contract, including every required field. Do not change schema, result "
        "type, or correlation: "
        + json.dumps(example, sort_keys=True, separators=(",", ":"))
    )
