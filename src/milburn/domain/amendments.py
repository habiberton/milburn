"""Versioned contracts for durable, user-authorized plan amendments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .base import (
    VersionedModel,
    require_enum,
    require_identifier,
    require_non_negative,
    require_text,
)
from .errors import InvalidEnvelopeError


class AmendmentCommandType(StrEnum):
    REQUEST = "request"
    ASSESS_IMPACT = "assess_impact"
    APPROVE = "approve"
    REJECT = "reject"
    APPLY = "apply"
    RESUME_DISPATCH = "resume_dispatch"


class AmendmentEventType(StrEnum):
    REQUESTED = "PlanAmendmentRequested"
    IMPACT_ASSESSED = "PlanAmendmentImpactAssessed"
    APPROVED = "PlanAmendmentApproved"
    REJECTED = "PlanAmendmentRejected"
    APPLIED = "PlanAmendmentApplied"
    DISPATCH_RESUMED = "AgentDispatchResumed"


class AmendmentStatus(StrEnum):
    PENDING = "pending"
    ASSESSED = "assessed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    EFFECTIVE = "effective"


class ImpactClassification(StrEnum):
    UNAFFECTED = "unaffected"
    NEEDS_STEERING = "needs_steering"
    MUST_PAUSE = "must_pause"
    MUST_STOP = "must_stop"


@dataclass(frozen=True, slots=True)
class ActiveAttempt(VersionedModel):
    """Durable ownership and generation evidence at assessment time."""

    task_id: str
    attempt_id: str
    owner: str
    generation: int

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.task_id, "task_id")
        require_identifier(self.attempt_id, "attempt_id")
        require_identifier(self.owner, "owner")
        require_non_negative(self.generation, "generation")


@dataclass(frozen=True, slots=True)
class ActiveWorkImpact(VersionedModel):
    """Explicit decision for one active attempt without implicit mutation."""

    attempt: ActiveAttempt
    classification: ImpactClassification
    instruction: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_enum(self.classification, ImpactClassification, "classification")
        require_text(self.instruction, "instruction")


@dataclass(frozen=True, slots=True)
class GitHubAmendmentEffect(VersionedModel):
    """Bounded GitHub evidence included in an approved amendment bundle."""

    effect_id: str
    description: str
    remote_reference: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.effect_id, "effect_id")
        require_text(self.description, "description")
        require_identifier(self.remote_reference, "remote_reference")


@dataclass(frozen=True, slots=True)
class AmendmentApproval(VersionedModel):
    """Immutable revisions and effects bound by user/controller approval."""

    approved_by: str
    expected_planning_revision: str
    specification_revision: str
    registry_revision: str
    github_effects: tuple[GitHubAmendmentEffect, ...] = ()

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_text(self.approved_by, "approved_by")
        require_identifier(
            self.expected_planning_revision, "expected_planning_revision"
        )
        require_identifier(self.specification_revision, "specification_revision")
        require_identifier(self.registry_revision, "registry_revision")
        effect_ids = [effect.effect_id for effect in self.github_effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise InvalidEnvelopeError("GitHub amendment effect IDs must be unique")


@dataclass(frozen=True, slots=True)
class PlanAmendmentCommand(VersionedModel):
    """One strictly versioned command in the amendment lifecycle."""

    command_id: str
    amendment_id: str
    command_type: AmendmentCommandType
    expected_version: int
    authority: str | None = None
    requested_change: str | None = None
    affected_tasks: tuple[str, ...] = ()
    impacts: tuple[ActiveWorkImpact, ...] = ()
    approval: AmendmentApproval | None = None
    rejection_reason: str | None = None
    planning_revision: str | None = None
    effective_revision: str | None = None
    remote_merge_revision: str | None = None
    primary_revision: str | None = None
    remote_effects_reconciled: bool = False

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.command_id, "command_id")
        require_identifier(self.amendment_id, "amendment_id")
        require_enum(self.command_type, AmendmentCommandType, "command_type")
        if self.expected_version < -1:
            raise InvalidEnvelopeError("expected_version must be at least -1")
        task_ids = list(self.affected_tasks)
        if len(task_ids) != len(set(task_ids)):
            raise InvalidEnvelopeError("affected task IDs must be unique")
        for task_id in task_ids:
            require_identifier(task_id, "affected_tasks")
        attempt_ids = [impact.attempt.attempt_id for impact in self.impacts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise InvalidEnvelopeError("impact attempt IDs must be unique")
        self._validate_command_shape()

    def _validate_command_shape(self) -> None:
        present = {
            name
            for name, value in {
                "authority": self.authority,
                "requested_change": self.requested_change,
                "affected_tasks": self.affected_tasks,
                "impacts": self.impacts,
                "approval": self.approval,
                "rejection_reason": self.rejection_reason,
                "planning_revision": self.planning_revision,
                "effective_revision": self.effective_revision,
                "remote_merge_revision": self.remote_merge_revision,
                "primary_revision": self.primary_revision,
                "remote_effects_reconciled": self.remote_effects_reconciled,
            }.items()
            if value not in (None, (), False)
        }
        allowed = {
            AmendmentCommandType.REQUEST: {
                "authority",
                "requested_change",
                "affected_tasks",
            },
            AmendmentCommandType.ASSESS_IMPACT: {"impacts"},
            AmendmentCommandType.APPROVE: {"approval"},
            AmendmentCommandType.REJECT: {"rejection_reason"},
            AmendmentCommandType.APPLY: {
                "planning_revision",
                "effective_revision",
                "remote_merge_revision",
                "primary_revision",
                "remote_effects_reconciled",
            },
            AmendmentCommandType.RESUME_DISPATCH: set(),
        }[self.command_type]
        unexpected = present - allowed
        if unexpected:
            raise InvalidEnvelopeError(
                f"{self.command_type.value} command has unrelated fields "
                f"{sorted(unexpected)}"
            )
        if self.command_type is AmendmentCommandType.REQUEST:
            if self.expected_version != -1:
                raise InvalidEnvelopeError("amendment request must expect version -1")
            if self.authority is None or self.requested_change is None:
                raise InvalidEnvelopeError(
                    "amendment request requires authority and requested_change"
                )
            require_text(self.authority, "authority")
            require_text(self.requested_change, "requested_change")
            if not self.affected_tasks:
                raise InvalidEnvelopeError("amendment request requires affected tasks")
            return
        if self.command_type is AmendmentCommandType.ASSESS_IMPACT:
            return
        if self.command_type is AmendmentCommandType.APPROVE:
            if self.approval is None:
                raise InvalidEnvelopeError("amendment approval requires approval evidence")
            return
        if self.command_type is AmendmentCommandType.REJECT:
            if self.rejection_reason is None:
                raise InvalidEnvelopeError("amendment rejection requires a reason")
            require_text(self.rejection_reason, "rejection_reason")
            return
        if self.command_type is AmendmentCommandType.APPLY:
            required = {
                "planning_revision": self.planning_revision,
                "effective_revision": self.effective_revision,
                "remote_merge_revision": self.remote_merge_revision,
                "primary_revision": self.primary_revision,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise InvalidEnvelopeError(
                    f"amendment application missing {', '.join(missing)}"
                )
            for name, value in required.items():
                require_identifier(value, name)  # type: ignore[arg-type]
            if not self.remote_effects_reconciled:
                raise InvalidEnvelopeError(
                    "amendment application requires reconciled remote effects"
                )


@dataclass(frozen=True, slots=True)
class PlanAmendmentEvent(VersionedModel):
    """Append-only fact produced from one amendment command."""

    event_id: str
    amendment_id: str
    event_type: AmendmentEventType
    sequence: int
    occurred_at: datetime
    command: PlanAmendmentCommand

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.event_id, "event_id")
        require_identifier(self.amendment_id, "amendment_id")
        require_enum(self.event_type, AmendmentEventType, "event_type")
        require_non_negative(self.sequence, "sequence")
        if self.command.amendment_id != self.amendment_id:
            raise InvalidEnvelopeError("event and command amendment IDs must match")
        if self.command.expected_version + 1 != self.sequence:
            raise InvalidEnvelopeError("event sequence must follow the expected version")
        expected_event_type = EVENT_FOR_COMMAND[self.command.command_type]
        if self.event_type is not expected_event_type:
            raise InvalidEnvelopeError(
                f"{self.command.command_type.value} command requires "
                f"{expected_event_type.value}"
            )


EVENT_FOR_COMMAND = {
    AmendmentCommandType.REQUEST: AmendmentEventType.REQUESTED,
    AmendmentCommandType.ASSESS_IMPACT: AmendmentEventType.IMPACT_ASSESSED,
    AmendmentCommandType.APPROVE: AmendmentEventType.APPROVED,
    AmendmentCommandType.REJECT: AmendmentEventType.REJECTED,
    AmendmentCommandType.APPLY: AmendmentEventType.APPLIED,
    AmendmentCommandType.RESUME_DISPATCH: AmendmentEventType.DISPATCH_RESUMED,
}
