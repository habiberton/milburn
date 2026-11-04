from __future__ import annotations

from pathlib import Path

from milburn.app.bootstrap import bootstrap
from milburn.app.configuration import Configuration


def test_bootstrap_accepts_resolved_configuration(repository_path: Path) -> None:
    configuration = Configuration(
        home=repository_path / ".milburn",
        repository=repository_path,
        base_branch="main",
    )

    assert bootstrap(configuration) is configuration
