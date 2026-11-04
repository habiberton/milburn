#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$repo_root" ]]; then
  echo "Milburn bootstrap requires an existing Git repository." >&2
  exit 1
fi

cd "$repo_root"

required=(
  AGENTS.md
  PRD.md
  ARCH.md
  bootstrap/README.md
  bootstrap/ROOT_PROMPT.md
  bootstrap/tasks.json
  bootstrap/decisions.md
  bootstrap/progress/coordinator.md
  bootstrap/progress/tasks/TEMPLATE.md
  scripts/smoke-test.sh
)

for path in "${required[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "Missing required bootstrap file: $path" >&2
    exit 1
  fi
done

mkdir -p ../milburn-worktrees

python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("bootstrap/tasks.json").read_text())
assert payload["schema_version"] == 1
tasks = payload["tasks"]
ids = [task["id"] for task in tasks]
assert len(ids) == len(set(ids)), "duplicate task IDs"
known = set(ids)
for task in tasks:
    missing = set(task["dependencies"]) - known
    assert not missing, f"{task['id']} has unknown dependencies: {sorted(missing)}"
print(f"Validated {len(tasks)} bootstrap tasks across {len(payload['waves'])} waves.")
PY

scripts/smoke-test.sh

echo
echo "Milburn bootstrap is ready."
echo "Launch the root Codex task from: $repo_root"
echo "Use the prompt in bootstrap/ROOT_PROMPT.md"

