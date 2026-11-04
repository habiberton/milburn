"""Pure controller authority policies shared by orchestration services."""

from __future__ import annotations

from .commands import CommandEnvelope, CommandType
from .errors import InvalidTransitionError
from .states import AttemptState, Role


_COMMAND_ACTORS: dict[CommandType, frozenset[Role]] = {
    CommandType.SUBMIT_INTAKE_PROPOSAL: frozenset({Role.COORDINATOR}),
    CommandType.REQUEST_STATUS_SUMMARY: frozenset({Role.COORDINATOR}),
    CommandType.PROPOSE_ROLE_ROUTE: frozenset({Role.CLASSIFIER_ROUTER}),
    CommandType.SUBMIT_PLAN: frozenset({Role.PLANNER}),
    CommandType.SUBMIT_ARCHITECTURE: frozenset({Role.ARCHITECT}),
    CommandType.SUBMIT_ISSUE_DRAFTS: frozenset({Role.ARCHITECT}),
    CommandType.REPORT_PROGRESS: frozenset({Role.CODER}),
    CommandType.REPORT_CODER_CHECKPOINT: frozenset({Role.CODER}),
    CommandType.SUBMIT_CANDIDATE: frozenset({Role.CODER}),
    CommandType.SUBMIT_QA_REPORT: frozenset({Role.TESTER}),
    CommandType.REQUEST_DECISION: frozenset(
        {Role.PLANNER, Role.ARCHITECT, Role.CODER, Role.TESTER}
    ),
    CommandType.ANSWER_DECISION: frozenset({Role.COORDINATOR}),
    CommandType.ACKNOWLEDGE_STEERING: frozenset(
        {Role.PLANNER, Role.ARCHITECT, Role.CODER, Role.TESTER}
    ),
}


ACTIVE_ATTEMPT_STATES = frozenset(
    {
        AttemptState.STARTING,
        AttemptState.BUSY,
        AttemptState.IDLE,
        AttemptState.WAITING,
        AttemptState.WAITING_USER,
        AttemptState.UNKNOWN,
    }
)


def ensure_command_allowed(command: CommandEnvelope) -> None:
    """Reject agent commands that exceed their role's bounded authority."""

    allowed = _COMMAND_ACTORS.get(command.command_type, frozenset())
    if command.actor_role not in allowed:
        raise InvalidTransitionError(
            f"role {command.actor_role} cannot issue command {command.command_type}"
        )


def is_active_attempt(state: AttemptState) -> bool:
    """Return whether an attempt still reserves scheduling capacity."""

    if not isinstance(state, AttemptState):
        raise InvalidTransitionError("attempt state must be a known AttemptState value")
    return state in ACTIVE_ATTEMPT_STATES
