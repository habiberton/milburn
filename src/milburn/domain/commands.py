"""Controller command contracts; commands request effects but record no facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .base import VersionedModel, require_enum, require_identifier
from .states import Role


class CommandType(StrEnum):
    ACCEPT_REQUEST = "accept_request"
    SUBMIT_INTAKE_PROPOSAL = "submit_intake_proposal"
    REQUEST_STATUS_SUMMARY = "request_status_summary"
    PROPOSE_ROLE_ROUTE = "propose_role_route"
    SUBMIT_PLAN = "submit_plan"
    SUBMIT_ARCHITECTURE = "submit_architecture"
    SUBMIT_ISSUE_DRAFTS = "submit_issue_drafts"
    REQUEST_AGENT_LAUNCH = "request_agent_launch"
    REPORT_PROGRESS = "report_progress"
    REPORT_CODER_CHECKPOINT = "report_coder_checkpoint"
    SUBMIT_CANDIDATE = "submit_candidate"
    REQUEST_TESTING = "request_testing"
    SUBMIT_QA_REPORT = "submit_qa_report"
    REQUEST_DECISION = "request_decision"
    ANSWER_DECISION = "answer_decision"
    QUEUE_STEERING = "queue_steering"
    ACKNOWLEDGE_STEERING = "acknowledge_steering"
    INTERRUPT_AGENT = "interrupt_agent"
    TERMINATE_AGENT = "terminate_agent"
    RESUME_AGENT = "resume_agent"
    REPLACE_AGENT = "replace_agent"
    RETIRE_AGENT = "retire_agent"


@dataclass(frozen=True, slots=True)
class CommandArgument(VersionedModel):
    name: str
    value: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.name, "name")
        if not isinstance(self.value, str):
            from .errors import InvalidEnvelopeError

            raise InvalidEnvelopeError("value must be a string")


@dataclass(frozen=True, slots=True)
class CommandEnvelope(VersionedModel):
    command_id: str
    command_type: CommandType
    actor_role: Role
    feature_id: str
    issue_number: int | None
    attempt_id: str | None
    correlation_id: str
    arguments: tuple[CommandArgument, ...] = ()

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.command_id, "command_id")
        require_enum(self.command_type, CommandType, "command_type")
        require_enum(self.actor_role, Role, "actor_role")
        require_identifier(self.feature_id, "feature_id")
        require_identifier(self.correlation_id, "correlation_id")
        if self.issue_number is not None:
            from .base import require_non_negative

            require_non_negative(self.issue_number, "issue_number")
        if self.attempt_id is not None:
            require_identifier(self.attempt_id, "attempt_id")
        names = [argument.name for argument in self.arguments]
        if len(names) != len(set(names)):
            from .errors import InvalidEnvelopeError

            raise InvalidEnvelopeError("command argument names must be unique")
