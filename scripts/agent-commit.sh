#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <commit summary without task prefix>" >&2
  exit 2
fi

summary=$1
if [[ -z "$summary" || "$summary" == *$'\n'* ]]; then
  echo "Commit summary must be one non-empty line." >&2
  exit 1
fi

role=$(git config --worktree --get milburn.agentRole || true)
task_id=$(git config --worktree --get milburn.taskId || true)
attempt_id=$(git config --worktree --get milburn.attemptId || true)
worker_id=$(git config --worktree --get milburn.workerId || true)

if [[ -z "$role" || -z "$task_id" || -z "$attempt_id" || -z "$worker_id" ]]; then
  echo "This worktree has no Milburn identity." >&2
  echo "The root coordinator must run configure-worktree-identity.sh first." >&2
  exit 1
fi

if git diff --cached --quiet; then
  echo "No staged changes to commit." >&2
  exit 1
fi

git commit \
  -m "${task_id}: ${summary}" \
  -m "Milburn-Agent: ${role}
Milburn-Worker: ${worker_id}
Milburn-Task: ${task_id}
Milburn-Attempt: ${attempt_id}"

