"""Minimal JSON Schema checker for the subset ``milburn.domain.schema`` emits.

Supported keywords: type, enum, properties, required, additionalProperties,
items, anyOf. Any other keyword fails loudly so a generator change cannot pass
these tests by emitting something the checker silently ignores.
"""

from __future__ import annotations

from typing import Any

_KNOWN = frozenset(
    {"type", "enum", "properties", "required", "additionalProperties", "items", "anyOf"}
)
_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def schema_errors(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    unknown = set(schema) - _KNOWN
    if unknown:
        raise AssertionError(f"{path}: unsupported schema keywords {sorted(unknown)}")
    if "anyOf" in schema:
        options = [schema_errors(option, value, path) for option in schema["anyOf"]]
        if any(not errors for errors in options):
            return []
        return [f"{path}: matches no anyOf option"]
    errors: list[str] = []
    kind = schema.get("type")
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{path}: expected integer"]
    elif kind == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [f"{path}: expected number"]
    elif kind is not None:
        if not isinstance(value, _TYPES[kind]):
            return [f"{path}: expected {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if kind == "object":
        properties = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                errors.append(f"{path}: missing {name}")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}: unexpected {name}")
        for name, sub in properties.items():
            if name in value:
                errors.extend(schema_errors(sub, value[name], f"{path}.{name}"))
    if kind == "array":
        for index, item in enumerate(value):
            errors.extend(schema_errors(schema["items"], item, f"{path}[{index}]"))
    return errors
