#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <worktree> <role> <task-id> <attempt-id>" >&2
  exit 2
fi

worktree=$1
role=$2
task_id=$3
attempt_id=$4

if [[ ! -d "$worktree" ]]; then
  echo "Worktree does not exist: $worktree" >&2
  exit 1
fi

if ! [[ "$role" =~ ^[a-z][a-z0-9_-]*$ ]]; then
  echo "Invalid role: $role" >&2
  exit 1
fi

if ! [[ "$task_id" =~ ^(MB-[0-9]{3}|BOOTSTRAP)$ ]]; then
  echo "Invalid task ID: $task_id" >&2
  exit 1
fi

if ! [[ "$attempt_id" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Invalid attempt ID: $attempt_id" >&2
  exit 1
fi

if ! git -C "$worktree" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a Git worktree: $worktree" >&2
  exit 1
fi

identity_email=$(git -C "$worktree" config --get milburn.identityEmail || true)
if [[ -z "$identity_email" ]]; then
  identity_email=$(git -C "$worktree" config --get user.email || true)
fi
if [[ -z "$identity_email" ]]; then
  echo "No approved commit email is configured." >&2
  echo "Set user.email once in the primary checkout, then rerun bootstrap-repo.sh." >&2
  exit 1
fi

case "$role" in
  coordinator) role_label="Coordinator" ;;
  builder) role_label="Builder" ;;
  coder) role_label="Coder" ;;
  reviewer) role_label="Reviewer" ;;
  tester) role_label="Tester" ;;
  planner) role_label="Planner" ;;
  architect) role_label="Architect" ;;
  router|classifier-router) role_label="Classifier/Router" ;;
  worker) role_label="Worker" ;;
  *) role_label="$role" ;;
esac

worker_id="${role}-${task_id}-${attempt_id}"
identity_name="Milburn ${role_label} [${task_id}/${attempt_id}]"

git -C "$worktree" config extensions.worktreeConfig true
git -C "$worktree" config --worktree user.name "$identity_name"
git -C "$worktree" config --worktree user.email "$identity_email"
git -C "$worktree" config --worktree user.useConfigOnly true
git -C "$worktree" config --worktree milburn.agentRole "$role"
git -C "$worktree" config --worktree milburn.taskId "$task_id"
git -C "$worktree" config --worktree milburn.attemptId "$attempt_id"
git -C "$worktree" config --worktree milburn.workerId "$worker_id"

echo "Configured Git identity: $identity_name"
echo "Worker ID: $worker_id"

