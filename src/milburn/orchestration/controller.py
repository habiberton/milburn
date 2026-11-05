"""Small deterministic controller shell for validated command effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Protocol

from milburn.domain import (
    CommandEnvelope,
    DomainEvent,
    EventFact,
    EventType,
)
from milburn.domain.policies import (
    ensure_command_allowed,
    ensure_command_intent_allowed,
)


class EventStore(Protocol):
    def read_stream(
        self, stream: str, *, after_sequence: int = -1
    ) -> tuple[DomainEvent, ...]: ...

    def append(
        self,
        stream: str,
        expected_sequence: int,
        events: tuple[DomainEvent, ...],
        *,
        guard_sequences: Mapping[str, int] | None = None,
    ) -> tuple[DomainEvent, ...]: ...


class DuplicateCommandError(ValueError):
    """Raised when a command's durable intent was already recorded."""


class StaleCommandError(ValueError):
    """Raised when a command was based on an old stream sequence."""


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    intent: DomainEvent
    effect_result: object | None


class Controller:
    """Authorize commands, durably record intent, then request an effect."""

    def __init__(
        self,
        event_store: EventStore,
        *,
        clock: Callable[[], datetime],
        event_ids: Callable[[], str],
    ) -> None:
        self._event_store = event_store
        self._clock = clock
        self._event_ids = event_ids

    def handle(
        self,
        command: CommandEnvelope,
        *,
        intent_type: EventType,
        expected_sequence: int,
        request_effect: Callable[[], object] | None = None,
        stream: str | None = None,
        facts: tuple[EventFact, ...] = (),
        guard_sequences: Mapping[str, int] | None = None,
    ) -> CommandReceipt:
        """Record one authorized command before crossing an external boundary."""

        ensure_command_allowed(command)
        ensure_command_intent_allowed(command, intent_type)
        target_stream = stream or f"feature:{command.feature_id}"
        history = self._event_store.read_stream(target_stream)
        if any(event.causation_id == command.command_id for event in history):
            raise DuplicateCommandError(
                f"command {command.command_id} was already handled"
            )

        actual_sequence = history[-1].sequence if history else -1
        if actual_sequence != expected_sequence:
            raise StaleCommandError(
                f"stream {target_stream} is at sequence {actual_sequence}; "
                f"command expected {expected_sequence}"
            )

        intent = DomainEvent(
            event_id=self._event_ids(),
            stream=target_stream,
            sequence=expected_sequence + 1,
            event_type=intent_type,
            occurred_at=self._clock(),
            correlation_id=command.correlation_id,
            causation_id=command.command_id,
            facts=(
                EventFact(name="command_type", value=command.command_type.value),
                EventFact(name="actor_role", value=command.actor_role.value),
                *facts,
            ),
        )
        if guard_sequences:
            self._event_store.append(
                target_stream, expected_sequence, (intent,),
                guard_sequences=guard_sequences,
            )
        else:
            self._event_store.append(target_stream, expected_sequence, (intent,))
        result = request_effect() if request_effect is not None else None
        return CommandReceipt(intent=intent, effect_result=result)
