#!/usr/bin/env bash
# Smoke test: the specs exist, the CLI imports, and the full product suite passes.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$repo_root" ]]; then
  echo "Smoke test must run inside a Git repository." >&2
  exit 1
fi
cd "$repo_root"

for path in AGENTS.md PRD.md ARCH.md pyproject.toml; do
  if [[ ! -s "$path" ]]; then
    echo "Required file is missing or empty: $path" >&2
    exit 1
  fi
done

test_python=$("$repo_root/scripts/dev-env.sh" --print-python) || {
  echo "The shared test environment could not be prepared; see scripts/dev-env.sh." >&2
  exit 1
}
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
"$test_python" -m milburn.app.cli --version >/dev/null
"$test_python" -m pytest --collect-only -q >/dev/null
"$test_python" -m pytest -q
