"""Explicit failures raised by Milburn's domain boundary."""


class DomainError(ValueError):
    """Base class for invalid domain input or state."""


class InvalidIdentifierError(DomainError):
    """Raised when an identifier is empty or malformed."""


class InvalidEnvelopeError(DomainError):
    """Raised when a serialized envelope is incomplete or malformed."""


class UnsupportedSchemaVersionError(InvalidEnvelopeError):
    """Raised when an envelope uses an unsupported schema version."""


class InvalidTransitionError(DomainError):
    """Raised when a lifecycle or role transition is not allowed."""
