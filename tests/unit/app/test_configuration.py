from __future__ import annotations

from pathlib import Path

import pytest

from milburn.app.configuration import Configuration, ConfigurationError, load_configuration


def test_defaults_are_resolved_from_explicit_working_directory(
    repository_path: Path,
) -> None:
    assert load_configuration(cwd=repository_path) == Configuration(
        home=repository_path / ".milburn",
        repository=repository_path,
        base_branch="main",
    )


def test_process_environment_is_not_read_implicitly(
    repository_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MILBURN_HOME", "hidden-process-state")

    configuration = load_configuration(cwd=repository_path)

    assert configuration.home == repository_path / ".milburn"


def test_file_and_environment_inputs_are_merged_deterministically(
    repository_path: Path,
) -> None:
    path = repository_path / "milburn.toml"
    path.write_text(
        """\
[milburn]
home = "state"
repository = "source"
base_branch = "trunk"
"""
    )

    first = load_configuration(
        path,
        environ={"MILBURN_HOME": "override", "MILBURN_BASE_BRANCH": "main"},
        cwd=repository_path,
    )
    second = load_configuration(
        path,
        environ={"MILBURN_HOME": "override", "MILBURN_BASE_BRANCH": "main"},
        cwd=repository_path,
    )

    assert first == second == Configuration(
        home=repository_path / "override",
        repository=repository_path / "source",
        base_branch="main",
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("milburn = 1\n", r"\[milburn\] section must be a table"),
        ("[milburn]\nunknown = true\n", "unknown configuration field"),
        ("[milburn]\nbase_branch = ''\n", "base_branch must be a non-empty string"),
    ],
)
def test_invalid_configuration_is_explicit(
    repository_path: Path,
    content: str,
    message: str,
) -> None:
    path = repository_path / "milburn.toml"
    path.write_text(content)

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(path, cwd=repository_path)


def test_missing_configuration_file_is_explicit(repository_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="could not load configuration"):
        load_configuration(repository_path / "missing.toml", cwd=repository_path)
