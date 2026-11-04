"""Pure controller authority policies shared by orchestration services."""

from __future__ import annotations

from .commands import CommandEnvelope, CommandType
from .errors import InvalidTransitionError
from .events import EventType
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

_COMMAND_INTENT_EVENTS: dict[CommandType, frozenset[EventType]] = {
    CommandType.ACCEPT_REQUEST: frozenset({EventType.REQUEST_ACCEPTED}),
    CommandType.SUBMIT_INTAKE_PROPOSAL: frozenset({EventType.REQUEST_ACCEPTED}),
    CommandType.REQUEST_STATUS_SUMMARY: frozenset({EventType.USER_MESSAGE_RECEIVED}),
    CommandType.PROPOSE_ROLE_ROUTE: frozenset({EventType.ROLE_ROUTE_PROPOSED}),
    CommandType.SUBMIT_PLAN: frozenset({EventType.PLAN_RECEIVED}),
    CommandType.SUBMIT_ARCHITECTURE: frozenset(
        {EventType.ARCHITECTURE_PACKAGE_RECEIVED}
    ),
    CommandType.SUBMIT_ISSUE_DRAFTS: frozenset(
        {EventType.ARCHITECTURE_PACKAGE_RECEIVED}
    ),
    CommandType.REQUEST_AGENT_LAUNCH: frozenset(
        {EventType.AGENT_LAUNCH_REQUESTED}
    ),
    CommandType.REPORT_PROGRESS: frozenset({EventType.CODER_CHECKPOINT_OBSERVED}),
    CommandType.REPORT_CODER_CHECKPOINT: frozenset(
        {EventType.CODER_CHECKPOINT_OBSERVED}
    ),
    CommandType.SUBMIT_CANDIDATE: frozenset({EventType.CODER_RESULT_RECEIVED}),
    CommandType.REQUEST_TESTING: frozenset({EventType.TESTING_REQUESTED}),
    CommandType.SUBMIT_QA_REPORT: frozenset({EventType.TEST_RESULT_RECEIVED}),
    CommandType.REQUEST_DECISION: frozenset({EventType.DECISION_REQUESTED}),
    CommandType.ANSWER_DECISION: frozenset({EventType.USER_DECISION_RECEIVED}),
    CommandType.QUEUE_STEERING: frozenset({EventType.STEERING_QUEUED}),
    CommandType.ACKNOWLEDGE_STEERING: frozenset(
        {EventType.STEERING_ACKNOWLEDGED}
    ),
    # Lifecycle commands lack pre-effect request events in the current event
    # contract. They must not be represented by postcondition facts.
    CommandType.INTERRUPT_AGENT: frozenset(),
    CommandType.TERMINATE_AGENT: frozenset(),
    CommandType.RESUME_AGENT: frozenset(),
    CommandType.REPLACE_AGENT: frozenset(),
    CommandType.RETIRE_AGENT: frozenset(),
}

if set(_COMMAND_INTENT_EVENTS) != set(CommandType):
    raise RuntimeError("every command type must have an explicit intent policy")


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


def ensure_command_intent_allowed(
    command: CommandEnvelope, intent_type: EventType
) -> None:
    """Reject event facts that do not represent the validated command."""

    if not isinstance(intent_type, EventType):
        raise InvalidTransitionError("intent type must be a known EventType value")
    allowed = _COMMAND_INTENT_EVENTS.get(command.command_type, frozenset())
    if intent_type not in allowed:
        raise InvalidTransitionError(
            f"command {command.command_type} cannot record intent {intent_type}"
        )


def is_active_attempt(state: AttemptState) -> bool:
    """Return whether an attempt still reserves scheduling capacity."""

    if not isinstance(state, AttemptState):
        raise InvalidTransitionError("attempt state must be a known AttemptState value")
    return state in ACTIVE_ATTEMPT_STATES
