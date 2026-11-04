#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$repo_root" ]]; then
  echo "Smoke test must run inside a Git repository." >&2
  exit 1
fi

cd "$repo_root"

for path in AGENTS.md PRD.md ARCH.md bootstrap/README.md bootstrap/tasks.json; do
  if [[ ! -s "$path" ]]; then
    echo "Required file is missing or empty: $path" >&2
    exit 1
  fi
done

python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("bootstrap/tasks.json").read_text())
tasks = payload.get("tasks", [])
assert tasks, "task registry is empty"
ids = {task["id"] for task in tasks}
for task in tasks:
    required = {
        "id", "wave", "title", "status", "dependencies", "owned_paths",
        "acceptance_criteria", "required_tests"
    }
    missing = required - set(task)
    assert not missing, f"{task.get('id', '<unknown>')} missing {sorted(missing)}"
    unknown_dependencies = set(task["dependencies"]) - ids
    assert not unknown_dependencies, (
        f"{task['id']} has unknown dependencies {sorted(unknown_dependencies)}"
    )
print(f"Bootstrap registry: {len(tasks)} tasks valid")
PY

if [[ -f pyproject.toml ]]; then
  if [[ -f uv.lock ]] && command -v uv >/dev/null 2>&1; then
    uv run pytest --collect-only -q >/dev/null
    uv run pytest -q
  elif python3 -c 'import pytest' >/dev/null 2>&1; then
    python3 -m pytest --collect-only -q >/dev/null
    python3 -m pytest -q
  else
    echo "pyproject.toml exists but pytest is unavailable." >&2
    echo "Install the project's development dependencies before continuing." >&2
    exit 1
  fi
else
  echo "Product test suite not created yet; bootstrap checks passed."
fi
