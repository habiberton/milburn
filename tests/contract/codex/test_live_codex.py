"""Protected live Codex smoke contract.

This module is skipped unless ``MILBURN_RUN_LIVE_CODEX=1`` is explicitly set.
Deterministic tests use ``tests.fakes.codex`` and never launch this command.
"""

import os
import shutil
import subprocess

import pytest


def test_live_codex_cli_is_available_and_reports_a_version() -> None:
    if os.environ.get("MILBURN_RUN_LIVE_CODEX") != "1":
        pytest.skip("set MILBURN_RUN_LIVE_CODEX=1 for the protected live contract")
    executable = shutil.which("codex")
    if executable is None:
        pytest.fail("MILBURN_RUN_LIVE_CODEX=1 but codex is not installed")

    completed = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert "codex" in completed.stdout.lower()
