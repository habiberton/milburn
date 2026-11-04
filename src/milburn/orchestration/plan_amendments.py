"""Expected-version coordinator and launch fence for plan amendments."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol, TypeVar

from milburn.domain.amendments import (
    ActiveAttempt,
    AmendmentCommandType,
    AmendmentEventType,
    EVENT_FOR_COMMAND,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
)
from milburn.persistence.amendment_projections import (
    AmendmentProjection,
    AmendmentProjectionError,
    project_amendment_events,
)
from milburn.validation.amendment_policy import ensure_agent_launch_allowed


class AmendmentConcurrencyError(RuntimeError):
    """Raised when an amendment command targets an old stream version."""


class AmendmentCommandConflictError(RuntimeError):
    """Raised when a stable command ID is reused with different content."""


class AmendmentEventStore(Protocol):
    def read_stream(self, amendment_id: str) -> tuple[PlanAmendmentEvent, ...]: ...

    def append(
        self,
        amendment_id: str,
        expected_version: int,
        events: tuple[PlanAmendmentEvent, ...],
    ) -> tuple[PlanAmendmentEvent, ...]: ...


Result = TypeVar("Result")


class PlanAmendmentCoordinator:
    """Validate, append, and replay one durable amendment stream at a time."""

    def __init__(
        self,
        store: AmendmentEventStore,
        *,
        clock: Callable[[], datetime],
        event_ids: Callable[[], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._event_ids = event_ids

    def handle(
        self,
        command: PlanAmendmentCommand,
        *,
        active_attempts: tuple[ActiveAttempt, ...] = (),
    ) -> PlanAmendmentEvent:
        history = self._store.read_stream(command.amendment_id)
        duplicate = next(
            (event for event in history if event.command.command_id == command.command_id),
            None,
        )
        if duplicate is not None:
            if duplicate.command != command:
                raise AmendmentCommandConflictError(
                    f"command ID {command.command_id} has conflicting content"
                )
            return duplicate

        actual_version = history[-1].sequence if history else -1
        if actual_version != command.expected_version:
            raise AmendmentConcurrencyError(
                f"amendment {command.amendment_id} is at version {actual_version}; "
                f"expected {command.expected_version}"
            )
        current = project_amendment_events(history)
        self._validate_command(command, current, active_attempts)
        event = PlanAmendmentEvent(
            event_id=self._event_ids(),
            amendment_id=command.amendment_id,
            event_type=EVENT_FOR_COMMAND[command.command_type],
            sequence=command.expected_version + 1,
            occurred_at=self._clock(),
            command=command,
        )
        # Project before append so illegal lifecycle facts never enter the stream.
        project_amendment_events((*history, event))
        try:
            self._store.append(
                command.amendment_id, command.expected_version, (event,)
            )
        except AmendmentConcurrencyError:
            raise
        return event

    def state(self, amendment_id: str) -> AmendmentProjection | None:
        return project_amendment_events(self._store.read_stream(amendment_id))

    @staticmethod
    def request_agent_launch(
        amendments: tuple[AmendmentProjection, ...],
        *,
        dirty_planning_paths: tuple[str, ...] = (),
        request_effect: Callable[[], Result],
    ) -> Result:
        """Fence both AgentLaunchRequested intent and its process effect."""

        ensure_agent_launch_allowed(
            amendments, dirty_planning_paths=dirty_planning_paths
        )
        return request_effect()

    @staticmethod
    def _validate_command(
        command: PlanAmendmentCommand,
        current: AmendmentProjection | None,
        active_attempts: tuple[ActiveAttempt, ...],
    ) -> None:
        if command.command_type is AmendmentCommandType.REQUEST:
            if current is not None:
                raise AmendmentProjectionError("amendment was already requested")
            return
        if current is None:
            raise AmendmentProjectionError("amendment must be requested first")
        if command.command_type is AmendmentCommandType.ASSESS_IMPACT:
            attempt_ids = [attempt.attempt_id for attempt in active_attempts]
            if len(attempt_ids) != len(set(attempt_ids)):
                raise AmendmentProjectionError("active attempt IDs must be unique")
            relevant = {
                attempt.attempt_id: attempt for attempt in active_attempts
            }
            assessed = {impact.attempt.attempt_id: impact for impact in command.impacts}
            if assessed.keys() != relevant.keys():
                raise AmendmentProjectionError(
                    "impact assessment must classify every affected active attempt exactly once"
                )
            for attempt_id, attempt in relevant.items():
                if assessed[attempt_id].attempt != attempt:
                    raise AmendmentProjectionError(
                        "impact assessment cannot change active ownership or generation"
                    )
            return
        if command.command_type is AmendmentCommandType.APPROVE:
            if command.approval is None:
                raise AmendmentProjectionError("approval evidence is required")
            if command.approval.approved_by != current.authority:
                raise AmendmentProjectionError(
                    "approval authority does not match the user-authorized request"
                )
            return
        if command.command_type is AmendmentCommandType.APPLY:
            if current.approval is None:
                raise AmendmentProjectionError("amendment must be approved before apply")
            if command.planning_revision != current.approval.expected_planning_revision:
                raise AmendmentProjectionError(
                    "application uses a stale planning revision"
                )
            if command.primary_revision != command.remote_merge_revision:
                raise AmendmentProjectionError(
                    "primary checkout must match the observed remote merge"
                )
