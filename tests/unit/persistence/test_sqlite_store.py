"""Public SQLite event-store behavior."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from milburn.domain import DomainEvent, EventFact, EventType
from milburn.persistence import (
    NO_STREAM,
    ConcurrencyError,
    InvalidEventBatchError,
    MigrationError,
    SQLiteEventStore,
)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def event(
    event_id: str,
    stream: str,
    sequence: int,
    event_type: EventType = EventType.REQUEST_ACCEPTED,
    *facts: tuple[str, str],
) -> DomainEvent:
    return DomainEvent(
        event_id=event_id,
        stream=stream,
        sequence=sequence,
        event_type=event_type,
        occurred_at=NOW,
        correlation_id="correlation-1",
        causation_id=None,
        facts=tuple(EventFact(name=name, value=value) for name, value in facts),
    )


def migration_metadata(database: Path) -> tuple[tuple[tuple[int, str], ...], int]:
    connection = sqlite3.connect(database)
    try:
        rows = tuple(
            (int(version), str(checksum))
            for version, checksum in connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            )
        )
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        return rows, user_version
    finally:
        connection.close()


def test_append_and_read_preserve_stream_and_global_order(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database) as store:
        first = event("event-1", "feature:one", 0)
        second = event("event-2", "feature:one", 1, EventType.PLAN_RECEIVED)
        other = event("event-3", "feature:two", 0)

        assert store.append("feature:one", NO_STREAM, (first, second)) == (
            first,
            second,
        )
        store.append("feature:two", NO_STREAM, (other,))

        assert store.stream_sequence("feature:one") == 1
        assert store.stream_sequence("missing") == NO_STREAM
        assert store.read_stream("feature:one") == (first, second)
        assert store.read_stream("feature:one", after_sequence=0) == (second,)
        assert store.read_all() == (first, second, other)
        assert store.read_all(after_position=1) == (second, other)


def test_stale_expected_sequence_is_rejected_across_connections(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database) as first, SQLiteEventStore(database) as second:
        first.append("feature:one", NO_STREAM, (event("event-1", "feature:one", 0),))

        with pytest.raises(ConcurrencyError, match="is at sequence 0; expected -1"):
            second.append(
                "feature:one",
                NO_STREAM,
                (event("event-2", "feature:one", 0),),
            )

        assert second.read_stream("feature:one") == (
            event("event-1", "feature:one", 0),
        )


def test_concurrent_writers_cannot_both_claim_the_same_sequence(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database) as first, SQLiteEventStore(database) as second:
        def append(store: SQLiteEventStore, event_id: str) -> str:
            try:
                store.append(
                    "feature:one",
                    NO_STREAM,
                    (event(event_id, "feature:one", 0),),
                )
            except ConcurrencyError:
                return "stale"
            return "stored"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(append, (first, second), ("event-1", "event-2"))
            )

        assert sorted(results) == ["stale", "stored"]
        assert len(first.read_all()) == 1


def test_duplicate_event_id_rolls_back_the_entire_batch(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database) as store:
        batch = (
            event("duplicate", "feature:one", 0),
            event("duplicate", "feature:one", 1),
        )

        with pytest.raises(InvalidEventBatchError, match="UNIQUE"):
            store.append("feature:one", NO_STREAM, batch)

        assert store.stream_sequence("feature:one") == NO_STREAM
        assert store.read_all() == ()


@pytest.mark.parametrize(
    "stream,expected,events,match",
    [
        ("", NO_STREAM, (), "stream"),
        ("feature:one", -2, (), "expected_sequence"),
        ("feature:one", NO_STREAM, (), "non-empty tuple"),
        (
            "feature:one",
            NO_STREAM,
            (event("event-1", "feature:two", 0),),
            "belongs to",
        ),
        (
            "feature:one",
            NO_STREAM,
            (event("event-1", "feature:one", 1),),
            "expected 0",
        ),
    ],
)
def test_invalid_batches_fail_before_writing(
    tmp_path: Path,
    stream: str,
    expected: int,
    events: tuple[DomainEvent, ...],
    match: str,
) -> None:
    with SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(InvalidEventBatchError, match=match):
            store.append(stream, expected, events)
        assert store.read_all() == ()


def test_restart_reads_the_same_versioned_events(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    expected = event(
        "event-1",
        "effect:one",
        0,
        EventType.GITHUB_EFFECT_REQUESTED,
        ("effect_id", "effect-1"),
    )
    with SQLiteEventStore(database) as store:
        store.append("effect:one", NO_STREAM, (expected,))

    with SQLiteEventStore(database) as restarted:
        assert restarted.read_all() == (expected,)
        assert restarted.migration_versions == (1,)


def test_migrations_are_repeatable_and_set_user_version(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database) as store:
        assert store.migration_versions == (1,)
    with SQLiteEventStore(database) as store:
        assert store.migration_versions == (1,)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    finally:
        connection.close()


def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database):
        pass
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("changed",),
        )
        connection.commit()
    finally:
        connection.close()
    before = migration_metadata(database)

    with pytest.raises(MigrationError, match="checksum changed"):
        SQLiteEventStore(database)

    assert migration_metadata(database) == before


@pytest.mark.parametrize(
    "versions",
    [
        pytest.param((0, 1), id="unknown-version"),
        pytest.param((1, 2), id="future-version"),
        pytest.param((2,), id="gap-before-first-version"),
    ],
)
def test_unrecognized_migration_sequences_are_rejected_without_metadata_changes(
    tmp_path: Path, versions: tuple[int, ...]
) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database):
        pass
    connection = sqlite3.connect(database)
    try:
        checksum = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 1"
        ).fetchone()[0]
        connection.execute("DELETE FROM schema_migrations")
        connection.executemany(
            "INSERT INTO schema_migrations (version, checksum) VALUES (?, ?)",
            ((version, checksum) for version in versions),
        )
        connection.execute(f"PRAGMA user_version = {versions[-1]}")
        connection.commit()
    finally:
        connection.close()
    before = migration_metadata(database)

    with pytest.raises(MigrationError, match="exact recognized prefix"):
        SQLiteEventStore(database)

    assert migration_metadata(database) == before


def test_future_user_version_is_rejected_without_being_lowered(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database):
        pass
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA user_version = 99")
        connection.commit()
    finally:
        connection.close()
    before = migration_metadata(database)

    with pytest.raises(MigrationError, match="user_version is 99; expected 1"):
        SQLiteEventStore(database)

    assert migration_metadata(database) == before


def test_user_version_must_agree_with_applied_prefix(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database):
        pass
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
    finally:
        connection.close()
    before = migration_metadata(database)

    with pytest.raises(MigrationError, match="user_version is 0; expected 1"):
        SQLiteEventStore(database)

    assert migration_metadata(database) == before


def test_locked_append_preserves_explicit_concurrency_error(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database, busy_timeout_ms=1) as store:
        locker = sqlite3.connect(database, isolation_level=None)
        try:
            locker.execute("BEGIN IMMEDIATE")
            with pytest.raises(ConcurrencyError, match="database lock") as raised:
                store.append(
                    "feature:one",
                    NO_STREAM,
                    (event("event-1", "feature:one", 0),),
                )
            assert "cannot rollback" not in str(raised.value).lower()
            assert isinstance(raised.value.__cause__, sqlite3.OperationalError)
        finally:
            locker.execute("ROLLBACK")
            locker.close()


def test_locked_migration_preserves_explicit_migration_error(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    with SQLiteEventStore(database):
        pass
    locker = sqlite3.connect(database, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(MigrationError, match="database lock") as raised:
            SQLiteEventStore(database, busy_timeout_ms=1)
        assert "cannot rollback" not in str(raised.value).lower()
        assert isinstance(raised.value.__cause__, sqlite3.OperationalError)
    finally:
        locker.execute("ROLLBACK")
        locker.close()
