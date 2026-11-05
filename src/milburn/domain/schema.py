"""JSON Schemas generated from versioned domain models (PRD R36).

The schema mirrors ``VersionedModel.from_dict``: every field is required, no
extra field is allowed, and ``schema_version`` is pinned to the model's current
version. An annotation the generator cannot express exactly raises
``SchemaGenerationError`` rather than producing a weaker schema.

Emitted keywords: type, enum, properties, required, additionalProperties,
items, anyOf. Datetimes are strings; their ISO-8601 and timezone rules are
enforced by ``from_dict`` after generation, not by the schema.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from .base import VersionedModel


class SchemaGenerationError(TypeError):
    """Raised when a model field has no exact JSON Schema equivalent."""


def model_schema(model: type[VersionedModel]) -> dict[str, Any]:
    """Return the strict JSON Schema for one versioned model."""

    if not (
        isinstance(model, type)
        and issubclass(model, VersionedModel)
        and is_dataclass(model)
    ):
        raise SchemaGenerationError(f"{model!r} is not a versioned domain model")
    hints = get_type_hints(model)
    properties: dict[str, Any] = {}
    for field in fields(model):
        if field.name == "schema_version":
            properties[field.name] = {
                "type": "integer",
                "enum": [model.CURRENT_SCHEMA_VERSION],
            }
            continue
        try:
            properties[field.name] = _annotation_schema(hints[field.name])
        except SchemaGenerationError as error:
            raise SchemaGenerationError(
                f"{model.__name__}.{field.name}: {error}"
            ) from error
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple:
        if len(arguments) != 2 or arguments[1] is not Ellipsis:
            raise SchemaGenerationError(f"only tuple[X, ...] is supported, got {annotation!r}")
        return {"type": "array", "items": _annotation_schema(arguments[0])}
    if origin in (Union, types.UnionType):
        options = [
            {"type": "null"} if candidate is type(None) else _annotation_schema(candidate)
            for candidate in arguments
        ]
        return {"anyOf": options}
    if isinstance(annotation, type) and issubclass(annotation, VersionedModel):
        return model_schema(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = [member.value for member in annotation]
        if not all(isinstance(value, str) for value in values):
            raise SchemaGenerationError(f"enum {annotation.__name__} has non-string values")
        return {"type": "string", "enum": values}
    if annotation is datetime or annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    raise SchemaGenerationError(f"no JSON Schema for annotation {annotation!r}")
