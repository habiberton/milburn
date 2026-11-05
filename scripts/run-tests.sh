#!/usr/bin/env bash
# Run pytest for the current checkout or worktree using the shared test
# environment (scripts/dev-env.sh) with this checkout's src/ on PYTHONPATH.
#
# Output stays bounded: full output goes to a log file, and stdout gets a
# one-line result (plus the failing excerpt on failure). Pass --verbose, or set
# MILBURN_VERBOSE=1, to stream pytest output directly.
#
# Usage: scripts/run-tests.sh [--verbose] [pytest arguments...]
# Environment: MILBURN_LOG_DIR (default: ${TMPDIR:-/tmp}/milburn-logs)
set -euo pipefail

verbose=${MILBURN_VERBOSE:-0}
args=()
for arg in "$@"; do
  if [[ "$arg" == --verbose ]]; then verbose=1; else args+=("$arg"); fi
done

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$repo_root" ]]; then
  echo "run-tests: run inside a Git repository." >&2
  exit 1
fi
cd "$repo_root"

python=$("$repo_root/scripts/dev-env.sh" --print-python)
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$verbose" == 1 ]]; then
  exec "$python" -m pytest ${args[@]+"${args[@]}"}
fi

log_dir=${MILBURN_LOG_DIR:-${TMPDIR:-/tmp}/milburn-logs}
mkdir -p "$log_dir"
log="$log_dir/pytest-$(basename "$repo_root")-$(date +%Y%m%dT%H%M%S)-$$.log"

start=$SECONDS
status=0
"$python" -m pytest ${args[@]+"${args[@]}"} >"$log" 2>&1 || status=$?
elapsed=$((SECONDS - start))

summary=$(tail -n 1 "$log")
if (( status == 0 )); then
  echo "pytest OK (${elapsed}s): $summary [log: $log]"
else
  echo "pytest FAILED exit=$status (${elapsed}s): $summary [log: $log]"
  echo "--- last 40 lines ---"
  tail -n 40 "$log"
fi
exit "$status"
