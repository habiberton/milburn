from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

from milburn.runtime.tmux import ObservationStatus, TmuxRuntime, WindowSpec


pytestmark = pytest.mark.skipif(
    os.environ.get("MILBURN_RUN_TMUX_CONTRACTS") != "1" or shutil.which("tmux") is None,
    reason="set MILBURN_RUN_TMUX_CONTRACTS=1 with tmux installed",
)


def test_real_tmux_stable_ids_generation_isolation_and_termination(tmp_path: Path) -> None:
    session = f"milburn-contract-{uuid.uuid4().hex[:10]}"
    runtime = TmuxRuntime()
    command = (
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGINT, lambda *_: exit(0)); time.sleep(60)",
    )
    first = runtime.create_window(
        WindowSpec(session, "duplicate", "attempt-contract", "coder", 1, command, tmp_path)
    )
    second = runtime.create_window(
        WindowSpec(session, "duplicate", "attempt-contract", "coder", 2, command, tmp_path)
    )
    try:
        assert first.window_id != second.window_id
        assert first.pane_id != second.pane_id
        assert runtime.inspect(first).status is ObservationStatus.STALE_GENERATION
        assert runtime.inspect(second).matched
        assert runtime.terminate(second).status is ObservationStatus.MISSING
    finally:
        subprocess.run(("tmux", "kill-session", "-t", session), check=False, capture_output=True)
