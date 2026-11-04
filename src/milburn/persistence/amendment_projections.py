"""Pure replay projections for durable plan-amendment streams."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from milburn.domain.amendments import (
    ActiveWorkImpact,
    AmendmentApproval,
    AmendmentEventType,
    AmendmentStatus,
    PlanAmendmentEvent,
)


class AmendmentProjectionError(ValueError):
    """Raised when a stream cannot represent one deterministic amendment."""


@dataclass(frozen=True, slots=True)
class AmendmentProjection:
    amendment_id: str
    version: int
    status: AmendmentStatus
    authority: str
    requested_change: str
    affected_tasks: tuple[str, ...]
    impacts: Mapping[str, ActiveWorkImpact]
    approval: AmendmentApproval | None
    rejection_reason: str | None
    effective_revision: str | None
    remote_merge_revision: str | None
    primary_revision: str | None
    remote_effects_reconciled: bool
    dispatch_frozen: bool
    last_event_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "impacts", MappingProxyType(dict(self.impacts)))


@dataclass(frozen=True, slots=True)
class AmendmentOperatorView:
    amendment_id: str
    authority: str
    requested_change: str
    affected_tasks: tuple[str, ...]
    active_work_impacts: tuple[ActiveWorkImpact, ...]
    status: AmendmentStatus
    effective_revision: str | None
    remote_merge_revision: str | None
    dispatch_frozen: bool
    dispatch_reason: str


def project_amendment_events(
    events: Iterable[PlanAmendmentEvent],
) -> AmendmentProjection | None:
    """Replay one stream, ignoring exact duplicate deliveries by event ID."""

    state: AmendmentProjection | None = None
    seen: dict[str, PlanAmendmentEvent] = {}
    for event in events:
        previous = seen.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise AmendmentProjectionError(
                    f"event ID {event.event_id} was reused with different content"
                )
            continue
        seen[event.event_id] = event
        state = project_amendment_event(state, event)
    return state


def project_amendment_event(
    state: AmendmentProjection | None, event: PlanAmendmentEvent
) -> AmendmentProjection:
    """Apply one fact without mutating the previous projection."""

    expected_sequence = 0 if state is None else state.version + 1
    if event.sequence != expected_sequence:
        raise AmendmentProjectionError(
            f"event sequence {event.sequence} does not follow {expected_sequence - 1}"
        )
    if state is not None and event.amendment_id != state.amendment_id:
        raise AmendmentProjectionError("one stream cannot mix amendment IDs")

    command = event.command
    if event.event_type is AmendmentEventType.REQUESTED:
        if state is not None:
            raise AmendmentProjectionError("amendment can only be requested once")
        return AmendmentProjection(
            amendment_id=event.amendment_id,
            version=event.sequence,
            status=AmendmentStatus.PENDING,
            authority=command.authority or "",
            requested_change=command.requested_change or "",
            affected_tasks=command.affected_tasks,
            impacts={},
            approval=None,
            rejection_reason=None,
            effective_revision=None,
            remote_merge_revision=None,
            primary_revision=None,
            remote_effects_reconciled=False,
            dispatch_frozen=True,
            last_event_id=event.event_id,
        )
    if state is None:
        raise AmendmentProjectionError("amendment stream must begin with a request")

    if event.event_type is AmendmentEventType.IMPACT_ASSESSED:
        _require_status(state, AmendmentStatus.PENDING)
        return _replace(
            state,
            version=event.sequence,
            status=AmendmentStatus.ASSESSED,
            impacts={impact.attempt.attempt_id: impact for impact in command.impacts},
            last_event_id=event.event_id,
        )
    if event.event_type is AmendmentEventType.APPROVED:
        _require_status(state, AmendmentStatus.ASSESSED)
        return _replace(
            state,
            version=event.sequence,
            status=AmendmentStatus.APPROVED,
            approval=command.approval,
            last_event_id=event.event_id,
        )
    if event.event_type is AmendmentEventType.REJECTED:
        _require_status(state, AmendmentStatus.ASSESSED)
        return _replace(
            state,
            version=event.sequence,
            status=AmendmentStatus.REJECTED,
            rejection_reason=command.rejection_reason,
            last_event_id=event.event_id,
        )
    if event.event_type is AmendmentEventType.APPLIED:
        _require_status(state, AmendmentStatus.APPROVED)
        if state.approval is None:
            raise AmendmentProjectionError("approved amendment lacks approval evidence")
        if command.planning_revision != state.approval.expected_planning_revision:
            raise AmendmentProjectionError(
                "application planning revision does not match approval"
            )
        if command.primary_revision != command.remote_merge_revision:
            raise AmendmentProjectionError(
                "primary checkout has not reconciled the remote merge revision"
            )
        return _replace(
            state,
            version=event.sequence,
            status=AmendmentStatus.APPLIED,
            effective_revision=command.effective_revision,
            remote_merge_revision=command.remote_merge_revision,
            primary_revision=command.primary_revision,
            remote_effects_reconciled=command.remote_effects_reconciled,
            last_event_id=event.event_id,
        )
    if event.event_type is AmendmentEventType.DISPATCH_RESUMED:
        if state.status not in {AmendmentStatus.APPLIED, AmendmentStatus.REJECTED}:
            raise AmendmentProjectionError(
                f"cannot resume dispatch in {state.status.value}"
            )
        if state.status is AmendmentStatus.APPLIED and (
            not state.remote_effects_reconciled
            or state.primary_revision != state.remote_merge_revision
        ):
            raise AmendmentProjectionError(
                "dispatch cannot resume before remote reconciliation"
            )
        return _replace(
            state,
            version=event.sequence,
            status=(
                AmendmentStatus.REJECTED
                if state.status is AmendmentStatus.REJECTED
                else AmendmentStatus.EFFECTIVE
            ),
            dispatch_frozen=False,
            last_event_id=event.event_id,
        )
    raise AmendmentProjectionError(f"unknown event type {event.event_type!r}")


def operator_view(state: AmendmentProjection) -> AmendmentOperatorView:
    """Expose bounded amendment evidence without private session context."""

    reason = (
        "dispatch is frozen until the amendment is rejected or applied, remotely "
        "reconciled, and explicitly resumed"
        if state.dispatch_frozen
        else (
            "dispatch resumed after the rejected amendment was reconciled"
            if state.status is AmendmentStatus.REJECTED
            else "dispatch resumed after amendment reconciliation"
        )
    )
    return AmendmentOperatorView(
        amendment_id=state.amendment_id,
        authority=state.authority,
        requested_change=state.requested_change,
        affected_tasks=state.affected_tasks,
        active_work_impacts=tuple(
            state.impacts[key] for key in sorted(state.impacts)
        ),
        status=state.status,
        effective_revision=state.effective_revision,
        remote_merge_revision=state.remote_merge_revision,
        dispatch_frozen=state.dispatch_frozen,
        dispatch_reason=reason,
    )


def _require_status(
    state: AmendmentProjection, expected: AmendmentStatus
) -> None:
    if state.status is not expected:
        raise AmendmentProjectionError(
            f"expected amendment status {expected.value}, got {state.status.value}"
        )


def _replace(state: AmendmentProjection, **changes: object) -> AmendmentProjection:
    values = {
        "amendment_id": state.amendment_id,
        "version": state.version,
        "status": state.status,
        "authority": state.authority,
        "requested_change": state.requested_change,
        "affected_tasks": state.affected_tasks,
        "impacts": state.impacts,
        "approval": state.approval,
        "rejection_reason": state.rejection_reason,
        "effective_revision": state.effective_revision,
        "remote_merge_revision": state.remote_merge_revision,
        "primary_revision": state.primary_revision,
        "remote_effects_reconciled": state.remote_effects_reconciled,
        "dispatch_frozen": state.dispatch_frozen,
        "last_event_id": state.last_event_id,
    }
    values.update(changes)
    return AmendmentProjection(**values)  # type: ignore[arg-type]
