"""Deterministic application configuration loading."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
import tomllib


_ENVIRONMENT_KEYS: Final = {
    "MILBURN_HOME": "home",
    "MILBURN_REPOSITORY": "repository",
    "MILBURN_BASE_BRANCH": "base_branch",
}
_KNOWN_KEYS: Final = frozenset(_ENVIRONMENT_KEYS.values())


class ConfigurationError(ValueError):
    """Raised when configuration input cannot produce a valid configuration."""


@dataclass(frozen=True, slots=True)
class Configuration:
    """Resolved controller paths and repository binding."""

    home: Path
    repository: Path
    base_branch: str


def load_configuration(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Configuration:
    """Load configuration from explicit local inputs without external effects.

    Values in ``environ`` override values from the optional TOML file. The
    mapping is explicit instead of reading ``os.environ`` so identical inputs
    always produce identical output. Relative paths are resolved from ``cwd``.
    """

    root = (cwd or Path.cwd()).resolve()
    values: dict[str, object] = {}

    if path is not None:
        config_path = _resolve_path(path, root)
        try:
            with config_path.open("rb") as config_file:
                document = tomllib.load(config_file)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigurationError(
                f"could not load configuration from {config_path}: {error}"
            ) from error

        section = document.get("milburn", {})
        if not isinstance(section, dict):
            raise ConfigurationError("the [milburn] section must be a table")
        unknown = set(section) - _KNOWN_KEYS
        if unknown:
            joined = ", ".join(sorted(unknown))
            raise ConfigurationError(f"unknown configuration field(s): {joined}")
        values.update(section)

    for environment_key, field_name in _ENVIRONMENT_KEYS.items():
        if environ is not None and environment_key in environ:
            values[field_name] = environ[environment_key]

    home = _path_value(values.get("home", ".milburn"), "home", root)
    repository = _path_value(values.get("repository", "."), "repository", root)
    base_branch = _string_value(values.get("base_branch", "main"), "base_branch")
    return Configuration(home=home, repository=repository, base_branch=base_branch)


def _path_value(value: object, field: str, root: Path) -> Path:
    text = _string_value(value, field)
    return _resolve_path(Path(text), root)


def _resolve_path(path: Path, root: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    return candidate.resolve()


def _string_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    return value.strip()
