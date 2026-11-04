"""Versioned SQLite migrations owned by the event store."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered, immutable schema migration."""

    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n-- statement --\n".join(self.statements).encode()
        return sha256(payload).hexdigest()


MIGRATIONS = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE events (
                global_position INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                stream TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                event_type TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE (stream, sequence)
            )
            """,
            """
            CREATE INDEX events_stream_position
            ON events (stream, sequence)
            """,
        ),
    ),
)

__all__ = ["MIGRATIONS", "Migration"]
