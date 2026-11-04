"""Pure projection and restart replay behavior."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from milburn.domain import (
    AttemptState,
    DomainEvent,
    EventFact,
    EventType,
    GitHubEffectStatus,
    IssueState,
)
from milburn.persistence import (
    NO_STREAM,
    DecisionState,
    ProjectionError,
    SQLiteEventStore,
    WorkflowProjection,
    project_event,
    project_events,
    replay,
)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def event(
    event_id: str,
    stream: str,
    sequence: int,
    event_type: EventType,
    **facts: str,
) -> DomainEvent:
    return DomainEvent(
        event_id=event_id,
        stream=stream,
        sequence=sequence,
        event_type=event_type,
        occurred_at=NOW,
        correlation_id="correlation-1",
        causation_id=None,
        facts=tuple(EventFact(name=name, value=value) for name, value in facts.items()),
    )


def workflow_events() -> tuple[DomainEvent, ...]:
    return (
        event(
            "issue-created",
            "issue:2",
            0,
            EventType.GITHUB_ISSUE_CREATED,
            issue_number="2",
        ),
        event(
            "issue-ready",
            "issue:2",
            1,
            EventType.GITHUB_ISSUE_READY,
            issue_number="2",
        ),
        event(
            "agent-started",
            "agent:attempt-1",
            0,
            EventType.AGENT_STARTED,
            attempt_id="attempt-1",
        ),
        event(
            "decision-requested",
            "decision:decision-1",
            0,
            EventType.DECISION_REQUESTED,
            decision_id="decision-1",
            source_attempt_id="attempt-1",
        ),
        event(
            "notification-queued",
            "coordinator:home-1",
            0,
            EventType.COORDINATOR_NOTIFICATION_QUEUED,
            notification_id="notification-1",
        ),
        event(
            "effect-requested",
            "effect:github:effect-1",
            0,
            EventType.GITHUB_EFFECT_REQUESTED,
            effect_id="effect-1",
        ),
        event(
            "effect-observed",
            "effect:github:effect-1",
            1,
            EventType.GITHUB_EFFECT_OBSERVED,
            effect_id="effect-1",
            remote_identity="issue-2",
        ),
        event(
            "decision-resolved",
            "decision:decision-1",
            1,
            EventType.DECISION_RESOLVED,
            decision_id="decision-1",
        ),
        event(
            "notification-read",
            "coordinator:home-1",
            1,
            EventType.USER_MESSAGE_RECEIVED,
            notification_id="notification-1",
            notification_unread="false",
        ),
    )


def test_projection_rebuilds_every_required_state_category() -> None:
    projection = project_events(workflow_events())

    assert projection.tasks["2"].state is IssueState.READY
    assert projection.attempts["attempt-1"].state is AttemptState.WAITING_USER
    assert projection.decisions["decision-1"].state is DecisionState.RESOLVED
    assert projection.notifications["notification-1"].unread is False
    assert projection.effects["effect-1"].state is GitHubEffectStatus.OBSERVED
    assert projection.effects["effect-1"].remote_identity == "issue-2"


def test_project_event_is_pure_and_preserves_previous_state() -> None:
    original = WorkflowProjection()
    updated = project_event(original, workflow_events()[0])

    assert dict(original.tasks) == {}
    assert updated.tasks["2"].state is IssueState.DRAFT
    with pytest.raises(TypeError):
        updated.tasks["3"] = updated.tasks["2"]  # type: ignore[index]


def test_explicit_fact_state_overrides_default_event_mapping() -> None:
    projected = project_events(
        (
            event(
                "custom-task",
                "issue:2",
                0,
                EventType.GITHUB_ISSUE_READY,
                task_id="task-2",
                task_state="blocked",
            ),
            event(
                "custom-attempt",
                "agent:attempt-2",
                0,
                EventType.AGENT_STARTED,
                attempt_id="attempt-2",
                attempt_state="idle",
            ),
        )
    )

    assert projected.tasks["task-2"].state is IssueState.BLOCKED
    assert projected.attempts["attempt-2"].state is AttemptState.IDLE


def test_invalid_boolean_projection_fact_fails_explicitly() -> None:
    invalid = event(
        "bad-notification",
        "coordinator:home-1",
        0,
        EventType.COORDINATOR_NOTIFICATION_QUEUED,
        notification_id="notification-1",
        notification_unread="maybe",
    )

    with pytest.raises(ProjectionError, match="must be true or false"):
        project_events((invalid,))


def test_unknown_projection_state_fact_fails_explicitly() -> None:
    invalid = event(
        "bad-task-state",
        "issue:2",
        0,
        EventType.GITHUB_ISSUE_READY,
        task_id="task-2",
        task_state="invented",
    )

    with pytest.raises(ProjectionError, match="unknown IssueState"):
        project_events((invalid,))


@pytest.mark.parametrize(
    ("event_type", "match"),
    [
        (EventType.GITHUB_ISSUE_READY, "task_id or issue_number"),
        (EventType.AGENT_STARTED, "attempt_id"),
        (EventType.DECISION_REQUESTED, "attempt_id"),
        (EventType.DECISION_PRESENTED, "decision_id"),
        (EventType.COORDINATOR_NOTIFICATION_QUEUED, "notification_id"),
        (EventType.GITHUB_EFFECT_REQUESTED, "effect_id"),
    ],
)
def test_state_changing_events_cannot_silently_omit_projection_identity(
    event_type: EventType, match: str
) -> None:
    invalid = event("missing-identity", "feature:one", 0, event_type)

    with pytest.raises(ProjectionError, match=match):
        project_events((invalid,))


def test_restart_replay_produces_identical_projection(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    events = workflow_events()
    streams: dict[str, list[DomainEvent]] = {}
    for item in events:
        streams.setdefault(item.stream, []).append(item)

    with SQLiteEventStore(database) as store:
        for stream, stream_events in streams.items():
            store.append(stream, NO_STREAM, tuple(stream_events))
        before_restart = replay(store)

    with SQLiteEventStore(database) as restarted:
        after_restart = replay(restarted)

    assert after_restart == before_restart
    assert after_restart == project_events(events)
