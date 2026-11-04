from __future__ import annotations

import pytest

from milburn import __version__
from milburn.app.cli import main


def test_help_screen_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])

    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "usage: milburn" in output
    assert "--version" in output


def test_version_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--version"])

    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == f"milburn {__version__}"


def test_empty_command_finishes_without_external_work() -> None:
    assert main([]) == 0
