"""Explicit failures raised by the persistence boundary."""


class PersistenceError(RuntimeError):
    """Base class for durable-store failures."""


class ConcurrencyError(PersistenceError):
    """Raised when a stream changed after the caller observed it."""


class InvalidEventBatchError(PersistenceError):
    """Raised when an append batch cannot be stored atomically."""


class MigrationError(PersistenceError):
    """Raised when an applied migration differs from the known migration."""


class ProjectionError(PersistenceError):
    """Raised when a durable event cannot be projected without guessing."""
