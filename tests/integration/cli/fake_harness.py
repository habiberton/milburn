"""Stub harness executable for CLI integration tests.

Invoked as ``fake_harness.py codex|claude-code [harness flags...]`` with the
rendered brief on stdin. It acts as the role named in the brief and prints the
real stream format of the named harness. Behaviour knobs (environment):

- FAKE_CODER_MODE: candidate (default) | nocommit | wronghead | blocked
- FAKE_TESTER_OUTCOME: passed (default) | changes_requested
"""

import json
import os
import re
import subprocess
import sys

harness = sys.argv[1]
brief = sys.stdin.read()
role = re.search(r"^- role: (\S+)$", brief, re.M).group(1)
task_id = re.search(r"^- task_id: (\S+)$", brief, re.M).group(1)
attempt_id = re.search(r"^- attempt_id: (\S+)$", brief, re.M).group(1)
number = int(task_id[1:])


def git(*args: str) -> str:
    return subprocess.run(("git", *args), check=True, capture_output=True, text=True).stdout.strip()


if role == "coder":
    mode = os.environ.get("FAKE_CODER_MODE", "candidate")
    if mode == "blocked":
        payload = {
            "schema_version": 1, "attempt_id": attempt_id, "issue_number": number,
            "outcome": "blocked", "head_sha": git("rev-parse", "HEAD"),
            "progress_path": "progress.txt", "commits": [], "files_changed": [],
            "test_claims": [], "risks": ["blocked on a missing decision"],
        }
    else:
        base = git("rev-parse", "HEAD")
        with open(f"feature_{task_id}.txt", "w") as handle:
            handle.write(f"done by {attempt_id}\n")
        with open("progress.txt", "w") as handle:
            handle.write(f"{task_id} {attempt_id} complete\n")
        if mode != "nocommit":
            git("add", f"feature_{task_id}.txt", "progress.txt")
            git("commit", "-q", "-m", f"{task_id}: implement")
        head = git("rev-parse", "HEAD")
        commits = git("rev-list", f"{base}..{head}").split()
        if mode == "wronghead":
            head = "0" * 40
        payload = {
            "schema_version": 1, "attempt_id": attempt_id, "issue_number": number,
            "outcome": "candidate", "head_sha": head, "progress_path": "progress.txt",
            "commits": commits,
            "files_changed": [f"feature_{task_id}.txt", "progress.txt"],
            "test_claims": [{"schema_version": 1, "name": "stub", "outcome": "passed", "evidence": "ok"}],
            "risks": [],
        }
    result_type = "coder_result"
else:
    candidate = re.search(r"Candidate SHA under test: (\S+)", brief).group(1)
    outcome = os.environ.get("FAKE_TESTER_OUTCOME", "passed")
    payload = {
        "schema_version": 1, "attempt_id": attempt_id, "issue_number": number,
        "candidate_sha": candidate, "outcome": outcome,
        "acceptance_results": [{"schema_version": 1, "name": "criterion 1", "outcome": outcome, "evidence": "checked"}],
        "commands": ["cat feature file"], "evidence_artifacts": [],
        "defects": [] if outcome == "passed" else ["criterion 1 fails"],
        "summary": f"QA {outcome}",
    }
    result_type = "qa_report"

envelope = {
    "schema_version": 1, "role": role, "task_id": task_id, "attempt_id": attempt_id,
    "task_success": True, "result_type": result_type, "payload": payload,
}
if harness == "codex":
    events = [
        {"type": "thread.started", "thread_id": f"thread-{task_id}-{attempt_id}"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Working on it."}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(envelope)}},
        {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 400,
                                             "output_tokens": 50, "reasoning_output_tokens": 5}},
    ]
else:
    session = {"session_id": f"session-{task_id}-{attempt_id}"}
    events = [
        {"type": "system", "subtype": "init", **session},
        {"type": "result", "subtype": "success", "is_error": False, "structured_output": envelope,
         "result": json.dumps(envelope),
         "usage": {"input_tokens": 10, "cache_read_input_tokens": 700,
                   "cache_creation_input_tokens": 100, "output_tokens": 30}, **session},
    ]
for event in events:
    print(json.dumps(event))
