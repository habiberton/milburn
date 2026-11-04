"""Shared deterministic pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repository_path(tmp_path: Path) -> Path:
    """Return an isolated repository-shaped directory for application tests."""

    repository = tmp_path / "repository"
    repository.mkdir()
    return repository

