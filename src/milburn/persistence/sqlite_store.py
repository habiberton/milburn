"""SQLite-backed append-only event store with optimistic sequencing."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
from types import TracebackType
from typing import Self

from milburn.domain import DomainEvent

from .errors import ConcurrencyError, InvalidEventBatchError, MigrationError
from .migrations import MIGRATIONS


NO_STREAM = -1


class SQLiteEventStore:
    """Store versioned events atomically in ordered named streams."""

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._connection = sqlite3.connect(
            self._database,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = RLock()
        self._apply_migrations()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def migration_versions(self) -> tuple[int, ...]:
        """Return applied schema versions in deterministic order."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        return tuple(int(row["version"]) for row in rows)

    def append(
        self,
        stream: str,
        expected_sequence: int,
        events: tuple[DomainEvent, ...],
    ) -> tuple[DomainEvent, ...]:
        """Atomically append an exact next sequence or reject the whole batch."""

        if not isinstance(stream, str) or not stream or stream != stream.strip():
            raise InvalidEventBatchError("stream must be a non-empty identifier")
        if not isinstance(expected_sequence, int) or isinstance(expected_sequence, bool):
            raise InvalidEventBatchError("expected_sequence must be an integer")
        if expected_sequence < NO_STREAM:
            raise InvalidEventBatchError("expected_sequence must be at least NO_STREAM")
        if not isinstance(events, tuple) or not events:
            raise InvalidEventBatchError("events must be a non-empty tuple")

        for offset, event in enumerate(events, start=1):
            if not isinstance(event, DomainEvent):
                raise InvalidEventBatchError("events must contain DomainEvent values")
            if event.stream != stream:
                raise InvalidEventBatchError(
                    f"event {event.event_id} belongs to {event.stream}, not {stream}"
                )
            required_sequence = expected_sequence + offset
            if event.sequence != required_sequence:
                raise InvalidEventBatchError(
                    f"event {event.event_id} has sequence {event.sequence}; "
                    f"expected {required_sequence}"
                )

        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                actual_sequence = self._stream_sequence(stream)
                if actual_sequence != expected_sequence:
                    raise ConcurrencyError(
                        f"stream {stream} is at sequence {actual_sequence}; "
                        f"expected {expected_sequence}"
                    )
                for event in events:
                    self._connection.execute(
                        """
                        INSERT INTO events (
                            event_id, stream, sequence, event_type,
                            schema_version, payload
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.stream,
                            event.sequence,
                            event.event_type.value,
                            event.schema_version,
                            json.dumps(
                                event.to_dict(),
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                self._connection.execute("COMMIT")
            except ConcurrencyError:
                self._connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as error:
                self._connection.execute("ROLLBACK")
                raise InvalidEventBatchError(f"event append rejected: {error}") from error
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
        return events

    def read_stream(
        self, stream: str, *, after_sequence: int = NO_STREAM
    ) -> tuple[DomainEvent, ...]:
        """Read a stream in sequence order after an exclusive cursor."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload FROM events
                WHERE stream = ? AND sequence > ?
                ORDER BY sequence
                """,
                (stream, after_sequence),
            ).fetchall()
        return tuple(_decode_event(row["payload"]) for row in rows)

    def read_all(self, *, after_position: int = 0) -> tuple[DomainEvent, ...]:
        """Read all events in append order after an exclusive global cursor."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload FROM events
                WHERE global_position > ?
                ORDER BY global_position
                """,
                (after_position,),
            ).fetchall()
        return tuple(_decode_event(row["payload"]) for row in rows)

    def stream_sequence(self, stream: str) -> int:
        """Return the latest sequence or ``NO_STREAM`` when absent."""

        with self._lock:
            return self._stream_sequence(stream)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _stream_sequence(self, stream: str) -> int:
        row = self._connection.execute(
            "SELECT MAX(sequence) AS sequence FROM events WHERE stream = ?",
            (stream,),
        ).fetchone()
        return NO_STREAM if row is None or row["sequence"] is None else int(row["sequence"])

    def _apply_migrations(self) -> None:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        checksum TEXT NOT NULL
                    )
                    """
                )
                applied = {
                    int(row["version"]): str(row["checksum"])
                    for row in self._connection.execute(
                        "SELECT version, checksum FROM schema_migrations"
                    )
                }
                for migration in MIGRATIONS:
                    known_checksum = applied.get(migration.version)
                    if known_checksum is not None:
                        if known_checksum != migration.checksum:
                            raise MigrationError(
                                f"migration {migration.version} checksum changed"
                            )
                        continue
                    for statement in migration.statements:
                        self._connection.execute(statement)
                    self._connection.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (?, ?)",
                        (migration.version, migration.checksum),
                    )
                latest = max((migration.version for migration in MIGRATIONS), default=0)
                self._connection.execute(f"PRAGMA user_version = {latest}")
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise


def _decode_event(payload: str) -> DomainEvent:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as error:
        raise InvalidEventBatchError("stored event payload is invalid JSON") from error
    return DomainEvent.from_dict(decoded)
