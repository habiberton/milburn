"""Durable Coordinator notification boundary tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain import CoordinatorNotification
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
        with pytest.raises(ValueError):
            service.mark_read("missing")
        with pytest.raises(ValueError):
            service.mark_read([])  # type: ignore[arg-type]
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
        service.mark_read("result-1")
        with pytest.raises(ValueError):
            service.mark_read("result-1")
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
        with pytest.raises(ValueError):
            service.mark_read("notice-1")
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
        service.mark_read("notice-2")
    with SQLiteEventStore(database) as store:
        assert tuple(item.notification_id for item in queue(store).unread()) == (
            "notice-1",
        )
