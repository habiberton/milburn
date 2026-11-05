"""SubprocessCodexRuntime against a stub executable; the real Codex is never run."""

from __future__ import annotations

import itertools
from pathlib import Path
import stat
import sys

import pytest

from milburn.agents.codex_adapter import ProcessLaunch, ProcessState
from milburn.runtime.codex_process import SubprocessCodexRuntime


def _stub(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "stub-codex"
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _runtime(tmp_path: Path, **kwargs: float) -> SubprocessCodexRuntime:
    counter = itertools.count(1)
    return SubprocessCodexRuntime(
        tmp_path / "logs", endpoint_ids=lambda: f"run-{next(counter)}", **kwargs
    )


def test_timeout_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _runtime(tmp_path, timeout_seconds=0)


def test_unknown_endpoint_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        _runtime(tmp_path).collect("nope")


def test_exec_runs_cannot_be_steered(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "import sys; sys.stdin.read()\n")
    runtime = _runtime(tmp_path)
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), "brief"))

    ack = runtime.steer(endpoint, "more instructions")

    assert ack.accepted is False
    runtime.collect(endpoint)


def test_a_run_past_its_timeout_is_stopped_and_reported_exited(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path, timeout_seconds=0.5)
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))

    collected = runtime.collect(endpoint)

    assert collected.state is ProcessState.EXITED
    assert collected.exit_code != 0


def test_stdin_brief_is_delivered_and_output_is_kept_as_a_log(tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "import sys\nbrief = sys.stdin.read()\n"
        "print('{\"type\": \"echo\", \"len\": %d}' % len(brief))\n"
        "print('warn', file=sys.stderr)\n",
    )
    runtime = _runtime(tmp_path)
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), "abcde"))

    collected = runtime.collect(endpoint)

    assert collected.exit_code == 0
    assert collected.stdout.strip() == '{"type": "echo", "len": 5}'
    assert collected.stderr.strip() == "warn"
    assert runtime.log_path(endpoint).read_text(encoding="utf-8") == collected.stdout
    assert runtime.collect(endpoint) is collected
    assert runtime.status(endpoint).state is ProcessState.EXITED


def test_env_pairs_are_added_to_the_inherited_environment(tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "import os, sys; sys.stdin.read(); "
        "print(os.environ['GIT_AUTHOR_NAME'] + '|' + ('PATH' in os.environ and 'path' or ''))\n",
    )
    runtime = _runtime(tmp_path)
    endpoint = runtime.launch(
        ProcessLaunch(
            (str(stub),), str(tmp_path), "", env=(("GIT_AUTHOR_NAME", "Milburn Coder t1/a1"),)
        )
    )
    collected = runtime.collect(endpoint)
    assert collected.exit_code == 0
    assert collected.stdout.strip() == "Milburn Coder t1/a1|path"


def test_a_child_that_exits_before_reading_its_brief_is_still_tracked(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "import sys; sys.exit(3)\n")
    runtime = _runtime(tmp_path)
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), "x" * 1_000_000))
    collected = runtime.collect(endpoint)
    assert collected.exit_code == 3
