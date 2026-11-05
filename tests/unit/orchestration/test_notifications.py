"""Durable Coordinator notification boundary tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain import CoordinatorNotification
from milburn.orchestration.coordinator import CoordinatorSessionManager
from milburn.orchestration.notifications import NotificationQueue
from milburn.persistence.sqlite_store import SQLiteEventStore


NOW = datetime(2026, 11, 4, tzinfo=UTC)


def notification(identifier: str = "notice-1") -> CoordinatorNotification:
    return CoordinatorNotification(
        notification_id=identifier,
        kind="decision",
        correlation_id="decision-1",
        priority=1,
        summary="Choose a path",
        unread=True,
        created_at=NOW,
    )


def queue(store: SQLiteEventStore) -> NotificationQueue:
    ids = (f"event-{i}" for i in range(100))
    return NotificationQueue(store, clock=lambda: NOW, event_ids=lambda: next(ids))


def register_coordinator(store: SQLiteEventStore) -> CoordinatorSessionManager:
    ids = (f"session-event-{i}" for i in range(100))
    manager = CoordinatorSessionManager(
        store, object(), clock=lambda: NOW, event_ids=lambda: next(ids)
    )
    manager.register_session("coordinator-1", endpoint="tmux:coordinator")
    return manager


def test_duplicate_notification_id_with_different_correlation_is_rejected(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = queue(store)
        service.queue(notification())
        changed = CoordinatorNotification(
            notification_id="notice-1",
            kind="result",
            correlation_id="other-decision",
            priority=1,
            summary="Different work",
            unread=True,
            created_at=NOW,
        )
        with pytest.raises(ValueError):
            service.queue(changed)
        assert service.unread() == (notification(),)


def test_unknown_or_already_read_notification_cannot_be_marked_read(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = queue(store)
        assert not hasattr(service, "mark_read")
        manager = register_coordinator(store)
        with pytest.raises(ValueError):
            manager.present_notification("missing", coordinator_attempt_id="coordinator-1", presentation_id="message-1")
        with pytest.raises(ValueError):
            manager.present_notification([], coordinator_attempt_id="coordinator-1", presentation_id="message-1")  # type: ignore[arg-type]
        result = CoordinatorNotification(
            notification_id="result-1",
            kind="result",
            correlation_id="attempt-1",
            priority=1,
            summary="Completed",
            unread=True,
            created_at=NOW,
        )
        service.queue(result)
        with pytest.raises(ValueError):
            manager.present_notification("result-1", coordinator_attempt_id="forged", presentation_id="message-1")
        with pytest.raises(ValueError):
            manager.accept_new_work("Start another task")
        manager.present_notification("result-1", coordinator_attempt_id="coordinator-1", presentation_id="message-1")
        with pytest.raises(ValueError):
            manager.present_notification("result-1", coordinator_attempt_id="coordinator-1", presentation_id="message-2")
        assert manager.accept_new_work("Start another task")
        assert service.unread() == ()


def test_routine_progress_is_not_an_actionable_notification(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = queue(store)
        progress = CoordinatorNotification(
            notification_id="progress-1",
            kind="progress",
            correlation_id="attempt-1",
            priority=1,
            summary="Still working",
            unread=True,
            created_at=NOW,
        )
        with pytest.raises(ValueError):
            service.queue(progress)
        assert service.unread() == ()


def test_decision_notification_cannot_be_read_without_presentation(tmp_path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        service = queue(store)
        service.queue(notification())
        manager = register_coordinator(store)
        with pytest.raises(ValueError):
            manager.present_notification("notice-1", coordinator_attempt_id="coordinator-1", presentation_id="message-1")
        assert service.unread() == (notification(),)


def test_unread_notifications_survive_restart_in_priority_order(tmp_path) -> None:
    database = tmp_path / "events.db"
    with SQLiteEventStore(database) as store:
        service = queue(store)
        service.queue(notification())
        service.queue(
            CoordinatorNotification(
                notification_id="notice-2",
                kind="failure",
                correlation_id="failure-2",
                priority=4,
                summary="Worker failed",
                unread=True,
                created_at=NOW,
            )
        )
    with SQLiteEventStore(database) as store:
        service = queue(store)
        assert tuple(item.notification_id for item in service.unread()) == (
            "notice-2", "notice-1"
        )
        manager = register_coordinator(store)
        manager.present_notification("notice-2", coordinator_attempt_id="coordinator-1", presentation_id="message-1")
    with SQLiteEventStore(database) as store:
        assert tuple(item.notification_id for item in queue(store).unread()) == (
            "notice-1",
        )
