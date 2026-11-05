"""The ``milburn`` enforcement CLI (ARCH §4).

Output is one summary line (or a short block for reports); ``--json`` prints
the structured result instead. Exit status: 0 done; 1 refused (preconditions
unmet, nothing changed); 2 usage error; 3 project or environment error before
any effect; 4 failed after effects may have started (the record says what
happened: run ``milburn status``).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys

from milburn import __version__

READ_ONLY_COMMANDS = frozenset({"status", "usage"})


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser without performing any external effects."""

    parser = argparse.ArgumentParser(
        prog="milburn",
        description="Enforcement CLI for the Milburn Coordinator: leases, QA gate, delivery, events.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="create .milburn/config.toml and the private state directories")
    sub.add_parser("status", help="work items and tasks (read-only)")
    sub.add_parser("usage", help="token usage per task, role, and harness (read-only)")

    task = sub.add_parser("task", help="create or complete tasks")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create", help="create a code task (opens a work item if needed)")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--accept", action="append", default=[], required=True,
                        help="an acceptance criterion; repeat for each")
    create.add_argument("--work-item")
    complete = task_sub.add_parser("complete", help="run the independent QA gate")
    complete.add_argument("task")

    dispatch = sub.add_parser("dispatch", help="start a Coder attempt for a task")
    dispatch.add_argument("task")
    qa = sub.add_parser("qa", help="start a Tester attempt for a task's candidate")
    qa.add_argument("task")
    collect = sub.add_parser("collect", help="collect a task's latest attempt")
    collect.add_argument("task")
    collect.add_argument("--wait", type=float, default=0, help="seconds to wait for the run")
    integrate = sub.add_parser("integrate", help="merge a completed task into its work item")
    integrate.add_argument("task")
    deliver = sub.add_parser("deliver", help="deliver a work item per the delivery mode")
    deliver.add_argument("work_item")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit status."""

    from .commands import CommandRefused, Commands, EffectFailed, refuse_inside_role_agent
    from .project import ProjectError, init_project, load_project
    from milburn.persistence.sqlite_store import SQLiteEventStore

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        return 0
    try:
        if args.command not in READ_ONLY_COMMANDS:
            refuse_inside_role_agent(os.environ)
        if args.command == "init":
            project, created = init_project(Path.cwd())
            message = (
                f"{'created' if created else 'kept'} .milburn/config.toml; "
                f"state in {project.state_dir}"
            )
            return _emit(args, message, {"state_dir": str(project.state_dir), "created": created})
        project = load_project(Path.cwd())
        with SQLiteEventStore(project.store_path) as store:
            commands = Commands(project, store)
            if args.command == "status":
                outcome = commands.status()
            elif args.command == "usage":
                outcome = commands.usage()
            elif args.command == "task" and args.task_command == "create":
                outcome = commands.task_create(args.title, args.objective, args.accept, args.work_item)
            elif args.command == "task":
                outcome = commands.complete(args.task)
            elif args.command == "dispatch":
                outcome = commands.dispatch(args.task, "coder")
            elif args.command == "qa":
                outcome = commands.dispatch(args.task, "tester")
            elif args.command == "collect":
                outcome = commands.collect(args.task, args.wait)
            elif args.command == "integrate":
                outcome = commands.integrate(args.task)
            else:
                outcome = commands.deliver(args.work_item)
        return _emit(args, outcome.summary, outcome.data)
    except CommandRefused as refused:
        _emit(args, "refused: " + "; ".join(refused.reasons), {"refused": refused.reasons}, sys.stderr)
        return 1
    except ProjectError as error:
        _emit(args, f"error: {error}", {"error": str(error)}, sys.stderr)
        return 3
    except EffectFailed as error:
        _emit(args, f"failed: {error}; run `milburn status`", {"failed": str(error)}, sys.stderr)
        return 4
    except Exception as error:  # noqa: BLE001 - the exit-code contract needs a catch-all
        message = f"{type(error).__name__}: {error}".splitlines()[0]
        _emit(args, f"failed: {message}; effects may be partial, run `milburn status`",
              {"failed": message}, sys.stderr)
        return 4


def _emit(args: argparse.Namespace, summary: str, data: dict, stream=None) -> int:
    stream = stream or sys.stdout
    if args.json:
        print(json.dumps(data, sort_keys=True, default=str), file=stream, flush=True)
    else:
        print(summary, file=stream, flush=True)
    return 0


def run() -> int:
    """Console-script adapter."""

    return main()


if __name__ == "__main__":  # pragma: no cover - exercised by the console script
    raise SystemExit(run())
