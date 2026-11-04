#!/usr/bin/env python3
"""Verify that candidate commits belong to one assigned Milburn worker."""

from __future__ import annotations

import re
import subprocess
import sys


ROLE_LABELS = {
    "coordinator": "Coordinator",
    "builder": "Builder",
    "coder": "Coder",
    "reviewer": "Reviewer",
    "tester": "Tester",
    "planner": "Planner",
    "architect": "Architect",
    "router": "Classifier/Router",
    "classifier-router": "Classifier/Router",
    "worker": "Worker",
}


def run(*args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{' '.join(args)} failed: {detail}")
    return completed.stdout


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "Usage: verify-candidate-commits.py "
            "<base-sha> <candidate-sha> <role> <task-id> <attempt-id>",
            file=sys.stderr,
        )
        return 2

    base, candidate, role, task_id, attempt_id = sys.argv[1:]
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", role):
        fail(f"invalid role: {role}")
        return 1
    if not re.fullmatch(r"(?:MB-[0-9]{3}|BOOTSTRAP)", task_id):
        fail(f"invalid task ID: {task_id}")
        return 1
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", attempt_id):
        fail(f"invalid attempt ID: {attempt_id}")
        return 1

    expected_email = run("git", "config", "--get", "milburn.identityEmail").strip()
    expected_name = (
        f"Milburn {ROLE_LABELS.get(role, role)} [{task_id}/{attempt_id}]"
    )
    expected_worker = f"{role}-{task_id}-{attempt_id}"

    try:
        run("git", "rev-parse", "--verify", f"{base}^{{commit}}")
        run("git", "rev-parse", "--verify", f"{candidate}^{{commit}}")
        run("git", "merge-base", "--is-ancestor", base, candidate)
    except RuntimeError as error:
        fail(str(error))
        return 1

    commits = [
        line
        for line in run("git", "rev-list", "--reverse", f"{base}..{candidate}").splitlines()
        if line
    ]
    if not commits:
        fail("candidate contains no commits after the assigned base")
        return 1

    failures: list[str] = []
    for commit in commits:
        fields = run(
            "git",
            "show",
            "-s",
            "--format=%an%x00%ae%x00%cn%x00%ce%x00%s%x00%B",
            commit,
        ).split("\x00", 5)
        if len(fields) != 6:
            failures.append(f"{commit}: could not parse commit metadata")
            continue
        author_name, author_email, committer_name, committer_email, subject, body = (
            value.strip() for value in fields
        )

        parent_fields = run("git", "rev-list", "--parents", "-n", "1", commit).split()
        if len(parent_fields) > 2:
            failures.append(f"{commit}: worker candidates may not contain merge commits")

        expected_subject_prefix = f"{task_id}: "
        if not subject.startswith(expected_subject_prefix):
            failures.append(
                f"{commit}: subject must start with {expected_subject_prefix!r}"
            )

        for label, actual, expected in (
            ("author name", author_name, expected_name),
            ("author email", author_email, expected_email),
            ("committer name", committer_name, expected_name),
            ("committer email", committer_email, expected_email),
        ):
            if actual != expected:
                failures.append(
                    f"{commit}: {label} is {actual!r}; expected {expected!r}"
                )

        trailer_output = run("git", "interpret-trailers", "--parse", input_text=body)
        trailers: dict[str, str] = {}
        for line in trailer_output.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                trailers[key.strip()] = value.strip()

        expected_trailers = {
            "Milburn-Agent": role,
            "Milburn-Worker": expected_worker,
            "Milburn-Task": task_id,
            "Milburn-Attempt": attempt_id,
        }
        for key, expected in expected_trailers.items():
            actual = trailers.get(key)
            if actual != expected:
                failures.append(
                    f"{commit}: trailer {key} is {actual!r}; expected {expected!r}"
                )

    if failures:
        for message in failures:
            fail(message)
        return 1

    print(
        f"Verified {len(commits)} commit(s) for "
        f"{expected_worker} at {candidate}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

