"""Controller tests prove authorization, idempotency, and effect ordering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from milburn.domain import (
    CommandEnvelope,
    CommandType,
    DomainEvent,
    EventFact,
    EventType,
    InvalidTransitionError,
    Role,
)
from milburn.orchestration.controller import (
    Controller,
    DuplicateCommandError,
    StaleCommandError,
)


class MemoryStore:
    def __init__(self, order: list[str] | None = None) -> None:
        self.events: dict[str, tuple[DomainEvent, ...]] = {}
        self.order = order

    def read_stream(
        self, stream: str, *, after_sequence: int = -1
    ) -> tuple[DomainEvent, ...]:
        return tuple(
            event
            for event in self.events.get(stream, ())
            if event.sequence > after_sequence
        )

    def append(
        self,
        stream: str,
        expected_sequence: int,
        events: tuple[DomainEvent, ...],
    ) -> tuple[DomainEvent, ...]:
        current = self.events.get(stream, ())
        actual = current[-1].sequence if current else -1
        if actual != expected_sequence:
            raise AssertionError("concurrent append")
        self.events[stream] = (*current, *events)
        if self.order is not None:
            self.order.append("intent")
        return events


def command(
    *,
    command_id: str = "command-1",
    command_type: CommandType = CommandType.SUBMIT_CANDIDATE,
    role: Role = Role.CODER,
) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=command_id,
        command_type=command_type,
        actor_role=role,
        feature_id="feature-1",
        issue_number=4,
        attempt_id="attempt-1",
        correlation_id="correlation-1",
    )


def controller(store: MemoryStore) -> Controller:
    ids = iter(("event-1", "event-2"))
    return Controller(
        store,
        clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
        event_ids=lambda: next(ids),
    )


def test_controller_records_intent_before_requesting_external_effect() -> None:
    order: list[str] = []
    store = MemoryStore(order)

    receipt = controller(store).handle(
        command(),
        intent_type=EventType.CODER_RESULT_RECEIVED,
        expected_sequence=-1,
        facts=(EventFact(name="head_sha", value="abc123"),),
        request_effect=lambda: order.append("effect") or "requested",
    )

    assert order == ["intent", "effect"]
    assert receipt.effect_result == "requested"
    assert receipt.intent.causation_id == "command-1"
    assert receipt.intent.facts[-1] == EventFact(name="head_sha", value="abc123")


def test_effect_failure_does_not_erase_recorded_intent() -> None:
    store = MemoryStore()

    def fail() -> None:
        raise RuntimeError("boundary unavailable")

    with pytest.raises(RuntimeError, match="boundary unavailable"):
        controller(store).handle(
            command(),
            intent_type=EventType.CODER_RESULT_RECEIVED,
            expected_sequence=-1,
            request_effect=fail,
        )

    assert len(store.events["feature:feature-1"]) == 1


def test_duplicate_command_does_not_record_or_repeat_effect() -> None:
    store = MemoryStore()
    effects = 0

    def request() -> None:
        nonlocal effects
        effects += 1

    subject = controller(store)
    subject.handle(
        command(),
        intent_type=EventType.CODER_RESULT_RECEIVED,
        expected_sequence=-1,
        request_effect=request,
    )

    with pytest.raises(DuplicateCommandError, match="already handled"):
        subject.handle(
            command(),
            intent_type=EventType.CODER_RESULT_RECEIVED,
            expected_sequence=0,
            request_effect=request,
        )

    assert effects == 1
    assert len(store.events["feature:feature-1"]) == 1


def test_stale_command_is_rejected_before_effect() -> None:
    store = MemoryStore()
    subject = controller(store)
    subject.handle(
        command(command_id="command-existing"),
        intent_type=EventType.CODER_RESULT_RECEIVED,
        expected_sequence=-1,
    )

    with pytest.raises(StaleCommandError, match="expected -1"):
        subject.handle(
            command(command_id="command-stale"),
            intent_type=EventType.CODER_RESULT_RECEIVED,
            expected_sequence=-1,
            request_effect=lambda: pytest.fail("effect must not run"),
        )


def test_agent_cannot_request_controller_owned_lifecycle_effect() -> None:
    store = MemoryStore()
    lifecycle = command(
        command_type=CommandType.REQUEST_AGENT_LAUNCH,
        role=Role.COORDINATOR,
    )

    with pytest.raises(InvalidTransitionError, match="cannot issue"):
        controller(store).handle(
            lifecycle,
            intent_type=EventType.AGENT_LAUNCH_REQUESTED,
            expected_sequence=-1,
        )

    assert store.events == {}


def test_wrong_agent_role_cannot_submit_another_roles_result() -> None:
    store = MemoryStore()

    with pytest.raises(InvalidTransitionError, match="cannot issue"):
        controller(store).handle(
            command(role=Role.TESTER),
            intent_type=EventType.CODER_RESULT_RECEIVED,
            expected_sequence=-1,
        )
