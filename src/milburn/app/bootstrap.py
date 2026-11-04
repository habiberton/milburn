"""Composition entry point reserved for the Milburn controller application."""

from __future__ import annotations

from milburn.app.configuration import Configuration


def bootstrap(configuration: Configuration) -> Configuration:
    """Return the validated configuration until later tasks add components."""

    return configuration
