#!/usr/bin/env bash
# Ensure the shared Milburn test environment exists and report where it is.
#
# One virtualenv, outside every worktree, holds only the test dependencies from
# pyproject.toml ([project.optional-dependencies].test). Milburn itself is not
# installed into it: callers put the current worktree's src/ on PYTHONPATH, so
# the same environment works for the primary checkout and every worktree.
#
# Usage:
#   scripts/dev-env.sh                 create or verify; print the venv path
#   scripts/dev-env.sh --print-python  create or verify; print the venv python
#   scripts/dev-env.sh --check         verify only; never create (exit 1 if absent)
#
# Environment:
#   MILBURN_VENV         venv location (default: ~/.cache/milburn/venv)
#   MILBURN_BASE_PYTHON  interpreter used to create it (default: python3)
set -euo pipefail

mode=ensure
print=path
for arg in "$@"; do
  case "$arg" in
    --check) mode=check ;;
    --print-python) print=python ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$repo_root" || ! -f "$repo_root/pyproject.toml" ]]; then
  echo "dev-env: run inside a Milburn checkout that has pyproject.toml." >&2
  exit 1
fi

venv=${MILBURN_VENV:-$HOME/.cache/milburn/venv}
base_python=${MILBURN_BASE_PYTHON:-python3}
venv_python="$venv/bin/python"

env_ready() {
  [[ -x "$venv_python" ]] && "$venv_python" - <<'PY' >/dev/null 2>&1
import pytest, pytest_timeout, xdist  # noqa: F401
PY
}

emit() {
  if [[ "$print" == python ]]; then echo "$venv_python"; else echo "$venv"; fi
}

if env_ready; then
  emit
  exit 0
fi

if [[ "$mode" == check ]]; then
  echo "dev-env: test environment not ready at $venv (run scripts/dev-env.sh)." >&2
  exit 1
fi

if ! command -v "$base_python" >/dev/null 2>&1; then
  echo "dev-env: $base_python not found; set MILBURN_BASE_PYTHON." >&2
  exit 1
fi
if ! "$base_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "dev-env: $base_python is older than Python 3.11 (required by pyproject.toml)." >&2
  exit 1
fi

# Several agents may start at once; let one create the environment.
lock="$venv.lock"
mkdir -p "$(dirname "$venv")"
waited=0
until mkdir "$lock" 2>/dev/null; do
  if env_ready; then emit; exit 0; fi
  if (( waited >= 180 )); then
    echo "dev-env: timed out waiting for $lock; if no other setup is running, remove it." >&2
    exit 1
  fi
  sleep 2
  waited=$((waited + 2))
done
trap 'rmdir "$lock" 2>/dev/null || true' EXIT

if env_ready; then emit; exit 0; fi

# Read the test dependency list from pyproject.toml.
requirements=()
while IFS= read -r line; do
  [[ -n "$line" ]] && requirements+=("$line")
done < <("$base_python" - "$repo_root/pyproject.toml" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)
for requirement in data.get("project", {}).get("optional-dependencies", {}).get("test", []):
    print(requirement)
PY
)
if (( ${#requirements[@]} == 0 )); then
  echo "dev-env: no [project.optional-dependencies].test entries in pyproject.toml." >&2
  exit 1
fi

echo "dev-env: creating test environment at $venv" >&2
rm -rf "$venv"
"$base_python" -m venv "$venv" >&2
if ! "$venv_python" -m pip install --quiet --disable-pip-version-check "${requirements[@]}" >&2; then
  rm -rf "$venv"
  echo "dev-env: installing ${requirements[*]} failed. The first setup needs network" >&2
  echo "access to a package index; re-run once it is available, or point" >&2
  echo "MILBURN_VENV at an environment that already has the test dependencies." >&2
  exit 1
fi

if ! env_ready; then
  echo "dev-env: environment was created but pytest imports still fail." >&2
  exit 1
fi
emit
