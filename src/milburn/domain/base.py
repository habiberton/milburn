"""Shared immutable, versioned domain-model behavior."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
import types
from typing import Any, ClassVar, Self, Union, get_args, get_origin, get_type_hints

from .errors import (
    InvalidEnvelopeError,
    InvalidIdentifierError,
    UnsupportedSchemaVersionError,
)


SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionedModel:
    """A frozen value object with strict versioned dict serialization."""

    schema_version: int = SCHEMA_VERSION
    CURRENT_SCHEMA_VERSION: ClassVar[int] = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != self.CURRENT_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"unsupported schema version {self.schema_version}; "
                f"expected {self.CURRENT_SCHEMA_VERSION}"
            )
        hints = get_type_hints(type(self))
        for field in fields(self):
            _validate_runtime_value(getattr(self, field.name), hints[field.name], field.name)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible representation."""

        return {field.name: _encode(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Decode a strict representation without retaining mutable input."""

        if not isinstance(payload, dict):
            raise InvalidEnvelopeError(f"{cls.__name__} payload must be a dictionary")
        expected = {field.name for field in fields(cls)}
        missing = expected - payload.keys()
        extra = payload.keys() - expected
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing {sorted(missing)}")
            if extra:
                details.append(f"unknown {sorted(extra)}")
            raise InvalidEnvelopeError(f"invalid {cls.__name__}: {', '.join(details)}")
        hints = get_type_hints(cls)
        try:
            values = {
                field.name: _decode(payload[field.name], hints[field.name])
                for field in fields(cls)
            }
            return cls(**values)
        except (InvalidEnvelopeError, InvalidIdentifierError):
            raise
        except (TypeError, ValueError) as error:
            raise InvalidEnvelopeError(f"invalid {cls.__name__}: {error}") from error


def require_identifier(value: str, field_name: str) -> None:
    """Require a compact, non-whitespace identifier."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidIdentifierError(f"{field_name} must be a non-empty identifier")
    if any(character.isspace() for character in value):
        raise InvalidIdentifierError(f"{field_name} must not contain whitespace")


def require_text(value: str, field_name: str) -> None:
    """Require meaningful prose while preserving the caller's exact value."""

    if not isinstance(value, str) or not value.strip():
        raise InvalidEnvelopeError(f"{field_name} must be non-empty text")


def require_non_negative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidEnvelopeError(f"{field_name} must be a non-negative integer")


def require_bool(value: bool, field_name: str) -> None:
    if not isinstance(value, bool):
        raise InvalidEnvelopeError(f"{field_name} must be a boolean")


def require_enum(value: Enum, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise InvalidEnvelopeError(
            f"{field_name} must be a known {enum_type.__name__} value"
        )


def _encode(value: Any) -> Any:
    if isinstance(value, VersionedModel):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any, annotation: Any) -> Any:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple:
        if not isinstance(value, list):
            raise InvalidEnvelopeError("tuple fields must be encoded as lists")
        item_type = arguments[0]
        return tuple(_decode(item, item_type) for item in value)
    if origin in (Union, types.UnionType):
        if value is None and type(None) in arguments:
            return None
        failures = []
        for candidate in arguments:
            if candidate is type(None):
                continue
            try:
                return _decode(value, candidate)
            except (InvalidEnvelopeError, TypeError, ValueError) as error:
                failures.append(str(error))
        raise InvalidEnvelopeError("value does not match any allowed type")
    if isinstance(annotation, type) and issubclass(annotation, VersionedModel):
        return annotation.from_dict(value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        try:
            return annotation(value)
        except ValueError as error:
            raise InvalidEnvelopeError(
                f"unknown {annotation.__name__} value: {value!r}"
            ) from error
    if annotation is datetime:
        if not isinstance(value, str):
            raise InvalidEnvelopeError("datetime fields must be ISO-8601 strings")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise InvalidEnvelopeError("datetime fields must include a timezone")
        return parsed
    if annotation is bool:
        if not isinstance(value, bool):
            raise InvalidEnvelopeError("expected a boolean")
        return value
    if annotation is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidEnvelopeError("expected an integer")
        return value
    if annotation is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidEnvelopeError("expected a number")
        return float(value)
    if annotation is str:
        if not isinstance(value, str):
            raise InvalidEnvelopeError("expected a string")
        return value
    return value


def _validate_runtime_value(value: Any, annotation: Any, field_name: str) -> None:
    """Reject values that violate annotations before they can hide mutability."""

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple:
        if not isinstance(value, tuple):
            raise InvalidEnvelopeError(f"{field_name} must be an immutable tuple")
        for item in value:
            _validate_runtime_value(item, arguments[0], field_name)
        return
    if origin in (Union, types.UnionType):
        if value is None and type(None) in arguments:
            return
        for candidate in arguments:
            if candidate is type(None):
                continue
            try:
                _validate_runtime_value(value, candidate, field_name)
                return
            except InvalidEnvelopeError:
                pass
        raise InvalidEnvelopeError(f"{field_name} does not match an allowed type")
    if isinstance(annotation, type) and issubclass(annotation, (VersionedModel, Enum)):
        if not isinstance(value, annotation):
            raise InvalidEnvelopeError(f"{field_name} must be {annotation.__name__}")
        return
    if annotation is datetime:
        if not isinstance(value, datetime):
            raise InvalidEnvelopeError(f"{field_name} must be a datetime")
        return
    if annotation is bool:
        if not isinstance(value, bool):
            raise InvalidEnvelopeError(f"{field_name} must be a boolean")
        return
    if annotation is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidEnvelopeError(f"{field_name} must be an integer")
        return
    if annotation is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidEnvelopeError(f"{field_name} must be a number")
        return
    if annotation is str and not isinstance(value, str):
        raise InvalidEnvelopeError(f"{field_name} must be a string")
