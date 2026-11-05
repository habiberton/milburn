"""DetachedRunRuntime against stub executables; no real harness is run."""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import stat
import sys
import time

import pytest

from milburn.agents.codex_adapter import ProcessLaunch, ProcessState
from milburn.runtime.run_host import DetachedRunRuntime, RunHostError


def _stub(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _runtime(run_dir: Path, ids: list[str] | None = None) -> DetachedRunRuntime:
    counter = itertools.count(1)
    supply = iter(ids) if ids else None
    return DetachedRunRuntime(
        run_dir,
        endpoint_ids=(lambda: next(supply)) if supply else (lambda: f"run-{next(counter)}"),
        stop_grace_seconds=3,
    )


def _wait_exit(runtime: DetachedRunRuntime, endpoint: str) -> None:
    status = runtime.wait(endpoint, 8)
    assert status.state is ProcessState.EXITED, status


# --- negative cases first ---------------------------------------------------

def test_relative_run_dir_is_refused() -> None:
    with pytest.raises(ValueError):
        DetachedRunRuntime(Path("runs"), endpoint_ids=lambda: "x")


@pytest.mark.parametrize("bad", ["", "../x", "a/b", " x", "-x"])
def test_unsafe_endpoint_ids_are_refused_before_any_file(tmp_path: Path, bad: str) -> None:
    runtime = _runtime(tmp_path / "runs", [bad])
    with pytest.raises(RunHostError):
        runtime.launch(ProcessLaunch(("true",), str(tmp_path), ""))
    assert not (tmp_path / "runs").exists() or not list((tmp_path / "runs").iterdir())


def test_duplicate_endpoint_is_refused(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "ok", "import sys; sys.stdin.read()\n")
    runtime = _runtime(tmp_path / "runs", ["same", "same"])
    runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    with pytest.raises(RunHostError, match="already launched"):
        runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))


def test_unknown_endpoint_is_rejected(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runs")
    with pytest.raises(KeyError):
        runtime.status("nope")
    with pytest.raises(KeyError):
        runtime.collect("../etc")


def test_steering_is_refused(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "ok", "import sys; sys.stdin.read()\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    assert not runtime.steer(endpoint, "go").accepted


def test_missing_executable_exits_127_with_reason(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(tmp_path / "missing"),), str(tmp_path), ""))
    _wait_exit(runtime, endpoint)
    collected = runtime.collect(endpoint)
    assert collected.exit_code == 127
    assert "could not start" in collected.stderr


def test_a_dead_host_without_exit_file_is_exited_without_code(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    host = json.loads((tmp_path / "runs" / f"{endpoint}.host.json").read_text())
    os.killpg(host["pid"], 9)
    deadline = time.monotonic() + 5
    while runtime.status(endpoint).state is ProcessState.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)
    assert runtime.status(endpoint).state is ProcessState.UNKNOWN
    collected = runtime.collect(endpoint)
    assert collected.state is ProcessState.EXITED and collected.exit_code is None


def test_running_endpoint_cannot_be_retired(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    assert not runtime.retire(endpoint).observed
    runtime.interrupt(endpoint)


# --- behaviour --------------------------------------------------------------

def test_brief_env_output_and_exit_code_survive_a_new_runtime_instance(tmp_path: Path) -> None:
    stub = _stub(
        tmp_path,
        "echo",
        "import os, sys\n"
        "data = sys.stdin.read()\n"
        "print(data + '|' + os.environ['GIT_AUTHOR_NAME'] + '|' + os.getcwd())\n"
        "print('warn', file=sys.stderr)\n"
        "sys.exit(5)\n",
    )
    work = tmp_path / "work"
    work.mkdir()
    launcher = _runtime(tmp_path / "runs")
    endpoint = launcher.launch(
        ProcessLaunch((str(stub),), str(work), "brief-text", env=(("GIT_AUTHOR_NAME", "Coder"),))
    )
    observer = _runtime(tmp_path / "runs")  # a later CLI process
    _wait_exit(observer, endpoint)
    collected = observer.collect(endpoint)
    assert collected.exit_code == 5
    assert collected.stdout.strip() == f"brief-text|Coder|{os.path.realpath(work)}"
    assert collected.stderr.strip() == "warn"
    launch_file = tmp_path / "runs" / f"{endpoint}.launch.json"
    assert stat.S_IMODE(launch_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "runs").stat().st_mode) == 0o700


def test_collect_does_not_block_while_running(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    started = time.monotonic()
    collected = runtime.collect(endpoint)
    assert collected.state is ProcessState.RUNNING
    assert time.monotonic() - started < 2
    assert runtime.interrupt(endpoint).observed


def test_interrupt_stops_the_whole_run_and_records_an_exit(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    assert runtime.wait(endpoint, 0.5).state is ProcessState.RUNNING
    assert runtime.interrupt(endpoint).observed
    status = runtime.status(endpoint)
    assert status.state is ProcessState.EXITED
    assert status.exit_code is not None and status.exit_code != 0
    assert runtime.retire(endpoint).observed


def test_child_pythonpath_is_the_callers_not_the_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/caller/path")
    stub = _stub(tmp_path, "pp", "import os; print(os.environ.get('PYTHONPATH', ''))\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    _wait_exit(runtime, endpoint)
    assert runtime.collect(endpoint).stdout.strip() == "/caller/path"


def test_a_harness_child_that_outlives_its_host_keeps_the_run_running(tmp_path: Path) -> None:
    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = _runtime(tmp_path / "runs")
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    host = json.loads((tmp_path / "runs" / f"{endpoint}.host.json").read_text())
    import subprocess

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        members = subprocess.run(
            ["pgrep", "-g", str(host["pid"])], capture_output=True, text=True
        ).stdout.split()
        if len(members) >= 2:  # the host and its harness child
            break
        time.sleep(0.05)
    os.kill(host["pid"], 9)  # only the host, not its process group
    time.sleep(0.3)
    assert runtime.status(endpoint).state is ProcessState.RUNNING
    assert runtime.collect(endpoint).state is ProcessState.RUNNING
    os.killpg(host["pid"], 9)


def test_an_unidentified_host_is_never_collected_while_its_group_runs(tmp_path: Path) -> None:
    class Blind:
        def identify(self, pid: int):
            return None

    stub = _stub(tmp_path, "sleep", "import time; time.sleep(30)\n")
    runtime = DetachedRunRuntime(tmp_path / "runs", endpoint_ids=lambda: "blind-1", inspector=Blind())
    endpoint = runtime.launch(ProcessLaunch((str(stub),), str(tmp_path), ""))
    assert runtime.collect(endpoint).state is ProcessState.RUNNING
    host = json.loads((tmp_path / "runs" / f"{endpoint}.host.json").read_text())
    os.killpg(host["pid"], 9)
